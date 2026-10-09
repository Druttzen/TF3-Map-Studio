"""Selected-area OSM XML downloads and cached visible map tiles. GPL-3.0."""
from __future__ import annotations
from contextlib import closing
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr
from PIL import Image
from converter import validate_bounds
from job import Cancelled

USER_AGENT='Druttzen-OSM-TF3-Converter/0.15 (+https://github.com/Druttzen/TF3-Map-Studio)'
OVERPASS='https://overpass-api.de/api/interpreter'
TILES='https://tile.openstreetmap.org/{z}/{x}/{y}.png'
R=6378137.0
WORLD=2*math.pi*R
PART_METRES=8000
MAX_PARTS=64
MAX_REQUESTS=128


class AreaTooLarge(ValueError):
    """A server resource refusal eligible for a smaller-area request."""


def ground_extent(bounds):
    south,west,north,east=bounds
    x,y=mercator(south,west);xx,yy=mercator(north,east)
    scale=math.cos(math.radians((south+north)/2))
    return (xx-x)*scale,(yy-y)*scale


def download_parts(bounds):
    """Cover the exact selection; adjacent parts share their boundary."""
    width,height=ground_extent(bounds)
    nx=max(1,math.ceil(width/PART_METRES));ny=max(1,math.ceil(height/PART_METRES))
    if nx*ny>MAX_PARTS:
        raise ValueError('This selection is too large for the public OSM download. Use a regional .osm extract or reduce the area scale.')
    south,west,north,east=bounds
    xs=[west+(east-west)*i/nx for i in range(nx+1)]
    ys=[south+(north-south)*i/ny for i in range(ny+1)]
    xs[0],xs[-1]=west,east;ys[0],ys[-1]=south,north
    return [[ys[j],xs[i],ys[j+1],xs[i+1]] for j in range(ny) for i in range(nx)]


def smaller_parts(bounds):
    south,west,north,east=bounds
    width,height=ground_extent(bounds)
    if width>=height:
        middle=(west+east)/2
        return [[south,west,north,middle],[south,middle,north,east]]
    middle=(south+north)/2
    return [[south,west,middle,east],[middle,west,north,east]]


def wait_for_service(seconds,cancel):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        check(cancel)
        time.sleep(min(.1,max(0,until-time.monotonic())))
    check(cancel)

def check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled('OSM download cancelled. Existing files were kept.')

def mercator(lat,lon):
    if not all(math.isfinite(v) for v in (lat,lon)) or not (-85<lat<85 and -180<=lon<=180):
        raise ValueError('Use latitude between -85 and 85 and longitude between -180 and 180.')
    return R*math.radians(lon),R*math.log(math.tan(math.pi/4+math.radians(lat)/2))

def geographic(x,y):
    return math.degrees(math.atan(math.sinh(y/R))),math.degrees(x/R)

def area_bounds(center,size,coverage=1):
    """Game aspect in EPSG:3857; metre scale is ground distance at the centre."""
    lat,lon=center
    x,y=mercator(lat,lon)
    validate_bounds([-1,-1,1,1],size)
    if not math.isfinite(coverage) or not 0.01<=coverage<=100:
        raise ValueError('Area scale must be between 0.01 and 100.')
    scale=coverage/math.cos(math.radians(lat))
    south,west=geographic(x-size[0]*scale/2,y-size[1]*scale/2)
    north,east=geographic(x+size[0]*scale/2,y+size[1]*scale/2)
    result=[south,west,north,east]
    validate_bounds(result,size)
    return result

class Selection:
    def __init__(self,size,center=(59.3293,18.0686),coverage=1):
        self.size=tuple(size);self.center=tuple(center);self.coverage=coverage;self.locked=False
        self.bounds=area_bounds(self.center,self.size,self.coverage)
    def move(self,center):
        if self.locked:return
        bounds=area_bounds(center,self.size,self.coverage)
        self.center=tuple(center);self.bounds=bounds
    def lock(self,center):
        if self.locked:return
        self.move(center);self.locked=True
    def unlock(self):self.locked=False
    def resize(self,size,coverage):
        bounds=area_bounds(self.center,size,coverage)
        self.size=tuple(size);self.coverage=coverage;self.bounds=bounds;self.locked=False

def pixel(lat,lon,zoom):
    x,y=mercator(lat,lon);n=256*2**zoom
    return (x/WORLD+.5)*n,(.5-y/WORLD)*n

def pixel_geographic(x,y,zoom):
    n=256*2**zoom
    return geographic((x/n-.5)*WORLD,(.5-y/n)*WORLD)

def fit_zoom(bounds,width,height):
    south,west,north,east=bounds
    a,b=pixel(north,west,0);c,d=pixel(south,east,0)
    scale=min(max(100,width-100)/(c-a),max(100,height-100)/(d-b))
    return max(2,min(19,math.floor(math.log2(scale))))

def visible_tiles(center,zoom,width,height):
    x,y=pixel(*center,zoom);left=x-width/2;top=y-height/2;n=2**zoom
    return [(zoom,tx,ty,tx*256-left,ty*256-top)
            for ty in range(max(0,math.floor(top/256)),min(n-1,math.floor((top+height-1)/256))+1)
            for tx in range(max(0,math.floor(left/256)),min(n-1,math.floor((left+width-1)/256))+1)]

def https_url(url):
    parts=urllib.parse.urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Use a public HTTPS address without login details or fragments.')
    return url

def query_for(bounds):
    validate_bounds(bounds,[1,1])
    bbox=','.join(format(v,'.17g') for v in bounds)
    # Full descendants preserve complete ways, multipolygons and nested relations.
    return f'[out:xml][timeout:180];nwr({bbox});(._;>>;);out body;'

def _chunks(request,cancel,opener,headers=None):
    """One request; cancellation stays responsive even while waiting for headers."""
    packets=queue.Queue(maxsize=4);stop=threading.Event()
    def send(item):
        while not stop.is_set():
            try:packets.put(item,timeout=.1);return
            except queue.Full:pass
    def worker():
        try:
            with opener(request,timeout=240) as response:
                if stop.is_set():return
                https_url(response.geturl())
                send(('headers',response.headers))
                while not stop.is_set():
                    chunk=response.read1(65536) if hasattr(response,'read1') else response.read(65536)
                    if not chunk:break
                    send(('data',chunk))
                send(('done',None))
        except Exception as exc:send(('error',exc))
    threading.Thread(target=worker,daemon=True).start()
    try:
        while True:
            check(cancel)
            try:kind,value=packets.get(timeout=.1)
            except queue.Empty:continue
            if kind=='error':raise value
            if kind=='done':return
            if kind=='headers':
                if headers is not None:headers.update(dict(value.items()))
                continue
            yield value
    finally:stop.set()

class SafeXmlReader:
    def __init__(self,stream,cancel):self.stream=stream;self.cancel=cancel;self.tail=b''
    def read(self,n=-1):
        check(self.cancel);chunk=self.stream.read(n)
        scan=(self.tail+chunk).upper()
        if b'<!DOCTYPE' in scan or b'<!ENTITY' in scan or b'\x00' in chunk:raise ValueError('The server returned unsupported XML declarations or encoding.')
        self.tail=scan[-16:];return chunk

def rewrite_xml(source,target,bounds,cancel=None,progress=None):
    """Stream validated entities and embed the exact locked selection bounds."""
    counts={'nodes':0,'ways':0,'relations':0};depth=0;root=None
    keys={'node':'nodes','way':'ways','relation':'relations'}
    with Path(source).open('rb') as incoming,Path(target).open('wb') as outgoing:
        reader=SafeXmlReader(incoming,cancel)
        for event,elem in ET.iterparse(reader,events=('start','end')):
            if event=='start':
                depth+=1
                if root is None:
                    root=elem
                    if elem.tag!='osm' or elem.get('version')!='0.6':raise ValueError('The server did not return OSM 0.6 XML.')
                    attrs=' '.join(k+'='+quoteattr(v) for k,v in elem.attrib.items())
                    outgoing.write(('<?xml version="1.0" encoding="UTF-8"?>\n<osm '+attrs+'>\n').encode('utf-8'))
                    bounds_node=ET.Element('bounds',dict(zip(('minlat','minlon','maxlat','maxlon'),(format(v,'.17g') for v in bounds))))
                    outgoing.write(ET.tostring(bounds_node,encoding='utf-8')+b'\n')
                continue
            if depth==2:
                check(cancel)
                if elem.tag in {'remark','error'}:
                    message=''.join(elem.itertext()).strip()[:500]
                    error=AreaTooLarge if any(word in message.lower() for word in ('timed out','timeout','out of memory','exceeded')) else ValueError
                    raise error('The OSM service could not complete the selected area: '+message)
                if elem.tag in keys:
                    if not elem.get('id'):raise ValueError('The OSM service returned an object without an ID.')
                    if elem.tag=='node':
                        lat,lon=float(elem.get('lat','nan')),float(elem.get('lon','nan'))
                        if not all(math.isfinite(v) for v in (lat,lon)) or not (-90<=lat<=90 and -180<=lon<=180):raise ValueError('Invalid node coordinates in OSM response.')
                    counts[keys[elem.tag]]+=1
                    if progress and sum(counts.values())%5000==0:progress(90,'Checking OSM XML',f"{sum(counts.values()):,} objects")
                if elem.tag!='bounds':outgoing.write(ET.tostring(elem,encoding='utf-8')+b'\n')
                root.remove(elem);elem.clear()
            depth-=1
        if root is None:raise ValueError('The OSM service returned an empty response.')
        outgoing.write(b'</osm>\n');outgoing.flush();os.fsync(outgoing.fileno())
    return counts


def fetch_part(bounds,raw,prepared,endpoint,cancel,opener,update):
    request=urllib.request.Request(endpoint,data=urllib.parse.urlencode({'data':query_for(bounds)}).encode(),headers={'User-Agent':USER_AGENT,'Accept':'application/xml','Content-Type':'application/x-www-form-urlencoded'})
    for attempt in range(2):
        received=0;total=0;headers={}
        try:
            with raw.open('wb') as out:
                for chunk in _chunks(request,cancel,opener,headers):
                    out.write(chunk);received+=len(chunk)
                    total=int(headers.get('Content-Length',headers.get('content-length','0')) or 0)
                    update(None,'Downloading OSM XML',f'{received/1048576:.2f} MB received for this part')
            if total and received!=total:raise ValueError('The OSM response was truncated. Existing files were kept.')
            return rewrite_xml(raw,prepared,bounds,cancel,update)
        except urllib.error.HTTPError as exc:
            code=exc.code
            retry_after=exc.headers.get('Retry-After') if exc.headers else None
            exc.close()
            if code==504:raise AreaTooLarge('OSM service could not process this area (HTTP 504).') from exc
            if code in (429,502,503) and attempt==0:
                try: delay=max(15,float(retry_after or 15))
                except ValueError:
                    try: delay=max(15,(parsedate_to_datetime(retry_after)-datetime.now(timezone.utc)).total_seconds())
                    except (TypeError,ValueError): delay=15
                if not math.isfinite(delay) or delay>120:
                    raise ValueError(f'OSM service is busy (HTTP {code}). Retry later; existing files were kept.') from exc
                update(None,'Waiting for OSM service',f'Server busy; retrying in {delay:g} seconds. You can cancel.')
                wait_for_service(delay,cancel)
                continue
            raise ValueError(f'OSM service is busy (HTTP {code}). Retry later; existing files were kept.' if code in (429,502,503) else f'OSM download failed (HTTP {code}). Existing files were kept.') from exc
        except (urllib.error.URLError,TimeoutError) as exc:
            raise ValueError('Could not reach the OSM data service. Check the connection or retry later. Existing files were kept.') from exc


def merge_parts(parts,target,bounds,database,cancel,update):
    """Disk-backed deduplication retains ordered references and outside members."""
    keys={'node':'nodes','way':'ways','relation':'relations'}
    counts={key:0 for key in keys.values()}
    with closing(sqlite3.connect(database)) as db:
        db.execute('CREATE TABLE objects (kind TEXT, id TEXT, xml BLOB, signature TEXT, PRIMARY KEY(kind,id))')
        for part in parts:
            root=None;depth=0
            with part.open('rb') as incoming:
                for event,elem in ET.iterparse(SafeXmlReader(incoming,cancel),events=('start','end')):
                    if event=='start':
                        depth+=1
                        if root is None:root=elem
                        continue
                    if depth==2:
                        check(cancel)
                        if elem.tag in keys:
                            # Whitespace and attribute ordering are not OSM content.
                            signature=json.dumps([sorted(elem.attrib.items()),[(child.tag,sorted(child.attrib.items())) for child in elem]],ensure_ascii=False)
                            previous=db.execute('SELECT signature FROM objects WHERE kind=? AND id=?',(elem.tag,elem.get('id'))).fetchone()
                            if previous and previous[0]!=signature:
                                raise ValueError('OSM data changed between downloaded parts. Retry the download; existing files were kept.')
                            if not previous:
                                elem.tail=None
                                db.execute('INSERT INTO objects VALUES (?,?,?,?)',(elem.tag,elem.get('id'),ET.tostring(elem,encoding='utf-8'),signature))
                                counts[keys[elem.tag]]+=1
                                if sum(counts.values())%5000==0:update(90,'Combining OSM parts',f"{sum(counts.values()):,} unique objects")
                        root.remove(elem);elem.clear()
                    depth-=1
            db.commit()
        with target.open('wb') as outgoing:
            outgoing.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="Druttzen-OSM-TF3-Converter">\n')
            outgoing.write(ET.tostring(ET.Element('bounds',dict(zip(('minlat','minlon','maxlat','maxlon'),map(lambda v:format(v,'.17g'),bounds)))),encoding='utf-8')+b'\n')
            for kind in keys:
                for (xml,) in db.execute('SELECT xml FROM objects WHERE kind=? ORDER BY rowid',(kind,)):
                    check(cancel);outgoing.write(xml+b'\n')
            outgoing.write(b'</osm>\n');outgoing.flush();os.fsync(outgoing.fileno())
    return counts

def download(bounds,size,target,endpoint=OVERPASS,coverage=1,progress=None,cancel=None,opener=None,overview=None):
    bounds=list(bounds);size=list(size);validate_bounds(bounds,size);https_url(endpoint)
    if not math.isfinite(coverage) or not 0.01<=coverage<=100:raise ValueError('Invalid area scale.')
    target=Path(target).resolve()
    if target.suffix.lower()!='.osm':raise ValueError('Save downloaded OSM XML as a .osm file.')
    target.parent.mkdir(parents=True,exist_ok=True)
    report_path=target.with_suffix('.download.json')
    pending=download_parts(bounds)
    staging=Path(tempfile.mkdtemp(prefix='.osm-download-',dir=target.parent))
    raw=staging/'response.xml';prepared=staging/target.name;preserve_staging=False
    def update(percent,stage,detail=''):
        check(cancel)
        if progress:progress(percent,stage,detail)
    try:
        update(None,'Waiting for OSM service','You can cancel while the server prepares the area')
        completed=[];part_bounds=[];requests=0
        def counted_opener(*args,**kwargs):
            nonlocal requests
            if requests>=MAX_REQUESTS:
                raise ValueError('OSM download request limit reached. Retry later or use a regional .osm extract. Existing files were kept.')
            requests+=1
            return (opener or urllib.request.urlopen)(*args,**kwargs)
        while pending:
            part=pending.pop(0)
            update(None,'Downloading OSM area',f'Part {len(completed)+1} of {len(completed)+len(pending)+1}; parts are downloaded one at a time')
            part_file=staging/f'part-{len(completed)}.osm'
            try:
                counts=fetch_part(part,raw,part_file,endpoint,cancel,counted_opener,update)
            except AreaTooLarge as exc:
                if max(ground_extent(part))<=1000 or len(completed)+len(pending)+2>MAX_PARTS:
                    raise ValueError('OSM service is busy or this area is too dense. Retry later or use a regional .osm extract. Existing files were kept.') from exc
                update(None,'Splitting a busy OSM area','Retrying as two smaller parts; you can cancel')
                wait_for_service(5,cancel)
                pending[0:0]=smaller_parts(part)
                continue
            completed.append(part_file);part_bounds.append(part)
        update(85,'Checking OSM XML')
        if len(completed)==1:
            os.replace(completed[0],prepared)
        else:
            counts=merge_parts(completed,prepared,bounds,staging/'objects.sqlite',cancel,update)
        digest=hashlib.sha256()
        with prepared.open('rb') as file:
            while chunk:=file.read(1048576):check(cancel);digest.update(chunk)
        report={'format':'Druttzen-OSM-download','version':1,'createdUtc':datetime.now(timezone.utc).isoformat(),'bounds':bounds,'mapSize':size,'groundAreaScaleAtCentre':coverage,'source':'OpenStreetMap via Overpass','endpoint':endpoint,'counts':counts,'osmSha256':digest.hexdigest(),'output':str(target),'licence':'ODbL 1.0','attribution':'© OpenStreetMap contributors','copyrightUrl':'https://www.openstreetmap.org/copyright','geometryNote':'Complete referenced geometry may extend outside the selection. The converter clips it to the locked bounds.'}
        report['downloadParts']=part_bounds;report['requestCount']=requests
        files=[(prepared,target,staging/'previous.osm')]
        if overview is not None:
            from map_overview import save_overview
            update(94,'Creating map overview PNG')
            overview_path=target.with_suffix('.overview.png');staged_overview=staging/overview_path.name
            report['overview']=str(overview_path)
            report['overviewMetadata']=save_overview(staged_overview,bounds,size,overview,cancel)
            report['overviewSha256']=hashlib.sha256(staged_overview.read_bytes()).hexdigest()
            files.append((staged_overview,overview_path,staging/'previous.overview.png'))
        staged_report=staging/report_path.name;staged_report.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        files.append((staged_report,report_path,staging/'previous.download.json'))
        update(98,'Saving OSM XML, overview and download log' if overview is not None else 'Saving OSM XML and download log')
        backups={}
        for _,destination,backup in files:
            check(cancel)
            if destination.exists():shutil.copy2(destination,backup);backups[destination]=backup
        check(cancel)
        committed=[]
        try:
            for source,destination,_ in files:
                os.replace(source,destination);committed.append(destination)
        except OSError:
            errors=[]
            for destination in reversed(committed):
                try:
                    if destination in backups:os.replace(backups[destination],destination)
                    else:destination.unlink()
                except OSError as restore:errors.append(restore)
            if errors:
                preserve_staging=True
                raise RuntimeError(f'Could not restore the previous download files. Backup retained in {staging}') from errors[0]
            raise
        report['log']=str(report_path)
        # A completed final commit is successful even if cancellation arrives now.
        if progress:progress(100,'OSM download complete',f"{counts['nodes']:,} nodes · {counts['ways']:,} ways · {counts['relations']:,} relations")
        return report
    finally:
        # Keep backup evidence if the filesystem also prevents restoration.
        if not preserve_staging:shutil.rmtree(staging)

class TileCache:
    def __init__(self,folder,url=TILES,opener=None):
        self.folder=Path(folder);self.url=url;https_url(url.format(z=0,x=0,y=0));self.opener=opener or urllib.request.urlopen
        self.namespace=hashlib.sha256(url.encode()).hexdigest()[:16]
    def get(self,z,x,y,cancel=None):
        check(cancel)
        folder=self.folder/self.namespace/str(z)/str(x);path=folder/f'{y}.png';meta=folder/f'{y}.json';now=time.time()
        info={}
        if path.exists():
            try:
                data=path.read_bytes()
                with Image.open(io.BytesIO(data)) as image:
                    if image.format!='PNG' or image.size!=(256,256):raise ValueError('Invalid cached tile')
                    image.verify()
                try:info=json.loads(meta.read_text())
                except (OSError,ValueError):pass
                if float(info.get('expires',path.stat().st_mtime+7*86400))>now:return data
            except (OSError,ValueError):info={}
        headers={'User-Agent':USER_AGENT,'Accept':'image/png'}
        if info.get('etag'):headers['If-None-Match']=info['etag']
        if info.get('modified'):headers['If-Modified-Since']=info['modified']
        request=urllib.request.Request(self.url.format(z=z,x=x,y=y),headers=headers)
        try:
            with self.opener(request,timeout=15) as response:
                https_url(response.geturl());data=response.read(1048577)
                if len(data)>1048576:raise ValueError('Map tile is too large.')
                with Image.open(io.BytesIO(data)) as image:
                    if image.format!='PNG' or image.size!=(256,256):raise ValueError('Invalid map tile response.')
                    image.verify()
                info={'expires':now+7*86400,'etag':response.headers.get('ETag'),'modified':response.headers.get('Last-Modified')}
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code!=304 or not path.exists():raise
            data=path.read_bytes();info['expires']=now+7*86400
        check(cancel);folder.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(dir=folder,prefix=f'{y}.')
        try:
            with os.fdopen(fd,'wb') as file:file.write(data)
            os.replace(tmp,path);meta.write_text(json.dumps(info),encoding='utf-8')
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return data

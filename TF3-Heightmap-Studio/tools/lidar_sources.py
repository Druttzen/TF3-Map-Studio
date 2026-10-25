"""OSM-AOI discovery of public regional ground DEMs and global LiDAR catalogs.

Provider contracts are linked in LIDAR-SOURCES.md. Discovery never substitutes
satellite DSMs for LiDAR or claims complete global coverage. GPL-3.0.
"""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import hashlib,json,math,os,queue,ssl,tempfile,threading,time,xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import certifi
from alignment import read_report,osm
from providers import fetch_geotiff,expanded_bounds
from job import Job

LM_SEARCH='https://api.lantmateriet.se/stac-hojd/v1/search'
LM_SITE='https://geotorget.lantmateriet.se/geodataprodukter/markhojdmodell-nedladdning-api'
USGS_SEARCH='https://tnmaccess.nationalmap.gov/api/v1/products'
USGS_SITE='https://www.usgs.gov/tools/lidarexplorer'
OT_CATALOG='https://portal.opentopography.org/stac/raster_catalog.json'
OT_SEARCH='https://portal.opentopography.org/API/otCatalog'
OT_SITE='https://opentopography.org/developers'
PROVIDERS=['All available regions','Sweden (Lantmäteriet)','USA (USGS 1 m)','Worldwide (OpenTopography)','Automatic for map']
CATALOG_MAX_ASSETS=4096
DISCOVERY_CACHE_SECONDS=86400
_CATALOG_SLOTS=threading.BoundedSemaphore(6)
# Verified catalog IDs of the broad satellite/ensemble/bathymetry products.
# They remain available through Elevation, never presented as fine LiDAR.
COARSE_RASTER_IDS={'OTALOS.112016.4326.2','OTALOS.082017.4326.1','OTSDEM.032025.3979.1',
 'OTSDEM.032021.4326.3','OTSDEM.032021.4326.1','OTSDEM.122023.4326.1','OTSDEM.122023.4326.2',
 'OTSDEM.082025.4326.1','OTSDEM.032021.4326.2','OTSRTM.122019.4326.1','OTSRTM.082015.4326.1',
 'OTSRTM.082016.4326.1','OTSRTM.042013.4326.1'}

def area_bounds(report_path='',osm_path='',job=None):
 # A converter report owns the chosen crop. Raw OSM bounds are a search-only
 # fallback; exporting still requires the normal checksum/alignment contract.
 if report_path:return read_report(report_path)['bounds']
 if not osm_path:raise ValueError('Choose an OSM/XML file or its converter report first.')
 job=job or Job();minimum=[float('inf'),float('inf')];maximum=[-float('inf'),-float('inf')];explicit=None
 with Path(osm_path).open('rb') as source:
  iterator=ET.iterparse(source,events=['start','end']);_,root=next(iterator);count=0
  for event,element in iterator:
   if event!='end':continue
   job.check()
   if element.tag=='bounds':
    value=[float(element.attrib[k]) for k in ['minlat','minlon','maxlat','maxlon']]
    if explicit is not None and value!=explicit:raise ValueError('OSM contains conflicting bounds.')
    explicit=value
   elif element.tag=='node':
    lat=float(element.attrib['lat']);lon=float(element.attrib['lon'])
    minimum=[min(minimum[0],lat),min(minimum[1],lon)];maximum=[max(maximum[0],lat),max(maximum[1],lon)]
   element.clear()
   count+=1
   if count%1024==0:root.clear()
 bounds=explicit or minimum+maximum;osm.validate_bounds(bounds,[1,1]);return bounds

def safe_url(url):
 parts=urlsplit(url)
 if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:raise ValueError('Data service must use HTTPS without embedded credentials.')
 return url

def fetch_json(url,job=None):
 safe_url(url);job=job or Job();job.check()
 packets=queue.Queue(maxsize=1);stop=threading.Event()
 def worker():
  acquired=False
  try:
   while not stop.is_set():
    if _CATALOG_SLOTS.acquire(timeout=.1):acquired=True;break
   if not acquired or stop.is_set():return
   context=ssl.create_default_context(cafile=certifi.where())
   if stop.is_set():return
   with urlopen(Request(url,headers={'User-Agent':'TF3-Heightmap-Studio/0.11'}),timeout=25,context=context) as response:
    safe_url(response.geturl());parts=[];total=0
    while not stop.is_set():
     chunk=response.read(65536)
     if not chunk:break
     total+=len(chunk)
     if total>16*1024*1024:raise ValueError('Data catalog response exceeded 16 MB.')
     parts.append(chunk)
    if stop.is_set():return
    value=json.loads(b''.join(parts))
    if not isinstance(value,dict):raise ValueError('Data catalog did not return a JSON object.')
    packets.put_nowait(('ok',value))
  except (HTTPError,URLError,TimeoutError,json.JSONDecodeError) as exc:
   code=f' (HTTP {exc.code})' if isinstance(exc,HTTPError) else ''
   if isinstance(exc,HTTPError):exc.close()
   packets.put_nowait(('error',ValueError('Data catalog could not be read'+code+'. Check access or try another source.')))
  except Exception as exc:packets.put_nowait(('error',exc))
  finally:
   if acquired:_CATALOG_SLOTS.release()
 threading.Thread(target=worker,daemon=True).start()
 try:
  while True:
   job.check()
   try:kind,value=packets.get(timeout=.1)
   except queue.Empty:continue
   if kind=='error':raise value
   return value
 finally:stop.set()

def intersects(a,b):
 return all(isinstance(box,(list,tuple)) and len(box)>=4 and all(type(v) in (int,float) and math.isfinite(v) for v in box[:4]) for box in (a,b)) and a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]

def stac_bbox(bounds):return [bounds[1],bounds[0],bounds[3],bounds[2]]

def tile_access(row,limit,truncated=False):
 count=len(row['assets']);blocked=count>limit or truncated
 row.update(tileCount=count,downloadBlocked=blocked,requiredTileLimit=count,catalogTruncated=truncated)
 if truncated:
  row.update(tileCountAtLeast=count+1,downloadHint=f'More than {count} map tiles were found. Narrow the map before downloading.')
 elif blocked:row['downloadHint']=f'This map needs {count} tiles; the current download limit is {limit}. Increase the tile limit before downloading.'
 else:row['downloadHint']=f'{count} map tiles are within the download limit.'
 return row

def sweden(bounds,job,limit):
 bbox=stac_bbox(expanded_bounds(bounds));url=LM_SEARCH+'?'+urlencode({'bbox':','.join(map(str,bbox)),'collections':'dtm-cog','limit':100})
 assets=[];seen=set();visited=set();truncated=False
 while url:
  if url in visited:raise ValueError('Lantmäteriet catalog pagination repeated a page.')
  if len(visited)>=100:raise ValueError('Lantmäteriet catalog exceeded 100 pages. Narrow the map before searching again.')
  visited.add(url);data=fetch_json(url,job)
  for feature in data.get('features',[]):
   if feature.get('collection','dtm-cog')!='dtm-cog':continue
   asset=feature.get('assets',{}).get('data',{});href=asset.get('href','')
   if not href or href in seen or not intersects(feature.get('bbox',[]),bbox):continue
   if not urlsplit(href).path.lower().endswith(('.tif','.tiff')):continue
   safe_url(href)
   if urlsplit(href).hostname not in {'dl1.lantmateriet.se','dl2.lantmateriet.se'} or urlsplit(href).port not in (None,443):raise ValueError('Unexpected Lantmäteriet asset host. Access credentials were not sent.')
   if len(assets)>=CATALOG_MAX_ASSETS:truncated=True;break
   properties=feature.get('properties',{})
   seen.add(href);assets.append({'url':href,'bytes':asset.get('file:size'), 'bbox':feature['bbox'],'date':properties.get('datetime',''),
                               'resolutionMetres':properties.get('geometriskupplosning'),
                               'heightUncertaintyMetres':properties.get('lagesosakerhethojd'),
                               'surveyMethod':properties.get('huvudsakliglagesbestamningsmetod')})
  if truncated:break
  url=next((x['href'] for x in data.get('links',[]) if x.get('rel')=='next'),None)
  if url and urlsplit(url).hostname!='api.lantmateriet.se':raise ValueError('Unexpected catalog pagination host.')
 if not assets:return []
 assets.sort(key=lambda a:a['date'],reverse=True)
 return [tile_access({'id':'lm-ground-1m','name':f'Lantmäteriet ground model 1 m · {len(assets)} tiles','provider':'Lantmäteriet','assets':assets,'access':'account',
          'resolution':'1 m cells; measured uncertainty varies','verticalDatum':'RH2000','site':LM_SITE,'attribution':LM_SITE,'surface':'Ground model from laser scanning / photogrammetry; see tile origin metadata'},limit,truncated)]

def usa(bounds,job,limit):
 bbox=stac_bbox(expanded_bounds(bounds));offset=0;assets=[];seen=set();truncated=False
 while True:
  data=fetch_json(USGS_SEARCH+'?'+urlencode({'bbox':','.join(map(str,bbox)),'datasets':'Digital Elevation Model (DEM) 1 meter','max':100,'offset':offset,'outputFormat':'JSON'}),job)
  items=data.get('items',[])
  for item in items:
   href=item.get('downloadURL','');box=item.get('boundingBox',{});tile=[box.get(k,0) for k in ['minX','minY','maxX','maxY']]
   if href in seen or item.get('format')!='GeoTIFF' or not intersects(tile,bbox):continue
   safe_url(href)
   if urlsplit(href).hostname!='prd-tnm.s3.amazonaws.com':continue
   if len(assets)>=CATALOG_MAX_ASSETS:truncated=True;break
   seen.add(href);assets.append({'url':href,'bytes':item.get('sizeInBytes'),'bbox':tile,'date':item.get('dateCreated','')})
  if truncated:break
  offset+=len(items)
  if not items or offset>=data.get('total',offset):break
  if offset>=10000:raise ValueError('USGS search exceeded 10,000 records. Narrow the map.')
 if not assets:return []
 assets.sort(key=lambda a:a['date'],reverse=True)
 return [tile_access({'id':'usgs-ground-1m','name':f'USGS 3DEP ground DEM 1 m · {len(assets)} tiles','provider':'USGS','assets':assets,'access':'open',
          'resolution':'1 m cells; source quality varies','verticalDatum':'Read GeoTIFF / project metadata','site':USGS_SITE,'attribution':'U.S. Geological Survey, 3DEP / The National Map. '+USGS_SITE,'surface':'Ground DEM, regional coverage'},limit,truncated)]

def ot_collections(cache,job):
 cache=Path(cache);cache.mkdir(parents=True,exist_ok=True);path=cache/'ot-collections.json'
 if path.exists() and time.time()-path.stat().st_mtime<7*86400:
  try:
   data=json.loads(path.read_text());
   if isinstance(data,list) and all(isinstance(x,dict) for x in data):return data,[]
  except (OSError,ValueError):pass
 root=fetch_json(OT_CATALOG,job);links=[x['href'] for x in root.get('links',[]) if x.get('rel')=='child']
 if len(links)>1000:raise ValueError('OpenTopography catalog is larger than the supported search limit.')
 for url in links:
  if urlsplit(url).hostname!='portal.opentopography.org':raise ValueError('Unexpected OpenTopography collection host.')
 results=[];errors=[]
 def read(url):
  try:return fetch_json(url,job)
  except ValueError:return None
 with ThreadPoolExecutor(max_workers=6) as pool:
  for index,result in enumerate(pool.map(read,links)):
   job.update(5+20*(index+1)/max(1,len(links)),'Searching global LiDAR catalog',f'{index+1}/{len(links)} regions')
   if result:results.append(result)
   else:errors.append('Some OpenTopography regions could not be read; the search is incomplete.')
 if not errors:
  fd,name=tempfile.mkstemp(prefix='.catalog-',dir=cache)
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump(results,out)
   os.replace(name,path)
  finally:
   if Path(name).exists():Path(name).unlink()
 return results,list(dict.fromkeys(errors))

def worldwide(bounds,job,limit,cache):
 bbox=stac_bbox(expanded_bounds(bounds));collections,warnings=ot_collections(cache,job);rows=[]
 for collection in collections:
  if collection.get('id') in COARSE_RASTER_IDS:continue
  if not any(intersects(box,bbox) for box in collection.get('extent',{}).get('spatial',{}).get('bbox',[])):continue
  assets=[];seen=set();truncated=False
  # Only the provider's explicit bare-earth products qualify as ground data.
  for link in collection.get('links',[]):
   href=link.get('href','')
   if link.get('rel')!='item' or not href.endswith('_be.json'):continue
   if urlsplit(href).hostname!='portal.opentopography.org':continue
   try:item=fetch_json(href,job)
   except ValueError as exc:
    warnings.append(collection.get('title','OpenTopography')+': '+str(exc));continue
   for asset in item.get('assets',{}).values():
    url=asset.get('href','')
    if url in seen or 'data' not in asset.get('roles',[]) or 'image/tiff' not in asset.get('type','') or not intersects(asset.get('bbox',item.get('bbox',[])),bbox):continue
    safe_url(url)
    if len(assets)>=CATALOG_MAX_ASSETS:truncated=True;break
    seen.add(url);assets.append({'url':url,'bytes':asset.get('file:size'),'bbox':asset.get('bbox',item.get('bbox',[]))})
   if truncated:break
  if assets:rows.append(tile_access({'id':collection['id'],'name':collection.get('title',collection['id'])+f' · ground DEM · {len(assets)} tiles',
                       'provider':'OpenTopography','assets':assets,'access':'unknown','resolution':'See dataset documentation','verticalDatum':'See dataset documentation',
                       'site':next((x['href'] for x in collection.get('links',[]) if x.get('rel')=='about'),OT_SITE),
                       'attribution':collection.get('sci:citation','')+' Licence: '+collection.get('license','See dataset terms'),'surface':'Provider bare-earth DEM derived from regional surveys'},limit,truncated))
 # Raw-point coverage is searchable worldwide, but the portal may require an
 # account/processing request. Never invent a downloadable URL from its DOI.
 query={'minx':bbox[0],'miny':bbox[1],'maxx':bbox[2],'maxy':bbox[3],'productFormat':'PointCloud','detail':'false','outputFormat':'json'}
 try:
  data=fetch_json(OT_SEARCH+'?'+urlencode(query),job)
  for item in data.get('Datasets',[]):
   d=item.get('Dataset',{});identifier=d.get('identifier',{}).get('value','')
   if identifier:rows.append({'id':identifier,'name':d.get('name',identifier)+' · raw point catalog','provider':'OpenTopography','assets':[],
                            'access':'portal','resolution':'Point density varies','verticalDatum':'See survey documentation','site':d.get('url',OT_SITE),'attribution':d.get('citation',''),'surface':'Raw point cloud; download LAS/LAZ via provider, then Add files'})
 except ValueError as exc:warnings.append(str(exc))
 return rows,warnings

def _discovery_cache(bounds,provider,limit,cache):
 identity={'version':2,'bounds':list(bounds),'provider':provider,'tileLimit':limit,
           'sources':[LM_SEARCH,USGS_SEARCH,OT_CATALOG,OT_SEARCH],'lmCollection':'dtm-cog'}
 key=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return Path(cache)/('discovery-'+key+'.json'),identity


def discover(bounds,provider,options,cache,job=None):
 job=job or Job();job.check();osm.validate_bounds(bounds,[1,1]);limit=options['public_max_tiles']
 if provider not in PROVIDERS:raise ValueError('Unknown LiDAR catalog.')
 original_provider=provider
 box=stac_bbox(bounds)
 if provider==PROVIDERS[-1]:
  provider=PROVIDERS[1] if intersects(box,[10,55,25,70]) else PROVIDERS[2] if intersects(box,[-180,17,-65,75]) else PROVIDERS[3]
 path,identity=_discovery_cache(bounds,original_provider,limit,cache)
 try:
  if path.is_file() and path.stat().st_size<=32*1024*1024:
   saved=json.loads(path.read_text(encoding='utf-8'))
   if not isinstance(saved,dict) or not isinstance(saved.get('result'),dict):raise ValueError('Invalid discovery cache')
   age=time.time()-saved['created']
   result=saved['result']
   valid_rows=isinstance(result.get('rows'),list) and all(isinstance(row,dict) and isinstance(row.get('assets'),list) and all(isinstance(row.get(k),str) for k in ('id','name','provider','access','resolution','verticalDatum','site','surface')) for row in result['rows'])
   if saved['identity']==identity and 0<=age<DISCOVERY_CACHE_SECONDS and result.get('complete') is True and valid_rows:
    job.check();job.update(25,'Using cached elevation search',provider)
    return {**result,'fromCache':True,'cacheAgeSeconds':round(age)}
 except (OSError,ValueError,KeyError,TypeError):pass
 searches=[]
 if provider==PROVIDERS[1] or provider==PROVIDERS[0] and intersects(box,[10,55,25,70]):searches.append(('Lantmäteriet',lambda child: (sweden(bounds,child,limit),[])))
 if provider==PROVIDERS[2] or provider==PROVIDERS[0] and intersects(box,[-180,17,-65,75]):searches.append(('USGS',lambda child:(usa(bounds,child,limit),[])))
 if provider in (PROVIDERS[0],PROVIDERS[3]):searches.append(('OpenTopography',lambda child:worldwide(bounds,child,limit,cache)))
 rows=[];warnings=[];results={};pool=ThreadPoolExecutor(max_workers=3)
 try:
  pending={pool.submit(search,Job(cancel=job.cancel)):name for name,search in searches}
  job.update(5,'Searching elevation coverage',', '.join(pending.values()))
  while pending:
   job.check();finished,_=wait(pending,timeout=.1,return_when=FIRST_COMPLETED)
   for future in finished:
    name=pending.pop(future)
    try:results[name]=future.result()
    except ValueError as exc:results[name]=([], [name+': '+str(exc)])
   if finished:job.update(5+20*len(results)/max(1,len(searches)),'Searching elevation coverage',', '.join(pending.values()) or 'Search complete')
 finally:pool.shutdown(wait=False,cancel_futures=True)
 for name,_ in searches:
  found,notes=results[name];rows.extend(found);warnings.extend(notes)
 for row in rows:
  if row.get('catalogTruncated'):warnings.append(row['provider']+': '+row['downloadHint'])
 result={'bounds':list(bounds),'rows':rows,'warnings':warnings,'complete':not warnings,
         'fromCache':False,'cacheAgeSeconds':0,'providersSearched':[name for name,_ in searches],
         'requestedProvider':original_provider,'selectedProvider':provider}
 if result['complete']:
  # Cache contains public catalog metadata only; credentials never enter discovery.
  temporary=None
  try:
   path.parent.mkdir(parents=True,exist_ok=True)
   fd,temporary=tempfile.mkstemp(prefix='.discovery-',dir=path.parent)
   with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump({'created':time.time(),'identity':identity,'result':result},out)
   job.check();os.replace(temporary,path)
  except OSError:pass
  finally:
   if temporary and Path(temporary).exists():Path(temporary).unlink()
 return result

def download_selection(selection,bounds,options,cache,job=None,credentials=None):
 job=job or Job();assets=selection.get('assets',[]);cache=Path(cache);files=[]
 if selection.get('catalogTruncated'):raise ValueError('The catalog search was incomplete. Narrow the map and search again before downloading.')
 if not assets:raise ValueError('This entry is a raw-data catalog. Open its provider, download LAS/LAZ and use Add files.')
 if len(assets)>options['public_max_tiles']:raise ValueError('Selected dataset exceeds the tile limit.')
 headers=None
 if selection['provider']=='Lantmäteriet':
  import base64
  if not credentials or not all(credentials):raise ValueError('Lantmäteriet needs your approved Geotorget API username/password. An email or ordinary website password alone does not grant data access.')
  if any(urlsplit(a['url']).hostname not in {'dl1.lantmateriet.se','dl2.lantmateriet.se'} or urlsplit(a['url']).port not in (None,443) for a in assets):raise ValueError('Unexpected access host; credentials were not sent.')
  headers={'Authorization':'Basic '+base64.b64encode((credentials[0]+':'+credentials[1]).encode()).decode()}
 for i,asset in enumerate(assets):
  job.check();url=safe_url(asset['url'])
  if not intersects(asset.get('bbox',stac_bbox(bounds)),stac_bbox(expanded_bounds(bounds))):continue
  if asset.get('bytes') and asset['bytes']>options['download_max_mb']*1048576:raise ValueError('A selected tile exceeds the per-file download limit. Increase the limit or choose another dataset.')
  target=cache/'downloads'/(hashlib.sha256(url.encode()).hexdigest()[:24]+'.tif')
  metadata={k:selection.get(k) for k in ['provider','id','site','attribution','surface','verticalDatum']};metadata['requestBounds']=list(bounds)
  for key in ('resolutionMetres','heightUncertaintyMetres','surveyMethod'):
   if asset.get(key) is not None:metadata[key]=asset[key]
  files.append(fetch_geotiff(url,target,job,i,len(assets),options['download_max_mb'],selection['provider']+f' tile {i+1}',metadata,headers=headers))
 if not files:raise ValueError('Selected data does not intersect this map. Search again after changing the map.')
 return files

"""Elevation provider plans and validated local downloads. GPL-3.0."""
from datetime import datetime,timezone
import hashlib,json,math,os,ssl,tempfile
from pathlib import Path
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen,build_opener,HTTPSHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
import certifi,rasterio
from rasterio.warp import transform_bounds
from elevation import download_tiles,tile_names,PUBLIC_DOC,PUBLIC_LICENSE
from alignment import osm,mercator_bounds
from job import Job

COP_DOC='https://registry.opendata.aws/copernicus-dem/'
OT_DOC='https://opentopography.org/developers'
COP_CREDIT='Produced using Copernicus WorldDEM: © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM. https://registry.opendata.aws/copernicus-dem/'
OT_DATASETS=['COP30','COP90','SRTMGL1','SRTMGL3','AW3D30','NASADEM','EU_DTM','USGS10m','USGS30m']


def expanded_bounds(bounds):
 # Allow interpolation at map corner vertices even when a provider crops at
 # cell edges or removes a duplicated edge row. Output bounds remain exact.
 south,west,north,east=bounds;dy=.002;dx=dy/max(.08,math.cos(math.radians((south+north)/2)))
 return [max(-85+1e-8,south-dy),max(-180,west-dx),min(85-1e-8,north+dy),min(180,east+dx)]


def parse_urls(text):
 urls=text.split()
 if not urls:raise ValueError('Paste one or more public, direct GeoTIFF URLs in the Elevation tab.')
 for url in urls:
  p=urlsplit(url)
  if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Direct DEM links must be HTTPS URLs without embedded login credentials.')
 return list(dict.fromkeys(urls))


def download_plan(bounds,options):
 osm.validate_bounds(bounds,[1,1]);mode=options['source_mode'];p={'provider':mode,'mapBounds':list(bounds),'requestBounds':list(bounds),'requests':[],'site':''}
 if mode=='Local elevation files':return p
 if mode=='Download public terrain (Mapzen)':
  p['site']=PUBLIC_DOC;p['requests']=[{'tile':n} for n in tile_names(bounds)]
 elif mode in ['Download Copernicus GLO-30','Download Copernicus GLO-90']:
  resolution=30 if mode.endswith('30') else 90;code='10' if resolution==30 else '30';p['site']=COP_DOC;p['requestBounds']=expanded_bounds(bounds)
  for n in tile_names(p['requestBounds']):
   stem=f'Copernicus_DSM_COG_{code}_{n[:3]}_00_{n[3:]}_00_DEM'
   p['requests'].append({'tile':n,'filename':stem+'.tif','url':f'https://copernicus-dem-{resolution}m.s3.amazonaws.com/{stem}/{stem}.tif'})
 elif mode=='Download OpenTopography':
  p['site']=OT_DOC;p['requestBounds']=expanded_bounds(bounds);p['requests']=[{'dataset':options['opentopo_dataset']}]
 elif mode=='Download direct GeoTIFF links':
  p['requests']=[{'url':u} for u in parse_urls(options['dem_urls'])]
 else:raise ValueError('Unsupported elevation source.')
 if len(p['requests'])>options['public_max_tiles']:raise ValueError(f'This area/source requires {len(p["requests"])} downloads, above the configured limit of {options["public_max_tiles"]}.')
 return p


def validate_geotiff(path):
 with rasterio.open(path) as src:
  if src.driver!='GTiff' or not src.crs or src.count<1 or src.width<2 or src.height<2:raise ValueError('The source did not return a georeferenced elevation GeoTIFF. Use a direct DEM file link, not an HTML download page.')
  # A small pixel read detects truncated or corrupt tiles before cache commit.
  src.read(1,window=rasterio.windows.Window(0,0,min(16,src.width),min(16,src.height)))
  src.read(1,window=rasterio.windows.Window(max(0,src.width-16),max(0,src.height-16),min(16,src.width),min(16,src.height)))


class ScopedRedirect(HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  before=urlsplit(req.full_url);after=urlsplit(newurl)
  if after.scheme!='https':raise ValueError('Elevation server redirected to a non-HTTPS address.')
  redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
  if (before.hostname,before.port)!=(after.hostname,after.port):redirected.remove_header('Authorization')
  return redirected

def file_sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def fetch_geotiff(url,target,job,index,total,maximum_mb,label,metadata,headers=None):
 target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():
  try:
   validate_geotiff(target)
   info=target.with_suffix('.download.json')
   if info.exists() and json.loads(info.read_text()).get('sha256')!=file_sha(target):raise ValueError('Cached elevation checksum differs.')
   job.update(21+14*(index+1)/total,'Using cached elevation',label);return target
  except (OSError,ValueError,rasterio.errors.RasterioError):pass
 fd,tmp=tempfile.mkstemp(prefix='.download-',suffix='.tif',dir=target.parent);temporary=Path(tmp)
 try:
  try:
   context=ssl.create_default_context(cafile=certifi.where());request=Request(url,headers={'User-Agent':'TF3-Heightmap-Studio/0.7',**(headers or {})})
   with os.fdopen(fd,'wb') as output,(build_opener(HTTPSHandler(context=context),ScopedRedirect()).open(request,timeout=30) if headers else urlopen(request,timeout=30,context=context)) as response:
    if hasattr(response,'geturl') and urlsplit(response.geturl()).scheme!='https':raise ValueError('Elevation server redirected to a non-HTTPS address.')
    size=int(response.headers.get('Content-Length','0'));limit=maximum_mb*1024*1024;received=0
    if size>limit:raise ValueError(f'{label}: exceeds the {maximum_mb:g} MB per-file download limit.')
    while True:
     job.check();chunk=response.read(131072)
     if not chunk:break
     received+=len(chunk)
     if received>limit:raise ValueError(f'{label}: exceeds the per-file download limit.')
     output.write(chunk);fraction=min(.98,received/size) if size else min(.95,received/limit)
     job.update(21+14*(index+fraction)/total,'Downloading elevation',f'{label}: {received/1048576:.1f} MB')
    if size and size!=received:raise ValueError('Elevation download ended before the full file arrived.')
  except HTTPError as exc:
   if exc.code in [401,403]:raise ValueError(f'{label}: provider rejected access (HTTP {exc.code}). Check your API key or choose another provider.') from None
   if exc.code==404:raise ValueError(f'{label}: tile/file is unavailable. Copernicus public coverage excludes some land and ocean tiles; choose another source for this area.') from None
   raise ValueError(f'{label}: elevation server returned HTTP {exc.code}.') from None
  except (URLError,TimeoutError) as exc:raise ValueError(f'{label}: elevation connection failed. Check internet access and try again.') from None
  try:validate_geotiff(temporary)
  except (OSError,rasterio.errors.RasterioError):raise ValueError(f'{label}: response is not a readable elevation GeoTIFF. Check that this is a direct file URL and that the provider request succeeded.') from None
  job.check();os.replace(temporary,target)
  info={**metadata,'downloadedUtc':datetime.now(timezone.utc).isoformat(),'bytes':received,'sha256':file_sha(target)}
  target.with_suffix('.download.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
 finally:
  if temporary.exists():temporary.unlink()
 job.update(21+14*(index+1)/total,'Elevation downloaded',label);return target


def acquire(bounds,options,cache,job=None,api_key=None):
 job=job or Job();plan=download_plan(bounds,options);mode=options['source_mode'];cache=Path(cache);requests=plan['requests'];sources=[];credits=[]
 if mode=='Download public terrain (Mapzen)':
  sources=download_tiles(bounds,cache,job,options['public_max_tiles']);credits=[{'provider':'Mapzen Terrain Tiles / Skadi','site':PUBLIC_DOC,'attribution':PUBLIC_LICENSE}]
 elif mode.startswith('Download Copernicus'):
  for i,r in enumerate(requests):
   sources.append(fetch_geotiff(r['url'],cache/'copernicus'/r['filename'],job,i,len(requests),options['download_max_mb'],r['tile'],{'provider':mode,'url':r['url'],'site':COP_DOC}))
  credits=[{'provider':mode,'site':COP_DOC,'attribution':COP_CREDIT,'verticalDatum':'EGM2008','surface':'DSM includes vegetation and buildings'}]
 elif mode=='Download OpenTopography':
  dataset=options['opentopo_dataset'];south,west,north,east=plan['requestBounds'];identity=json.dumps([dataset,plan['requestBounds']],separators=(',',':'));name=hashlib.sha256(identity.encode()).hexdigest()[:24]+'.tif';target=cache/'opentopography'/name
  # API key is supplied only to this request, never serialized or included in
  # source metadata, cache filenames, progress, reports or project settings.
  if not api_key and not target.exists():raise ValueError('Enter your OpenTopography API key in Elevation. It is kept only for this app session and is not saved with projects.')
  key=api_key or '';params={'south':south,'west':west,'north':north,'east':east,'outputFormat':'GTiff','API_Key':key}
  endpoint='usgsdem' if dataset.startswith('USGS') else 'globaldem';params['datasetName' if endpoint=='usgsdem' else 'demtype']=dataset
  url='https://portal.opentopography.org/API/'+endpoint+'?'+urlencode(params)
  sources=[fetch_geotiff(url,target,job,0,1,options['download_max_mb'],'OpenTopography '+dataset,{'provider':'OpenTopography','dataset':dataset,'requestBounds':plan['requestBounds'],'site':OT_DOC})]
  credits=[{'provider':'OpenTopography '+dataset,'site':OT_DOC,'attribution':'Retain the selected dataset’s licence and provider credits from OpenTopography. '+options['source_credit']}]
 elif mode=='Download direct GeoTIFF links':
  for i,r in enumerate(requests):
   url=r['url'];name=hashlib.sha256(url.encode()).hexdigest()[:24]+'.tif';host=urlsplit(url).hostname
   sources.append(fetch_geotiff(url,cache/'direct'/name,job,i,len(requests),options['download_max_mb'],f'{host} file {i+1}',{'provider':'Direct GeoTIFF','site':'https://'+host,'resource':urlsplit(url).path}))
  credits=[{'provider':'Direct GeoTIFF downloads','site':'','attribution':options['source_credit'] or 'User-selected DEM provider; retain its licence and attribution.'}]
 else:raise ValueError('Choose a downloadable elevation source.')
 job.update(35,'Elevation sources ready',f'{len(sources)} files')
 return sources,plan,credits

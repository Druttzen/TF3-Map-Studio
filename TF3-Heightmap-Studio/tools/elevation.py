"""Local DEM and public Mapzen/Skadi acquisition and aligned sampling. GPL-3.0."""
from contextlib import ExitStack
from datetime import datetime, timezone
import gzip, json, math, os, re, ssl, tempfile
from pathlib import Path
from urllib.request import Request, urlopen
import certifi
import numpy as np
import rasterio
from rasterio import Affine
from rasterio.warp import reproject, transform, Resampling
from alignment import mercator_bounds
from job import Job

PUBLIC_URL='https://elevation-tiles-prod.s3.amazonaws.com/skadi/{prefix}/{tile}.hgt.gz'
PUBLIC_DOC='https://registry.opendata.aws/terrain-tiles/'
PUBLIC_LICENSE='https://github.com/tilezen/joerd/blob/master/docs/attribution.md'


def tile_names(bounds):
 a,b,c,d=bounds
 return [f'{"N" if lat>=0 else "S"}{abs(lat):02d}{"E" if lon>=0 else "W"}{abs(lon):03d}'
         for lat in range(math.floor(a),math.ceil(c)) for lon in range(math.floor(b),math.ceil(d))]


def hgt_data(path,name=None):
 path=Path(path);name=name or path.name;match=re.fullmatch(r'([NS])(\d{2})([EW])(\d{3})\.hgt(?:\.gz)?',name,re.I)
 if not match:raise ValueError('HGT files need a geographic name, such as N59E018.hgt or N59E018.hgt.gz.')
 south=int(match[2])*(-1 if match[1].upper()=='S' else 1);west=int(match[4])*(-1 if match[3].upper()=='W' else 1)
 if not -90<=south<90 or not -180<=west<180:raise ValueError('HGT tile coordinates are invalid.')
 opener=gzip.open if name.lower().endswith('.gz') else open
 with opener(path,'rb') as f:data=f.read(32*1024*1024+1)
 if len(data)>32*1024*1024:raise ValueError('HGT tile is too large.')
 n=math.isqrt(len(data)//2)
 if n<3 or n>3601 or len(data)!=2*n*n:raise ValueError('HGT data must contain a square grid of signed 16-bit elevations.')
 array=np.frombuffer(data,dtype='>i2').astype(np.int16).reshape(n,n)
 delta=1/(n-1)
 return array,Affine(delta,0,west-delta/2,0,-delta,south+1+delta/2),'EPSG:4326'


def download_tiles(bounds,cache,job=None,max_tiles=16):
 job=job or Job();names=tile_names(bounds)
 if len(names)>max_tiles:raise ValueError(f'This area needs {len(names)} public tiles. The configured limit is {max_tiles}; narrow the bounds or increase the limit.')
 cache=Path(cache);cache.mkdir(parents=True,exist_ok=True);files=[]
 for i,name in enumerate(names):
  job.update(21+14*i/max(1,len(names)),'Getting public elevation',f'Tile {i+1}/{len(names)}: {name}')
  target=cache/(name+'.hgt.gz');url=PUBLIC_URL.format(prefix=name[:3],tile=name)
  valid=False
  if target.exists():
   try:hgt_data(target);valid=True
   except (OSError,ValueError,EOFError):pass
  if not valid:
   fd,tmp=tempfile.mkstemp(prefix='.download-',suffix='.hgt.gz',dir=cache);temporary=Path(tmp)
   try:
    request=Request(url,headers={'User-Agent':'TF3-Heightmap-Studio/0.1'})
    with os.fdopen(fd,'wb') as output, urlopen(request,timeout=15,context=ssl.create_default_context(cafile=certifi.where())) as response:
     total=int(response.headers.get('Content-Length','0'));received=0
     while True:
      job.check();chunk=response.read(65536)
      if not chunk:break
      received+=len(chunk)
      if received>32*1024*1024:raise ValueError('Public tile exceeds the download limit.')
      output.write(chunk)
      job.update(21+14*(i+min(1,received/max(1,total)))/max(1,len(names)),'Getting public elevation',f'{name}: {received/1048576:.1f} MB')
    # The provider filename supplies the geographic origin to the decoder.
    hgt_data(temporary,name+'.hgt.gz')
    job.check();os.replace(temporary,target)
    metadata={'url':url,'downloadedUtc':datetime.now(timezone.utc).isoformat(),'bytes':received,'provider':'Mapzen terrain tiles / Skadi','attribution':PUBLIC_LICENSE}
    target.with_suffix('.download.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
   finally:
    if temporary.exists():temporary.unlink()
  files.append(target)
 job.update(35,'Public elevation ready',f'{len(files)} tiles')
 return files


def haversine(a,b):
 lat0,lon0=a;lat1,lon1=b
 x=math.sin(math.radians(lat1-lat0)/2)**2+math.cos(math.radians(lat0))*math.cos(math.radians(lat1))*math.sin(math.radians(lon1-lon0)/2)**2
 return 6371008.8*2*math.asin(min(1,math.sqrt(x)))


def resolution_metres(affine,crs,width,height):
 p=[affine*(width/2+.5,height/2+.5),affine*(width/2+1.5,height/2+.5),affine*(width/2+.5,height/2+1.5)]
 lon,lat=transform(crs,'EPSG:4326',[v[0] for v in p],[v[1] for v in p])
 return [haversine((lat[0],lon[0]),(lat[i],lon[i])) for i in [1,2]]


def load_source(path,options,stack):
 path=Path(path).resolve()
 if not path.is_file():raise ValueError('Elevation file does not exist: '+str(path))
 if path.name.lower().endswith(('.hgt','.hgt.gz')):
  if options['band']!=1:raise ValueError('HGT files have one elevation band.')
  array,affine,crs=hgt_data(path);n=array.shape[0]
  return {'source':array,'transform':affine,'crs':crs,'nodata':-32768,'scale':1.0,'offset':0.0,'units':'metres','path':str(path),
          'metadata':{'file':str(path),'format':'HGT','shape':[n,n],'crs':crs,'sourceResolutionMetres':resolution_metres(affine,crs,n,n),'verticalDatum':'EGM96 (HGT convention)','synthetic':n not in {1201,3601}}}
 if path.suffix.lower() not in {'.tif','.tiff','.asc'}:raise ValueError('Use a local GeoTIFF, ASCII grid, HGT or HGT.GZ elevation file.')
 src=stack.enter_context(rasterio.open(path))
 if options['band']>src.count:raise ValueError(f'{path.name} has only {src.count} bands.')
 crs=src.crs or options['crs_override']
 if not crs:raise ValueError(path.name+' has no coordinate reference system. Enter its known EPSG code in Elevation settings.')
 band=options['band'];tags=src.tags()
 return {'source':rasterio.band(src,band),'transform':src.transform,'crs':crs,'nodata':src.nodatavals[band-1],
         'scale':src.scales[band-1],'offset':src.offsets[band-1],'units':src.units[band-1] or '', 'path':str(path),
         'metadata':{'file':str(path),'format':src.driver,'shape':[src.height,src.width],'crs':str(crs),'band':band,
           'scale':src.scales[band-1],'offset':src.offsets[band-1],'units':src.units[band-1],
           'sourceResolutionMetres':resolution_metres(src.transform,crs,src.width,src.height),
           'verticalDatum':tags.get('VERTICAL_DATUM','Unknown / unchanged'),
           'synthetic':tags.get('SYNTHETIC','').lower() in {'true','yes','1'}}}


def sample_sources(paths,bounds,shape,options,job=None):
 job=job or Job();ny,nx=shape;minx,miny,maxx,maxy=mercator_bounds(bounds)
 dx=(maxx-minx)/(nx-1);dy=(maxy-miny)/(ny-1)
 destination_transform=Affine(dx,0,minx-dx/2,0,-dy,maxy+dy/2)
 result=np.full((ny,nx),np.nan,dtype=np.float64);metadata=[]
 if not paths:raise ValueError('Add an elevation file, or choose public-data download.')
 with ExitStack() as stack, rasterio.Env(GDAL_CACHEMAX=128*1024*1024):
  sources=[load_source(path,options,stack) for path in paths]
  for i,source in enumerate(sources):
   job.check();meta=dict(source['metadata']);metadata.append(meta)
   units=source['units'].lower();factor=.3048 if options['source_units']=='Feet' or options['source_units']=='Auto / metres' and units in {'ft','foot','feet','international foot'} else 1.0
   meta['heightUnitMultiplier']=factor
   for row in range(0,ny,128):
    job.update(35+30*(i+row/ny)/len(sources),'Sampling elevation',f'{Path(source["path"]).name}; row {row+1}/{ny}')
    count=min(128,ny-row);chunk=np.full((count,nx),np.nan,dtype=np.float64)
    # Vertex samples must retain their point interpolation kernel, including
    # when shrinking a source raster. GDAL's default downsampling widens it.
    reproject(source['source'],chunk,src_transform=source['transform'],src_crs=source['crs'],src_nodata=source['nodata'],
              dst_transform=destination_transform*Affine.translation(0,row),dst_crs='EPSG:3857',dst_nodata=np.nan,
              resampling={'Bilinear':Resampling.bilinear,'Cubic':Resampling.cubic,'Nearest':Resampling.nearest}[options['resampling']],
              num_threads=2,warp_mem_limit=128,tolerance=0.0,XSCALE=1.0,YSCALE=1.0)
    chunk=(chunk*source['scale']+source['offset'])*factor
    part=result[row:row+count];fill=~np.isfinite(part)&np.isfinite(chunk);part[fill]=chunk[fill]
 job.update(65,'Elevation sampled')
 return result,destination_transform,metadata

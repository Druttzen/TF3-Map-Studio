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
from pyproj import CRS
from rasterio.warp import reproject, transform, transform_bounds, Resampling
from rasterio.enums import MaskFlags, ColorInterp
from rasterio.windows import Window
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


def resolution_metres(affine,crs,width,height,at=None):
 col,row=at if at is not None else (width/2,height/2)
 p=[affine@(col,row),affine@(col+1,row),affine@(col,row+1)]
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
 if src.colorinterp[band-1] in {ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha,ColorInterp.palette}:
  raise ValueError(path.name+' contains an image/colour band, not a DEM height band. Choose measured elevation GeoTIFF data; image colours cannot be used as terrain heights.')
 if np.issubdtype(np.dtype(src.dtypes[band-1]),np.complexfloating):raise ValueError(path.name+' contains complex values, not scalar terrain heights.')
 original_crs=CRS.from_user_input(crs)
 vertical=next((c for c in original_crs.sub_crs_list if c.is_vertical),None) if original_crs.is_compound else None
 horizontal=next((c for c in original_crs.sub_crs_list if c.is_projected or c.is_geographic),None) if original_crs.is_compound else original_crs
 if horizontal is None:raise ValueError(path.name+' has no horizontal coordinate reference system.')
 # Warp XY only. Keep measured Z and its datum; never silently apply a geoid shift.
 crs=horizontal.to_2d().to_wkt()
 units=src.units[band-1] or (vertical.axis_info[0].unit_name if vertical and vertical.axis_info else '')
 download=None;record=path.with_suffix('.download.json')
 if record.exists():
  try:
   value=json.loads(record.read_text(encoding='utf-8'))
   if isinstance(value,dict):download=value
  except (OSError,ValueError):pass
 return {'source':rasterio.band(src,band),'dataset':src,'band':band,'transform':src.transform,'crs':crs,'nodata':src.nodatavals[band-1],
         'scale':src.scales[band-1],'offset':src.offsets[band-1],'units':units, 'path':str(path),
         'metadata':{'file':str(path),'format':src.driver,'shape':[src.height,src.width],'crs':original_crs.to_string(),'horizontalCrs':horizontal.to_2d().to_string(),'band':band,
           'scale':src.scales[band-1],'offset':src.offsets[band-1],'units':units,
           'sourceResolutionMetres':resolution_metres(src.transform,crs,src.width,src.height),
           'verticalDatum':tags.get('VERTICAL_DATUM',vertical.name if vertical else 'Unknown / unchanged'),
           'lidar':json.loads(tags['LIDAR_PROVENANCE']) if tags.get('LIDAR_PROVENANCE') else None,
           'download':download,
           'synthetic':tags.get('SYNTHETIC','').lower() in {'true','yes','1'}}}


def map_resolution(source,bounds):
 """Measure source cell spacing near this OSM area, rather than a distant tile centre."""
 minx,miny,maxx,maxy=mercator_bounds(bounds)
 x,y=transform('EPSG:3857',source['crs'],[(minx+maxx)/2],[(miny+maxy)/2])
 col,row=(~source['transform'])@(x[0],y[0]);height,width=source['metadata']['shape']
 at=(min(max(.5,col),width-.5),min(max(.5,row),height-.5))
 return resolution_metres(source['transform'],source['crs'],width,height,at)


def unit_multiplier(units,selection):
 if selection=='Feet':return .3048
 if selection=='Metres':return 1.0
 unit=units.strip().lower()
 if unit in {'ft','foot','feet','international foot'}:return .3048
 if unit in {'us survey foot','us_survey_foot','foot_us'}:return 1200/3937
 if unit in {'','m','metre','meter','metres','meters'}:return 1.0
 raise ValueError('Unsupported elevation unit '+repr(units)+'. Choose the known Metres or Feet units, or convert this DEM first.')


def masked_source(source, destination_transform, shape, stack, job):
 """Apply authoritative GDAL masks before warping, in bounded disk-backed rows.

 An explicit mask can mark a nodata-valued pixel valid, or a normal pixel
 invalid. Passing scalar src_nodata to GDAL alone loses that distinction.
 Only the AOI and interpolation halo are read; the original is untouched.
 """
 src=source.get('dataset');band=source.get('band')
 if src is None or not ({MaskFlags.per_dataset,MaskFlags.alpha}&set(src.mask_flag_enums[band-1])):return source
 edges=rasterio.transform.array_bounds(*shape,destination_transform)
 left,bottom,right,top=transform_bounds('EPSG:3857',source['crs'],*edges,densify_pts=41)
 inv=~src.transform
 corners=[inv*(x,y) for x in (left,right) for y in (bottom,top)]
 c0=max(0,math.floor(min(p[0] for p in corners))-3);c1=min(src.width,math.ceil(max(p[0] for p in corners))+3)
 r0=max(0,math.floor(min(p[1] for p in corners))-3);r1=min(src.height,math.ceil(max(p[1] for p in corners))+3)
 if c1<=c0 or r1<=r0:return {**source,'source':np.full((1,1),np.nan),'nodata':np.nan}
 directory=stack.enter_context(tempfile.TemporaryDirectory(prefix='tf3-dem-mask-'))
 path=Path(directory)/'masked.tif';affine=src.transform*Affine.translation(c0,r0)
 with rasterio.open(path,'w',driver='GTiff',width=c1-c0,height=r1-r0,count=1,dtype='float64',crs=source['crs'],transform=affine,nodata=np.nan) as out:
  rows=max(1,min(128,8_000_000//max(1,c1-c0)))
  for row in range(r0,r1,rows):
   job.check();n=min(rows,r1-row);window=Window(c0,row,c1-c0,n)
   data=src.read(band,window=window).astype(np.float64)
   data[src.read_masks(band,window=window)==0]=np.nan
   out.write(data,1,window=Window(0,row-r0,c1-c0,n))
 masked=stack.enter_context(rasterio.open(path))
 return {**source,'source':rasterio.band(masked,1),'transform':affine,'nodata':np.nan}


def sample_sources(paths,bounds,shape,options,job=None):
 job=job or Job();ny,nx=shape;minx,miny,maxx,maxy=mercator_bounds(bounds)
 dx=(maxx-minx)/(nx-1);dy=(maxy-miny)/(ny-1)
 destination_transform=Affine(dx,0,minx-dx/2,0,-dy,maxy+dy/2)
 result=np.full((ny,nx),np.nan,dtype=np.float64);metadata=[]
 if not paths:raise ValueError('Add an elevation file, or choose public-data download.')
 with ExitStack() as stack, rasterio.Env(GDAL_CACHEMAX=128*1024*1024):
  sources=[load_source(path,options,stack) for path in paths]
  for index,source in enumerate(sources):
   source['metadata']['fileListPosition']=index+1
   source['metadata']['sourceResolutionMetres']=map_resolution(source,bounds)
  if options['source_priority']=='Finest elevation first':
   sources.sort(key=lambda s:round(max(s['metadata']['sourceResolutionMetres']),6))
  for i,source in enumerate(sources):
   source=masked_source(source,destination_transform,shape,stack,job)
   job.check();meta=dict(source['metadata']);metadata.append(meta)
   factor=unit_multiplier(source['units'],options['source_units'])
   meta['heightUnitMultiplier']=factor
   meta.update(priority=i+1,availableSamples=0,contributedSamples=0,resampling=options['resampling'],resolutionMeasuredAt='Near OSM area; nearest source cell if outside its footprint')
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
    part=result[row:row+count];valid=np.isfinite(chunk);fill=~np.isfinite(part)&valid;part[fill]=chunk[fill]
    meta['availableSamples']+=int(np.count_nonzero(valid));meta['contributedSamples']+=int(np.count_nonzero(fill))
   meta['coveragePercent']=100*meta['contributedSamples']/(nx*ny)
 job.update(65,'Elevation sampled')
 return result,destination_transform,metadata

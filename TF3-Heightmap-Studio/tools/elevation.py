"""Local DEM and public Mapzen/Skadi acquisition and aligned sampling. GPL-3.0."""
from contextlib import ExitStack
from datetime import datetime, timezone
import gzip, json, math, os, re, ssl, tempfile
import xml.etree.ElementTree as ET
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


def source_window(source,destination_transform,shape,halo=3):
 """Native source cells needed by the map, with the interpolation neighbours.

 This only bounds disk I/O. It must not crop away the neighbouring samples
 needed by a kernel at a map corner or at a joined file boundary.
 """
 values=source['source'];height,width=values.shape
 edges=rasterio.transform.array_bounds(*shape,destination_transform)
 left,bottom,right,top=transform_bounds('EPSG:3857',source['crs'],*edges,densify_pts=41)
 inverse=~source['transform']
 corners=[inverse*(x,y) for x in (left,right) for y in (bottom,top)]
 c0=max(0,math.floor(min(p[0] for p in corners))-halo);c1=min(width,math.ceil(max(p[0] for p in corners))+halo)
 r0=max(0,math.floor(min(p[1] for p in corners))-halo);r1=min(height,math.ceil(max(p[1] for p in corners))+halo)
 return (c0,r0,c1-c0,r1-r0) if c1>c0 and r1>r0 else None


def disk_backed_array(source,destination_transform,shape,stack,job):
 """Keep many HGT inputs from accumulating full decoded arrays in RAM."""
 window=source_window(source,destination_transform,shape)
 if window is None:
  return {**source,'source':np.full((1,1),np.nan),'nodata':np.nan,'empty':True}
 c0,r0,width,height=window;values=source['source'];job.check()
 directory=stack.enter_context(tempfile.TemporaryDirectory(prefix='tf3-hgt-aoi-'))
 path=Path(directory)/'source.tif';affine=source['transform']*Affine.translation(c0,r0)
 with rasterio.open(path,'w',driver='GTiff',width=width,height=height,count=1,dtype=values.dtype,
                    crs=source['crs'],transform=affine,nodata=source['nodata'],compress='deflate') as out:
  for row in range(0,height,128):
   job.check();count=min(128,height-row)
   out.write(values[r0+row:r0+row+count,c0:c0+width],1,window=Window(0,row,width,count))
 dataset=stack.enter_context(rasterio.open(path))
 return {**source,'source':rasterio.band(dataset,1),'dataset':dataset,'band':1,'transform':affine}


def compatible_grid(first,other):
 """Only neighbours on the same calibrated native lattice may share a kernel."""
 a,b=first['transform'],other['transform']
 if a.b or a.d or b.b or b.d or a.a<=0 or a.e>=0:return False
 if not (math.isclose(a.a,b.a,rel_tol=1e-12,abs_tol=1e-12) and math.isclose(a.e,b.e,rel_tol=1e-12,abs_tol=1e-12)):return False
 if any(abs(v-round(v))>1e-7 for v in ((b.c-a.c)/a.a,(b.f-a.f)/a.e)):return False
 if CRS.from_user_input(first['crs'])!=CRS.from_user_input(other['crs']):return False
 return (first['scale'],first['offset'],first['factor'],first['metadata']['verticalDatum'])==(
         other['scale'],other['offset'],other['factor'],other['metadata']['verticalDatum'])


def source_mosaic(sources,destination_transform,shape,stack,job):
 """A virtual, first-valid native grid, joined *before* interpolation.

 VRT source rectangles are clipped to this map plus a native-cell halo. The
 resulting grid is virtual, so a fine DEM or hundreds of tiles do not create
 a full-size in-memory mosaic. Authoritative masks were applied beforehand.
 GDAL VRT sources compose last-first, hence reverse our first-valid priority.
 """
 origin=sources[0]['transform'];entries=[]
 for source in sources:
  job.check()
  if source.get('empty'):continue
  window=source_window(source,destination_transform,shape)
  if window is None:continue
  c0,r0,width,height=window
  transform=source['transform']*Affine.translation(c0,r0)
  col=round((transform.c-origin.c)/origin.a);row=round((transform.f-origin.f)/origin.e)
  entries.append((source,window,col,row))
 if len(entries)<2:return None
 mincol=min(e[2] for e in entries);minrow=min(e[3] for e in entries)
 width=max(e[2]+e[1][2] for e in entries)-mincol
 height=max(e[3]+e[1][3] for e in entries)-minrow
 if max(width,height)>2147483647:return None
 affine=origin*Affine.translation(mincol,minrow)
 vrt=ET.Element('VRTDataset',rasterXSize=str(width),rasterYSize=str(height))
 ET.SubElement(vrt,'SRS').text=CRS.from_user_input(sources[0]['crs']).to_wkt()
 ET.SubElement(vrt,'GeoTransform').text=','.join(format(v,'.17g') for v in affine.to_gdal())
 band=ET.SubElement(vrt,'VRTRasterBand',dataType='Float64',band='1')
 ET.SubElement(band,'NoDataValue').text='nan'
 for source,window,col,row in reversed(entries):
  values=source['source'];c0,r0,w,h=window
  entry=ET.SubElement(band,'ComplexSource')
  ET.SubElement(entry,'SourceFilename',relativeToVRT='0').text=str(Path(values.ds.name).resolve())
  ET.SubElement(entry,'SourceBand').text=str(values.bidx)
  ET.SubElement(entry,'SrcRect',xOff=str(c0),yOff=str(r0),xSize=str(w),ySize=str(h))
  ET.SubElement(entry,'DstRect',xOff=str(col-mincol),yOff=str(row-minrow),xSize=str(w),ySize=str(h))
  nodata=source['nodata']
  if nodata is not None:ET.SubElement(entry,'NODATA').text=str(nodata)
 directory=stack.enter_context(tempfile.TemporaryDirectory(prefix='tf3-dem-mosaic-'))
 path=Path(directory)/'joined.vrt';ET.ElementTree(vrt).write(path,encoding='utf-8',xml_declaration=True)
 joined=stack.enter_context(rasterio.open(path))
 return {'source':rasterio.band(joined,1),'transform':affine,'crs':sources[0]['crs'],'nodata':np.nan}


def warp_chunk(source,destination_transform,row,count,nx,resampling):
 chunk=np.full((count,nx),np.nan,dtype=np.float64)
 if source.get('empty'):return chunk
 # Point-sampled vertices must not acquire GDAL's widened downsample kernel.
 reproject(source['source'],chunk,src_transform=source['transform'],src_crs=source['crs'],src_nodata=source['nodata'],
           dst_transform=destination_transform*Affine.translation(0,row),dst_crs='EPSG:3857',dst_nodata=np.nan,
           resampling=resampling,num_threads=2,warp_mem_limit=128,tolerance=0.0,XSCALE=1.0,YSCALE=1.0)
 return chunk


def sample_sources(paths,bounds,shape,options,job=None):
 job=job or Job();ny,nx=shape;minx,miny,maxx,maxy=mercator_bounds(bounds)
 dx=(maxx-minx)/(nx-1);dy=(maxy-miny)/(ny-1)
 destination_transform=Affine(dx,0,minx-dx/2,0,-dy,maxy+dy/2)
 result=np.full((ny,nx),np.nan,dtype=np.float64);metadata=[]
 if not paths:raise ValueError('Add an elevation file, or choose public-data download.')
 with ExitStack() as stack, rasterio.Env(GDAL_CACHEMAX=128*1024*1024):
  sources=[]
  for index,path in enumerate(paths):
   job.check();source=load_source(path,options,stack)
   source['metadata']['fileListPosition']=index+1
   source['metadata']['sourceResolutionMetres']=map_resolution(source,bounds)
   source['factor']=unit_multiplier(source['units'],options['source_units'])
   if len(paths)>1 and isinstance(source['source'],np.ndarray):source=disk_backed_array(source,destination_transform,shape,stack,job)
   sources.append(source)
  if options['source_priority']=='Finest elevation first':
   sources.sort(key=lambda s:round(max(s['metadata']['sourceResolutionMetres']),6))
  prepared=[]
  for i,source in enumerate(sources):
   source=masked_source(source,destination_transform,shape,stack,job)
   job.check();meta=dict(source['metadata']);metadata.append(meta)
   meta['heightUnitMultiplier']=source['factor']
   meta.update(priority=i+1,availableSamples=0,contributedSamples=0,resampling=options['resampling'],resolutionMeasuredAt='Near OSM area; nearest source cell if outside its footprint')
   prepared.append((source,meta))
  groups=[]
  for pair in prepared:
   if not groups or not compatible_grid(groups[-1][0][0],pair[0]):groups.append([])
   groups[-1].append(pair)
  resampling={'Bilinear':Resampling.bilinear,'Cubic':Resampling.cubic,'Nearest':Resampling.nearest}[options['resampling']]
  completed=0
  for group_index,group in enumerate(groups):
   members=[s for s,_ in group]
   joined=source_mosaic(members,destination_transform,shape,stack,job) if len(group)>1 else None
   if joined:
    for _,meta in group:
     meta.update(mosaicGroup=group_index+1,mosaicSourceCount=len(group),interpolationAcrossTiles=True,
                 sampleAttribution='First valid original source at each output vertex; interpolation also uses neighbouring aligned source cells')
   for row in range(0,ny,128):
    job.update(35+30*(completed+len(group)*row/ny)/len(sources),'Sampling elevation',f'{len(group)} aligned source(s); row {row+1}/{ny}')
    count=min(128,ny-row);part=result[row:row+count]
    mosaic=warp_chunk(joined,destination_transform,row,count,nx,resampling) if joined else None
    if mosaic is not None:
     with np.errstate(over='ignore',invalid='ignore'):
      mosaic=(mosaic*members[0]['scale']+members[0]['offset'])*members[0]['factor']
    for source,meta in group:
     job.check();chunk=warp_chunk(source,destination_transform,row,count,nx,resampling)
     with np.errstate(over='ignore',invalid='ignore'):
      chunk=(chunk*source['scale']+source['offset'])*source['factor']
     valid=np.isfinite(chunk);fill=~np.isfinite(part)&valid
     # Preserve original coverage, gap policy and per-file priority accounting.
     # Only replace already-covered heights with the continuous mosaic kernel.
     if mosaic is not None:chunk=np.where(np.isfinite(mosaic),mosaic,chunk)
     part[fill]=chunk[fill]
     meta['availableSamples']+=int(np.count_nonzero(valid));meta['contributedSamples']+=int(np.count_nonzero(fill))
   for _,meta in group:meta['coveragePercent']=100*meta['contributedSamples']/(nx*ny)
   completed+=len(group)
 job.update(65,'Elevation sampled')
 return result,destination_transform,metadata

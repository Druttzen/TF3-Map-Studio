"""Stream classified LAS/LAZ (including local COPC) into aligned ground DEMs.

Only ASPRS ground class 2, excluding withheld points, contributes. No automatic
classification or vertical datum conversion is claimed. GPL-3.0.
"""
import hashlib,json,math,os,tempfile
from pathlib import Path
import laspy
import numpy as np
import rasterio
from rasterio import Affine
from pyproj import CRS,Transformer
from alignment import mercator_bounds
from job import Job

POINT_SUFFIXES={'.las','.laz'}

def horizontal_crs(crs):
 value=CRS.from_user_input(crs)
 if value.is_compound:
  value=next((c for c in value.sub_crs_list if c.is_projected or c.is_geographic),None)
  if value is None:raise ValueError('LiDAR file has no known horizontal coordinate system.')
 return value.to_2d()

def ground_dem(path,bounds,shape,options,cache,job=None):
 job=job or Job();path=Path(path).resolve();cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
 ny,nx=shape;minx,miny,maxx,maxy=mercator_bounds(bounds);dx=(maxx-minx)/(nx-1);dy=(maxy-miny)/(ny-1)
 affine=Affine(dx,0,minx-dx/2,0,-dy,maxy+dy/2)
 stat=path.stat();identity=lambda s:(s.st_size,s.st_mtime_ns,s.st_ctime_ns)
 key=json.dumps([str(path),identity(stat),bounds,list(shape),*[options[k] for k in ['crs_override','source_units','vertical_datum','lidar_max_points']],'class2-mean-v1'])
 target=cache/(hashlib.sha256(key.encode()).hexdigest()[:24]+'.tif')
 if target.exists():
  with rasterio.open(target) as src:
   if src.tags().get('LIDAR_POLICY')=='class2-mean-v1' and src.shape==shape:return target
 with laspy.open(path) as source:
  crs=source.header.parse_crs()
  if crs is None:
   if not options['crs_override']:raise ValueError(path.name+' has no coordinate system. Enter its known EPSG code; coordinates cannot be guessed.')
   crs=CRS.from_user_input(options['crs_override'])
  crs=CRS.from_user_input(crs);horizontal=horizontal_crs(crs)
  if source.header.point_count>options['lidar_max_points']:raise ValueError(f'{path.name} contains {source.header.point_count:,} points, above the LiDAR read limit. Clip the file or increase the limit.')
  transformer=Transformer.from_crs(horizontal,'EPSG:3857',always_xy=True)
  vertical=next((c for c in crs.sub_crs_list if c.is_vertical),None) if crs.is_compound else None
  unit=vertical.axis_info[0].unit_name if vertical and vertical.axis_info else 'Unknown'
  if unit=='Unknown' and options['source_units']=='Auto / metres':raise ValueError('LiDAR vertical units are unspecified. Choose known Metres or Feet in Elevation; Z units cannot be inferred from the horizontal CRS.')
  # Keep original Z units; the ordinary elevation importer owns unit scaling.
  band_unit='ft' if unit.lower() in {'foot','international foot'} else 'm' if unit.lower() in {'metre','meter'} else ''
  if unit.lower()=='us survey foot':raise ValueError('LiDAR uses US survey feet. Convert its vertical units explicitly before import; international feet are different.')
  metadata={'originalFile':str(path),'originalCrs':crs.to_string(),'verticalDatum':vertical.name if vertical else options['vertical_datum'],
            'verticalUnits':unit,'pointCount':source.header.point_count,'classification':'ASPRS ground class 2; withheld excluded',
            'aggregation':'mean of classified ground points per aligned cell; empty cells remain missing',
            'gridCellMetresAtCentre':[dx*math.cos(math.radians((bounds[0]+bounds[2])/2)),dy*math.cos(math.radians((bounds[0]+bounds[2])/2))]}
  with tempfile.TemporaryDirectory(prefix='.lidar-',dir=cache) as directory:
   directory=Path(directory);sums=np.memmap(directory/'sums.bin',dtype='float64',mode='w+',shape=ny*nx);counts=np.memmap(directory/'counts.bin',dtype='uint32',mode='w+',shape=ny*nx)
   scanned=selected=0
   try:
    for points in source.chunk_iterator(250_000):
     job.check();scanned+=len(points);keep=(np.asarray(points.classification)==2)&(np.asarray(points.withheld)==0)
     if np.any(keep):
      x,y=transformer.transform(np.asarray(points.x)[keep],np.asarray(points.y)[keep]);z=np.asarray(points.z)[keep]
      x=np.asarray(x);y=np.asarray(y);finite=np.isfinite(x)&np.isfinite(y)&np.isfinite(z)
      # Clip before converting to integer to avoid overflow from bad coordinates.
      finite&=(x>=minx-dx/2)&(x<maxx+dx/2)&(y>miny-dy/2)&(y<=maxy+dy/2)
      x=x[finite];y=y[finite];z=z[finite]
      columns=np.floor((x-(minx-dx/2))/dx).astype(np.int64);rows=np.floor(((maxy+dy/2)-y)/dy).astype(np.int64)
      inside=(rows>=0)&(rows<ny)&(columns>=0)&(columns<nx)
      ids=rows[inside]*nx+columns[inside];np.add.at(sums,ids,z[inside]);np.add.at(counts,ids,1);selected+=len(ids)
     job.update(25+10*scanned/max(1,source.header.point_count),'Reading LiDAR ground',f'{path.name}: {scanned:,} points; {selected:,} ground points in map')
    if selected==0:raise ValueError(path.name+' contains no non-withheld classified ground points in this map. Buildings/unclassified points are not substituted for terrain.')
    metadata['groundPointsInMap']=selected;metadata['unfilledCells']=int(np.count_nonzero(counts==0))
    temporary=directory/'ground.tif'
    with rasterio.open(temporary,'w',driver='GTiff',width=nx,height=ny,count=1,dtype='float64',crs='EPSG:3857',transform=affine,nodata=np.nan,compress='deflate') as out:
     for row in range(0,ny,128):
      job.check();end=min(ny,row+128);sl=slice(row*nx,end*nx);chunk=np.full((end-row)*nx,np.nan)
      np.divide(sums[sl],counts[sl],out=chunk,where=counts[sl]>0)
      out.write(chunk.reshape(end-row,nx),1,window=rasterio.windows.Window(0,row,nx,end-row))
     if band_unit:out.set_band_unit(1,band_unit)
     out.update_tags(LIDAR_POLICY='class2-mean-v1',VERTICAL_DATUM=metadata['verticalDatum'],LIDAR_PROVENANCE=json.dumps(metadata))
    job.check()
    if identity(path.stat())!=identity(stat):raise ValueError('LiDAR source changed during import. No cache file was saved.')
    os.replace(temporary,target)
   finally:
    sums._mmap.close();counts._mmap.close();del sums,counts
 return target

def prepare_sources(paths,bounds,shape,options,cache,job=None):
 return [ground_dem(p,bounds,shape,options,cache,job) if Path(p).suffix.lower() in POINT_SUFFIXES else Path(p) for p in paths]

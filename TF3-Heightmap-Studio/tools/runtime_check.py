"""Headless packaged-runtime check using only a tiny fictional point fixture."""
import json,tempfile
from pathlib import Path

def check(output):
 result={'ok':False}
 try:
  import laspy,numpy as np,rasterio
  from pyproj import CRS
  from lidar import ground_dem
  from height_settings import normalize
  from elevation import sample_sources
  from alignment import mercator_bounds
  from rasterio import Affine
  with tempfile.TemporaryDirectory(prefix='tf3-lidar-runtime-') as folder:
   folder=Path(folder);header=laspy.LasHeader(point_format=6,version='1.4');header.add_crs(CRS.from_epsg(3857))
   data=laspy.LasData(header);data.x=[0,5,10,5];data.y=[0,5,10,5];data.z=[10,20,30,999];data.classification=[2,2,2,6]
   file=folder/'fictional.laz';data.write(file)
   raster=ground_dem(file,[0,0,.0001,.0001],(3,3),normalize({'source_units':'Metres'}),folder/'cache')
   with rasterio.open(raster) as src:
    values=src.read(1);assert np.nanmax(values)==30;assert src.crs.to_epsg()==3857
   bounds=[0,0,.0001,.0001];x0,y0,x1,y1=mercator_bounds(bounds)
   files=[]
   for n in [9,17]:
    dx=(x1-x0)/(n-1);dy=(y1-y0)/(n-1);affine=Affine(dx,0,x0-dx/2,0,-dy,y1+dy/2)
    values=np.full((n,n),10.)
    if n==17:
     values[:]=np.nan;values[4:13,4:13]=42;values[8,8]=49;values[10,10]=np.nan
    file=folder/f'fictional-{n}.tif';files.append(file)
    with rasterio.open(file,'w',driver='GTiff',width=n,height=n,count=1,dtype='float64',crs='EPSG:3857',transform=affine,nodata=np.nan) as dst:dst.write(values,1)
   enhanced,affine,metadata=sample_sources(files,bounds,(9,9),normalize())
   assert enhanced[4,4]==49 and enhanced[5,5]==10 and enhanced[0,0]==10
   assert metadata[0]['file']==str(files[1].resolve())
   assert np.allclose(affine@(.5,.5),(x0,y1))
   result={'ok':True,'laspy':laspy.__version__,'lazCompression':'round-trip passed','projection':'EPSG:3857 verified','groundFiltering':'building excluded','geotiff':'written and read','geotiffDetail':'priority, nodata fallback and OSM bounds passed'}
 except Exception as exc:result['error']=str(exc)
 finally:
  Path(output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 return 0 if result['ok'] else 1

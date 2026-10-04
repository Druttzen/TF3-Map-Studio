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
  with tempfile.TemporaryDirectory(prefix='tf3-lidar-runtime-') as folder:
   folder=Path(folder);header=laspy.LasHeader(point_format=6,version='1.4');header.add_crs(CRS.from_epsg(3857))
   data=laspy.LasData(header);data.x=[0,5,10,5];data.y=[0,5,10,5];data.z=[10,20,30,999];data.classification=[2,2,2,6]
   file=folder/'fictional.laz';data.write(file)
   raster=ground_dem(file,[0,0,.0001,.0001],(3,3),normalize({'source_units':'Metres'}),folder/'cache')
   with rasterio.open(raster) as src:
    values=src.read(1);assert np.nanmax(values)==30;assert src.crs.to_epsg()==3857
   result={'ok':True,'laspy':laspy.__version__,'lazCompression':'round-trip passed','projection':'EPSG:3857 verified','groundFiltering':'building excluded','geotiff':'written and read'}
 except Exception as exc:result['error']=str(exc)
 finally:
  Path(output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 return 0 if result['ok'] else 1

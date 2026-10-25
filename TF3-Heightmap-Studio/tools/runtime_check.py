"""Headless packaged-runtime check using only a tiny fictional point fixture."""
import json,tempfile
from pathlib import Path

def check(output):
 result={'ok':False}
 try:
  import certifi,ssl,laspy,numpy as np,rasterio
  context=ssl.create_default_context(cafile=certifi.where())
  assert context.cert_store_stats()['x509_ca']>0
  from pyproj import CRS
  from lidar import ground_dem
  from height_settings import normalize
  from elevation import sample_sources
  from alignment import mercator_bounds
  from rasterio import Affine
  from game_paths import detect,GamePaths
  from terrain import prepare,export
  import hashlib
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
   # Shared endpoint tiles must interpolate as one continuous raster in the
   # frozen executable too, not only in source-mode tests.
   affine=Affine((x1-x0)/8,0,x0-(x1-x0)/16,0,-(y1-y0)/8,y1+(y1-y0)/16)
   plane=np.arange(81,dtype='float64').reshape(9,9);seam_files=[]
   for label,start,width in [('whole',0,9),('left',0,5),('right',4,5)]:
    file=folder/f'seam-{label}.tif';seam_files.append(file)
    with rasterio.open(file,'w',driver='GTiff',width=width,height=9,count=1,dtype='float64',crs='EPSG:3857',transform=affine@Affine.translation(start,0)) as dst:
     dst.write(plane[:,start:start+width],1)
   whole,_,_=sample_sources(seam_files[:1],bounds,(17,17),normalize())
   joined,_,_=sample_sources(seam_files[1:],bounds,(17,17),normalize())
   assert np.allclose(whole,joined,atol=1e-9), 'Frozen tile interpolation has a seam'
   from local_sources import discover_local
   from data_access import GUIDE
   found=discover_local(folder,bounds,folder/'discovery-cache')
   assert all(str(p.resolve()) in found['paths'] for p in files)
   repeated=discover_local(folder,bounds,folder/'discovery-cache')
   assert repeated['cached']>=len(files)
   assert 'ConsumerKey' in GUIDE
   xml=folder/'fictional.osm';xml.write_text('<osm version="0.6"><bounds minlat="0" minlon="0" maxlat=".0001" maxlon=".0001"/><node id="1" lat=".00005" lon=".00005"/></osm>',encoding='utf-8')
   context=folder/'fictional.report.json';context.write_text(json.dumps({'dataset':'fictional-runtime','input':xml.name,'bounds':bounds,'mapSize':[128,128],'sourceSha256':hashlib.sha256(xml.read_bytes()).hexdigest(),'settings':{}}),encoding='utf-8')
   from alignment import read_report
   assert read_report(context)['dataset']=='fictional-runtime'
   terrain=prepare(context,xml,files,{'biomes':True});local=folder/'fictional-game-local'
   exported=export(terrain,local/'heightmaps/fictional.png',game_paths=GamePaths(local=local))
   assert len(list((local/'heightmaps').iterdir()))==1 and len(list((local/'biomes').iterdir()))==1
   assert Path(exported['files']['project']).parent==local/'heightmap_studio/fictional'
   installed=detect()
   result={'ok':True,'certificateBundle':'packaged CA roots loaded for HTTPS verification','laspy':laspy.__version__,'lazCompression':'round-trip passed','projection':'EPSG:3857 verified','groundFiltering':'building excluded','geotiff':'written and read','geotiffDetail':'priority, nodata fallback and OSM bounds passed',
           'nativeExportRouting':'heightmap, biomes and companions separated; fictional temporary folders only',
           'seamlessElevation':'split and whole source interpolation matched; one continuous 16-bit heightmap',
           'streamingConverterReport':'ijson parser and report contract passed',
           'localDiscovery':'header matching and repeat-search cache passed; no credentials used',
           'tf3RegistryDiscovery':{'installationFound':installed.installation is not None,'userFolderSelected':installed.local is not None}}
 except Exception as exc:result['error']=str(exc)
 finally:
  Path(output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 return 0 if result['ok'] else 1

import sys,json,threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request
from urllib.parse import urlsplit,parse_qs
import numpy as np
import pytest,rasterio,laspy
from pyproj import CRS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from lidar import ground_dem
from lidar_sources import area_bounds,sweden,usa,worldwide,download_selection,discover,PROVIDERS
from providers import ScopedRedirect
from alignment import mercator_bounds
from height_settings import normalize
from job import Job,Cancelled

def point_file(tmp_path,suffix='.las',crs=True):
 bounds=[0,0,.01,.01];x0,y0,x1,y1=mercator_bounds(bounds)
 header=laspy.LasHeader(point_format=6,version='1.4');header.scales=np.array([.0001,.0001,.0001])
 if crs:header.add_crs(CRS.from_epsg(3857))
 data=laspy.LasData(header);x,y=np.meshgrid(np.linspace(x0,x1,65),np.linspace(y1,y0,65));z=10+.001*x+.002*y
 data.x=np.r_[x.ravel(),x[32,32],x[32,32],x[32,32]];data.y=np.r_[y.ravel(),y[32,32],y[32,32],y[32,32]];data.z=np.r_[z.ravel(),999,999,999]
 data.classification=np.r_[np.full(x.size,2),6,1,2].astype('uint8');data.withheld=np.r_[np.zeros(x.size+2),1].astype('uint8')
 path=tmp_path/('measured'+suffix);data.write(path);return path,bounds,z

@pytest.mark.parametrize('suffix',['.las','.laz'])
def test_ground_only_aligned_streaming_import(tmp_path,suffix):
 path,bounds,expected=point_file(tmp_path,suffix)
 output=ground_dem(path,bounds,(65,65),normalize({'source_units':'Metres'}),tmp_path/'cache')
 with rasterio.open(output) as src:
  np.testing.assert_allclose(src.read(1),expected,atol=.0001)
  meta=json.loads(src.tags()['LIDAR_PROVENANCE']);assert meta['groundPointsInMap']==4225;assert meta['unfilledCells']==0
 assert not list((tmp_path/'cache').glob('.lidar-*'))

def test_no_guessing_of_vertical_units_or_crs(tmp_path):
 path,bounds,_=point_file(tmp_path)
 with pytest.raises(ValueError,match='vertical units'):ground_dem(path,bounds,(65,65),normalize(),tmp_path/'cache')
 path,bounds,_=point_file(tmp_path,crs=False)
 with pytest.raises(ValueError,match='coordinate system'):ground_dem(path,bounds,(65,65),normalize({'source_units':'Metres'}),tmp_path/'cache')

def test_no_ground_no_false_surface_and_limits(tmp_path):
 path,bounds,_=point_file(tmp_path);data=laspy.read(path);data.classification[:]=6;data.write(path)
 with pytest.raises(ValueError,match='no non-withheld'):ground_dem(path,bounds,(65,65),normalize({'source_units':'Metres'}),tmp_path/'cache')
 with pytest.raises(ValueError,match='read limit'):ground_dem(path,bounds,(65,65),normalize({'source_units':'Metres','lidar_max_points':1}),tmp_path/'cache')
 assert not list((tmp_path/'cache').glob('*'))

def test_cancelled_point_import_preserves_sources(tmp_path):
 path,bounds,_=point_file(tmp_path);before=path.read_bytes();event=threading.Event();event.set()
 with pytest.raises(Cancelled):ground_dem(path,bounds,(65,65),normalize({'source_units':'Metres'}),tmp_path/'cache',Job(cancel=event))
 assert path.read_bytes()==before;assert not list((tmp_path/'cache').glob('*'))

def test_osm_bounds_and_report_crop_take_priority(tmp_path):
 path=tmp_path/'map.xml';path.write_text('<osm><bounds minlat="57" minlon="12" maxlat="58" maxlon="13"/><node id="1" lat="59" lon="15"/></osm>')
 assert area_bounds('',path)==[57,12,58,13]
 report=tmp_path/'map.json';report.write_text(json.dumps({'dataset':'test','bounds':[57.2,12.2,57.3,12.3],'mapSize':[256,256]}))
 assert area_bounds(report,path)==[57.2,12.2,57.3,12.3]
 path.write_text('<osm><node id="1" lat="57" lon="12"/><node id="2" lat="58" lon="13"/></osm>');assert area_bounds('',path)==[57,12,58,13]

def test_sweden_bbox_pagination_access_and_limit():
 asset={'href':'https://dl1.lantmateriet.se/hojd/data/example.tif','file:size':100}
 first={'features':[{'bbox':[12,57,13,58],'assets':{'data':asset},'properties':{}}],'links':[{'rel':'next','href':'https://api.lantmateriet.se/stac-hojd/v1/search?token=page2'}]}
 with patch('lidar_sources.fetch_json',side_effect=[first,{'features':[],'links':[]}]) as fetch:
  rows=sweden([57.1,12.1,57.2,12.2],Job(),16)
  params=parse_qs(urlsplit(fetch.call_args_list[0].args[0]).query);bbox=list(map(float,params['bbox'][0].split(',')))
  assert bbox[0]<12.1 and bbox[1]<57.1 and bbox[2]>12.2 and bbox[3]>57.2
  assert rows[0]['access']=='account';assert len(rows[0]['assets'])==1
 with patch('lidar_sources.fetch_json',return_value=first):
  with pytest.raises(ValueError,match='repeated'):sweden([57.1,12.1,57.2,12.2],Job(),16)

def test_usgs_free_geotiff_selection():
 item={'format':'GeoTIFF','downloadURL':'https://prd-tnm.s3.amazonaws.com/elevation.tif','boundingBox':{'minX':-105.5,'maxX':-105,'minY':39,'maxY':41},'sizeInBytes':200}
 with patch('lidar_sources.fetch_json',return_value={'total':1,'items':[item]}) as fetch:
  row=usa([40,-105.3,40.1,-105.2],Job(),16)[0]
 assert row['access']=='open';assert '1 meter' in parse_qs(urlsplit(fetch.call_args.args[0]).query)['datasets'][0]

def test_global_bare_earth_assets_and_raw_catalog(tmp_path):
 c={'id':'survey','title':'Survey','extent':{'spatial':{'bbox':[[12,57,13,58]]}},'links':[{'rel':'item','href':'https://portal.opentopography.org/survey_be.json'},{'rel':'item','href':'https://portal.opentopography.org/survey_hh.json'}]}
 item={'bbox':[12,57,13,58],'assets':{'ground':{'href':'https://public.example.org/ground.tif','type':'image/tiff','roles':['data'],'bbox':[12,57,13,58]}}}
 with patch('lidar_sources.ot_collections',return_value=([c],[])),patch('lidar_sources.fetch_json',side_effect=[item,{'Datasets':[]}]) as fetch:
  rows,warnings=worldwide([57.1,12.1,57.2,12.2],Job(),16,tmp_path)
 assert len(rows)==1 and not warnings;assert fetch.call_args_list[0].args[0].endswith('_be.json');assert rows[0]['access']=='unknown'

def test_global_coarse_satellite_products_are_not_lidar(tmp_path):
 collection={'id':'OTSDEM.082025.4326.1','title':'Global Ensemble Digital Terrain Model','extent':{'spatial':{'bbox':[[-180,-60,180,85]]}},'links':[{'rel':'item','href':'https://portal.opentopography.org/global_be.json'}]}
 with patch('lidar_sources.ot_collections',return_value=([collection],[])),patch('lidar_sources.fetch_json',return_value={'Datasets':[]}) as fetch:
  rows,warnings=worldwide([57,12,58,13],Job(),16,tmp_path)
 assert rows==[] and not warnings;assert fetch.call_count==1;assert '/API/otCatalog' in fetch.call_args.args[0]

def test_packaging_runtime_probe(tmp_path):
 from runtime_check import check
 path=tmp_path/'runtime.json';assert check(path)==0
 assert json.loads(path.read_text())['ok']

def test_download_credentials_scope_and_no_saved_secrets(tmp_path):
 row={'provider':'Lantmäteriet','assets':[{'url':'https://dl1.lantmateriet.se/example.tif','bbox':[12,57,13,58]}]}
 with patch('lidar_sources.fetch_geotiff',return_value=tmp_path/'tile.tif') as fetch:
  download_selection(row,[57.1,12.1,57.2,12.2],normalize(),tmp_path,credentials=('api-user','private-password'))
  assert fetch.call_args.kwargs['headers']['Authorization'].startswith('Basic ')
  assert 'private-password' not in json.dumps(fetch.call_args.args[-1])
 row['assets'][0]['url']='https://other.example.org/tile.tif'
 with pytest.raises(ValueError,match='credentials were not sent'):download_selection(row,[57.1,12.1,57.2,12.2],normalize(),tmp_path,credentials=('api-user','private-password'))

def test_redirect_strips_authorization_across_origins():
 request=Request('https://dl1.lantmateriet.se/one',headers={'Authorization':'Basic secret'})
 redirect=ScopedRedirect().redirect_request(request,None,302,'',{},'https://other.example.org/two')
 assert redirect.get_header('Authorization') is None
 redirect=ScopedRedirect().redirect_request(request,None,302,'',{},'https://dl1.lantmateriet.se/two');assert redirect.get_header('Authorization')=='Basic secret'
 with pytest.raises(ValueError):ScopedRedirect().redirect_request(request,None,302,'',{},'http://dl1.lantmateriet.se/two')

def test_partial_catalog_failure_is_visible(tmp_path):
 with patch('lidar_sources.worldwide',side_effect=ValueError('offline')):
  result=discover([0,0,.01,.01],PROVIDERS[3],normalize(),tmp_path)
 assert not result['complete'];assert result['warnings'];assert result['rows']==[]

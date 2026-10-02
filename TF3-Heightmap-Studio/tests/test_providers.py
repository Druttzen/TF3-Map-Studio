import sys,json,io,threading,hashlib
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import pytest,numpy as np,rasterio
from rasterio import Affine
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from alignment import alignment_summary,geographic,mercator_bounds
from height_settings import normalize,dimensions
from providers import download_plan,acquire,fetch_geotiff,parse_urls,expanded_bounds
from terrain import prepare,export,project_dict
from elevation import sample_sources
from job import Job,Cancelled
from test_terrain import source

@pytest.mark.parametrize('size',[[256,128],[1024,2048],[8192,4096]])
def test_chosen_tf3_size_keeps_osm_coordinates(source,size):
 report=json.loads(source['report'].read_text());report['mapSize']=size;source['report'].write_text(json.dumps(report));result=prepare(source['report'],source['xml'],[source['dem']]);a=result['alignment'];nx,ny=dimensions(size,normalize())
 assert result['terrain'].shape==(ny,nx);assert a['gameWidthMetres']==size[0] and a['gameHeightMetres']==size[1];assert a['gridSpacingGameMetres']==[4,4]
 # The same geographic OSM nodes land at the same terrain raster fractions,
 # even when the chosen TF3 map has a different physical size/aspect ratio.
 from alignment import osm
 for lat,lon in [(0,0),(.003,.007),(.01,.01)]:
  x,y=osm.project(lat,lon,report['bounds'],size);row=(.5-y/size[1])*(ny-1);col=(x/size[0]+.5)*(nx-1)
  expected=100+row*32/(ny-1)+col*16/(nx-1)
  from terrain import sample_world
  assert sample_world(result['terrain'],[(x,y)],size)[0]==pytest.approx(expected,abs=1e-6)
  assert geographic(x,y,report['bounds'],size)==pytest.approx((lat,lon),abs=1e-10)
 assert result['geoTransform']*(.5,.5)==pytest.approx(source['affine']*(.5,.5))

@pytest.mark.parametrize('mode',['Download Copernicus GLO-30','Download Copernicus GLO-90'])
def test_copernicus_correct_urls_and_bounds(mode):
 bounds=[59.2,18.2,59.4,18.5];p=download_plan(bounds,normalize({'source_mode':mode}));assert p['mapBounds']==bounds and p['requestBounds'][0]<bounds[0]
 assert len(p['requests'])==1;r=p['requests'][0];assert 'N59_00_E018_00_DEM' in r['url'];assert ('COG_10_' if mode.endswith('30') else 'COG_30_') in r['url'];assert r['url'].endswith('/'+r['filename'])

def test_copernicus_integer_border_includes_neighbours():
 p=download_plan([59,18,59.001,18.001],normalize({'source_mode':'Download Copernicus GLO-30'}));assert {r['tile'] for r in p['requests']}=={'N58E017','N58E018','N59E017','N59E018'}

@pytest.mark.parametrize('mode',['Download public terrain (Mapzen)','Download Copernicus GLO-30','Download OpenTopography','Download direct GeoTIFF links'])
def test_all_source_plans_keep_authoritative_map_bounds(mode):
 bounds=[45.82,6.86,45.86,6.94];p=download_plan(bounds,normalize({'source_mode':mode,'dem_urls':'https://example.org/dem.tif'}));assert p['mapBounds']==bounds;assert p['requestBounds'][0]<=bounds[0] and p['requestBounds'][3]>=bounds[3]

@pytest.mark.parametrize('url',['http://example.org/dem.tif','file:///C:/dem.tif','https://name:secret@example.org/dem.tif',''])
def test_invalid_direct_links(url):
 with pytest.raises(ValueError):parse_urls(url)

def test_download_request_limit():
 with pytest.raises(ValueError,match='limit'):download_plan([1,1,3,3],normalize({'source_mode':'Download Copernicus GLO-30','public_max_tiles':1}))

class Response(io.BytesIO):
 def __init__(self,payload):super().__init__(payload);self.headers={'Content-Length':str(len(payload))}

def test_direct_download_uses_same_alignment_and_validated_cache(source,tmp_path):
 options=normalize({'source_mode':'Download direct GeoTIFF links','dem_urls':'https://dem.example.org/data.tif'})
 with patch('providers.urlopen',return_value=Response(source['dem'].read_bytes())) as fetch:
  result=prepare(source['report'],source['xml'],[],options,cache=tmp_path/'cache');assert fetch.call_count==1
 np.testing.assert_allclose(result['terrain'],source['z'],atol=1e-9)
 with patch('providers.urlopen',side_effect=AssertionError('Cache not reused')):prepare(source['report'],source['xml'],[],options,cache=tmp_path/'cache')
 report=export(result,tmp_path/'map.png');assert report['coordinateMatch']['south']==0;assert report['downloadPlan']['mapBounds']==source['bounds']
 assert not list((tmp_path/'cache').rglob('.download-*'))

@pytest.mark.parametrize('dataset',['COP30','SRTMGL1','USGS10m'])
def test_opentopo_bounds_dataset_and_secret_not_saved(source,tmp_path,dataset):
 options=normalize({'source_mode':'Download OpenTopography','opentopo_dataset':dataset});seen=[];secret='private-api-key-DoNotSave'
 def response(req,**kw):seen.append(req.full_url);return Response(source['dem'].read_bytes())
 with patch('providers.urlopen',side_effect=response):result=prepare(source['report'],source['xml'],[],options,cache=tmp_path/'cache',api_key=secret)
 query=parse_qs(urlsplit(seen[0]).query);bounds=result['providerPlan']['requestBounds'];assert float(query['south'][0])==bounds[0];assert float(query['east'][0])==bounds[3];assert query['API_Key']==[secret];assert query['datasetName' if dataset.startswith('USGS') else 'demtype']==[dataset]
 assert ('/usgsdem?' if dataset.startswith('USGS') else '/globaldem?') in seen[0]
 report=export(result,tmp_path/'map.png')
 for file in list((tmp_path/'cache').rglob('*.json'))+[Path(p) for p in report['files'].values() if str(p).endswith(('.json','.txt'))]:assert secret not in file.read_text(encoding='utf-8')
 assert secret not in json.dumps(project_dict(result));np.testing.assert_allclose(result['terrain'],source['z'],atol=1e-9)
 with patch('providers.urlopen',side_effect=AssertionError('Cache not reused')):prepare(source['report'],source['xml'],[],options,cache=tmp_path/'cache')

def test_opentopo_key_required_before_network(source,tmp_path):
 with patch('providers.urlopen',side_effect=AssertionError('Unexpected network')),pytest.raises(ValueError,match='API key'):acquire(source['bounds'],normalize({'source_mode':'Download OpenTopography'}),tmp_path)

def test_bad_html_download_does_not_replace_previous_cache(source,tmp_path):
 target=tmp_path/'dem.tif';target.write_bytes(b'old invalid cache')
 with patch('providers.urlopen',return_value=Response(b'<html>provider login</html>')),pytest.raises(ValueError,match='GeoTIFF'):fetch_geotiff('https://example.org/dem',target,Job(),0,1,10,'Provider',{})
 assert target.read_bytes()==b'old invalid cache';assert not list(tmp_path.glob('.download-*'))

def test_direct_cancel_keeps_existing_cache(source,tmp_path):
 target=tmp_path/'dem.tif';target.write_bytes(b'old invalid cache');event=threading.Event()
 class Slow(Response):
  def read(self,n=-1):event.set();return super().read(n)
 with patch('providers.urlopen',return_value=Slow(source['dem'].read_bytes())),pytest.raises(Cancelled):fetch_geotiff('https://example.org/dem.tif',target,Job(cancel=event),0,1,10,'Provider',{})
 assert target.read_bytes()==b'old invalid cache';assert not list(tmp_path.glob('.download-*'))

def test_download_size_limit(source,tmp_path):
 response=Response(source['dem'].read_bytes());response.headers={'Content-Length':str(2*1024*1024)}
 with patch('providers.urlopen',return_value=response),pytest.raises(ValueError,match='limit'):fetch_geotiff('https://example.org/dem.tif',tmp_path/'map.tif',Job(),0,1,1,'Provider',{})
 assert not (tmp_path/'map.tif').exists()

def test_utm_source_reprojects_to_same_non_square_game_rectangle(source,tmp_path):
 from rasterio.warp import reproject,calculate_default_transform,Resampling
 with rasterio.open(source['dem']) as src:
  transform,w,h=calculate_default_transform(src.crs,'EPSG:32631',src.width,src.height,*src.bounds);z=np.full((h,w),77.)
 file=tmp_path/'utm.tif'
 # Extend UTM coverage beyond original rectangle so no edge samples are lost.
 transform=transform*Affine.translation(-10,-10);w+=20;h+=20
 with rasterio.open(file,'w',driver='GTiff',width=w,height=h,count=1,dtype='float64',crs='EPSG:32631',transform=transform) as ds:ds.write(np.full((h,w),77.),1)
 values,affine,meta=sample_sources([file],source['bounds'],(129,257),normalize());np.testing.assert_allclose(values,77,atol=1e-9);assert meta[0]['crs']=='EPSG:32631'
 assert affine*(.5,.5)==pytest.approx(source['affine']*(.5,.5))
def test_projected_dem_vertex_values_use_exact_transform(tmp_path):
 from rasterio.warp import transform,calculate_default_transform
 bounds=[59.2,18.2,59.3,18.4];loX,loY,hiX,hiY=mercator_bounds(bounds)
 affine,w,h=calculate_default_transform('EPSG:3857','EPSG:32634',257,129,loX,loY,hiX,hiY);affine=affine*Affine.translation(-10,-10);w+=20;h+=20
 xx,yy=np.meshgrid(np.arange(w)+.5,np.arange(h)+.5);u=affine.a*xx+affine.b*yy+affine.c;v=affine.d*xx+affine.e*yy+affine.f
 file=tmp_path/'projected.tif'
 with rasterio.open(file,'w',driver='GTiff',width=w,height=h,count=1,dtype='float64',crs='EPSG:32634',transform=affine) as ds:ds.write(u*.001+v*.0001,1)
 actual,t,meta=sample_sources([file],bounds,(129,257),normalize());xx,yy=np.meshgrid(np.arange(257)+.5,np.arange(129)+.5);mx=t.a*xx+t.c;my=t.e*yy+t.f;x,y=transform('EPSG:3857','EPSG:32634',mx.ravel(),my.ravel());expected=(np.array(x)*.001+np.array(y)*.0001).reshape(actual.shape)
 np.testing.assert_allclose(actual,expected,atol=1e-8,rtol=0)

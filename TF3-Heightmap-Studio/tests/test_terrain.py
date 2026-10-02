import sys,json,hashlib,gzip,io,threading,os
from pathlib import Path
from unittest.mock import patch
import pytest
import numpy as np
import rasterio
from rasterio import Affine
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from alignment import mercator_bounds,geographic,load_context
from terrain import prepare,export,fill_gaps,water_mask,limit_grade,apply_stroke,load_project,project_dict
from elevation import sample_sources,hgt_data,tile_names,download_tiles
from height_settings import normalize,dimensions,validate_stroke
from job import Job,Cancelled
import osm_converter as osm

@pytest.fixture
def source(tmp_path):
 bounds=[0,0,.01,.01];size=[256,256];nx=ny=65
 xml=tmp_path/'demo.osm';xml.write_text('<osm version="0.6"><bounds minlat="0" minlon="0" maxlat="0.01" maxlon="0.01"/><node id="1" lat="0.002" lon="0.002"/><node id="2" lat="0.008" lon="0.008"/><way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>')
 report=tmp_path/'demo.report.json';report.write_text(json.dumps({'dataset':'fixture-1','input':xml.name,'bounds':bounds,'mapSize':size,'sourceSha256':hashlib.sha256(xml.read_bytes()).hexdigest(),'settings':{}}))
 minx,miny,maxx,maxy=mercator_bounds(bounds);dx=(maxx-minx)/64;dy=(maxy-miny)/64
 affine=Affine(dx,0,minx-dx/2,0,-dy,maxy+dy/2)
 z=100+np.arange(ny)[:,None]*.5+np.arange(nx)[None,:]*.25
 dem=tmp_path/'elevation.tif'
 with rasterio.open(dem,'w',driver='GTiff',width=nx,height=ny,count=1,dtype='float64',crs='EPSG:3857',transform=affine,nodata=-9999) as ds:ds.write(z,1);ds.set_band_unit(1,'m')
 return {'xml':xml,'report':report,'dem':dem,'bounds':bounds,'size':size,'z':z,'affine':affine}

def run(s,options=None,**kw):return prepare(s['report'],s['xml'],[s['dem']],options,**kw)

def test_exact_vertices_and_north_orientation(source):
 result=run(source);np.testing.assert_allclose(result['terrain'],source['z'],atol=1e-9)
 transform=result['geoTransform'];minx,miny,maxx,maxy=mercator_bounds(source['bounds'])
 np.testing.assert_allclose(transform*(.5,.5),(minx,maxy),atol=1e-9)
 np.testing.assert_allclose(transform*(64.5,64.5),(maxx,miny),atol=1e-9)
 assert geographic(-128,128,source['bounds'],source['size'])==pytest.approx((.01,0),abs=1e-12)
 assert geographic(128,-128,source['bounds'],source['size'])==pytest.approx((0,.01),abs=1e-12)

@pytest.mark.parametrize('lat,lon',[(60,18),(-45,-73),(70,120)])
def test_projection_inverse_high_latitudes(lat,lon):
 bounds=[lat,lon,lat+.1,lon+.2];size=[2048,1024]
 for la,lo in [(lat,lon),(lat+.033,lon+.125),(lat+.1,lon+.2)]:
  x,y=osm.project(la,lo,bounds,size);assert geographic(x,y,bounds,size)==pytest.approx((la,lo),abs=1e-10)

def test_checksum_rejects_other_osm(source):
 source['xml'].write_text(source['xml'].read_text().replace('0.008','0.009'))
 with pytest.raises(ValueError,match='checksum'):run(source)

def test_legacy_report_warns(source):
 p=json.loads(source['report'].read_text());p.pop('sourceSha256');source['report'].write_text(json.dumps(p))
 assert any('checksum' in w.lower() for w in run(source)['warnings'])

def test_feet_scale_offset(source):
 with rasterio.open(source['dem'],'r+') as ds:ds.scales=(2,);ds.offsets=(3,);ds.set_band_unit(1,'ft')
 np.testing.assert_allclose(run(source)['terrain'],(source['z']*2+3)*.3048,atol=1e-8)

@pytest.mark.parametrize('settings',[{'bogus':1},{'band':True},{'vertical_scale':float('nan')},{'pixels_x':33.5},{'range_min':1000,'range_max':-1}])
def test_invalid_settings(settings):
 with pytest.raises(ValueError):normalize(settings)

def test_large_grid_rejected():
 with pytest.raises(ValueError):dimensions([65536,65536],normalize())
 with pytest.raises(ValueError,match='53 million'):dimensions([30000,30000],normalize())

@pytest.mark.parametrize('tiles',[
 [(16,16),(10,20),(8,24),(8,24),(6,30)],
 [(32,32),(22,44),(18,54),(16,54),(14,70)],
 [(44,44),(32,64),(26,78),(22,88),(20,100)],
 [(56,56),(40,80),(32,96),(28,112),(24,126)],
 [(64,64),(44,88),(36,108),(32,128),(28,140)],
 [(80,80),(56,112),(46,138),(40,160),(34,170)],
 [(96,96),(66,132),(54,162),(48,192),(42,210)],
 [(112,112),(80,160),(64,192),(56,224),(50,250)],
])
def test_all_tf3_native_map_formats_fit_exact_four_metre_grid(tiles):
 for x,y in tiles:
  assert dimensions([x*256,y*256],normalize())==(x*64+1,y*64+1)

def test_gap_stop_and_limited_fill():
 z=np.ones((65,65));z[32,32]=np.nan
 with pytest.raises(ValueError,match='missing'):fill_gaps(z,[256,256],normalize(),Job())
 result=fill_gaps(z,[256,256],normalize({'missing_data':'Fill small gaps (nearest)','max_gap_m':4}),Job());assert result['filledSamples']==1;assert result['maximumFillDistanceMetres']==4;assert z[32,32]==1
 z[32,32]=np.nan
 with pytest.raises(ValueError,match='largest'):fill_gaps(z,[256,256],normalize({'missing_data':'Fill small gaps (nearest)','max_gap_m':3}),Job())

def test_mosaic_priority_and_voids(source,tmp_path):
 with rasterio.open(source['dem'],'r+') as ds:z=source['z'].copy();z[30:35,30:35]=-9999;ds.write(z,1)
 other=tmp_path/'other.tif'
 with rasterio.open(other,'w',driver='GTiff',width=65,height=65,count=1,dtype='float64',crs='EPSG:3857',transform=source['affine']) as ds:ds.write(np.full((65,65),77.),1)
 z,_,_=sample_sources([source['dem'],other],source['bounds'],(65,65),normalize({'resampling':'Nearest'}))
 assert z[32,32]==77;assert z[0,0]==100

def test_hgt_big_endian_orientation(tmp_path):
 p=tmp_path/'S01W002.hgt.gz';values=np.arange(9,dtype='>i2').reshape(3,3);p.write_bytes(gzip.compress(values.tobytes()));z,a,crs=hgt_data(p)
 np.testing.assert_array_equal(z,values);assert a*(.5,.5)==(-2,0);assert a*(2.5,2.5)==(-1,-1);assert crs=='EPSG:4326'

def test_public_tile_names_and_limit(tmp_path):
 assert tile_names([-.1,-.1,.1,.1])==['S01W001','S01E000','N00W001','N00E000']
 assert tile_names([59,18,60,19])==['N59E018']
 with pytest.raises(ValueError,match='limit'):download_tiles([0,0,3,3],tmp_path,max_tiles=2)

def test_download_validation_and_cache(tmp_path):
 payload=gzip.compress(np.arange(9,dtype='>i2').tobytes())
 class Response(io.BytesIO):headers={'Content-Length':str(len(payload))}
 with patch('elevation.urlopen',return_value=Response(payload)) as fetch:
  files=download_tiles([59,18,59.1,18.1],tmp_path);assert fetch.call_count==1;assert files[0].name=='N59E018.hgt.gz'
 with patch('elevation.urlopen',side_effect=AssertionError('Cache missed')):assert download_tiles([59,18,59.1,18.1],tmp_path)==files
 assert not list(tmp_path.glob('.download-*'))

def test_download_cancel_keeps_invalid_old_cache(tmp_path):
 old=tmp_path/'N59E018.hgt.gz';old.write_bytes(b'old');payload=gzip.compress(np.arange(9,dtype='>i2').tobytes());event=threading.Event()
 class Response(io.BytesIO):
  headers={'Content-Length':str(len(payload))}
  def read(self,n=-1):event.set();return super().read(n)
 with patch('elevation.urlopen',return_value=Response(payload)),pytest.raises(Cancelled):download_tiles([59,18,59.1,18.1],tmp_path,Job(cancel=event))
 assert old.read_bytes()==b'old';assert not list(tmp_path.glob('.download-*'))

def test_lake_hole_preserved():
 outer=[[-100,-100],[100,-100],[100,100],[-100,100]];inner=[[-20,-20],[20,-20],[20,20],[-20,20]]
 mask=water_mask({'size':[256,256],'lakes':[{'outer':[outer],'inner':[inner]}]},(65,65));assert not mask[32,32];assert mask[32,45];assert not mask[0,0]

def test_grade_limit():
 p=np.column_stack([np.arange(6)*10,np.zeros(6)]);z=limit_grade(np.array([0.,10,30,-20,100,0]),p,3)
 assert np.max(np.abs(np.diff(z)))<=.3000000001

@pytest.mark.parametrize('tool,strength',[('Raise',3),('Lower',3),('Smooth',.5),('Flatten',.5)])
def test_brush_locality_and_undo(tool,strength):
 z=np.zeros((65,65));z[32,32]=10;old=z.copy();stroke={'tool':tool,'x':0,'y':0,'radius':40,'strength':strength,'target':20}
 undo=apply_stroke(z,[256,256],stroke);assert not np.array_equal(z,old);assert z[0,0]==0
 r0,r1,c0,c1,prev=undo;z[r0:r1,c0:c1]=prev;np.testing.assert_array_equal(z,old)

def test_brush_invalid_strength():
 with pytest.raises(ValueError):validate_stroke({'tool':'Smooth','x':0,'y':0,'radius':40,'strength':3,'target':0},[256,256])

def test_export_precision_georef_and_progress(source,tmp_path):
 result=run(source);events=[];report=export(result,tmp_path/'my.map.png',progress=lambda p,*a:events.append(p))
 assert events==sorted(events) and events[-1]==100
 with Image.open(report['files']['png']) as img:
  codes=np.asarray(img);assert codes.shape==(65,65);decoded=report['importMinimumMetres']+codes*(report['importMaximumMetres']-report['importMinimumMetres'])/65535
 np.testing.assert_allclose(decoded,result['terrain'],atol=report['pngEncodingStepMetres']/2+1e-8)
 header=Path(report['files']['png']).read_bytes()[:26];assert header[24:26]==b'\x10\x00'
 with rasterio.open(report['files']['dem']) as ds:np.testing.assert_array_equal(ds.read(1),result['terrain']);assert ds.transform==result['geoTransform'];assert ds.dtypes==('float64',)
 assert all(Path(p).exists() for p in report['files'].values());assert report['nativeTF3ImportVerified'] is False
 p=load_project(report['files']['project']);assert p['osmSha256']==result['context']['osmSha256'];assert p['options']==result['options']

def test_manual_range_and_explicit_clip(source,tmp_path):
 result=run(source,{'range_mode':'Manual range','range_min':110,'range_max':120})
 with pytest.raises(ValueError,match='outside'):export(result,tmp_path/'map.png')
 result['options']['clip_heights']=True;report=export(result,tmp_path/'map.png');assert report['clippedPngSamples']>0
 with rasterio.open(report['files']['dem']) as ds:assert ds.read(1).min()==100

def test_project_relative_paths_and_report_changes(source,tmp_path):
 result=run(source);p=project_dict(result,'out.png');p['converterReport']=source['report'].name;p['osmFile']=source['xml'].name;p['elevationFiles']=[source['dem'].name]
 path=tmp_path/'profile.json';path.write_text(json.dumps(p));loaded=load_project(path);assert Path(loaded['osmFile'])==source['xml'];assert Path(loaded['output'])==tmp_path/'out.png'
 report=json.loads(source['report'].read_text());report['mapSize']=[512,512];source['report'].write_text(json.dumps(report))
 with pytest.raises(ValueError,match='changed'):load_project(path)

def test_prepare_cancel_at_ready(source):
 event=threading.Event()
 def progress(p,*a):
  if p>=95:event.set()
 with pytest.raises(Cancelled):run(source,cancel=event,progress=progress)

def test_export_cancel_keeps_all_files(source,tmp_path):
 result=run(source);report=export(result,tmp_path/'map.png');before={p:Path(p).read_bytes() for p in report['files'].values()};event=threading.Event()
 def progress(p,*a):
  if p>=95:event.set()
 with pytest.raises(Cancelled):export(result,tmp_path/'map.png',progress=progress,cancel=event)
 assert all(Path(p).read_bytes()==b for p,b in before.items());assert not list(tmp_path.glob('.tf3-heightmap-export-*'))

def test_commit_failure_rolls_back(source,tmp_path):
 result=run(source);report=export(result,tmp_path/'map.png');before={p:Path(p).read_bytes() for p in report['files'].values()};replace=os.replace;failed=False
 def fail(src,dst):
  nonlocal failed
  if str(dst).endswith('.heightmap-report.json') and not failed:failed=True;raise OSError('Simulated commit failure')
  return replace(src,dst)
 with patch('terrain.os.replace',side_effect=fail),pytest.raises(OSError):export(result,tmp_path/'map.png')
 assert all(Path(p).read_bytes()==b for p,b in before.items());assert not list(tmp_path.glob('.tf3-heightmap-export-*'))

def test_export_protects_source(source):
 result=run(source)
 # A .dem.tif sidecar may never replace the input DEM.
 target=source['dem'].parent/'elevation.png';protected=target.with_name('elevation.dem.tif');protected.write_bytes(source['dem'].read_bytes());result['sourceFiles'].append(str(protected))
 with pytest.raises(ValueError,match='source'):export(result,target)
def test_bridge_corridor_is_excluded(source):
 xml=source['xml'].read_text().replace('<tag k="highway" v="residential"/>','<tag k="highway" v="residential"/><tag k="bridge" v="yes"/>');source['xml'].write_text(xml)
 report=json.loads(source['report'].read_text());report['sourceSha256']=hashlib.sha256(source['xml'].read_bytes()).hexdigest();source['report'].write_text(json.dumps(report))
 result=run(source,{'roads':True});np.testing.assert_array_equal(result['terrain'],result['baseline']);assert any('excluded' in w for w in result['warnings'])

def test_saved_brush_reproduces_terrain(source,tmp_path):
 result=run(source);stroke={'tool':'Raise','x':24,'y':48,'radius':40,'strength':3,'target':0};apply_stroke(result['terrain'],source['size'],stroke);result['strokes']=[stroke]
 report=export(result,tmp_path/'map.png');project=load_project(report['files']['project']);replayed=prepare(project['converterReport'],project['osmFile'],project['elevationFiles'],project['options'],project['brushStrokes']);np.testing.assert_array_equal(replayed['terrain'],result['terrain'])

def test_missing_crs_requires_explicit_override(source,tmp_path):
 file=tmp_path/'unreferenced.tif'
 with rasterio.open(file,'w',driver='GTiff',width=65,height=65,count=1,dtype='float64',transform=source['affine']) as ds:ds.write(source['z'],1)
 with pytest.raises(ValueError,match='reference system'):sample_sources([file],source['bounds'],(65,65),normalize())
 z,_,_=sample_sources([file],source['bounds'],(65,65),normalize({'crs_override':'EPSG:3857'}));np.testing.assert_allclose(z,source['z'],atol=1e-9)

def test_public_export_contains_provider_credits(source,tmp_path):
 result=run(source);result['public']=True;report=export(result,tmp_path/'public.png');credits=Path(report['files']['attribution']).read_text(encoding='utf-8');assert 'Copernicus' in credits and 'U.S. Geological Survey' in credits

def test_preview_keeps_physical_map_aspect(source):
 from terrain import preview_image
 result=run(source);result['context']['size']=[512,256];img=preview_image(result,(800,800));assert img.size==(800,400)

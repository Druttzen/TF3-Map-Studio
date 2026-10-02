import json,sys,threading
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import pytest
import rasterio

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import biomes
from height_settings import normalize
from terrain import prepare,export,load_project,project_dict,apply_stroke
from job import Job,Cancelled
from test_terrain import source

def run(s,**options):
 return prepare(s['report'],s['xml'],[s['dem']],{'biomes':True,**options})

@pytest.mark.parametrize('climate',list(biomes.CLIMATES))
def test_vanilla_climates_export_native_codes_exactly_and_keep_heights(source,tmp_path,climate):
 r=run(source,biome_climate=climate);before=r['terrain'].copy()
 strokes=[{'x':-100+i*50,'y':60,'radius':19,'biome':i} for i in range(5)]
 r['biomeStrokes']=strokes;r['biomes']=None;grid=biomes.ensure(r).copy()
 report=export(r,tmp_path/'map.png');metadata=report['biomes']
 assert metadata['climate']==climate;assert metadata['northUp'];assert metadata['mapSize']==source['size']
 assert metadata['bounds']==source['bounds'];assert metadata['nativeGameImportVerified'] is False
 with Image.open(report['files']['biomes']) as image:
  assert image.mode=='L';assert image.size==(65,65)
  np.testing.assert_array_equal(np.asarray(image),biomes.CODES[grid])
  assert set(np.unique(np.asarray(image)))=={0,63,127,191,255}
 with rasterio.open(report['files']['biomeGeoTiff']) as ds:
  assert ds.transform==r['geoTransform'];assert ds.crs.to_epsg()==3857
  np.testing.assert_array_equal(ds.read(1),grid)
 assert sum(p['vertices'] for p in metadata['palette'])==65*65
 assert sum(p['percent'] for p in metadata['palette'])==pytest.approx(100)
 np.testing.assert_array_equal(r['terrain'],before)
 assert len(report['files'])==10;assert all(Path(p).is_file() for p in report['files'].values())
 assert '3493540/local/biomes' in Path(report['files']['instructions']).read_text()

def test_height_slope_water_and_osm_precedence():
 z=np.zeros((65,65));z[:16]=1600;z[16:32]=700;z[48:]=-10
 ctx={'size':[256,256],'lines':[],'bounds':[0,0,.01,.01],
      'biomeAreas':[{'kind':'forest','outer':[[[-80,-80],[80,-80],[80,80],[-80,80]]],
                     'inner':[[[-20,-20],[20,-20],[20,20],[-20,20]]]}]}
 opts=normalize({'biomes':True,'biome_rock_slope':90})
 grid,_=biomes.generate(z,ctx,opts)
 assert grid[8,8]==4;assert grid[22,8]==3;assert grid[40,8]==2;assert grid[60,8]==0
 assert grid[24,24]==1;assert grid[32,32]==2 # Polygon hole preserves base.
 assert grid[51,24]==0 # Underwater rule overrides forest.

def test_slope_in_degrees_uses_physical_size():
 ctx={'size':[256,256],'lines':[]};z=np.tile(np.arange(65)*4.,(65,1))
 opts=normalize({'biomes':True,'biome_mode':'Height and slope','biome_rock_slope':40})
 grid,_=biomes.generate(z,ctx,opts);assert np.all(grid==4) # 45-degree slope.
 ctx['size']=[512,256];grid,_=biomes.generate(z,ctx,opts);assert np.all(grid==2) # 26.6 degrees.

def test_single_biome_and_water_switch():
 ctx={'size':[256,256],'lines':[]};z=np.full((65,65),-10.)
 opts=normalize({'biomes':True,'biome_mode':'Single biome','biome_base':biomes.BIOME_CHOICES[3]})
 assert np.all(biomes.generate(z,ctx,opts)[0]==0)
 opts['biome_water']=False;assert np.all(biomes.generate(z,ctx,opts)[0]==3)

def test_paint_is_aligned_categorical_and_does_not_change_elevation():
 grid=np.zeros((65,65),dtype=np.uint8);size=[256,256]
 stroke={'x':64,'y':64,'radius':12,'biome':4};undo=biomes.paint(grid,size,stroke)
 assert grid[16,48]==4;assert grid[48,48]==0;assert grid[16,16]==0
 assert set(np.unique(grid))=={0,4}
 r0,r1,c0,c1,old=undo;grid[r0:r1,c0:c1]=old;assert not grid.any()

def test_brush_project_replay_and_terrain_edit_refresh(source,tmp_path):
 r=run(source,biome_alpine_m=900);stroke={'x':32,'y':64,'radius':25,'biome':4}
 r['biomeStrokes']=[stroke];r['biomes']=None;expected=biomes.ensure(r).copy()
 rep=export(r,tmp_path/'map.png');p=load_project(rep['files']['project'])
 replay=prepare(p['converterReport'],p['osmFile'],p['elevationFiles'],p['options'],p['brushStrokes'],biome_strokes=p['biomeStrokes'])
 np.testing.assert_array_equal(replay['biomes'],expected)
 z=replay['terrain'].copy();apply_stroke(replay['terrain'],p['mapSize'],{'tool':'Raise','x':-64,'y':-64,'radius':20,'strength':1000,'target':0})
 replay['biomes']=None;assert biomes.ensure(replay)[48,16]==4
 assert biomes.ensure(replay)[16,40]==4;assert not np.array_equal(z,replay['terrain'])

def test_imported_png_retains_regions_and_saved_checksum(source,tmp_path):
 png=tmp_path/'input.png';codes=np.tile(biomes.CODES[np.arange(65)%5],(65,1));Image.fromarray(codes).save(png)
 r=run(source,biome_mode='Import biome PNG',biome_source=str(png))
 np.testing.assert_array_equal(biomes.CODES[r['biomes']],codes)
 p=export(r,tmp_path/'map.png');loaded=load_project(p['files']['project']);assert loaded['biomeSourceSha256']
 replay=prepare(loaded['converterReport'],loaded['osmFile'],loaded['elevationFiles'],loaded['options'],loaded['brushStrokes'],biome_strokes=loaded['biomeStrokes'])
 np.testing.assert_array_equal(replay['biomes'],r['biomes'])
 Image.fromarray(np.zeros((65,65),dtype=np.uint8)).save(png)
 with pytest.raises(ValueError,match='checksum'):load_project(p['files']['project'])

@pytest.mark.parametrize('mode,shape,value',[('RGB',(65,65),0),('L',(33,33),63),('L',(65,65),64)])
def test_invalid_biome_png_rejected(source,tmp_path,mode,shape,value):
 png=tmp_path/'input.png';Image.new(mode,shape,value).save(png)
 with pytest.raises(ValueError):run(source,biome_mode='Import biome PNG',biome_source=str(png))

@pytest.mark.parametrize('options',[{'biome_climate':'Custom mod'},{'biome_base':'5'},{'biome_rock_slope':91},{'biome_alpine_m':0},{'biomes':1}])
def test_invalid_biome_settings_rejected(options):
 with pytest.raises(ValueError):normalize(options)

def test_osm_land_cover_multipolygons_keep_holes_and_skip_cycles():
 from alignment import osm
 positions={'1':[-100,-100],'2':[100,-100],'3':[100,100],'4':[-100,100],
            '5':[-20,-20],'6':[20,-20],'7':[20,20],'8':[-20,20]}
 ways={'o':(['1','2','3','4','1'],{}),'i':(['5','6','7','8','5'],{})}
 relations={'f':([{'type':'way','ref':'o','role':'outer'},{'type':'way','ref':'i','role':'inner'}],{'type':'multipolygon','landuse':'forest'}),
            'bad':([{'type':'relation','ref':'bad','role':'outer'}],{'type':'multipolygon','natural':'wood'})}
 warnings=[];areas=biomes.land_areas(ways,relations,positions,osm,Job(),warnings)
 assert len(areas)==1;assert areas[0]['kind']=='forest';assert len(areas[0]['inner'])==1
 assert any('Cyclic' in w for w in warnings)

def test_disabled_biomes_preserve_old_project_and_seven_file_exports(source,tmp_path):
 r=prepare(source['report'],source['xml'],[source['dem']]);rep=export(r,tmp_path/'map.png')
 assert rep['biomes'] is None;assert len(rep['files'])==7
 p=project_dict(r);p.pop('biomeStrokes');p.pop('biomeSourceSha256');p['options']={k:v for k,v in p['options'].items() if not k.startswith('biome')}
 path=tmp_path/'old.json';path.write_text(json.dumps(p));loaded=load_project(path)
 assert loaded['biomeStrokes']==[];assert loaded['options']['biomes'] is False

def test_biome_commit_failure_and_cancel_restore_all_outputs(source,tmp_path):
 r=run(source);rep=export(r,tmp_path/'map.png');before={p:Path(p).read_bytes() for p in rep['files'].values()}
 replace=__import__('os').replace;failed=False
 def fail(src,dst):
  nonlocal failed
  if str(dst).endswith('.biomes.tif') and not failed:failed=True;raise OSError('test failure')
  return replace(src,dst)
 with patch('terrain.os.replace',side_effect=fail),pytest.raises(OSError):export(r,tmp_path/'map.png')
 assert all(Path(p).read_bytes()==v for p,v in before.items())
 event=threading.Event()
 def progress(p,stage,detail):
  if stage=='Writing vanilla biome maps':event.set()
 with pytest.raises(Cancelled):export(r,tmp_path/'map.png',progress=progress,cancel=event)
 assert all(Path(p).read_bytes()==v for p,v in before.items())
 assert not list(tmp_path.glob('.tf3-heightmap-export-*'))

def test_biome_output_may_not_overwrite_imported_input(source,tmp_path):
 png=tmp_path/'map.biomes.png';Image.new('L',(65,65),63).save(png)
 r=run(source,biome_mode='Import biome PNG',biome_source=str(png))
 with pytest.raises(ValueError,match='source'):export(r,tmp_path/'map.png')

def test_cancellation_during_biome_generation(source):
 event=threading.Event()
 def progress(p,stage,detail):
  if stage=='Building vanilla biome regions':event.set()
 with pytest.raises(Cancelled):prepare(source['report'],source['xml'],[source['dem']],{'biomes':True},progress=progress,cancel=event)

import json,os,zipfile
from pathlib import Path
import pytest
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.native_projection import project_native_model,UnsupportedProjection
from trf3_mod_converter.native_donors import NativeDonorCatalog
from trf3_mod_converter.tf2_vehicle_port import NativeInventory,emit
from trf3_mod_converter import batch
from test_native_donors import Native,donor
from test_cargo_port import NativeCargo
from trf3_mod_converter.cargo_port import CargoCatalog

@pytest.mark.parametrize('binding',['local function _(x) return "Changed" end','function _(x) return "Changed" end'])
def test_shadowed_localization_is_blocked(binding):
 with pytest.raises(ValueError,match='shadowed localization'):
  load_lua_table(binding+' function data() return {info={name=_("Original")}} end')

def test_cargo_reinclusion_order_is_shared():
 catalog=CargoCatalog.from_native(NativeCargo())
 data={'cargoClassesIncluded':['UNIVERSAL'],'cargoClassesExcluded':['BULK'],'cargoTypesIncluded':['COAL'],'cargoTypesExcluded':[]}
 expected=catalog.evaluate_set(data)[0]
 assert 'coal' in expected
 assert catalog.resolve_set(data)[0]==expected
 from trf3_mod_converter.native_donors import _cargo_set
 from trf3_mod_converter.donor_cargo import _keys
 assert _cargo_set(data,catalog)==expected
 assert _keys({'cargoTypeSet':data},catalog,'fixture')==expected

def test_unused_lod_still_requires_valid_lua_grammar():
 with pytest.raises(UnsupportedProjection):project_native_model('function data() return {version=2,metadata={},boundingInfo={},lods={+1}} end')

def test_version_one_native_donor_cannot_complete_data():
 data=donor();data['version']=1
 with pytest.raises(ValueError,match='no verified'):
  NativeDonorCatalog.from_native(Native({'vehicle/old.mdl.lua':data}))

@pytest.mark.parametrize('storage',['loose','zip'])
def test_resume_requires_current_native_bytes(tmp_path,monkeypatch,storage):
 source=tmp_path/'mod';source.mkdir();(source/'mod.lua').write_text('function data() return {info={name="Fixture"}} end')
 (source/'res').mkdir();(source/'res/source.txt').write_text('data')
 game=tmp_path/'game';content=game/'base/content';content.mkdir(parents=True)
 resource='templates/required.trf.lua'
 def write(value):
  if storage=='zip':
   with zipfile.ZipFile(content/'game.zip','w') as archive:archive.writestr(resource,value)
  else:
   target=content/resource;target.parent.mkdir(exist_ok=True);target.write_text(value)
 write('original')
 monkeypatch.setattr(batch,'_preflight_profile',lambda root:None)
 def export(item,target,tf3,native_cache,tf2_cache,progress):
  target.mkdir();(target/'export.txt').write_text('reviewable')
  inventory=native_cache[str(game.resolve())].fork();inventory.read(resource)
  return {'nativeResourceFingerprints':inventory.dependencies}
 monkeypatch.setattr(batch,'_export',export)
 items=batch.scan_mods(source)['items'];output=tmp_path/'output'
 assert batch.convert_queue(items,output,tf3_game=game)['counts']['completed']==1
 assert batch.convert_queue(batch.scan_mods(source)['items'],output,tf3_game=game)['counts']['completed']==1
 before=(output/items[0].mod_id/'export.txt').read_bytes();write('modified')
 state=batch.convert_queue(batch.scan_mods(source)['items'],output,tf3_game=game)
 assert state['counts']['failed']==1
 assert (output/items[0].mod_id/'export.txt').read_bytes()==before

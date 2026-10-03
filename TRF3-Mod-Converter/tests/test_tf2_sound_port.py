import json
import math

import pytest

from trf3_mod_converter import convert_mod, prepare_mod
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_sound_port import port_sound_set
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot
from test_tf2_vehicle_port import fixture_mod


SOUND = '''local audioutil = require "audioutil"
local soundeffectsutil = require "soundeffectsutil"
function data() return {
 tracks = {
  {name="vehicle/CUSTOM/Drive.wav",refDist=25},
  {name="vehicle/train/wheels_ringing1.wav",refDist=25},
  {name="vehicle/train_electric_modern/_brakes.wav",refDist=25}
 },
 events = {
  clacks={names={"vehicle/clack/modern/part_1.wav"},refDist=15},
  horn={names={"vehicle/CUSTOM/Horn.wav"},refDist=50}
 },
 updateFn=function(input)
  local axleRefWeight=10
  return {
   tracks={
    {gain=soundeffectsutil.sampleCurve(audioutil.plotSqrt(0,.05,.3,.3,3),input.speed01),
     pitch=soundeffectsutil.sampleCurve({{0,.7},{1,1}},input.speed01)},
    soundeffectsutil.squeal(input.speed,input.sideForce,input.maxSideForce),
    soundeffectsutil.brake(input.speed,input.brakeDecel,.5)
   },
   events={clacks=soundeffectsutil.clacks(input.speed,input.weight,input.numAxles,axleRefWeight,input.gameSpeedUp),
           horn={gain=1,pitch=1}}
  }
 end
} end'''


class Native:
    def reference(self, path): return '::/'+path


def test_sound_translation_preserves_curves_order_distances_and_weight_units():
    calls = []
    def resolve(ref,kind):
        calls.append((ref,kind))
        return 'converted::/audio/'+ref.lower()
    result = port_sound_set(SOUND,resolve,Native())
    assert len(calls) == 5 and all(k == 'audio' for _,k in calls)
    assert result['tracks'][0] == {'name':'converted::/audio/vehicle/custom/drive.wav','attrs':{'refDist':25}}
    assert result['events']['horn']['attrs'] == {'refDist':50}
    assert result['updateScript']['fileName'] == '::/scripts/soundset_default.script@updateSoundSet'
    updates = result['updateScript']['params']['updateFunctions']
    assert [u['type'] for u in updates] == ['SampleCurve','Squeal','Brake','Clacks','SampleCurve']
    assert updates[0]['params']['gainCurve'] == [[0,.05],[.3/9,.05+.25/3],[.3*4/9,.05+.5/3],[.3,.3]]
    assert updates[0]['params']['pitchCurve'] == [[0,.7],[1,1]]
    assert updates[2]['params']['maxGain'] == .5
    assert updates[3] == {'type':'Clacks','params':{'axleRefWeight':10000},'eventKey':'clacks'}
    assert updates[4]['eventKey'] == 'horn'
    roundtrip = load_lua_table(emit(result))
    assert roundtrip['tracks'] == result['tracks'] and roundtrip['events'] == result['events']
    assert roundtrip['updateScript']['params']['updateFunctions'][0] == updates[0]


@pytest.mark.parametrize('old,new', [
    ('local axleRefWeight=10','local axleRefWeight=executeMod()'),
    ('local axleRefWeight=10','input.speed=0'),
    ('local axleRefWeight=10','local input=10'),
    ('input.speed01','input.mysteryField'),
    ('require "audioutil"','require "customHelper"'),
    ('input.sideForce','input.otherForce'),
    ('input.brakeDecel','input.otherDecel'),
    ('input.gameSpeedUp','input.otherSpeed'),
    ('local axleRefWeight=10','if true then return {} end'),
    ('refDist=25','refDist=-1'),
    ('{0,.7},{1,1}','{1,.7},{0,1}'),
    ('0,.05,.3,.3,3','0,.05,.3,.3,0'),
    ('local axleRefWeight=10','local soundeffectsutil=10'),
])
def test_unknown_behavior_is_not_silently_discarded(old,new):
    with pytest.raises(ValueError):
        port_sound_set(SOUND.replace(old,new),lambda r,k:r,Native())


def test_empty_lifecycle_callback_is_omitted_with_original_archived(tmp_path):
    source=tmp_path/'source';source.mkdir()
    original='function data() return {info={name="Empty callback"}, runFn=function(settings) -- no behavior\n end} end'
    (source/'mod.lua').write_text(original)
    d=prepare_mod(source)
    assert not d.blockers and d.run_script is None
    assert any('empty inline callback' in w for w in d.warnings)
    report=convert_mod(source,tmp_path/'output')
    assert 'runScript' not in json.loads((tmp_path/'output/mod.json').read_text())
    assert report['sourceMetadata']['mod.lua']['runScript']['unsupportedLuaValue']
    assert (source/'mod.lua').read_text()==original


def test_tf2_audio_fallback_is_not_reported_as_missing_local_tf3_file(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'mod.lua').write_text(emit({'info':{'name':'Sound fixture'}}))
    target=source/'res/config/sound_set/Custom.lua';target.parent.mkdir(parents=True)
    target.write_text(SOUND)
    drive=source/'res/audio/effects/vehicle/CUSTOM/Drive.wav';drive.parent.mkdir(parents=True)
    drive.write_bytes(b'authored test clip')
    d=prepare_mod(source)
    assert not any('missing local resource' in b for b in d.blockers)
    assert any('sound set needs migration' in b for b in d.blockers)
    rows=d.resource_audit['references']
    assert next(r for r in rows if r['reference']=='vehicle/CUSTOM/Drive.wav')['status']=='legacy_local'
    assert next(r for r in rows if 'wheels_ringing' in r['reference'])['status']=='legacy_base_or_missing'
    assert not d.as_inspection()['canConvert']


def test_tf2_model_and_material_paths_use_resource_type_roots(tmp_path):
    source=tmp_path/'source';source.mkdir()
    (source/'mod.lua').write_text(emit({'info':{'name':'Root fixture'}}))
    paths={'models/model/vehicle/test.mdl':emit({'version':1,'lods':[{'node':{'mesh':'shape.msh','materials':['paint.mtl']}}]}),
           'models/material/paint.mtl':emit({'type':'PHYSICAL','params':{'map_albedo':{'fileName':'paint.dds'}}}),
           'models/mesh/shape.msh':emit({})}
    for name,text in paths.items():
        path=source/'res'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    (source/'res/models/mesh/shape.msh.blob').write_bytes(b'authored fixture')
    texture=source/'res/textures/paint.dds';texture.parent.mkdir();texture.write_bytes(b'authored texture')
    d=prepare_mod(source)
    assert not any('missing local resource' in b for b in d.blockers)
    rows=d.resource_audit['references']
    assert next(r for r in rows if r['reference']=='paint.dds')['target']=='res/textures/paint.dds'
    assert next(r for r in rows if r['reference']=='shape.msh')['target']=='res/models/mesh/shape.msh'
    assert any('resource-type roots' in b for b in d.blockers)


@pytest.mark.parametrize('expression,expected', [('42/255',42/255),('100/12.5',8),('math.pow(1.37,.55)',math.pow(1.37,.55)),('2^3',8)])
def test_resource_numeric_constants_are_folded_without_executing_lua(expression,expected):
    text='function data() return {value='+expression+'} end'
    assert load_lua_table(text,constant_numbers=True)['value']==expected


@pytest.mark.parametrize('expression',['1/0','math.pow(-1,.5)','math.pow(1e300,1e300)'])
def test_undefined_constants_are_rejected(expression):
    with pytest.raises(ValueError): load_lua_table('return {value='+expression+'}',constant_numbers=True)


def test_shadowed_math_does_not_use_python_math():
    with pytest.raises(ValueError,match='shadowed'):
        load_lua_table('local function math() end function data() return {value=math.pow(2,3)} end',constant_numbers=True)


def test_port_sound_resource_and_uppercase_parent_folders(fixture_mod):
    source,game,output=fixture_mod
    model=source/'res/models/model/vehicle/train/test.mdl'
    d=load_lua_table(model.read_text());d['metadata']['railVehicle']['soundSet']={'name':'CUSTOM','horn':''}
    model.write_text(emit(d))
    sound=source/'res/config/sound_set/CUSTOM.lua';sound.parent.mkdir(parents=True)
    sound.write_text(SOUND)
    audio=source/'res/audio/effects/vehicle/CUSTOM';audio.mkdir(parents=True)
    for filename in ['Drive.wav','Horn.wav']: (audio/filename).write_bytes(b'original authored test audio')
    base=game/'base/content'
    script=base/'scripts/soundset_default.script.tl';script.parent.mkdir()
    script.write_text('-- authored inventory placeholder')
    for ref in ['train/wheels_ringing1.wav','train_electric_modern/_brakes.wav','clack/modern/part_1.wav']:
        clip=base/'vehicle/train/shared/sound'/ref;clip.parent.mkdir(parents=True,exist_ok=True);clip.write_bytes(b'base placeholder')
    before=snapshot(source)
    report=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Custom Sound')
    assert report['portCounts']['soundSets']==1
    assert snapshot(source)==before
    assert all(p.relative_to(output/'content').as_posix()==p.relative_to(output/'content').as_posix().lower() for p in (output/'content').rglob('*'))
    converted=load_lua_table((output/'content/config/sound_set/custom.snd.lua').read_text())
    assert converted['tracks'][0]['name']=='fixture_test::/audio/effects/vehicle/custom/drive.wav'
    assert converted['tracks'][1]['name']=='::/vehicle/train/shared/sound/train/wheels_ringing1.wav'
    assert (output/'_port_originals/res/config/sound_set/CUSTOM.lua').read_bytes()==sound.read_bytes()
    assert (output/'content/audio/effects/vehicle/custom/drive.wav').read_bytes()==(audio/'Drive.wav').read_bytes()
    vehicle=load_lua_table((output/'content/models/model/vehicle/train/test.mdl').read_text())
    assert vehicle['metadata']['soundConfig']['soundSet']['name']=='fixture_test::/config/sound_set/custom.snd'
    assert report['nativeTest']=='not_run'

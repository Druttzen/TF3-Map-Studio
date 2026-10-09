import pytest

from trf3_mod_converter.resource_audit import callback_status, parse_lua
from trf3_mod_converter.tf2_sound_port import port_sound_set
from test_tf2_sound_port import Native


def sound(control, locals='', events='', event_controls='', attrs=''):
    return '''local soundeffectsutil = require "soundeffectsutil"
function data() return {
 tracks={{name="drive.wav",refDist=25''' + attrs + '''}},
 events={''' + events + '''},
 updateFn=function(input)
 ''' + locals + '''
 return { tracks={''' + control + '''}, events={''' + event_controls + '''} }
 end } end'''


def scripts_writer(scripts):
    def write(key, text):
        scripts.append(text)
        return 'converted::/scripts/sound.script@update'
    return write


def test_power_dependent_curve_compiles_without_changing_authored_point_order():
    text = sound('{gain=soundeffectsutil.sampleCurve({{0,0},{.25,.5},{.2,powergain*1.2},{.28,powergain*1.1},{.4,0}},input.speed01),'
                 'pitch=.6+(input.speed01-.44)*20}', 'local powergain=1.5-(1-input.power01)')
    scripts, audit = [], {}
    result = port_sound_set(text, lambda r,k:r, Native(), script_writer=scripts_writer(scripts), report=audit, resource='custom.lua')
    update = result['updateScript']['params']['updateFunctions'][0]
    assert update == {'type':'Custom','params':{'customUpdateScript':'converted::/scripts/sound.script@update','customParams':{}}}
    assert callback_status(parse_lua(scripts[0]), 'update') == 'resolved'
    assert scripts[0].index('{0.25,0.5}') < scripts[0].index('{0.2,') < scripts[0].index('{0.28,')
    assert 'currentInfo.vehicle.power01' in scripts[0]
    assert 'currentInfo.vehicle.speed01' in scripts[0]
    assert 'ug_require "::/scripts/audioutil.lua"' in scripts[0]
    assert audit['soundMigrations'][0]['curveOrder'] == 'preserved'


def test_generated_controller_runtime_preserves_first_match_curves_and_affine_pitch():
    # Only the converter's generated callback is executed. Source mods and
    # their helpers are never loaded; the native sampling contract is stubbed.
    lupa = pytest.importorskip('lupa')
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    def sample_curve(points, value):
        if len(points)==1:
            return points[1][2]
        for index in range(2,len(points)+1):
            first, second = points[index-1], points[index]
            if value <= second[1]:
                break
        delta = second[1]-first[1]
        fraction = (value-first[1])/delta if delta else (1 if value>first[1] else 0)
        fraction = max(0,min(1,fraction))
        return first[2]+fraction*(second[2]-first[2])
    runtime.globals().native_sample = sample_curve
    runtime.execute('function ug_require(path) return {sampleCurve=native_sample} end')
    for points, expected in [
        ('{{0,0},{.25,.5},{.2,powergain*1.2},{.28,powergain*1.1},{.4,0}}', .45),
        ('{{0,0},{.2,powergain*1.2},{1,powergain},{1,0},{1,0}}', 1.2+(.225-.2)/.8*(1.0-1.2)),
    ]:
        scripts = []
        text = sound('{gain=soundeffectsutil.sampleCurve('+points+',input.speed01),pitch=.6+(input.speed01-.44)*20}',
                     'local powergain=1.5-(1-input.power01)')
        port_sound_set(text, lambda r,k:r, Native(), script_writer=scripts_writer(scripts))
        runtime.execute(scripts[0])
        result = runtime.table()
        current = runtime.table(vehicle=runtime.table(speed01=.225,power01=.5))
        runtime.globals().data()['update'](result, runtime.table(), current)
        assert result['gain'] == pytest.approx(expected)
        assert result['pitch'] == pytest.approx(.6+(.225-.44)*20)


def test_native_clip_attributes_are_preserved_for_tracks_and_events():
    text = sound('{gain=1,pitch=1}', attrs=',gain=2,rolloffFact=.8,hasVelocity=true',
                 events='horn={names={"horn.wav"},refDist=50,gain=.5,rolloffFact=1,hasVelocity=false}',
                 event_controls='horn={gain=2,pitch=1}')
    result = port_sound_set(text, lambda r,k:r, Native())
    assert result['tracks'][0]['attrs'] == {'refDist':25,'gain':2,'rolloffFact':.8,'hasVelocity':True}
    assert result['events']['horn']['attrs'] == {'refDist':50,'gain':.5,'rolloffFact':1,'hasVelocity':False}


@pytest.mark.parametrize('attribute', [',gain=-1', ',rolloffFact=-.1', ',hasVelocity=1', ',unknown=1'])
def test_invalid_or_unknown_clip_attributes_remain_blockers(attribute):
    with pytest.raises(ValueError):
        port_sound_set(sound('{gain=1,pitch=1}',attrs=attribute),lambda r,k:r,Native())


@pytest.mark.parametrize('expression', [
    'input.other', 'input.speed01/input.power01', 'input.speed01/0',
    'executeMod()', 'math.sin(input.speed01)', 'input.speed01^2',
])
def test_generated_controller_never_admits_unknown_runtime_calls_or_inputs(expression):
    scripts=[]
    with pytest.raises(ValueError):
        port_sound_set(sound('{gain='+expression+',pitch=1}'),lambda r,k:r,Native(),script_writer=scripts_writer(scripts))
    assert scripts == []


def test_dynamic_event_controls_are_not_substituted_with_triggerless_custom_events():
    scripts=[]
    text=sound('{gain=1,pitch=1}',events='horn={names={"horn.wav"},refDist=50}',
               event_controls='horn={gain=1+input.power01,pitch=1}')
    with pytest.raises(ValueError,match='event-trigger adapter'):
        port_sound_set(text,lambda r,k:r,Native(),script_writer=scripts_writer(scripts))
    assert scripts == []


def test_generated_writer_must_return_verified_resource_function_reference():
    with pytest.raises(ValueError,match='qualified @update'):
        port_sound_set(sound('{gain=1+input.power01,pitch=1}'),lambda r,k:r,Native(),script_writer=lambda k,t:'guess.lua')


def test_unused_known_pure_chuffs_call_is_audited_and_all_authored_controls_remain():
    text=sound('{gain=1,pitch=1}',locals='local chuffsFastFreq=4 local refWeight=100 '
               'local chuffs=soundeffectsutil.chuffs(input.speed,input.chuffStep,chuffsFastFreq,input.gameSpeedUp,refWeight)',
               events='chuffs={names={"chuff.wav"},refDist=25}',event_controls='chuffs={gain=.5,pitch=1}')
    audit={}
    result=port_sound_set(text,lambda r,k:r,Native(),report=audit)
    assert len(result['tracks'])==1
    assert result['events']['chuffs']['names']==['chuff.wav']
    assert [r['type'] for r in result['updateScript']['params']['updateFunctions']]==['SampleCurve','SampleCurve']
    assert audit['soundMigrations'][0]['policy']=='omit_unreferenced_pure_chuffs_result'
    with pytest.raises(ValueError):
        port_sound_set(text.replace('soundeffectsutil.chuffs(', 'unknownHelper.chuffs('),lambda r,k:r,Native())


def test_used_chuffs_migrate_adjacent_tracks_and_event_with_kg_reference_weight():
    text='''local soundeffectsutil = require "soundeffectsutil"
    function data() return {
      tracks={{name="idle.wav",refDist=25},{name="fast.wav",refDist=25}},
      events={chuffs={names={"part.wav"},refDist=25}},
      updateFn=function(input)
        local frequency=4 local refWeight=100
        local chuffs=soundeffectsutil.chuffs(input.speed,input.chuffStep,frequency,input.weight,refWeight)
        return {tracks={chuffs.idleTrack,chuffs.fastTrack},events={chuffs=chuffs.event}}
      end
    } end'''
    result=port_sound_set(text,lambda r,k:r,Native())
    assert result['updateScript']['params']['updateFunctions']==[
        {'type':'Chuffs','params':{'chuffsFastFreq':4,'refWeight':100000},'eventKey':'chuffs'}]
    assert [t['name'] for t in result['tracks']]==['idle.wav','fast.wav']
    with pytest.raises(ValueError,match='adjacent'):
        port_sound_set(text.replace('tracks={chuffs.idleTrack,chuffs.fastTrack}',
                                    'tracks={chuffs.fastTrack,chuffs.idleTrack}'),lambda r,k:r,Native())
    with pytest.raises(ValueError,match='source weight input'):
        port_sound_set(text.replace('frequency,input.weight', 'frequency,input.gameSpeedUp'),lambda r,k:r,Native())


def test_steam_sound_builder_uses_native_chuffs_without_duplicating_track_updates():
    text='''local soundsetutil=require "soundsetutil"
    function data()
      local d=soundsetutil.makeSoundSet()
      soundsetutil.makeSteamTrain(d,"idle.wav","fast.wav",25,{"chuff.wav"},20,4,100)
      soundsetutil.addTrackSqueal(d,"wheel.wav",10)
      return d
    end'''
    result=port_sound_set(text,lambda r,k:r,Native())
    assert [t['name'] for t in result['tracks']]==['idle.wav','fast.wav','wheel.wav']
    assert [u['type'] for u in result['updateScript']['params']['updateFunctions']]==['Chuffs','Squeal']
    assert result['updateScript']['params']['updateFunctions'][0]['params']['refWeight']==100000


def test_source_track_definition_mismatch_reports_actual_counts():
    with pytest.raises(ValueError,match='1 tracks but 2 controls'):
        port_sound_set(sound('{gain=1,pitch=1},{gain=1,pitch=1}'),lambda r,k:r,Native())


def test_shadowed_math_and_exponentially_expanding_aliases_are_rejected():
    with pytest.raises(ValueError,match='shadow bindings'):
        port_sound_set(sound('{gain=1,pitch=1}',locals='local math=0'),lambda r,k:r,Native())
    assignments=['local x0=input.power01']
    for index in range(1,20):
        assignments.append(f'local x{index}=x{index-1}+x{index-1}')
    with pytest.raises(ValueError,match='safe export limit'):
        port_sound_set(sound('{gain=x19,pitch=1}',locals='\n'.join(assignments)),lambda r,k:r,Native(),script_writer=lambda k,t:'safe::/x.script@update')


GATED_BUILDER='''local audioutil=require "audioutil"
local soundsetutil=require "soundsetutil"
function data()
 local d=soundsetutil.makeSoundSet()
 local function addBrakeTrack(data,name,refDist,gainCurve,pitchCurve,param01)
  soundsetutil.addTrack(data,name,refDist,function(track,input)
   if input["brakeDecel"] > 1 then
    track.gain=audioutil.sampleCurve(gainCurve,input[param01])
   else
    track.gain=0
   end
   track.pitch=audioutil.sampleCurve(pitchCurve,input[param01])
  end)
 end
 addBrakeTrack(d,"brake.wav",20,{{0,0},{1,1.2}},{{0,.8},{1,1.15}},"speed01")
 return d
end'''


def test_verified_brake_gate_compiles_and_preserves_threshold_gain_pitch_at_runtime():
    scripts,audit=[],{}
    result=port_sound_set(GATED_BUILDER,lambda r,k:r,Native(),script_writer=scripts_writer(scripts),report=audit)
    update=result['updateScript']['params']['updateFunctions'][0]
    assert update['type']=='Custom'
    assert callback_status(parse_lua(scripts[0]),'update')=='resolved'
    assert 'currentInfo.vehicle.brakeDecel > 1' in scripts[0]
    assert update['params']['customParams']=={'gainCurve':[[0,0],[1,1.2]],'pitchCurve':[[0,.8],[1,1.15]]}
    assert audit['soundMigrations'][0]['policy']=='compile_verified_brake_gated_track'
    lupa=pytest.importorskip('lupa')
    runtime=lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute('function ug_require(path) return {sampleCurve=function(p,x) '
                    'return p[1][2]+math.max(0,math.min(1,x))*(p[2][2]-p[1][2]) end} end')
    runtime.execute(scripts[0])
    params=runtime.table(gainCurve=runtime.table_from([runtime.table_from(p) for p in [[0,0],[1,1.2]]]),
                         pitchCurve=runtime.table_from([runtime.table_from(p) for p in [[0,.8],[1,1.15]]]))
    for deceleration,expected in [(0,0),(1,0),(1.001,.6)]:
        output=runtime.table()
        current=runtime.table(vehicle=runtime.table(speed01=.5,brakeDecel=deceleration))
        runtime.globals().data()['update'](output,params,current)
        assert output['gain']==pytest.approx(expected)
        assert output['pitch']==pytest.approx(.975)


@pytest.mark.parametrize('old,new', [
    ('input["brakeDecel"]','input["mystery"]'),
    ('track.gain=0','track.gain=executeMod()'),
    ('track.pitch=audioutil.sampleCurve','track.other=audioutil.sampleCurve'),
    ('input[param01]','input["arbitrary"]'),
    ('return d','d.tracks={} return d'),
])
def test_unknown_local_builder_behavior_is_not_dropped(old,new):
    with pytest.raises(ValueError):
        port_sound_set(GATED_BUILDER.replace(old,new),lambda r,k:r,Native(),script_writer=lambda k,t:'safe::/s.script@update')


def test_constant_overflow_is_not_reintroduced_as_generated_runtime_expression():
    with pytest.raises(ValueError):
        port_sound_set(sound('{gain=1e308*1e308,pitch=1}'),lambda r,k:r,Native(),script_writer=lambda k,t:'safe::/s.script@update')

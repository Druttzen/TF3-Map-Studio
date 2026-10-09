import math

import pytest

from trf3_mod_converter.legacy_sound_helpers import SOUND_HELPER_PROFILES
from trf3_mod_converter.tf2_sound_port import port_sound_set
from test_tf2_sound_port import Native, SOUND


def convert(module, *, text=None, verified=True, writer=True, digest=None):
    text = SOUND.replace('require "soundeffectsutil"', 'require "'+module+'"') if text is None else text
    digest = next(iter(SOUND_HELPER_PROFILES[module])) if digest is None else digest
    scripts, report = {}, {}
    def write(key, script):
        scripts[key] = script
        return 'converted::/scripts/'+key+'.script@update'
    result = port_sound_set(text, lambda ref, kind: 'converted::/audio/'+ref, Native(),
                            report=report, resource='config/sound_set/authored.lua',
                            script_writer=write if writer else None,
                            verified_helpers={module: digest} if verified else None)
    return result, scripts, report


@pytest.mark.parametrize('module,threshold', [('bbs2util', .5), ('soundeffectsutil2', .1)])
def test_exact_helper_profiles_preserve_curves_squeal_brake_and_events(module, threshold):
    result, scripts, report = convert(module)
    updates = result['updateScript']['params']['updateFunctions']
    assert [entry['type'] for entry in updates] == ['SampleCurve', 'Squeal', 'Custom', 'Clacks', 'SampleCurve']
    assert updates[2]['params']['customParams'] == {
        'threshold': threshold, 'maxBrakeDecel': 2.5, 'fadeStart': 3., 'fadeEnd': 7., 'maxGain': .5}
    assert updates[3]['params']['axleRefWeight'] == 10000
    assert updates[4]['eventKey'] == 'horn'
    assert len(result['tracks']) == 3 and set(result['events']) == {'clacks', 'horn'}
    assert 'currentInfo.vehicle.brakeDecel' in scripts['authored_brake']
    assert 'brakeDecelSmoothed' not in scripts['authored_brake']
    assert report['soundMigrations'][0]['sha256'] == next(iter(SOUND_HELPER_PROFILES[module]))
    assert report['soundMigrations'][1]['authoredParameters']['threshold'] == threshold


@pytest.mark.parametrize('module', ['bbs2util', 'soundeffectsutil2'])
@pytest.mark.parametrize('digest', [None, '0'*64, '80b7d45c5df3adefcea88226e80e463300b848a968ad1c5b8ff99e9430fc1910'])
def test_helper_names_or_changed_code_do_not_establish_equivalence(module, digest):
    with pytest.raises(ValueError, match='Unsupported sound helper import'):
        convert(module, verified=digest is not None, digest=digest)


def test_helper_mapping_cannot_be_replaced_by_a_name_only_allowlist():
    with pytest.raises(ValueError, match='module-to-SHA256'):
        port_sound_set(SOUND, lambda r, k: r, Native(), verified_helpers={'bbs2util'})


@pytest.mark.parametrize('module', ['bbs2util', 'soundeffectsutil2'])
def test_authored_brake_requires_script_writer(module):
    with pytest.raises(ValueError, match='requires a generated TF3 script writer'):
        convert(module, writer=False)


@pytest.mark.parametrize('module', ['bbs2util', 'soundeffectsutil2'])
def test_changed_chuff_transition_is_not_mapped_to_native_chuffs(module):
    text = SOUND.replace('require "soundeffectsutil"', 'require "'+module+'"')
    text = text.replace('local axleRefWeight=10',
                        'local axleRefWeight=10\nlocal chuffs=soundeffectsutil.chuffs(input.speed,input.chuffStep,8,input.weight,20)')
    with pytest.raises(ValueError):
        convert(module, text=text)


def test_authored_brake_cannot_invent_event_triggers():
    text = SOUND.replace('require "soundeffectsutil"', 'require "bbs2util"')
    text = text.replace('horn={gain=1,pitch=1}', 'horn=soundeffectsutil.brake(input.speed,input.brakeDecel,1)')
    with pytest.raises(ValueError, match='event-trigger adapter'):
        convert('bbs2util', text=text)


@pytest.mark.parametrize('replacement', ['input.mysteryDecel', 'input.brakeDecelSmoothed'])
def test_authored_brake_only_accepts_verified_raw_input(replacement):
    text = SOUND.replace('require "soundeffectsutil"', 'require "bbs2util"').replace('input.brakeDecel', replacement)
    with pytest.raises(ValueError, match='helper inputs'):
        convert('bbs2util', text=text)


@pytest.mark.parametrize('module,decel,speed,max_gain,expected', [
    ('bbs2util', .3, 1, 1, 0),
    ('soundeffectsutil2', .3, 1, 1, math.sqrt(.12)),
    ('bbs2util', .5, 1, 1, 0),
    ('bbs2util', 2.5, 10, 1, .5),
    ('soundeffectsutil2', 2.5, 10, 1.5, .75),
    ('bbs2util', 10, 6, 1, 2),
    ('soundeffectsutil2', 2.5, 0, 1, 0),
    ('bbs2util', 2.5, 20, 1, 0),
])
def test_generated_lua_preserves_authored_brake_boundaries(module, decel, speed, max_gain, expected):
    result, scripts, _ = convert(module)
    params = result['updateScript']['params']['updateFunctions'][2]['params']['customParams']
    params['maxGain'] = max_gain
    runtime = pytest.importorskip('lupa').LuaRuntime()
    runtime.execute(scripts['authored_brake'])
    output = runtime.table_from({'gain': 0, 'pitch': 0})
    runtime.globals().data()['update'](output, runtime.table_from(params),
                                     runtime.table_from({'vehicle': {'speed': speed, 'brakeDecel': decel}}, recursive=True))
    assert output['gain'] == pytest.approx(expected)
    assert output['pitch'] == 1


def test_slow_helper_preserves_its_wider_authored_speed_fade():
    text = SOUND.replace('require "soundeffectsutil"', 'require "bbs2util"')
    text = text.replace('soundeffectsutil.brake(input.speed,input.brakeDecel,.5)',
                        'soundeffectsutil.slow(input.speed,input.brakeDecel,1,input.speed01)')
    result, scripts, _ = convert('bbs2util', text=text)
    params = result['updateScript']['params']['updateFunctions'][2]['params']['customParams']
    assert params == {'threshold': .7, 'maxBrakeDecel': 2., 'fadeStart': 10., 'fadeEnd': 40., 'maxGain': 1}
    runtime = pytest.importorskip('lupa').LuaRuntime()
    runtime.execute(scripts['authored_brake'])
    output = runtime.table()
    runtime.globals().data()['update'](output, runtime.table_from(params),
                                     runtime.table_from({'vehicle': {'speed': 50, 'brakeDecel': 2}}, recursive=True))
    assert output['gain'] == pytest.approx(.5)


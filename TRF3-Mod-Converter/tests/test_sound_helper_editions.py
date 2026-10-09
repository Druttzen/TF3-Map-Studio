"""Behavioral coverage for the separately attested authored helper editions."""
from copy import deepcopy
import hashlib
import math

import pytest

from test_dependency_sound_export import authored_sound
from test_tf2_sound_port import Native, SOUND
from test_tf2_vehicle_port import fixture_mod
from test_verified_sound_helpers import convert
from trf3_mod_converter.legacy_sound_helpers import SOUND_HELPER_PROFILES
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_sound_port import port_sound_set
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot
from trf3_mod_converter.verified_helpers import (
    HELPER_DIGEST_VARIANTS, helper_digest_verified, verified_legacy_helpers,
)


STOCK_EDITION = 'a5f00cd3e74bcd6e29f4242a43e52ee38ed15e10eac8f6eb4ba99e196a0281e0'
BBS_EDITION = '2377f9c3ceeb9c782b4ae654308be7c166570b872a6553cd49eb01e1b2d0f027'


@pytest.mark.parametrize('module,digest', [('soundeffectsutil', STOCK_EDITION), ('bbs2util', BBS_EDITION)])
def test_separately_audited_helper_digests_are_not_name_based(module, digest):
    assert helper_digest_verified(module, digest)
    assert not helper_digest_verified(module, digest[:-1] + ('1' if digest[-1] != '1' else '0'))
    assert not helper_digest_verified('unknownHelper', digest)
    assert not helper_digest_verified(module, None)


@pytest.mark.parametrize('module,digest,expected', [
    ('soundeffectsutil', STOCK_EDITION,
     {'threshold': .1, 'maxBrakeDecel': 5., 'fadeStart': 2., 'fadeEnd': 4., 'maxGain': .5}),
    ('bbs2util', BBS_EDITION,
     {'threshold': .5, 'maxBrakeDecel': 2.25, 'fadeStart': 3.75, 'fadeEnd': 6.75, 'maxGain': .5}),
])
def test_authored_editions_do_not_fall_back_to_native_brake(module, digest, expected):
    result, scripts, report = convert(module, digest=digest)
    updates = result['updateScript']['params']['updateFunctions']
    assert updates[2]['type'] == 'Custom'
    assert updates[2]['params']['customParams'] == expected
    assert scripts['authored_brake'].count('math.sqrt(brakeDecel /') == 1
    assert report['soundMigrations'][0]['sha256'] == digest
    assert ('slow' in report['soundMigrations'][0]['supportedFunctions']) == (module == 'bbs2util')


@pytest.mark.parametrize('module,digest,function,threshold,maximum,fade_start,fade_end', [
    ('soundeffectsutil', STOCK_EDITION, 'brake', .1, 5, 2, 4),
    ('bbs2util', BBS_EDITION, 'brake', .5, 2.25, 3.75, 6.75),
    ('bbs2util', BBS_EDITION, 'slow', .7, 2.5, 10, 40),
])
def test_generated_brake_formula_preserves_threshold_fades_and_unclamped_gain(
        module, digest, function, threshold, maximum, fade_start, fade_end):
    text = SOUND.replace('require "soundeffectsutil"', 'require "' + module + '"')
    if function == 'slow':
        text = text.replace('soundeffectsutil.brake(input.speed,input.brakeDecel,.5)',
                            'soundeffectsutil.slow(input.speed,input.brakeDecel,.5,input.speed01)')
    result, scripts, _ = convert(module, text=text, digest=digest)
    params = result['updateScript']['params']['updateFunctions'][2]['params']['customParams']
    assert params['threshold'] == threshold and params['maxBrakeDecel'] == maximum
    runtime = pytest.importorskip('lupa').LuaRuntime()
    runtime.execute(scripts['authored_brake'])  # Only trusted converter output is executed.
    for deceleration in (0, threshold, threshold + .001, maximum, maximum * 4):
        brake_gain = math.sqrt(deceleration / maximum)
        for speed in (0, .5, 1, fade_start * (brake_gain + 1),
                      (fade_start + fade_end) / 2 * (brake_gain + 1),
                      fade_end * (brake_gain + 1), 100):
            expected = 0
            if deceleration > threshold:
                start, end = fade_start * (brake_gain + 1), fade_end * (brake_gain + 1)
                expected = (1 - min(1, max(0, (speed - start) / (end - start))))
                expected *= min(1, max(0, speed)) * brake_gain * .5
            output = runtime.table()
            current = runtime.table_from({'vehicle': {'speed': speed, 'brakeDecel': deceleration},
                                          'railVehicle': {'brakeDecelSmoothed': 100}}, recursive=True)
            runtime.globals().data()['update'](output, runtime.table_from(params), current)
            assert output['gain'] == pytest.approx(expected)
            assert output['pitch'] == 1


@pytest.mark.parametrize('module,digest', [('soundeffectsutil', STOCK_EDITION), ('bbs2util', BBS_EDITION)])
def test_authored_literal_squeal_preserves_force_threshold_and_speed_fade(module, digest):
    text = SOUND.replace('require "soundeffectsutil"', 'require "' + module + '"')
    text = text.replace('input.sideForce,input.maxSideForce', 'input.sideForce,.7')
    result, scripts, report = convert(module, text=text, digest=digest)
    update = result['updateScript']['params']['updateFunctions'][1]
    assert update['type'] == 'Custom'
    assert update['params']['customParams'] == {'maxSideForce': .7}
    assert 'vehicle.maxSideForce' not in scripts['authored_squeal']
    assert 'currentInfo.vehicle.sideForce' not in scripts['authored_squeal']
    assert 'railVehicle.sideForce' in scripts['authored_squeal']
    row = next(r for r in report['soundMigrations'] if r['policy'] == 'compile_verified_authored_squeal')
    assert row['sha256'] == digest and row['authoredParameters'] == {'maxSideForce': .7}
    assert row['targetInput'] == 'railVehicle.sideForce'
    runtime = pytest.importorskip('lupa').LuaRuntime()
    runtime.execute(scripts['authored_squeal'])
    for speed in (0, 20, 30, 40, 80):
        for side_force in (-.5, 0, .2, .45, .7, 1):
            # Installed Transformator.VehicleScriptingInfo has speed/raw
            # brakeDecel; force belongs to RailVehicleScriptingInfo instead.
            current = runtime.table_from({'vehicle': {'speed': speed},
                                          'railVehicle': {'sideForce': side_force,
                                                          'maxSideForce': 100}}, recursive=True)
            output = runtime.table()
            runtime.globals().data()['update'](output, runtime.table_from({'maxSideForce': .7}), current)
            expected = max(0, min(1, 1 - 2 * max(.7 - side_force, 0)))
            expected *= 1 - max(0, min(1, (speed - 20) / 20))
            assert output['gain'] == pytest.approx(expected)
            assert output['pitch'] == 1


@pytest.mark.parametrize('module,digest', [('soundeffectsutil', STOCK_EDITION), ('bbs2util', BBS_EDITION)])
@pytest.mark.parametrize('rail_info', [None, {}, {'maxSideForce': 100}])
def test_authored_squeal_missing_native_rail_force_uses_native_zero_force_guard(module, digest, rail_info):
    text = SOUND.replace('require "soundeffectsutil"', 'require "' + module + '"')
    text = text.replace('input.sideForce,input.maxSideForce', 'input.sideForce,.2')
    _, scripts, _ = convert(module, text=text, digest=digest)
    runtime = pytest.importorskip('lupa').LuaRuntime()
    runtime.execute(scripts['authored_squeal'])
    # A misleading vehicle-side value must never override the native rail
    # namespace, even when the optional rail info or its force is absent.
    values = {'vehicle': {'speed': 30, 'sideForce': 100}}
    if rail_info is not None:
        values['railVehicle'] = rail_info
    output = runtime.table()
    runtime.globals().data()['update'](output, runtime.table_from({'maxSideForce': .2}),
                                     runtime.table_from(values, recursive=True))
    assert output['gain'] == pytest.approx(.3)
    assert output['pitch'] == 1


@pytest.mark.parametrize('module,digest', [('soundeffectsutil', STOCK_EDITION), ('bbs2util', BBS_EDITION)])
def test_authored_squeal_native_rail_force_overrides_misleading_vehicle_value(module, digest):
    text = SOUND.replace('require "soundeffectsutil"', 'require "' + module + '"')
    text = text.replace('input.sideForce,input.maxSideForce', 'input.sideForce,.7')
    _, scripts, _ = convert(module, text=text, digest=digest)
    runtime = pytest.importorskip('lupa').LuaRuntime()
    runtime.execute(scripts['authored_squeal'])
    current = runtime.table_from({'vehicle': {'speed': 30, 'sideForce': 100},
                                  'railVehicle': {'sideForce': .45, 'maxSideForce': 100}}, recursive=True)
    output = runtime.table()
    runtime.globals().data()['update'](output, runtime.table_from({'maxSideForce': .7}), current)
    assert output['gain'] == pytest.approx(.25)
    assert output['pitch'] == 1


@pytest.mark.parametrize('digest', ['0' * 64, STOCK_EDITION[:-1] + '1'])
def test_unrecognized_named_stock_helper_attestation_cannot_select_native_formulas(digest):
    with pytest.raises(ValueError, match='Unsupported sound helper import'):
        convert('soundeffectsutil', digest=digest)


def test_authored_stock_edition_does_not_admit_missing_or_changed_chuff_methods():
    for call in ('soundeffectsutil.slow(input.speed,input.brakeDecel,1,input.speed01)',
                 'soundeffectsutil.chuffs(input.speed,input.chuffStep,4,input.weight,20)',
                 'soundeffectsutil.get("train")'):
        text = SOUND.replace('soundeffectsutil.brake(input.speed,input.brakeDecel,.5)', call)
        with pytest.raises(ValueError):
            convert('soundeffectsutil', text=text, digest=STOCK_EDITION)


@pytest.mark.parametrize('expression', ['input.arbitrary', 'input.maxSideForce + 1', 'executeMod()', 'true', '1e309'])
def test_authored_squeal_unknown_dynamic_force_limits_are_not_invented(expression):
    text = SOUND.replace('input.sideForce,input.maxSideForce', 'input.sideForce,' + expression)
    with pytest.raises(ValueError):
        convert('soundeffectsutil', text=text, digest=STOCK_EDITION)


def test_authored_squeal_requires_generated_writer_and_cannot_invent_event_triggers():
    text = SOUND.replace('input.sideForce,input.maxSideForce', 'input.sideForce,.7')
    with pytest.raises(ValueError, match='requires a generated TF3 script writer'):
        convert('soundeffectsutil', text=text, digest=STOCK_EDITION, writer=False)
    text = text.replace('horn={gain=1,pitch=1}', 'horn=soundeffectsutil.squeal(input.speed,input.sideForce,.7)')
    with pytest.raises(ValueError, match='event-trigger adapter'):
        convert('soundeffectsutil', text=text, digest=STOCK_EDITION)


def test_separately_attested_helper_keeps_repeated_sample_curve_points_in_authored_order():
    text = SOUND.replace('audioutil.plotSqrt(0,.05,.3,.3,3)', '{{0,0},{.2,1},{.2,.5},{.1,.75},{1,0}}')
    result, scripts, report = convert('soundeffectsutil', text=text, digest=STOCK_EDITION)
    assert result['updateScript']['params']['updateFunctions'][0]['type'] == 'Custom'
    assert '{0,0},{0.2,1},{0.2,0.5},{0.1,0.75},{1,0}' in scripts['sound_curve']
    assert next(r for r in report['soundMigrations'] if r['policy'] == 'compile_bounded_sound_expressions')['curveOrder'] == 'preserved'


def test_controls_without_authored_event_clips_remain_a_blocker():
    text = '''local sound=require "soundeffectsutil"
    function data() return {
      tracks={{name="drive.wav",refDist=5}},
      updateFn=function(input) return {
        tracks={sound.brake(input.speed,input.brakeDecel,2.5)},
        events={clacks={gain=sound.sampleCurve({{0,0},{1,1}},input.speed01),pitch=1}}
      } end
    } end'''
    with pytest.raises(ValueError, match='Unsupported or duplicate sound field: clacks'):
        convert('soundeffectsutil', text=text, digest=STOCK_EDITION)


def _add_root_helper(fixture_mod, monkeypatch, module, profile_digest):
    source, game, output = fixture_mod
    helper = source / ('res/scripts/' + module + '.lua')
    helper.parent.mkdir()
    helper.write_bytes(b'return { fixtureIdentity = "new exact audited edition" }\n')
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    monkeypatch.setitem(HELPER_DIGEST_VARIANTS, module, frozenset({digest}))
    profile = deepcopy(SOUND_HELPER_PROFILES[module][profile_digest])
    monkeypatch.setitem(SOUND_HELPER_PROFILES, module, {digest: profile})
    model_path = source / 'res/models/model/vehicle/train/test.mdl'
    data = load_lua_table(model_path.read_text())
    data['metadata']['railVehicle']['soundSet'] = {'name': 'authored', 'horn': ''}
    model_path.write_text(emit(data))
    sound = source / 'res/config/sound_set/authored.lua'
    sound.parent.mkdir(parents=True)
    sound.write_text('local sound=require "' + module + '"\nfunction data() return { '
                     'tracks={{name="horn.wav",refDist=25}}, events={}, '
                     'updateFn=function(input) return {tracks={sound.brake(input.speed,input.brakeDecel,1)},events={}} end } end')
    script = game / 'base/content/scripts/soundset_default.script.tl'
    script.parent.mkdir()
    script.write_text('-- synthetic native inventory placeholder')
    return source, game, output, helper, digest


@pytest.mark.parametrize('module,digest,maximum', [('soundeffectsutil', STOCK_EDITION, 5), ('bbs2util', BBS_EDITION, 2.25)])
def test_root_export_uses_actual_edition_digest_and_archives_helper(fixture_mod, monkeypatch, module, digest, maximum):
    source, game, output, helper, actual_digest = _add_root_helper(fixture_mod, monkeypatch, module, digest)
    before = snapshot(source)
    assert verified_legacy_helpers(source) == {module: helper}
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_edition', name='Authored edition')
    sound = load_lua_table((output / 'content/config/sound_set/authored.snd.lua').read_text())
    update = sound['updateScript']['params']['updateFunctions'][0]
    assert update['type'] == 'Custom' and update['params']['customParams']['maxBrakeDecel'] == maximum
    row = report['migrationAudit']['helperMigrations'][0]
    assert row['sha256'] == actual_digest
    assert (output / row['originalFile']).read_bytes() == helper.read_bytes()
    assert not (output / ('content/scripts/' + module + '.lua')).exists()
    assert snapshot(source) == before


def test_unrecognized_root_stock_helper_remains_a_blocker(fixture_mod, monkeypatch):
    source, game, output, helper, _ = _add_root_helper(fixture_mod, monkeypatch, 'soundeffectsutil', STOCK_EDITION)
    helper.write_bytes(helper.read_bytes() + b'-- behavior edited\n')
    with pytest.raises(ValueError, match='shadows the built-in helper'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_edition', name='Authored edition')
    assert not output.exists()


def test_dependency_stock_named_edition_uses_owner_digest_and_archive(authored_sound, monkeypatch):
    source, provider, game, output, old_helper, digest = authored_sound
    helper = old_helper.with_name('soundeffectsutil.lua')
    old_helper.rename(helper)
    sound = provider / 'res/config/sound_set/external_author.lua'
    sound.write_text(sound.read_text().replace('require "bbs2util"', 'require "soundeffectsutil"'))
    monkeypatch.setitem(HELPER_DIGEST_VARIANTS, 'soundeffectsutil', frozenset({digest}))
    monkeypatch.setitem(SOUND_HELPER_PROFILES, 'soundeffectsutil', {digest: deepcopy(SOUND_HELPER_PROFILES['soundeffectsutil'][STOCK_EDITION])})
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_edition', name='Owner edition')
    result = load_lua_table((output / 'content/config/sound_set/external_author.snd.lua').read_text())
    assert result['updateScript']['params']['updateFunctions'][0]['params']['customParams']['maxBrakeDecel'] == 5
    row = next(r for r in report['migrationAudit']['workshopDependencies'] if r['kind'] == 'helper')
    assert row['sha256'] == digest and row['providers'] == [str(helper)]
    assert (output / row['originalFile']).read_bytes() == helper.read_bytes()
    assert not (output / 'content/scripts/soundeffectsutil.lua').exists()

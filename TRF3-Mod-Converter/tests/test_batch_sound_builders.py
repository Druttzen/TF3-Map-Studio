import pytest

from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.resource_profiles import port_config
from trf3_mod_converter.tf2_sound_port import port_sound_set


class Native:
    def reference(self, path):
        return '::/' + path


BUILDER = '''local sounds = require "soundsetutil"
local clacks = {"part1.wav", "part2.wav"}
function data()
 local result = sounds.makeSoundSet()
 sounds.addTrackParam01(result, "idle.wav", 25,
   {{0, 1}, {1, 0}}, {{0, .8}, {1, 1.2}}, "power01")
 sounds.addTrackSqueal(result, "squeal.wav", 25)
 sounds.addTrackBrake(result, "brake.wav", 25, .5)
 sounds.addEventClacks(result, clacks, 15, 21)
 sounds.addEvent(result, "horn", {"horn.wav"}, 50)
 return result
end'''


def test_builder_keeps_authored_audio_curves_order_and_clack_units():
    calls = []
    def resolve(reference, kind):
        calls.append((reference, kind))
        return 'converted::/' + reference
    result = port_sound_set(BUILDER, resolve, Native())
    assert calls == [(n, 'audio') for n in ('idle.wav', 'squeal.wav', 'brake.wav', 'part1.wav', 'part2.wav', 'horn.wav')]
    assert result['tracks'][0] == {'name': 'converted::/idle.wav', 'attrs': {'refDist': 25}}
    updates = result['updateScript']['params']['updateFunctions']
    assert [u['type'] for u in updates] == ['SampleCurve', 'Squeal', 'Brake', 'Clacks', 'None']
    assert updates[0]['params']['gainCurve'] == [[0, 1], [1, 0]]
    assert updates[0]['params']['pitchCurve'] == [[0, .8], [1, 1.2]]
    assert updates[0]['params']['gainScriptingInfoKey'] == 'vehicle'
    assert updates[0]['params']['gainParamName'] == 'power01'
    assert updates[3] == {'type': 'Clacks', 'params': {'axleRefWeight': 21000}, 'eventKey': 'clacks'}
    assert updates[4]['eventKey'] == 'horn'


def test_road_builder_migrates_two_tracks_and_default_events():
    text = '''local soundsetutil = require "soundsetutil"
    function data()
      local d = soundsetutil.makeSoundSet()
      soundsetutil.makeRoadVehicle2(d, {.05, .1, .3}, "idle.wav", .075, .6, "drive.wav", .4, 18, "speed01")
      soundsetutil.addEvent(d, "openDoors", {"open.wav"}, 5)
      return d
    end'''
    result = port_sound_set(text, lambda r, k: r, Native())
    assert [track['name'] for track in result['tracks']] == ['idle.wav', 'drive.wav']
    idle, drive, doors = result['updateScript']['params']['updateFunctions']
    assert idle['params']['gainCurve'] == [[0, .6], [.05, 1], [.1, 1], [.3, 0]]
    assert drive['params']['gainCurve'] == [[.1, 0], [.3, 1]]
    assert len(idle['params']['pitchCurve']) == 4
    assert idle['params']['pitchCurve'][0] == pytest.approx([.048, .8])
    assert idle['params']['pitchCurve'][-1] == pytest.approx([.1171875, 1.25])
    assert doors == {'type': 'None', 'params': {}, 'eventKey': 'openDoors'}


@pytest.mark.parametrize('old,new', [
    ('return result', 'result.tracks={} return result'),
    ('local result = sounds.makeSoundSet()', 'local sounds = sounds.makeSoundSet()'),
    ('"power01"', '"unknown01"'),
    ('sounds.addTrackSqueal(result, "squeal.wav", 25)', 'sounds.addTrack(result, "squeal.wav", 25, function(track,input) track.gain=0 end)'),
    ('return result', 'if true then return result end'),
    ('sounds.addEvent(result, "horn", {"horn.wav"}, 50)', 'sounds.addEvent(result, "horn", {"horn.wav"}, 50, function() end)'),
    ('local clacks = {"part1.wav", "part2.wav"}', 'local clacks = getClacks()'),
    ('sounds.addTrackSqueal(result, "squeal.wav", 25)', 'sounds.addEvent(result, "horn", {"other.wav"}, 5)'),
    ('{1, 0}', '{0, 0}'),
    ('"idle.wav"', '_("idle.wav")'),
])
def test_builder_unknown_behavior_remains_a_blocker(old, new):
    with pytest.raises(ValueError):
        port_sound_set(BUILDER.replace(old, new), lambda r, k: r, Native())


def test_multiple_unit_group_references_are_resolved_by_type():
    calls = []
    def resolve(reference, kind):
        calls.append((reference, kind))
        return 'converted::/' + reference
    unit = {'vehicles': [{'name': 'front.mdl', 'forward': True}], 'name': 'Unit', 'groupFileName': 'parent.lua'}
    result = port_config('config/multiple_unit/variant.lua', unit, resolve)
    assert result['groupFileName'] == 'converted::/parent.lua'
    assert calls == [('front.mdl', 'model'), ('parent.lua', 'multiple_unit')]
    unit['groupFileName'] = 'front.mdl'
    assert port_config('config/multiple_unit/variant.lua', unit, resolve)['groupFileName'] == 'converted::/front.mdl'
    assert calls[-1] == ('front.mdl', 'model')
    unit['groupFileName'] = ''
    assert port_config('config/multiple_unit/variant.lua', unit, resolve)['groupFileName'] == ''


@pytest.mark.parametrize('parent', [42, TranslatedString('parent.lua'), 'parent.zip'])
def test_multiple_unit_group_does_not_guess_unknown_resources(parent):
    with pytest.raises(ValueError, match='groupFileName'):
        port_config('config/multiple_unit/variant.lua', {'vehicles': [{'name': 'front.mdl', 'forward': True}], 'groupFileName': parent}, lambda r, k: r)

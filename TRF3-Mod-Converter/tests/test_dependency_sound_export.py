"""Integration coverage for owner-scoped, digest-attested sound helper imports."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from test_tf2_vehicle_port import fixture_mod
from trf3_mod_converter.legacy_sound_helpers import SOUND_HELPER_PROFILES
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot
from trf3_mod_converter.verified_helpers import HELPER_DIGESTS
from trf3_mod_converter.workshop_resources import verify_workshop_dependencies


SOUND = '''local sound = require "bbs2util"
function data() return {
 tracks={{name="brake.wav",refDist=25}}, events={},
 updateFn=function(input) return {
  tracks={sound.brake(input.speed,input.brakeDecel,.5)}, events={}
 } end
} end'''


@pytest.fixture
def authored_sound(fixture_mod, tmp_path, monkeypatch):
    original, game, output = fixture_mod
    source = tmp_path/'1066780/123'
    source.parent.mkdir()
    original.rename(source)
    provider = source.parent/'456'
    provider.mkdir()
    (provider/'mod.lua').write_text(emit({'info':{'name':'Sound author','modid':'sound_author','steamId':456}}))
    own_model = source/'res/models/model/vehicle/train/test.mdl'
    data = load_lua_table(own_model.read_text())
    data['metadata']['railVehicle']['soundSet'] = {'name':'external_author','horn':''}
    own_model.write_text(emit(data))
    sound = provider/'res/config/sound_set/external_author.lua'
    sound.parent.mkdir(parents=True)
    sound.write_text(SOUND)
    clip = provider/'res/audio/effects/brake.wav'
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b'authored brake clip')
    helper = provider/'res/scripts/bbs2util.lua'
    helper.parent.mkdir(parents=True)
    # A synthetic golden identity tests resolver attestation independently from
    # the production helper audit. This text is never executed or emitted.
    helper.write_bytes(b'return { fixtureIdentity = "owner sound helper" }\n')
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    profile = deepcopy(next(iter(SOUND_HELPER_PROFILES['bbs2util'].values())))
    monkeypatch.setitem(HELPER_DIGESTS, 'bbs2util', digest)
    monkeypatch.setitem(SOUND_HELPER_PROFILES, 'bbs2util', {digest:profile})
    script = game/'base/content/scripts/soundset_default.script.tl'
    script.parent.mkdir()
    script.write_text('-- synthetic native inventory placeholder')
    return source, provider, game, output, helper, digest


def test_external_sound_helper_uses_exact_owner_bytes_and_records_identity(authored_sound):
    source, provider, game, output, helper, digest = authored_sound
    before = {str(path):snapshot(path) for path in (source, provider)}
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_owner_sound', name='Owner sound')
    converted = load_lua_table((output/'content/config/sound_set/external_author.snd.lua').read_text())
    update = converted['updateScript']['params']['updateFunctions'][0]
    assert update['type'] == 'Custom' and update['params']['customParams']['threshold'] == .5
    assert converted['tracks'][0]['name'] == 'fixture_owner_sound::/audio/effects/brake.wav'
    rows = report['migrationAudit']['workshopDependencies']
    helper_row = next(row for row in rows if row['kind'] == 'helper')
    assert helper_row['providers'] == [str(helper)]
    assert helper_row['sha256'] == digest and helper_row['lookupSource'] == str(provider)
    assert str(provider/'mod.lua') in helper_row['originFingerprints']
    assert 'targetReference' not in helper_row
    assert (output/helper_row['originalFile']).read_bytes() == helper.read_bytes()
    assert not (output/'content/scripts/bbs2util.lua').exists()
    assert {str(path):snapshot(path) for path in (source, provider)} == before
    assert verify_workshop_dependencies(source, rows, report['workshopResourceFingerprints'])
    helper.write_bytes(helper.read_bytes() + b'-- edited helper')
    assert not verify_workshop_dependencies(source, rows, report['workshopResourceFingerprints'])


def test_verified_root_helper_cannot_mask_a_different_external_author_helper(authored_sound):
    source, provider, game, output, helper, _ = authored_sound
    root_helper = source/'res/scripts/bbs2util.lua'
    root_helper.parent.mkdir(parents=True)
    root_helper.write_bytes(helper.read_bytes())  # Verified in the root scope.
    helper.write_bytes(b'return { fixtureIdentity = "different author behavior" }\n')
    before = {str(path):snapshot(path) for path in (source, provider)}
    with pytest.raises(ValueError, match='Dependency helper has no identical verified profile'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_owner_sound', name='Owner sound')
    assert not output.exists()
    assert {str(path):snapshot(path) for path in (source, provider)} == before

"""Regression coverage for TF2's filename-only sound-set representation."""
from copy import deepcopy

import pytest

from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot
from trf3_mod_converter.vehicle_profiles import normalize_sound_set
from test_tf2_vehicle_port import fixture_mod, model
from test_vehicle_profiles import adapt, plane, rail, road, ship


@pytest.mark.parametrize('factory,owner', [
    (rail, 'railVehicle'), (road, 'roadVehicle'),
    (ship, 'soundConfig'), (plane, 'soundConfig'),
])
def test_filename_sound_set_matches_named_table_and_preserves_source(factory, owner):
    source = factory()
    source[owner]['soundSet'] = 'legacy_sound'
    before = deepcopy(source)
    expected = deepcopy(source)
    expected[owner]['soundSet'] = {'name': 'legacy_sound'}
    actual = adapt(source)[0]
    assert actual == adapt(expected)[0]
    assert actual['soundConfig']['soundSet']['name'].endswith('/legacy_sound')
    assert source == before


def test_empty_filename_means_no_sound_set():
    source = rail()
    source['railVehicle']['soundSet'] = ''
    assert 'soundConfig' not in adapt(source)[0]


def test_full_export_accepts_filename_sound_set(fixture_mod):
    source, game, output = fixture_mod
    data = model()
    data['metadata']['railVehicle']['soundSet'] = 'train_electric_old'
    path = source/'res/models/model/vehicle/train/test.mdl'
    path.write_text(emit(data), encoding='utf-8')
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    assert report['sourceUnchanged'] and snapshot(source) == before
    target = load_lua_table((output/'content/models/model/vehicle/train/test.mdl').read_text())
    assert target['metadata']['soundConfig']['soundSet']['name'] == '::/vehicle/train/shared/sound/train_electric_old.snd'
    assert (output/'_port_originals/res/models/model/vehicle/train/test.mdl').read_bytes() == path.read_bytes()


@pytest.mark.parametrize('value', [42, True, ['legacy_sound'], {'name': 42}, {'horn': ['horn.wav']}, {'custom': 'sound'}])
def test_malformed_sound_sets_are_actionable_blockers(value):
    with pytest.raises(ValueError, match='soundSet'):
        normalize_sound_set(value)


def test_invalid_sound_set_does_not_replace_existing_export(fixture_mod):
    source, game, output = fixture_mod
    data = model()
    data['metadata']['railVehicle']['soundSet'] = {'name': 42}
    (source/'res/models/model/vehicle/train/test.mdl').write_text(emit(data), encoding='utf-8')
    output.mkdir()
    (output/'sentinel.txt').write_text('existing output')
    before = snapshot(source)
    with pytest.raises(ValueError, match='soundSet/name'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture', overwrite=True)
    assert snapshot(source) == before
    assert (output/'sentinel.txt').read_text() == 'existing output'

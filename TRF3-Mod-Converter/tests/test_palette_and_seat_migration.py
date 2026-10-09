from copy import deepcopy
import hashlib
import math
import zipfile

import pytest

from test_vehicle_profiles import Native, lods, rail, resolve
from test_tf2_vehicle_port import fixture_mod, model
from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.model_common import port_common_metadata
from trf3_mod_converter.vehicle_profiles import adapt_vehicle_metadata, derive_lod_nodes


class EvidenceNative(Native):
    def __init__(self):
        self.reads = []

    def read(self, path):
        self.reads.append(path)
        return b'installed schema proof'


@pytest.mark.parametrize('colors', [
    {'configs': [[[0.0, 0.4, 1.0]], [[0.7, 0.2, 0.1]]]},
    {'configs': [[[0, 0.4, 1]] * 4, [[1, 0.2, 0.1]] * 4]},
])
def test_active_palette_preserves_every_color_and_order_and_tracks_native_evidence(colors):
    source = {'colorConfig': colors}
    before = deepcopy(source)
    native, audit = EvidenceNative(), {}
    result = port_common_metadata(source, [], resolve, report=audit, model_path='car.mdl', native=native)
    assert source == before and result['colorConfig'] == colors
    assert result['colorConfig'] is not source['colorConfig']
    proof = ('vehicle/car/2cv/2cv.mdl' if len(colors['configs'][0]) == 1
             else 'characters/era_a_man_01/era_a_man_01.mdl')
    assert native.reads == [proof]
    migration = audit['colorMigrations'][0]
    assert migration['sourceValue'] == colors and migration['nativeSchemaResource'] == proof
    assert migration['nativeTest'] == 'not_run'


@pytest.mark.parametrize('colors', [
    {'configs': [[[True, 0, 0]]]},
    {'configs': [[[math.nan, 0, 0]]]},
    {'configs': [[[math.inf, 0, 0]]]},
    {'configs': [[[1.1, 0, 0]]]},
    {'configs': [[[-0.1, 0, 0]]]},
    {'configs': [[[1, 0]]]},
    {'configs': [[[]]]},
    {'configs': [[]]},
    {'configs': [[[0, 0, 0]] * 5]},
    {'configs': [[[0, 0, 0]], [[0, 0, 0]] * 4]},
    {'configs': {'named': [[0, 0, 0]]}},
    {'configs': [[[0, 0, 0]]], 'customRule': True},
])
def test_invalid_or_custom_palette_remains_blocked_and_source_unchanged(colors):
    source = {'colorConfig': colors}
    before = deepcopy(source)
    with pytest.raises(ValueError, match='colorConfig'):
        port_common_metadata(source, [], resolve)
    # NaN does not compare equal across copies, so use an exact representation.
    assert repr(source) == repr(before)


def test_empty_palette_is_preserved_without_native_dependency():
    native = EvidenceNative()
    assert port_common_metadata({'colorConfig': {'configs': []}}, [], resolve, native=native) == {
        'colorConfig': {'configs': []}}
    assert not native.reads


def adapt_seats(seats, native, audit):
    source = rail()
    source['seatProvider'] = {'seats': seats}
    before = deepcopy(source)
    nodes, transforms = derive_lod_nodes(lods())
    result, _ = adapt_vehicle_metadata(source, nodes, resolve, native, model_path='flirt.mdl',
                                      weight_max_payload=800, node_world_transforms=transforms, report=audit)
    assert source == before
    return result['seatProvider']['seats']


def test_matching_legacy_flags_preserve_explicit_poses_transforms_and_seat_order():
    transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 4, 2, 1, 1]
    seats = [{'standing': False, 'animation': 'sitting', 'group': 1, 'crew': True,
              'forward': False, 'transf': transform},
             {'standing': True, 'animation': 'idle', 'group': 1, 'crew': False,
              'forward': True, 'transf': transform}]
    native, audit = EvidenceNative(), {}
    result = adapt_seats(seats, native, audit)
    assert result == [dict((k, v) for k, v in seat.items() if k != 'standing') | {'group': 'body'}
                      for seat in seats]
    assert native.reads == ['vehicle/train/hst_125/hst_125_middle2.mdl']
    assert [row['sourceValue'] for row in audit['seatMigrations']] == [False, True]
    assert [row['animation'] for row in audit['seatMigrations']] == ['sitting', 'idle']
    assert [row['seatIndex'] for row in audit['seatMigrations']] == [0, 1]


@pytest.mark.parametrize('standing,animation', [
    (False, 'idle'), (True, 'sitting'), (False, 'driving'), (True, 'walk'),
    (0, 'sitting'), (1, 'idle'), ('false', 'sitting'), (None, 'sitting'),
    (True, None), (False, None), (True, TranslatedString('idle')),
])
def test_ambiguous_or_invalid_standing_is_not_discarded(standing, animation):
    source = rail()
    source['seatProvider'] = {'seats': [{'standing': standing, 'animation': animation, 'group': 1}]}
    before = deepcopy(source)
    nodes, transforms = derive_lod_nodes(lods())
    with pytest.raises(ValueError, match='seat/standing'):
        adapt_vehicle_metadata(source, nodes, resolve, EvidenceNative(), weight_max_payload=800,
                               node_world_transforms=transforms)
    assert source == before


def test_full_export_keeps_palette_pose_originals_and_native_proof_fingerprints(fixture_mod):
    from trf3_mod_converter.lua_metadata import load_lua_table
    from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot

    source, game, output = fixture_mod
    data = model()
    palette = {'configs': [[[0.2, 0.4, 0.6]], [[0.9, 0.7, 0.5]]]}
    data['metadata']['colorConfig'] = deepcopy(palette)
    transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 3, 1, 1]
    data['metadata']['seatProvider']['seats'] = [
        {'standing': False, 'animation': 'sitting', 'group': 1, 'crew': True, 'transf': transform},
        {'standing': True, 'animation': 'idle', 'group': 1, 'crew': False, 'transf': transform}]
    relative = 'models/model/vehicle/train/test.mdl'
    original = emit(data).encode()
    (source/'res'/relative).write_bytes(original)
    proofs = {'vehicle/car/2cv/2cv.mdl': b'color schema evidence',
              'vehicle/train/hst_125/hst_125_middle2.mdl': b'seat schema evidence'}
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        for path, contents in proofs.items():
            archive.writestr(path, contents)
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture', name='Fixture')
    assert snapshot(source) == before
    converted = load_lua_table((output/'content'/relative).read_text())['metadata']
    assert converted['colorConfig'] == palette
    assert [s['animation'] for s in converted['seatProvider']['seats']] == ['sitting', 'idle']
    assert all(s['transf'] == transform and 'standing' not in s for s in converted['seatProvider']['seats'])
    assert (output/'_port_originals/res'/relative).read_bytes() == original
    assert report['migrationAudit']['colorMigrations'][0]['sourceValue'] == palette
    assert [r['sourceValue'] for r in report['migrationAudit']['seatMigrations']] == [False, True]
    for path, contents in proofs.items():
        assert report['nativeResourceFingerprints'][path] == hashlib.sha256(contents).hexdigest()
    assert report['nativeTest'] == 'not_run'

import json
import math
import struct

import pytest

from trf3_mod_converter.cli import main
from trf3_mod_converter.conversion_plan import analyze_mod
from trf3_mod_converter.mesh_audit import audit_mesh
from trf3_mod_converter.tf2_vehicle_port import emit
from trf3_mod_converter.converter import prepare_mod, convert_mod


def write_model(root, name, metadata):
    path = root / 'res' / (name + '.mdl')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(emit({'version': 1, 'metadata': metadata}), encoding='utf-8')
    return path


@pytest.mark.parametrize('metadata,category', [
    ({'roadVehicle': {'engines': [{'type': 'DIESEL'}]}}, 'road_vehicle'),
    ({'roadVehicle': {'engines': [{'type': 'HORSE'}]}}, 'road_vehicle'),
    ({'railVehicle': {'engines': [{'type': 'STEAM'}]}}, 'rail_vehicle'),
    ({'railVehicle': {'engines': [{'type': 'ELECTRIC'}]}}, 'rail_vehicle'),
    ({'railVehicle': {'engines': []}}, 'rail_vehicle'),
    ({'railVehicle': {}, 'transportVehicle': {'carrier': 'TRAM'}}, 'tram'),
    ({'waterVehicle': {}}, 'water_vehicle'),
    ({'airVehicle': {}}, 'air_vehicle'),
    ({'person': {}}, 'model_metadata'),
    ({'signal': {}}, 'model_metadata'),
    ({}, 'static_model'),
])
def test_classification_uses_metadata_not_model_name(tmp_path, metadata, category):
    write_model(tmp_path, 'arbitrary_name', metadata)
    result = analyze_mod(tmp_path)
    row = result['resources'][0]
    assert row['category'] == category
    assert row['exportSupport'] == 'not_claimed_by_analysis'
    assert result['nativeTest'] == 'not_run'
    assert result['categories'] == {category: 1}


def test_unpowered_and_engine_types_retained(tmp_path):
    write_model(tmp_path, 'wagon', {'railVehicle': {'engines': []}})
    row = analyze_mod(tmp_path)['resources'][0]
    assert row['evidence']['unpowered'] is True
    assert row['evidence']['engineTypes'] == []


def test_mixed_mod_keeps_every_category_and_unknowns(tmp_path):
    write_model(tmp_path, 'bus', {'roadVehicle': {}})
    files = {
        'config/cargo_types/custom.lua': 'cargo',
        'config/multiple_unit/unit.lua': 'multiple_unit',
        'config/track/track.lua': 'infrastructure',
        'config/terrain_generator/test.lua': 'environment',
        'config/sound_set/test.lua': 'sound',
        'station.module.lua': 'module',
        'legacy_station.module': 'module',
        'station.con.lua': 'construction',
        'paint.mtl': 'rendering',
        'helper.lua': 'script',
        'future.xyz': 'unknown',
    }
    for name in files:
        path = tmp_path / 'res' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('function data() return {} end')
    (tmp_path / 'strings.lua').write_text('function data() return {} end')
    result = analyze_mod(tmp_path)
    assert result['mixedMod']
    assert result['status'] == 'needs_review'
    assert result['categories']['module'] == 2
    assert all(result['categories'][key] == 1 for key in set(files.values())-{'module'})
    assert result['categories']['localization'] == 1
    assert len(result['resources']) == len(files) + 2


def test_computed_model_and_scripts_are_not_executed(tmp_path, capsys):
    path = write_model(tmp_path, 'computed', {})
    path.write_text('os.execute("unsafe")\nfunction data() return calculate() end')
    result = analyze_mod(tmp_path)
    assert result['categories'] == {'unknown': 1}
    assert 'reason' in result['resources'][0]['evidence']
    assert not (tmp_path / 'unsafe').exists()
    assert main(['analyze', str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)['nativeTest'] == 'not_run'


def test_computed_metadata_is_not_misclassified_as_static_model(tmp_path):
    path = write_model(tmp_path, 'computed', {})
    path.write_text('function data() return {version=1, metadata=makeMetadata()} end')
    assert analyze_mod(tmp_path)['categories'] == {'unknown': 1}


def test_helper_import_does_not_hide_literal_vehicle_metadata(tmp_path):
    path = write_model(tmp_path, 'plane', {'airVehicle': {}})
    text = path.read_text()
    path.write_text('local helper = require("never_execute_this")\n' + text)
    assert analyze_mod(tmp_path)['categories'] == {'air_vehicle': 1}


def test_conditional_returns_are_not_guessed(tmp_path):
    path = write_model(tmp_path, 'conditional', {})
    path.write_text('function data() if choose() then return {metadata={airVehicle={}}} end return {metadata={roadVehicle={}}} end')
    assert analyze_mod(tmp_path)['categories'] == {'unknown': 1}


@pytest.mark.parametrize('statement', [
    'data = function() return calculateActualData() end',
    'local data = function() return calculateActualData() end',
    'if choose() then data = other end',
    'replaceDataFunction()',
    '_G.data = other',
])
def test_rebound_or_conditional_data_is_not_classified_from_old_body(tmp_path, statement):
    path = write_model(tmp_path, 'rebound', {'airVehicle': {}})
    path.write_text(path.read_text() + '\n' + statement)
    assert analyze_mod(tmp_path)['categories'] == {'unknown': 1}


def test_nil_vehicle_marker_does_not_override_valid_road_metadata(tmp_path):
    path = write_model(tmp_path, 'nil_marker', {})
    path.write_text('function data() return {metadata={airVehicle=nil,roadVehicle={}}} end')
    assert analyze_mod(tmp_path)['categories'] == {'road_vehicle': 1}


@pytest.mark.parametrize('metadata', [
    {'airVehicle': False, 'roadVehicle': {}},
    {'airVehicle': {}, 'waterVehicle': {}},
])
def test_invalid_or_conflicting_vehicle_markers_require_review(tmp_path, metadata):
    write_model(tmp_path, 'invalid', metadata)
    assert analyze_mod(tmp_path)['categories'] == {'unknown': 1}


def test_native_tf3_tram_uses_transport_modes(tmp_path):
    write_model(tmp_path, 'native_tram', {'railVehicle': {}, 'transportVehicle': {'transportModes': ['TRAM', 'ELECTRIC_TRAM']}})
    assert analyze_mod(tmp_path)['categories'] == {'tram': 1}


def mesh(root, *, bad_index=False, nonfinite=False):
    root.mkdir(parents=True, exist_ok=True)
    data = {'vertexAttr': {}, 'subMeshes': [{'indices': {}}]}
    blob = bytearray()
    for name, comp, values in [('position', 3, [0.0, 0.0, 0.0]),
                               ('normal', 3, [0.0, 0.0, 1.0] * 3),
                               ('uv0', 2, [0.0, 0.0, 0.5, 0.5, 1.0, 1.0]),
                               ('tangent', 4, [math.nan if nonfinite else 1.0, 0.0, 0.0, 1.0] * 3)]:
        data['vertexAttr'][name] = {'offset': len(blob), 'count': len(values) * 4, 'numComp': comp}
        blob.extend(struct.pack('<' + 'f' * len(values), *values))
    for name in data['vertexAttr']:
        indices = [0, 0, 0] if name == 'position' else [0, 1, 2]
        if bad_index and name == 'uv0': indices[-1] = 3
        data['subMeshes'][0]['indices'][name] = {'offset': len(blob), 'count': 12}
        blob.extend(struct.pack('<III', *indices))
    path = root / 'shape.msh'
    path.write_text(emit(data))
    path.with_suffix('.msh.blob').write_bytes(blob)
    return path, data


def test_mesh_validates_every_index_against_its_own_buffer(tmp_path):
    path, _ = mesh(tmp_path)
    result = audit_mesh(path)
    assert result['status'] == 'checked'
    assert result['separateAttributeIndices']
    assert result['attributes']['position']['items'] == 1
    assert result['attributes']['uv0']['items'] == 3
    path, _ = mesh(tmp_path, bad_index=True)
    result = audit_mesh(path)
    assert result['status'] == 'blocked'
    assert 'uv0' in result['errors'][0]


def test_mesh_nonfinite_is_reported_without_repair_or_game_claim(tmp_path):
    path, _ = mesh(tmp_path, nonfinite=True)
    original = path.with_suffix('.msh.blob').read_bytes()
    result = audit_mesh(path)
    assert result['status'] == 'checked_with_warnings'
    assert result['attributes']['tangent']['nonfiniteComponents'] == 3
    assert path.with_suffix('.msh.blob').read_bytes() == original


@pytest.mark.parametrize('mutation', ['range', 'component', 'unequal', 'triangle'])
def test_malformed_mesh_buffers_are_rejected(tmp_path, mutation):
    path, data = mesh(tmp_path)
    if mutation == 'range': data['vertexAttr']['uv0']['offset'] = 9999
    elif mutation == 'component': data['vertexAttr']['position']['numComp'] = 0
    elif mutation == 'unequal': data['subMeshes'][0]['indices']['uv0']['count'] = 0
    else: data['subMeshes'][0]['indices']['uv0']['count'] = 8
    path.write_text(emit(data))
    assert audit_mesh(path)['status'] == 'blocked'


def test_shared_mesh_checks_block_invalid_export_for_any_mod(tmp_path):
    source = tmp_path / 'source'
    mesh(source / 'content', bad_index=True)
    (source / 'mod.json').write_text('{"modId":"test","name":"Test"}')
    assert any('uv0' in b for b in prepare_mod(source).blockers)
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='uv0'):
        convert_mod(source, output)
    assert not output.exists()


def test_unknown_descriptor_never_claims_binary_checks_passed(tmp_path):
    path, _ = mesh(tmp_path)
    path.write_text('function data() return {} end')
    assert audit_mesh(path)['status'] == 'unverified'


def test_linked_resource_is_not_followed(tmp_path):
    outside = tmp_path / 'outside'
    mesh(outside)
    root = tmp_path / 'source'
    (root / 'content').mkdir(parents=True)
    try:
        (root / 'content' / 'linked').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('Symlinks unavailable')
    report = analyze_mod(root)
    assert report['problems'] and report['status'] == 'needs_review'
    assert report['geometry'] == []

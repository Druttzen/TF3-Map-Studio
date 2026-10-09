import json
from pathlib import Path

import pytest

from test_tf2_vehicle_port import fixture_mod
from trf3_mod_converter.batch import convert_queue, scan_mods
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, snapshot


def collection(fixture_mod, tmp_path):
    original, game, output = fixture_mod
    source = tmp_path/'1066780/123'
    source.parent.mkdir()
    original.rename(source)
    provider = source.parent/'456'
    (provider/'res').mkdir(parents=True)
    (provider/'mod.lua').write_text(emit({'info':{'name':'Dependency'}}))
    return source, provider, game, output


def move_resource(source, provider, relative):
    target = provider/'res'/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    (source/'res'/relative).rename(target)
    return target


def test_external_material_texture_and_mesh_closure_are_converted_and_rechecked(fixture_mod, tmp_path):
    source, provider, game, output = collection(fixture_mod, tmp_path)
    material = move_resource(source, provider, 'models/material/body.mtl')
    texture = move_resource(source, provider, 'textures/body.dds')
    mesh = move_resource(source, provider, 'models/mesh/wheel.msh')
    blob = move_resource(source, provider, 'models/mesh/wheel.msh.blob')
    before = {str(p):snapshot(p) for p in (source, provider)}
    result = convert_queue(scan_mods(source)['items'], output, tf3_game=game)
    assert result['counts'] == {'completed':1,'failed':0,'pending':0}
    target = Path(result['items'][0]['destination'])
    report = json.loads((target/'conversion-report.json').read_text())
    dependencies = report['migrationAudit']['workshopDependencies']
    assert {row['kind'] for row in dependencies} == {'material','texture','mesh','mesh_blob'}
    migrated = load_lua_table((target/'content/models/material/body.mtl').read_text())
    assert migrated['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName'].startswith('tf2_workshop_123::/')
    assert (target/'content/models/mesh/wheel.msh.blob').read_bytes() == blob.read_bytes()
    assert (target/'_port_originals/res/models/material/body.mtl').read_bytes() == material.read_bytes()
    assert {str(p):snapshot(p) for p in (source, provider)} == before
    material.write_text(material.read_text().replace('PHYSICAL','UNSUPPORTED'))
    resumed = convert_queue(scan_mods(source)['items'], output, tf3_game=game)
    assert resumed['counts']['failed'] == 1
    assert 'not overwritten' in resumed['items'][0]['message']


def test_missing_geometry_in_descriptor_provider_does_not_borrow_an_unrelated_blob(fixture_mod, tmp_path):
    source, provider, game, output = collection(fixture_mod, tmp_path)
    move_resource(source, provider, 'models/mesh/wheel.msh')
    # An unrelated package cannot supply geometry without its descriptor.
    other = source.parent/'789'
    move_resource(source, other, 'models/mesh/wheel.msh.blob')
    result = convert_queue(scan_mods(source)['items'], output, tf3_game=game)
    assert result['counts']['failed'] == 1
    assert 'not provided by its descriptor' in result['items'][0]['message']
    assert not Path(result['items'][0]['destination']).exists()

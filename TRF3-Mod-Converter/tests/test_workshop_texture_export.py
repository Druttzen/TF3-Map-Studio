import hashlib
import json
import pytest

from test_tf2_vehicle_port import fixture_mod
from trf3_mod_converter.batch import scan_mods, convert_queue
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, snapshot, port_tf2_mod


def test_exact_dependency_texture_is_copied_and_resume_rechecks_provider(fixture_mod, tmp_path):
    original, game, output = fixture_mod
    source = tmp_path/'1066780'/'123'
    source.parent.mkdir()
    original.rename(source)
    texture = source.parent/'456/res/textures/shared/dependency.dds'
    texture.parent.mkdir(parents=True)
    texture.write_bytes(b'authored external dependency texture')
    for name in ('body.mtl', 'light.mtl'):
        path = source/'res/models/material'/name
        data = load_lua_table(path.read_text())
        data['params']['map_albedo']['fileName'] = 'shared/dependency.dds'
        path.write_text(emit(data))
    before = snapshot(source)
    first = convert_queue(scan_mods(source)['items'], output, tf3_game=game)
    assert first['counts']['completed'] == 1
    target = output/first['items'][0]['mod_id']
    report = json.loads((target/'conversion-report.json').read_text())
    digest = hashlib.sha256(texture.read_bytes()).hexdigest()
    assert report['workshopResourceFingerprints'] == {
        str(texture):digest,
        str(source/'mod.lua'):hashlib.sha256((source/'mod.lua').read_bytes()).hexdigest()}
    assert (target/'content/_dependencies'/f'{digest}.dds').read_bytes() == texture.read_bytes()
    assert report['migrationAudit']['workshopDependencies'][0]['sourceReference'] == 'shared/dependency.dds'
    assert snapshot(source) == before
    texture.write_bytes(b'changed dependency texture')
    second = convert_queue(scan_mods(source)['items'], output, tf3_game=game)
    assert second['counts']['failed'] == 1
    assert 'not overwritten' in second['items'][0]['message']
    assert (target/'content/_dependencies'/f'{digest}.dds').read_bytes() == b'authored external dependency texture'


@pytest.mark.parametrize('valid', [False, True])
def test_workshop_stock_texture_uses_explicit_game_proof_and_rechecks_provider(fixture_mod, tmp_path, valid):
    from test_source_game_resources import dds
    from trf3_mod_converter.workshop_resources import verify_workshop_dependencies
    from trf3_mod_converter.source_game_resources import verify_source_game_dependencies
    original, game, output = fixture_mod
    source = tmp_path/'1066780'/'123'
    source.parent.mkdir()
    original.rename(source)
    for folder in (source.parent/'456/res/textures/shared', tmp_path/'tf2/res/textures/shared'):
        folder.mkdir(parents=True)
        (folder/'borrowed.dds').write_bytes(dds() if valid else b'original TF2 game texture bytes')
    (source.parent/'456/mod.lua').write_text(emit({'info':{'name':'Stock provider'}}))
    metadata = load_lua_table((source/'mod.lua').read_text())
    metadata['info']['requiredMods'] = [{'steamId':'456'}]
    (source/'mod.lua').write_text(emit(metadata))
    path = source/'res/models/material/body.mtl'
    data = load_lua_table(path.read_text())
    data['params']['map_albedo']['fileName'] = 'shared/borrowed.dds'
    path.write_text(emit(data))
    before = snapshot(source)
    if not valid:
        with pytest.raises(ValueError, match='malformed DDS header'):
            port_tf2_mod(source, output, tf3_game=game, tf2_game=tmp_path/'tf2',
                         mod_id='fixture_shared', name='Borrowed dependency')
        assert not output.exists()
    else:
        report = port_tf2_mod(source, output, tf3_game=game, tf2_game=tmp_path/'tf2',
                              mod_id='fixture_shared', name='Borrowed dependency')
        assert len(report['sourceGameDependencies']) == 1
        assert verify_source_game_dependencies(tmp_path/'tf2', report['sourceGameDependencies'],
            report['sourceGameResourceFingerprints'], report['sourceGameInventoryFingerprint'])
        rows = report['migrationAudit']['workshopDependencies']
        assert rows and all(row['policy'] == 'verify_stock_provider_selection_for_source_game_adaptation' for row in rows)
        assert verify_workshop_dependencies(source, rows, report['workshopResourceFingerprints'])
        assert (output/'content/textures/shared/borrowed.dds').read_bytes() == dds()
        (source.parent/'456/res/textures/shared/borrowed.dds').write_bytes(b'changed author asset')
        assert not verify_workshop_dependencies(source, rows, report['workshopResourceFingerprints'])
    assert snapshot(source) == before


def test_exact_installed_stock_path_precedes_unrelated_global_workshop_names(fixture_mod, tmp_path):
    from test_source_game_resources import dds
    original, game, output = fixture_mod
    source = tmp_path/'1066780'/'123'
    source.parent.mkdir()
    original.rename(source)
    for package, raw in (('456', b'unrelated custom texture'), ('789', b'another custom texture')):
        path = source.parent/package/'res/textures/stock.dds'
        path.parent.mkdir(parents=True)
        path.write_bytes(raw)
    stock = tmp_path/'tf2/res/textures/stock.dds'
    stock.parent.mkdir(parents=True)
    stock.write_bytes(dds())
    material = source/'res/models/material/body.mtl'
    data = load_lua_table(material.read_text())
    data['params']['map_albedo']['fileName'] = 'stock.dds'
    material.write_text(emit(data))
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=tmp_path/'tf2',
                          mod_id='fixture_shared', name='Stock path')
    assert (output/'content/textures/stock.dds').read_bytes() == dds()
    assert not report['migrationAudit'].get('workshopDependencies')
    assert len(report['sourceGameDependencies']) == 1


@pytest.mark.parametrize('authored_geometry', [True, False])
def test_stock_mesh_descriptor_does_not_replace_provider_authored_geometry(fixture_mod, tmp_path, authored_geometry):
    import struct
    from test_source_game_resources import geometry
    original, game, output = fixture_mod
    source = tmp_path/'1066780'/'123'
    source.parent.mkdir()
    original.rename(source)
    mesh, blob, _ = geometry()
    custom_blob = struct.pack('<f', 2)+blob[4:] if authored_geometry else blob
    provider = source.parent/'456'
    (provider/'res/models/mesh').mkdir(parents=True)
    (provider/'mod.lua').write_text(emit({'info':{'name':'Geometry provider'}}))
    metadata = load_lua_table((source/'mod.lua').read_text())
    metadata['info']['requiredMods'] = [{'steamId':'456'}]
    (source/'mod.lua').write_text(emit(metadata))
    tf2 = tmp_path/'tf2'
    (tf2/'res/models/mesh').mkdir(parents=True)
    for folder, raw in ((provider/'res/models/mesh', custom_blob), (tf2/'res/models/mesh', blob)):
        (folder/'light.msh').write_bytes(mesh)
        (folder/'light.msh.blob').write_bytes(raw)
    for suffix in ('', '.blob'):
        (source/'res/models/mesh'/('light.msh'+suffix)).unlink()
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=tf2,
                          mod_id='fixture_shared', name='Preserved geometry')
    assert (output/'content/models/mesh/light.msh.blob').read_bytes() == custom_blob
    rows = report['migrationAudit']['workshopDependencies']
    assert {row['kind'] for row in rows} == {'mesh', 'mesh_blob'}
    if authored_geometry:
        assert not report['sourceGameDependencies']
        assert any(row['policy'] == 'copy_exact_workshop_mesh_geometry' for row in rows)
    else:
        assert len(report['sourceGameDependencies']) == 2
        assert all(row['policy'] == 'verify_stock_provider_selection_for_source_game_adaptation' for row in rows)


def test_root_port_records_absent_declared_resource_before_stock_fallback(fixture_mod, tmp_path):
    from test_source_game_resources import dds
    from trf3_mod_converter.workshop_resources import verify_workshop_absences
    original, game, output = fixture_mod
    source = tmp_path/'1066780'/'123'
    source.parent.mkdir()
    original.rename(source)
    provider = source.parent/'456'
    provider.mkdir()
    (provider/'mod.lua').write_text(emit({'info':{'name':'Optional author resource'}}))
    metadata = load_lua_table((source/'mod.lua').read_text())
    metadata['info']['requiredMods'] = [{'steamId':'456'}]
    (source/'mod.lua').write_text(emit(metadata))
    stock = tmp_path/'tf2/res/textures/stock.dds'
    stock.parent.mkdir(parents=True)
    stock.write_bytes(dds())
    material = source/'res/models/material/body.mtl'
    data = load_lua_table(material.read_text())
    data['params']['map_albedo']['fileName'] = 'stock.dds'
    material.write_text(emit(data))
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=tmp_path/'tf2',
                          mod_id='fixture_shared', name='Stock fallback')
    rows = report['workshopAbsentDependencies']
    assert sum(row['sourceReference'] == 'stock.dds' for row in rows) == 1
    assert rows == report['migrationAudit']['workshopAbsentDependencies']
    assert verify_workshop_absences(source, rows)
    custom = provider/'res/textures/stock.dds'
    custom.parent.mkdir(parents=True)
    custom.write_bytes(b'new authored resource')
    assert not verify_workshop_absences(source, rows)
    assert (output/'content/textures/stock.dds').read_bytes() == dds()


@pytest.mark.parametrize('provider_bytes', [None, b'original stock placeholder', b'authored replacement'])
def test_declared_context_is_checked_before_native_role_and_retained_in_receipts(fixture_mod, tmp_path, provider_bytes):
    import zipfile
    from trf3_mod_converter.workshop_resources import (
        verify_workshop_absences, verify_native_stock_selections, verify_workshop_dependencies,
    )
    original, game, output = fixture_mod
    source = tmp_path/'1066780'/'123'
    source.parent.mkdir()
    original.rename(source)
    provider = source.parent/'456'
    provider.mkdir()
    (provider/'mod.lua').write_text(emit({'info':{'name':'Declared provider'}}))
    metadata = load_lua_table((source/'mod.lua').read_text())
    metadata['info']['requiredMods'] = [{'steamId':'456'}]
    (source/'mod.lua').write_text(emit(metadata))
    tf2 = tmp_path/'tf2'
    stock = tf2/'res/textures/default_normal_map.tga'
    stock.parent.mkdir(parents=True)
    stock.write_bytes(b'original stock placeholder')
    custom = provider/'res/textures/default_normal_map.tga'
    if provider_bytes is not None:
        custom.parent.mkdir(parents=True)
        custom.write_bytes(provider_bytes)
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('placeholders/mat/tex/default_normal_map.dds', b'native placeholder')
    material = source/'res/models/material/body.mtl'
    data = load_lua_table(material.read_text())
    data['params']['map_albedo']['fileName'] = 'default_normal_map.tga'
    material.write_text(emit(data))
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=tf2,
                          mod_id='fixture_shared', name='Native role')
    assert not report['sourceGameDependencies']
    rows = report['migrationAudit'].get('workshopDependencies', [])
    if provider_bytes == b'authored replacement':
        assert rows and all(row['policy'] != 'verify_stock_provider_selection_for_native_mapping' for row in rows)
        assert not any(row['sourceReference'] == 'default_normal_map.tga' for row in report['baseResourceReplacements'])
    elif provider_bytes is not None:
        assert rows and all(row['policy'] == 'verify_stock_provider_selection_for_native_mapping' for row in rows)
        assert all((output/row['originalFile']).read_bytes() == provider_bytes for row in rows)
        assert verify_workshop_dependencies(source, rows, report['workshopResourceFingerprints'])
        assert verify_native_stock_selections(source, game, rows, tf2_game=tf2)
        stock.write_bytes(b'updated installed stock bytes')
        assert not verify_native_stock_selections(source, game, rows, tf2_game=tf2)
    else:
        absent = report['workshopAbsentDependencies']
        assert sum(row['sourceReference'] == 'default_normal_map.tga' for row in absent) == 1
        assert verify_workshop_absences(source, absent)
        custom.parent.mkdir(parents=True)
        custom.write_bytes(b'new authored replacement')
        assert not verify_workshop_absences(source, absent)

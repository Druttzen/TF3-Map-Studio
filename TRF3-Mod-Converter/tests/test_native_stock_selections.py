import json
from pathlib import Path
import zipfile

import pytest

from trf3_mod_converter import batch
from trf3_mod_converter.base_resources import ROOTS, source_resource
from trf3_mod_converter.tf2_vehicle_port import emit, snapshot
from trf3_mod_converter.workshop_resources import (WorkshopResources,
    verify_native_stock_selections, verify_workshop_dependencies)


POLICY = 'verify_stock_provider_selection_for_native_mapping'


def stock_fixture(tmp_path, kind='texture', reference='default_normal_map.tga'):
    source = tmp_path/'1066780/123'
    source.mkdir(parents=True)
    (source/'mod.lua').write_text(emit({'info': {'name': 'Native stock selection',
        'authors': ['Author'], 'requiredMods': [{'steamId': 456, 'modId': 'dependency'}]}}))
    dependency = source.parent/'456'
    dependency.mkdir()
    (dependency/'mod.lua').write_text(emit({'info': {'modid': 'dependency', 'steamId': 456}}))
    resource = ROOTS['mesh']+'/'+reference if kind == 'mesh_blob' else source_resource(kind, reference)
    game = tmp_path/'Transport Fever 2'
    stock = game/'res'/resource
    stock.parent.mkdir(parents=True)
    stock.write_bytes(b'exact old stock input')
    provider = dependency/'res'/resource
    provider.parent.mkdir(parents=True)
    provider.write_bytes(stock.read_bytes())
    match = WorkshopResources(source).resolve(reference, kind, allow_global=False)
    row = {key: value for key, value in match.items() if key not in ('data', 'fingerprints')}
    row['policy'] = POLICY
    return source, game, tmp_path/'Transport Fever 3', stock, [row], match['fingerprints']


@pytest.mark.parametrize('kind,reference', [
    ('texture', 'default_normal_map.tga'), ('material', 'track/rail.mtl'),
    ('model', 'characters/driver.mdl'), ('mesh_blob', 'asset/light.msh.blob'),
    ('animation', 'vehicle/doors.ani'), ('audio', 'vehicle/horn.wav'), ('sound_set', 'train'),
])
def test_fresh_stock_bytes_are_required_even_when_selected_workshop_provider_is_unchanged(tmp_path, kind, reference):
    source, _, tf3, stock, rows, fingerprints = stock_fixture(tmp_path, kind, reference)
    assert verify_workshop_dependencies(source, rows, fingerprints)
    assert verify_native_stock_selections(source, tf3, rows)
    stock.write_bytes(b'changed installed stock')
    assert verify_workshop_dependencies(source, rows, fingerprints)
    assert not verify_native_stock_selections(source, tf3, rows)


def test_current_exact_mount_selection_is_used_and_loose_override_invalidates_stock_identity(tmp_path):
    source, game, tf3, stock, rows, _ = stock_fixture(tmp_path)
    data = stock.read_bytes()
    stock.unlink()
    archive = game/'res/textures.zip'
    with zipfile.ZipFile(archive, 'w') as contents:
        contents.writestr('textures/default_normal_map.tga', data)
    assert verify_native_stock_selections(source, tf3, rows)
    stock.write_bytes(b'new loose override')
    assert not verify_native_stock_selections(source, tf3, rows)


def test_only_explicit_port_input_may_override_canonical_game_selection(tmp_path):
    source, game, tf3, stock, rows, _ = stock_fixture(tmp_path)
    other = tmp_path/'explicit-tf2'
    explicit = other/'res/textures/default_normal_map.tga'
    explicit.parent.mkdir(parents=True)
    explicit.write_bytes(stock.read_bytes())
    stock.write_bytes(b'changed canonical stock')
    rows[0]['sourceGameInstallation'] = str(other)
    assert not verify_native_stock_selections(source, tf3, rows)
    assert verify_native_stock_selections(source, tf3, rows, tf2_game=other)
    assert not verify_native_stock_selections(source, None, rows)
    assert verify_native_stock_selections(source, None, rows, tf2_game=other)


@pytest.mark.parametrize('field,value', [
    ('kind', 'helper'), ('sourceReference', '../default_normal_map.tga'),
    ('sourceResource', 'textures/different.tga'), ('sha256', 'not a digest'),
])
def test_native_selection_evidence_rejects_invalid_kind_path_or_digest(tmp_path, field, value):
    source, _, tf3, _, rows, _ = stock_fixture(tmp_path)
    rows[0][field] = value
    assert not verify_native_stock_selections(source, tf3, rows)


def test_unselected_workshop_rows_and_empty_old_receipts_do_not_require_tf2(tmp_path):
    assert verify_native_stock_selections(tmp_path, None, [])
    assert verify_native_stock_selections(tmp_path, None, [{'policy': 'adapt_exact_authored_input'}])
    assert not verify_native_stock_selections(tmp_path, None, None)


def batch_fixture(tmp_path, monkeypatch):
    source, _, tf3, stock, rows, fingerprints = stock_fixture(tmp_path)
    actual = batch._export
    calls = []

    def export(*args):
        calls.append(args[0].mod_id)
        result = actual(*args)
        return {**result, 'migrationAudit': {'workshopDependencies': rows},
                'workshopResourceFingerprints': fingerprints}

    monkeypatch.setattr(batch, '_export', export)
    return source, tf3, stock, tmp_path/'exports', calls


def test_batch_native_selection_stock_change_denies_resume_without_overwriting_export(tmp_path, monkeypatch):
    source, tf3, stock, output, calls = batch_fixture(tmp_path, monkeypatch)
    first = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert first['counts']['completed'] == 1
    receipt = next(iter(json.loads((output/batch.STATE_NAME).read_text())['receipts'].values()))
    assert receipt['workshopDependencies'][0]['policy'] == POLICY
    assert receipt['sourceGameDependencies'] == []
    target = Path(first['items'][0]['destination'])
    before = snapshot(target)
    assert batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)['counts']['completed'] == 1
    stock.write_bytes(b'changed selected TF2 stock bytes')
    resumed = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert resumed['counts']['failed'] == 1
    assert 'not overwritten' in resumed['items'][0]['message']
    assert len(calls) == 1 and snapshot(target) == before


def test_stock_change_during_export_cannot_gain_completed_receipt(tmp_path, monkeypatch):
    source, tf3, stock, output, _ = batch_fixture(tmp_path, monkeypatch)
    actual = batch._export

    def export(*args):
        report = actual(*args)
        stock.write_bytes(b'changed selected TF2 stock bytes')
        return report

    monkeypatch.setattr(batch, '_export', export)
    state = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert state['counts']['failed'] == 1 and state['receipts'] == {}
    assert 'stock resources used to select native mappings changed' in state['items'][0]['message']

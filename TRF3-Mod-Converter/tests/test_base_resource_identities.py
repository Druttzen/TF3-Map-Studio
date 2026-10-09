import hashlib
import json
from pathlib import Path

import pytest

from trf3_mod_converter import batch
from trf3_mod_converter.tf2_vehicle_port import snapshot
from trf3_mod_converter.workshop_resources import verify_base_resource_identities
from test_native_stock_selections import stock_fixture


def identity_fixture(tmp_path, origin='tf2_base', method='byte_identical'):
    source, game, tf3, stock, _, _ = stock_fixture(tmp_path)
    row = {'kind':'texture', 'sourceReference':'default_normal_map.tga',
        'sourceResource':'res/textures/default_normal_map.tga', 'sourceOrigin':origin,
        'matchMethod':method, 'targetReference':'::/placeholders/mat/tex/default_normal_map.dds',
        'tf3Resource':'placeholders/mat/tex/default_normal_map.dds'}
    if method == 'byte_identical':
        row['sha256'] = hashlib.sha256(stock.read_bytes()).hexdigest()
    if origin == 'bundled_tf2_base':
        bundled = source/row['sourceResource']
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(stock.read_bytes())
    return source, game, tf3, stock, [row]


@pytest.mark.parametrize('origin,method', [
    ('tf2_base', 'byte_identical'), ('bundled_tf2_base', 'byte_identical'),
    ('bundled_tf2_base', 'verified_role_mapping'),
])
def test_native_mapping_stock_identity_rechecks_current_exact_tf2_input(tmp_path, origin, method):
    source, _, tf3, stock, rows = identity_fixture(tmp_path, origin, method)
    assert verify_base_resource_identities(source, tf3, rows)
    original_source = snapshot(source)
    stock.write_bytes(b'changed stock input')
    assert snapshot(source) == original_source
    assert not verify_base_resource_identities(source, tf3, rows)


def test_bundled_role_requires_exact_unmodified_safe_root_file(tmp_path):
    source, _, tf3, _, rows = identity_fixture(tmp_path, 'bundled_tf2_base', 'verified_role_mapping')
    bundled = source/rows[0]['sourceResource']
    bundled.write_bytes(b'authored replacement')
    assert not verify_base_resource_identities(source, tf3, rows)
    rows[0]['sourceResource'] = 'res/../outside.tga'
    assert not verify_base_resource_identities(source, tf3, rows)


def test_only_port_override_can_select_noncanonical_tf2_installation(tmp_path):
    source, _, _, stock, rows = identity_fixture(tmp_path)
    assert not verify_base_resource_identities(source, None, rows)
    assert verify_base_resource_identities(source, None, rows, tf2_game=stock.parents[2])


@pytest.mark.parametrize('changes', [
    {'sha256':None}, {'sourceResource':'res/textures/different.tga'},
    {'sourceReference':'../default_normal_map.tga'}, {'kind':'helper'},
])
def test_malformed_identity_evidence_is_rejected(tmp_path, changes):
    source, _, tf3, _, rows = identity_fixture(tmp_path)
    rows[0].update(changes)
    assert not verify_base_resource_identities(source, tf3, rows)


def test_empty_and_role_only_absent_local_input_need_no_tf2(tmp_path):
    assert verify_base_resource_identities(tmp_path, None, [])
    assert verify_base_resource_identities(tmp_path, None,
        [{'sourceOrigin':'tf2_base', 'matchMethod':'verified_role_mapping'}])
    assert not verify_base_resource_identities(tmp_path, None, [None])


def setup_batch(tmp_path, monkeypatch):
    source, _, tf3, stock, rows = identity_fixture(tmp_path)
    actual = batch._export
    calls = []

    def export(*args):
        calls.append(args[0].mod_id)
        report = {**actual(*args), 'baseResourceReplacements':rows}
        (args[1]/'conversion-report.json').write_text(json.dumps(report))
        return report

    monkeypatch.setattr(batch, '_export', export)
    return source, tf3, stock, tmp_path/'exports', calls


@pytest.mark.parametrize('old_receipt', [False, True])
def test_current_identity_resumes_but_changed_tf2_denies_without_overwrite(tmp_path, monkeypatch, old_receipt):
    source, tf3, stock, output, calls = setup_batch(tmp_path, monkeypatch)
    first = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert first['counts']['completed'] == 1
    state_path = output/batch.STATE_NAME
    state = json.loads(state_path.read_text())
    receipt = next(iter(state['receipts'].values()))
    assert len(receipt['baseResourceReplacements']) == 1
    if old_receipt:
        receipt.pop('baseResourceReplacements')
        state_path.write_text(json.dumps(state))
    target = Path(first['items'][0]['destination'])
    before = snapshot(target)
    assert batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)['counts']['completed'] == 1
    stock.write_bytes(b'changed exact stock input')
    resumed = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert resumed['counts']['failed'] == 1 and len(calls) == 1
    assert 'not overwritten' in resumed['items'][0]['message']
    assert snapshot(target) == before


def test_stock_change_during_export_never_gets_green_receipt(tmp_path, monkeypatch):
    source, tf3, stock, output, _ = setup_batch(tmp_path, monkeypatch)
    actual = batch._export

    def export(*args):
        report = actual(*args)
        stock.write_bytes(b'changed while exporting')
        return report

    monkeypatch.setattr(batch, '_export', export)
    state = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert state['counts']['failed'] == 1 and state['receipts'] == {}
    assert 'TF2 base resources used to select native mappings changed' in state['items'][0]['message']


@pytest.mark.parametrize('contents', ['not json', '[]', '{"baseResourceReplacements": null}'])
def test_old_receipt_malformed_saved_report_denies_resume(tmp_path, monkeypatch, contents):
    source, tf3, _, output, calls = setup_batch(tmp_path, monkeypatch)
    first = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    target = Path(first['items'][0]['destination'])
    (target/'conversion-report.json').write_text(contents)
    state_path = output/batch.STATE_NAME
    state = json.loads(state_path.read_text())
    receipt = next(iter(state['receipts'].values()))
    receipt.pop('baseResourceReplacements')
    receipt['outputFingerprint'] = batch.file_fingerprint(target)
    state_path.write_text(json.dumps(state))
    resumed = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=tf3)
    assert resumed['counts']['failed'] == 1 and len(calls) == 1


def test_old_report_reader_rejects_missing_nonregular_and_linked_report(tmp_path):
    target = tmp_path/'export'
    target.mkdir()
    report = target/'conversion-report.json'
    assert batch._receipt_base_replacements({}, target) is None
    report.mkdir()
    assert batch._receipt_base_replacements({}, target) is None
    report.rmdir()
    outside = tmp_path/'outside.json'
    outside.write_text('{}')
    try:
        report.symlink_to(outside)
    except OSError:
        pytest.skip('Creating symbolic links is unavailable')
    assert batch._receipt_base_replacements({}, target) is None

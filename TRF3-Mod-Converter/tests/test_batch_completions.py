import json

import pytest

from trf3_mod_converter import batch


def source_mod(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'mod.json').write_text(json.dumps({'name': 'Native completion test', 'authors': ['Creator']}), encoding='utf-8')
    return root


def exporter(monkeypatch, report):
    calls = []
    actual = batch._export

    def export(*args):
        calls.append(args[0].mod_id)
        actual(*args)
        return report

    monkeypatch.setattr(batch, '_export', export)
    return calls


@pytest.mark.parametrize('audit_key', ['dataCompletions', 'donorCompletions'])
def test_added_native_data_is_reported_and_persisted_before_completion_event(tmp_path, monkeypatch, audit_key):
    source = source_mod(tmp_path)
    output = tmp_path / 'exports'
    items = batch.scan_mods(source)['items']
    calls = exporter(monkeypatch, {'migrationAudit': {audit_key: [{'sourcePath': 'weight', 'donorValue': 24}]}})
    events = []

    def event(kind, value):
        if kind == 'item' and value['status'] == 'completed':
            saved = json.loads((output / batch.STATE_NAME).read_text(encoding='utf-8'))
            assert saved['items'][0]['message'] == 'Export saved · TF3 data added'
            assert saved['receipts'][value['key']]['tf3DataAdded'] is True
            events.append(value['message'])

    state = batch.convert_queue(items, output, event=event)
    assert calls == [items[0].mod_id]
    assert state['counts']['completed'] == 1
    assert events == ['Export saved · TF3 data added']
    assert items[0].message == 'Export saved · TF3 data added'


@pytest.mark.parametrize('report', [None, {}, {'migrationAudit': {}},
    {'migrationAudit': {'dataCompletions': [], 'donorCompletions': []}},
    {'migrationAudit': {'vehicleProfiles': [{'profile': 'tf2_train_electric'}], 'materialMigrations': [{'field': 'color'}]}},
    {'migrationAudit': {'dataCompletions': 'unexpected', 'donorCompletions': [{}]}},
    {'migrationAudit': []}])
def test_default_export_message_is_kept_when_no_completed_data_is_recorded(tmp_path, monkeypatch, report):
    source = source_mod(tmp_path)
    items = batch.scan_mods(source)['items']
    exporter(monkeypatch, report)
    state = batch.convert_queue(items, tmp_path / 'exports')
    assert state['counts']['completed'] == 1
    assert items[0].message == 'Export saved'
    assert state['receipts'][items[0].key]['tf3DataAdded'] is False


def test_verified_resume_keeps_completion_summary_without_running_export_again(tmp_path, monkeypatch):
    source = source_mod(tmp_path)
    output = tmp_path / 'exports'
    report = {'migrationAudit': {'donorCompletions': [{'targetValue': 72, 'donorResource': 'vehicle/native.mdl'}]}}
    calls = exporter(monkeypatch, report)
    initial = batch.scan_mods(source)['items']
    batch.convert_queue(initial, output)
    resumed = batch.scan_mods(source)['items']
    state = batch.convert_queue(resumed, output)
    assert calls == [initial[0].mod_id]
    assert state['counts']['completed'] == 1
    assert resumed[0].message == 'Previous export verified · TF3 data added'
    assert state['receipts'][resumed[0].key]['tf3DataAdded'] is True


@pytest.mark.parametrize('legacy_value', ['missing', False, 'true', 1])
def test_receipts_without_a_verified_completion_boolean_keep_plain_resume_message(tmp_path, legacy_value):
    source = source_mod(tmp_path)
    output = tmp_path / 'exports'
    original = batch.scan_mods(source)['items']
    batch.convert_queue(original, output)
    state_path = output / batch.STATE_NAME
    state = json.loads(state_path.read_text(encoding='utf-8'))
    receipt = state['receipts'][original[0].key]
    if legacy_value == 'missing':
        receipt.pop('tf3DataAdded')
    else:
        receipt['tf3DataAdded'] = legacy_value
    state_path.write_text(json.dumps(state), encoding='utf-8')
    resumed = batch.scan_mods(source)['items']
    assert batch.convert_queue(resumed, output)['counts']['completed'] == 1
    assert resumed[0].message == 'Previous export verified'


def test_failed_or_changed_export_does_not_gain_completion_receipt_or_success_message(tmp_path, monkeypatch):
    source = source_mod(tmp_path)
    output = tmp_path / 'exports'
    items = batch.scan_mods(source)['items']
    actual = batch._export

    def mutate_source(*args):
        actual(*args)
        (source / 'external-change.txt').write_text('changed during conversion', encoding='utf-8')
        return {'migrationAudit': {'dataCompletions': [{'field': 'weight', 'value': 24}]}}

    monkeypatch.setattr(batch, '_export', mutate_source)
    state = batch.convert_queue(items, output)
    assert state['counts']['failed'] == 1
    assert 'Source changed' in items[0].message
    assert 'TF3 data added' not in items[0].message
    assert items[0].key not in state['receipts']

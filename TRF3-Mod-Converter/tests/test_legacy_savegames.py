from copy import deepcopy
import json

import pytest

from trf3_mod_converter import __version__
from trf3_mod_converter.batch import STATE_NAME, convert_queue, file_fingerprint, scan_mods
from trf3_mod_converter.converter import convert_mod, prepare_mod
from trf3_mod_converter.tf2_vehicle_port import emit, snapshot


def legacy_package(root, ident='2857379678', *, save=True, authored_id='?_map_Scandinavia in 1971_125446'):
    source = root/'1066780'/ident
    source.mkdir(parents=True)
    (source/'mod.lua').write_text(emit({'id':authored_id, 'majorVersion':1,
                                     'info':{'name':'Scandinavia in 1971', 'visible':False}}))
    if save:
        maps = source/'maps'
        maps.mkdir()
        (maps/'Scandinavia in 1971.sav').write_bytes(b'opaque TF2 saved map data\x00\xff')
        (maps/'Scandinavia in 1971.sav.lua').write_text('return {name="Scandinavia in 1971"}')
    return source


@pytest.mark.parametrize('selection', ['folder', 'mod.lua'])
def test_direct_tf2_saved_map_rejected_before_any_output_copy(tmp_path, selection):
    source = legacy_package(tmp_path)
    selected = source if selection == 'folder' else source/'mod.lua'
    before = snapshot(source)
    destination = tmp_path/'new_output_parent'/'converted_map'
    descriptor = prepare_mod(selected, mod_id='tf2_workshop_2857379678')
    assert any('Unsupported TF2 saved map/savegame' in issue and '.sav.lua sidecar' in issue for issue in descriptor.blockers)
    with pytest.raises(ValueError, match='Metadata export cannot convert TF2 .sav data'):
        convert_mod(selected, destination, mod_id='tf2_workshop_2857379678', name='Renamed')
    assert snapshot(source) == before
    assert not destination.parent.exists()


def test_direct_rejection_preserves_existing_destination_without_backup(tmp_path):
    source = legacy_package(tmp_path)
    output = tmp_path/'old_output'
    output.mkdir()
    (output/'keep.txt').write_text('previous reviewed output')
    before_source, before_output = snapshot(source), snapshot(output)
    with pytest.raises(ValueError, match='Unsupported TF2 saved map/savegame'):
        convert_mod(source, output, mod_id='valid', overwrite=True)
    assert snapshot(source) == before_source and snapshot(output) == before_output
    assert not list(tmp_path.glob('old_output.backup-*'))


def test_queue_rejects_saved_map_before_receipt_resume_and_keeps_receipt_and_output(tmp_path):
    source = legacy_package(tmp_path)
    items = scan_mods(source)['items']
    assert items[0].mod_id == 'tf2_workshop_2857379678'
    assert items[0].scan_error == ''
    output = tmp_path/'outputs'
    target = output/items[0].mod_id
    target.mkdir(parents=True)
    (target/'keep.txt').write_text('previous output must remain unchanged')
    receipt = {'status':'completed', 'modId':items[0].mod_id,
               'sourceFingerprint':file_fingerprint(source), 'outputFingerprint':file_fingerprint(target),
               'converterVersion':__version__, 'tf3Game':None, 'nativeResources':{}}
    receipts = {items[0].key:deepcopy(receipt)}
    (output/STATE_NAME).write_text(json.dumps({'format':'tf3-converter-batch-v1', 'receipts':receipts}))
    before_source, before_output = snapshot(source), snapshot(target)
    events = []
    state = convert_queue(items, output, event=lambda kind,value: events.append((kind,value)))
    assert state['counts'] == {'completed':0, 'failed':1, 'pending':0}
    assert 'Unsupported TF2 saved map/savegame' in state['items'][0]['message']
    assert state['receipts'] == receipts
    assert json.loads((output/STATE_NAME).read_text())['receipts'] == receipts
    assert snapshot(source) == before_source and snapshot(target) == before_output
    assert not any(kind == 'item' and value['status'] == 'completed' for kind,value in events)


def test_invalid_tf2_workshop_id_uses_numeric_identity_and_records_namespace_change(tmp_path):
    source = legacy_package(tmp_path, save=False)
    before = snapshot(source)
    items = scan_mods(source)['items']
    assert items[0].mod_id == 'tf2_workshop_2857379678'
    output = tmp_path/'outputs'
    state = convert_queue(items, output)
    assert state['counts']['completed'] == 1
    report = json.loads((output/items[0].mod_id/'conversion-report.json').read_text())
    assert report['modId'] == 'tf2_workshop_2857379678'
    assert report['sourceModId'] == '?_map_Scandinavia in 1971_125446'
    assert report['idChange']['changed'] is True
    assert snapshot(source) == before


@pytest.mark.parametrize('native_metadata', ['mod.json', '_metadata/modinfo.json'])
def test_native_package_with_saved_data_is_not_reclassified_as_legacy(tmp_path, native_metadata):
    source = legacy_package(tmp_path, authored_id='native_save')
    native = source/native_metadata
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text(json.dumps({'name':'Native package', 'modId':'native_save', 'revision':1}))
    before = snapshot(source)
    assert not prepare_mod(source).blockers
    assert scan_mods(source)['items'][0].mod_id == 'native_save'
    output = tmp_path/'native_output'
    convert_mod(source, output)
    assert (output/'maps/Scandinavia in 1971.sav').read_bytes() == (source/'maps/Scandinavia in 1971.sav').read_bytes()
    assert snapshot(source) == before


def test_valid_legacy_id_and_invalid_native_id_remain_authoritative(tmp_path):
    legacy = legacy_package(tmp_path/'legacy', authored_id='legacy_map')
    assert scan_mods(legacy)['items'][0].mod_id == 'legacy_map'
    native = legacy_package(tmp_path/'native', save=False)
    (native/'mod.json').write_text('{"modId":"invalid-native-id","name":"Native"}')
    item = scan_mods(native)['items'][0]
    assert item.mod_id == 'invalid-native-id'
    result = convert_queue([item], tmp_path/'output')
    assert result['counts']['failed'] == 1 and 'Invalid mod ID' in result['items'][0]['message']

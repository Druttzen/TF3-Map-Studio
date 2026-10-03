import json
import os
import threading
from pathlib import Path
import subprocess
import sys

import pytest

from trf3_mod_converter import batch
from trf3_mod_converter.batch import scan_mods, convert_queue, output_lock, STATE_NAME
from trf3_mod_converter.tf2_vehicle_port import snapshot
from test_tf2_vehicle_port import fixture_mod


def mod(root, folder, name, *, callback=False, mod_id=None):
    source = root / folder
    source.mkdir(parents=True)
    info = {'name': name, 'authors': ['Creator']}
    if mod_id:
        info['modId'] = mod_id
    (source / 'mod.json').write_text(json.dumps(info), encoding='utf-8')
    if callback:
        (source / 'mod.json').unlink()
        (source / 'mod.lua').write_text('return {info={name="Blocked"},runFn=function() error("never execute") end}')
    return source


def test_scan_nested_collection_uses_display_names_and_package_boundaries(tmp_path):
    root = tmp_path / 'collection'
    first = mod(root, 'group/first', 'Readable Name')
    mod(first, 'res/scripts/helper', 'Internal Library')
    second = mod(root, 'second', 'mod_name')
    (second / 'strings.lua').write_text('function data() return {en={mod_name="Translated Name"}} end')
    exported = mod(root, 'exports/converted', 'Excluded')
    found = scan_mods(root, exclude=exported.parent)
    assert [i.display_name for i in found['items']] == ['Readable Name', 'Translated Name']
    assert len({i.mod_id for i in found['items']}) == 2
    assert [i.source for i in found['items']] == [str(first), str(second)]
    assert scan_mods(first)['items'][0].display_name == 'Readable Name'


def test_workshop_ids_are_stable_and_duplicate_names_do_not_collide(tmp_path):
    root = tmp_path / '1066780'
    mod(root, '123', 'Same Name'); mod(root, '456', 'Same Name')
    assert [i.mod_id for i in scan_mods(root)['items']] == ['tf2_workshop_123', 'tf2_workshop_456']


def test_literal_display_name_survives_local_description_constants(tmp_path):
    source = mod(tmp_path, 'source', 'MOD_NAME')
    (source / 'strings.lua').write_text('function data() local lb="\\n" return {en={MOD_NAME="Readable Name",description="a"..lb.."b",lb.."extra"}} end')
    assert scan_mods(source)['items'][0].display_name == 'Readable Name'


def test_translation_with_side_effects_or_computed_keys_is_not_executed_or_inferred(tmp_path):
    source = mod(tmp_path, 'source', 'MOD_NAME')
    (source / 'strings.lua').write_text('function data() local helper=executeMod() return {en={MOD_NAME="Unproved"}} end')
    assert scan_mods(source)['items'][0].display_name == 'MOD_NAME'
    (source / 'strings.lua').write_text('function data() local sep="x" return {en={MOD_NAME="Unproved",[executeMod()]="replaced"}} end')
    assert scan_mods(source)['items'][0].display_name == 'MOD_NAME'


def test_unreadable_metadata_is_listed_without_execution(tmp_path):
    root = tmp_path / 'collection'; path = root / 'dynamic'; path.mkdir(parents=True)
    (path / 'mod.lua').write_text('error("never execute") function data() return {} end')
    item = scan_mods(root)['items'][0]
    assert item.display_name == 'dynamic' and item.scan_error
    state = convert_queue([item], tmp_path / 'out')
    assert state['counts']['failed'] == 1 and not (tmp_path / 'out' / item.mod_id).exists()


def test_queue_continues_after_failed_mod_and_persists_before_success_event(tmp_path):
    root = tmp_path / 'collection'
    first = mod(root, 'a', 'First'); bad = mod(root, 'b', 'Blocked', callback=True); last = mod(root, 'c', 'Last')
    before = {str(p): snapshot(p) for p in (first, bad, last)}
    items = scan_mods(root)['items']; output = tmp_path / 'out'; order = []
    def event(kind, value):
        if kind == 'item' and value['status'] != 'running':
            saved = json.loads((output / STATE_NAME).read_text())
            row = next(i for i in saved['items'] if os.path.normcase(i['source']) == value['key'])
            assert row['status'] == value['status']
            order.append(value['status'])
    state = convert_queue(items, output, event=event)
    assert order == ['completed', 'failed', 'completed']
    assert state['counts'] == {'completed': 2, 'failed': 1, 'pending': 0}
    assert all(snapshot(p) == before[str(p)] for p in (first, bad, last))
    assert not (output / items[1].mod_id).exists()


def test_resume_verifies_original_and_output_instead_of_overwriting(tmp_path):
    root = tmp_path / 'collection'; mod(root, 'one', 'One'); mod(root, 'two', 'Two')
    items = scan_mods(root)['items']; output = tmp_path / 'out'
    assert convert_queue(items, output)['counts']['completed'] == 2
    original = snapshot(output / items[0].mod_id)
    assert convert_queue(scan_mods(root)['items'], output)['counts']['completed'] == 2
    assert snapshot(output / items[0].mod_id) == original
    (output / items[0].mod_id / 'extra.txt').write_text('external change')
    state = convert_queue(scan_mods(root)['items'], output)
    assert state['counts']['failed'] == 1 and state['counts']['completed'] == 1
    assert (output / items[0].mod_id / 'extra.txt').read_text() == 'external change'


def test_existing_unowned_output_is_preserved(tmp_path):
    source = mod(tmp_path, 'source', 'One'); items = scan_mods(source)['items']
    target = tmp_path / 'out' / items[0].mod_id; target.mkdir(parents=True)
    (target / 'keep.txt').write_text('existing data')
    assert convert_queue(items, target.parent)['counts']['failed'] == 1
    assert (target / 'keep.txt').read_text() == 'existing data'


def test_metadata_change_and_explicit_id_collision_are_blocked(tmp_path):
    root = tmp_path / 'collection'; source = mod(root, 'a', 'One', mod_id='shared'); mod(root, 'b', 'Two', mod_id='shared')
    items = scan_mods(root)['items']
    assert convert_queue(items, tmp_path / 'out')['counts']['failed'] == 2
    (source / 'mod.json').write_text('{"name":"Changed"}')
    assert convert_queue([items[0]], tmp_path / 'other')['counts']['failed'] == 1
    assert 'Metadata changed' in items[0].message


def test_stop_finishes_current_mod_then_resume(tmp_path):
    root = tmp_path / 'collection'; mod(root, 'a', 'One'); mod(root, 'b', 'Two')
    stop = threading.Event(); items = scan_mods(root)['items']; output = tmp_path / 'out'
    def event(kind, value):
        if kind == 'item' and value['status'] == 'completed': stop.set()
    state = convert_queue(items, output, stop=stop, event=event)
    assert state['cancelled'] and state['counts'] == {'completed': 1, 'failed': 0, 'pending': 1}
    assert convert_queue(scan_mods(root)['items'], output)['counts']['completed'] == 2


def test_output_inside_source_and_concurrent_queue_are_rejected(tmp_path):
    source = mod(tmp_path, 'source', 'One'); items = scan_mods(source)['items']
    with pytest.raises(ValueError, match='export folder'):
        convert_queue(items, '')
    with pytest.raises(ValueError, match='separate'):
        convert_queue(items, source / 'export')
    output = tmp_path / 'out'; output.mkdir()
    with output_lock(output):
        with pytest.raises(ValueError, match='Another conversion'):
            convert_queue(items, output)
    assert convert_queue(items, output)['counts']['completed'] == 1


def test_unrecognized_batch_report_is_preserved(tmp_path):
    source = mod(tmp_path, 'source', 'One'); items = scan_mods(source)['items']
    output = tmp_path / 'out'; output.mkdir()
    (output / STATE_NAME).write_text('[]')
    with pytest.raises(ValueError, match='not recognized'):
        convert_queue(items, output)
    assert (output / STATE_NAME).read_text() == '[]'
    assert not (output / items[0].mod_id).exists()


def test_tf2_content_uses_real_exporter_and_unsupported_content_is_not_metadata_success(fixture_mod):
    source, game, output = fixture_mod
    item = scan_mods(source)['items'][0]
    assert convert_queue([item], output, tf3_game=game)['counts']['completed'] == 1
    report = json.loads((output / item.mod_id / 'conversion-report.json').read_text())
    assert report['portProfile'] == 'tf2_electric_locomotive' and report['nativeTest'] == 'not_run'
    (source / 'res/custom.lua').write_text('error("never execute")')
    failed = convert_queue(scan_mods(source)['items'], output.parent / 'other', tf3_game=game)
    assert failed['counts']['failed'] == 1
    assert 'manual port' in failed['items'][0]['message']


def test_shared_native_inventory_is_built_once_and_references_are_independent(fixture_mod, monkeypatch):
    import shutil
    source, game, output = fixture_mod
    second = source.with_name('second'); shutil.copytree(source, second)
    items = [*scan_mods(source)['items'], *scan_mods(second)['items']]
    calls = []
    real = batch.NativeInventory
    def inventory(path):
        calls.append(path); return real(path)
    monkeypatch.setattr(batch, 'NativeInventory', inventory)
    state = convert_queue(items, output, tf3_game=game)
    assert state['counts']['completed'] == 2 and len(calls) == 1
    native = real(game)
    first, second = native.fork(), native.fork()
    first.reference('vehicle/train/shared/sound/train_electric_old.snd')
    assert not second.references and not native.references


def test_cli_scan_and_batch_share_queue_behavior(tmp_path, capsys):
    from trf3_mod_converter.cli import main
    root = tmp_path / 'collection'; mod(root, 'a', 'CLI One')
    assert main(['scan', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)['items'][0]['display_name'] == 'CLI One'
    assert main(['batch', str(root), str(tmp_path / 'out')]) == 0
    assert json.loads(capsys.readouterr().out)['counts']['completed'] == 1


def test_empty_source_and_cancelled_scan_do_not_traverse(tmp_path):
    with pytest.raises(ValueError): scan_mods('')
    stop = threading.Event(); stop.set()
    assert scan_mods(tmp_path, stop=stop)['cancelled']
    assert not scan_mods(tmp_path, stop=stop)['items']


def test_receipt_save_failure_does_not_emit_green_completion(tmp_path, monkeypatch):
    root = mod(tmp_path, 'source', 'One'); items = scan_mods(root)['items']; events = []
    save = batch._save_state; calls = 0
    def failure(output, state):
        nonlocal calls
        calls += 1
        if calls == 2: raise OSError('disk full')
        save(output, state)
    monkeypatch.setattr(batch, '_save_state', failure)
    with pytest.raises(OSError, match='disk full'):
        convert_queue(items, tmp_path / 'out', event=lambda kind, value: events.append((kind, value)))
    assert not any(kind == 'item' and value['status'] == 'completed' for kind, value in events)


def test_hard_process_exit_releases_lock_and_resumes_only_remaining_mods(tmp_path):
    root = tmp_path / 'collection'; mod(root, 'a', 'First'); mod(root, 'b', 'Second')
    output = tmp_path / 'out'
    code = '''import os,sys
sys.path.insert(0,sys.argv[1])
from trf3_mod_converter.batch import scan_mods,convert_queue
def event(kind,value):
    if kind == "item" and value["status"] == "completed": os._exit(0)
convert_queue(scan_mods(sys.argv[2])["items"],sys.argv[3],event=event)
'''
    subprocess.run([sys.executable, '-c', code, str(Path(__file__).resolve().parents[1] / 'src'),
                    str(root), str(output)], check=True, timeout=20,
                   creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    saved = json.loads((output / STATE_NAME).read_text())
    assert len(saved['receipts']) == 1
    state = convert_queue(scan_mods(root)['items'], output)
    assert state['counts']['completed'] == 2
    assert state['items'][0]['message'] == 'Previous export verified'

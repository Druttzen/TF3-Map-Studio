import json
import threading
import time
import tkinter as tk

import pytest

from trf3_mod_converter.gui import ConverterApp
from test_batch import mod


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f'Desktop display unavailable: {error}')
    root.withdraw()
    instance = ConverterApp(root)
    errors = []
    root.report_callback_exception = lambda *details: errors.append(details)
    yield instance
    assert not errors
    root.after_cancel(instance.poll_id)
    root.destroy()


def wait_for_work(app):
    deadline = time.monotonic() + 20
    while app.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(.01)
    app.root.update()
    assert not app.busy


def test_folder_selection_scans_names_and_minus_removes_only_queue_entry(app, tmp_path):
    root = tmp_path/'collection'
    first = mod(root, 'a', 'First')
    mod(root, 'b', 'Second')
    app._set_source(str(root))
    wait_for_work(app)
    assert [i.display_name for i in app.items] == ['First', 'Second']
    row = app.rows[app.items[0].key]
    assert row['minus']['text'] == '−'
    row['minus'].invoke()
    assert [i.display_name for i in app.items] == ['Second']
    assert (first/'mod.json').exists()


def test_convert_all_marks_success_green_and_checks_only_successes(app, tmp_path):
    root = tmp_path/'collection'
    mod(root, 'a', 'First')
    mod(root, 'b', 'Blocked', callback=True)
    mod(root, 'c', 'Last')
    app._set_source(str(root)); wait_for_work(app)
    app.variables['destination'].set(str(tmp_path/'out'))
    assert app.convert_button['text'] == 'Convert all listed mods'
    app.convert_all(); wait_for_work(app)
    assert [i.status for i in app.items] == ['completed', 'failed', 'completed']
    assert app.report['counts']['completed'] == 2
    for item in app.items:
        label = app.rows[item.key]['name']
        assert label['text'].endswith(' ✓') == (item.status == 'completed')
        assert label['fg'] == ('#16803a' if item.status == 'completed' else '#b53636')
    assert 'inline Lua callback' in app.details.get('1.0', 'end')
    assert str(app.stop_button['state']) == 'disabled'


def test_new_source_clears_queue_and_unneeded_controls_are_removed(app, tmp_path):
    root = mod(tmp_path, 'source', 'One')
    app._set_source(str(root)); wait_for_work(app)
    app.variables['source'].set(str(tmp_path/'different'))
    assert not app.items and str(app.convert_button['state']) == 'disabled'
    assert not hasattr(app, 'inspect_button')
    assert not hasattr(app, 'port_button')
    assert not hasattr(app, 'open_button')
    assert set(app.variables) == {'source', 'destination', 'tf3_game'}


def test_scan_error_is_correctable_and_output_change_removes_old_checks(app, tmp_path):
    app.variables['source'].set(str(tmp_path/'missing'))
    app.scan(); wait_for_work(app)
    assert app.status.get() == 'Could not continue'
    source = mod(tmp_path, 'source', 'One')
    app._set_source(str(source)); wait_for_work(app)
    app.variables['destination'].set(str(tmp_path/'out'))
    app.convert_all(); wait_for_work(app)
    item = app.items[0]
    assert app.rows[item.key]['name']['text'].endswith(' ✓')
    app.variables['destination'].set(str(tmp_path/'another'))
    assert item.status == 'pending'
    assert not app.rows[item.key]['name']['text'].endswith(' ✓')


def test_stop_disables_removal_and_allows_clean_queue_resume(app, tmp_path, monkeypatch):
    from trf3_mod_converter import gui
    root = mod(tmp_path, 'source', 'One')
    app._set_source(str(root)); wait_for_work(app)
    app.variables['destination'].set(str(tmp_path/'out'))
    entered = threading.Event()
    actual = gui.convert_queue
    def delayed(items, destination, **kwargs):
        entered.set()
        kwargs['stop'].wait(5)
        return actual(items, destination, **kwargs)
    monkeypatch.setattr(gui, 'convert_queue', delayed)
    app.convert_all()
    assert entered.wait(2)
    item = app.items[0]
    assert str(app.rows[item.key]['minus']['state']) == 'disabled'
    app.remove_item(item.key)
    assert len(app.items) == 1
    app.stop(); wait_for_work(app)
    assert app.report['cancelled'] and app.items[0].status == 'pending'
    assert str(app.convert_button['state']) == 'normal'


def test_same_queue_resume_verifies_exports_and_keeps_names(app, tmp_path):
    source = mod(tmp_path, 'source', 'Readable Name')
    app._set_source(str(source)); wait_for_work(app)
    app.variables['destination'].set(str(tmp_path/'out'))
    app.convert_all(); wait_for_work(app)
    item = app.items[0]
    first = json.loads((tmp_path/'out'/item.mod_id/'conversion-report.json').read_text())
    app.convert_all(); wait_for_work(app)
    assert item.message == 'Previous export verified'
    assert app.rows[item.key]['name']['text'] == 'Readable Name ✓'
    assert json.loads((tmp_path/'out'/item.mod_id/'conversion-report.json').read_text()) == first

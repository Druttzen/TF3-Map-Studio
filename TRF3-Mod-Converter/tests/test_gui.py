import json
import time
import tkinter as tk

import pytest

from trf3_mod_converter.gui import ConverterApp


@pytest.fixture
def app():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Desktop display unavailable: {error}")
    root.withdraw()
    instance = ConverterApp(root)
    errors = []
    root.report_callback_exception = lambda *details: errors.append(details)
    yield instance
    assert not errors
    root.destroy()


def wait_for_work(app):
    deadline = time.monotonic() + 5
    while app.busy and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.01)
    app.root.update()
    assert not app.busy


def test_desktop_preview_and_conversion(app, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    original = '{"name":"Desktop Test","revision":2,"authors":["Creator"]}'
    (source / "mod.json").write_text(original)
    (source / "README.txt").write_text("asset")
    app._set_source(str(source))
    app.inspect()
    wait_for_work(app)
    assert app.status.get() == "Ready to convert metadata"
    assert str(app.convert_button["state"]) == "normal"
    assert not (tmp_path / "source_converted").exists()
    app.convert()
    wait_for_work(app)
    assert app.status.get() == "Conversion complete"
    assert app.report["filesCopied"] == 2
    assert (source / "mod.json").read_text() == original
    output = tmp_path / "source_converted"
    assert json.loads((output / "mod.json").read_text())["revision"] == 2


def test_edit_requires_fresh_preview(app, tmp_path):
    path = tmp_path / "source"
    path.mkdir()
    (path / "mod.json").write_text('{"name":"Before"}')
    app._set_source(str(path))
    app.inspect()
    wait_for_work(app)
    app.variables["name"].set("After")
    assert app.preview is None
    assert str(app.convert_button["state"]) == "disabled"
    app.inspect()
    wait_for_work(app)
    assert app.preview.name == "After"


def test_unsupported_callback_shown_and_convert_disabled(app, tmp_path):
    path = tmp_path / "mod.lua"
    path.write_text('return {info={name="Callbacks"},runFn=function() print("run") end}')
    app._set_source(str(path))
    app.inspect()
    wait_for_work(app)
    assert app.status.get() == "Manual changes required"
    assert "inline Lua callback" in app.details.get("1.0", "end")
    assert str(app.convert_button["state"]) == "disabled"


def test_desktop_error_can_be_corrected(app, tmp_path):
    app.variables["source"].set(str(tmp_path / "missing"))
    app.inspect()
    wait_for_work(app)
    assert app.status.get() == "Could not continue"
    assert "Source does not exist" in app.details.get("1.0", "end")
    path = tmp_path / "source"
    path.mkdir()
    (path / "mod.json").write_text('{"name":"Corrected"}')
    app._set_source(str(path))
    app.variables["revision"].set("invalid")
    app.inspect()
    assert app.status.get() == "Could not continue"
    app.variables["revision"].set("4")
    app.inspect()
    wait_for_work(app)
    assert app.preview.revision == 4


def test_metadata_selection_default_output_is_outside_source_mod(app, tmp_path):
    source = tmp_path / 'source'
    metadata = source / '_metadata/modinfo.json'
    metadata.parent.mkdir(parents=True)
    metadata.write_text('{"name":"Browser"}')
    (source / 'mod.json').write_text('{"modId":"existing","revision":8}')
    app._set_source(str(metadata))
    assert app.variables['destination'].get() == str(tmp_path / 'source_converted')
    app.inspect()
    wait_for_work(app)
    assert app.preview.target_mod_id == 'existing'
    assert app.preview.revision == 8
    assert 'RESOURCE CHECKS' in app.details.get('1.0', 'end')


def test_desktop_port_uses_explicit_choices_and_metadata_overrides(app,tmp_path,monkeypatch):
    from trf3_mod_converter import gui,tf2_vehicle_port
    source=tmp_path/'source'; source.mkdir()
    (source/'mod.lua').write_text('function data() return {info={name="Original"}} end')
    app._set_source(str(source))
    app.variables['name'].set('Draft')
    app.variables['mod_id'].set('draft_test')
    app.variables['author'].set('Override')
    app.variables['revision'].set('4')
    monkeypatch.setattr(gui.filedialog,'askdirectory',lambda **kwargs:str(tmp_path/'game'))
    monkeypatch.setattr(gui.filedialog,'askopenfilename',lambda **kwargs:'')
    observed={}
    def port(source,destination,**kwargs):
        observed.update(kwargs)
        return {'destination':destination,'nativeTest':'not_run'}
    monkeypatch.setattr(tf2_vehicle_port,'port_tf2_mod',port)
    app.port_tf2(); wait_for_work(app)
    assert observed['mod_id']=='draft_test' and observed['repairs'] is None
    assert observed['author']=='Override' and observed['revision']==4
    assert app.report['nativeTest']=='not_run'

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
    path.write_text('return {info={name="Callbacks"},runFn=function() end}')
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

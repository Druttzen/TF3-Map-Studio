import json
from pathlib import Path

import pytest

from trf3_mod_converter import convert_mod, inspect_mod, prepare_mod
from trf3_mod_converter import converter
from trf3_mod_converter.cli import main


def json_mod(root, payload=None):
    root.mkdir(parents=True, exist_ok=True)
    path = root / "mod.json"
    path.write_text(json.dumps(payload or {"name": "Example", "revision": 3}), encoding="utf-8")
    return path


@pytest.mark.parametrize("filename", ["mod.json", "_metadata/modinfo.json"])
def test_source_file_cannot_be_overwritten(tmp_path, filename):
    root = tmp_path / "source"
    path = root / filename
    path.parent.mkdir(parents=True)
    original = '{"name":"Original","version":7,"customField":"keep me"}'
    path.write_text(original)
    with pytest.raises(ValueError, match="source"):
        convert_mod(path, root, overwrite=True)
    assert path.read_text() == original
    assert not (root / "conversion-report.json").exists()


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_source_ancestors_cannot_be_output(tmp_path, kind):
    source = tmp_path / "source"
    path = json_mod(source)
    with pytest.raises(ValueError, match="source"):
        convert_mod(source if kind == "directory" else path, tmp_path, overwrite=True)
    assert json.loads(path.read_text())["name"] == "Example"


def test_invalid_output_folder_name_has_no_side_effects(tmp_path):
    source = tmp_path / "source"
    json_mod(source)
    output = tmp_path / "bad-name"
    with pytest.raises(ValueError, match="folder name"):
        convert_mod(source, output)
    assert not output.exists()


def test_missing_or_invalid_metadata_has_no_output_side_effect(tmp_path):
    source = tmp_path / "source"
    path = json_mod(source)
    path.write_text("{broken")
    output = tmp_path / "new-parent" / "output"
    with pytest.raises(ValueError, match="Invalid JSON"):
        convert_mod(source, output)
    assert not output.parent.exists()


def test_inline_callback_is_inspectable_but_blocks_conversion(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mod.lua").write_text('function data() return {info={name="Callbacks"},runFn=function(settings, modParams) print("run") end} end')
    preview = prepare_mod(source)
    assert preview.name == "Callbacks"
    assert preview.run_script is None
    assert any("inline Lua callback" in error for error in preview.blockers)
    with pytest.raises(ValueError, match="manual"):
        convert_mod(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_numeric_metadata_keys_are_archived_and_block_instead_of_crashing(tmp_path):
    path=tmp_path/'mod.lua'
    original='function data() return {info={name="Mixed keys", dependencies={123}, [1]={456}, ["1"]="distinct string key"}} end'
    path.write_text(original)
    descriptor=inspect_mod(path)
    assert descriptor.name=='Mixed keys'
    assert any('non-text keys' in b for b in descriptor.blockers)
    entries=descriptor.source_metadata['mod.lua']['luaTableEntries']
    assert any(e=={'keyType':'number','key':1,'value':[456]} for e in entries)
    assert any(e=={'keyType':'string','key':'1','value':'distinct string key'} for e in entries)
    with pytest.raises(ValueError,match='non-text keys'):
        convert_mod(path,tmp_path/'output')
    assert path.read_text()==original and not (tmp_path/'output').exists()


def test_workshop_container_is_rejected_without_merging_child_mods(tmp_path):
    source=tmp_path/'workshop'
    originals={}
    for folder in ('123','456'):
        path=source/folder/'mod.lua';path.parent.mkdir(parents=True)
        originals[path]='return {info={name="Mod '+folder+'"}}'
        path.write_text(originals[path])
    with pytest.raises(ValueError,match='Batch conversion is not available'):
        convert_mod(source,tmp_path/'output')
    assert not (tmp_path/'output').exists()
    assert all(path.read_text()==original for path,original in originals.items())


@pytest.mark.parametrize("expression,expected", [
    ('[[\nFirst line\nSecond line]]', "First line\nSecond line"),
    ('[=[First ]] line\nSecond line]=]', "First ]] line\nSecond line"),
    (r'"First\nSecond\t\"quoted\"\\path"', 'First\nSecond\t"quoted"\\path'),
    (r'"\x41\065\u{1f600}\z   B"', "AA😀B"),
    ('"Ångström"', "Ångström"),
    ('"First " .. "second"', "First second"),
])
def test_lua_strings_round_trip(tmp_path, expression, expected):
    path = tmp_path / "mod.lua"
    path.write_text('return {info={name="Strings",description=' + expression + '}}', encoding="utf-8")
    assert inspect_mod(path).description == expected


def test_lua_block_comments_and_semicolon_fields(tmp_path):
    path = tmp_path / "mod.lua"
    path.write_text('--[=[\nreturn {info={name="Wrong"}}\n]=]\nreturn {info={name="Correct";minorVersion=4;tags={"Train";"Asset"}}}')
    metadata = inspect_mod(path)
    assert (metadata.name, metadata.revision, metadata.tags) == ("Correct", 4, ["Train", "Asset"])


def test_nested_helper_return_is_not_metadata(tmp_path):
    path = tmp_path / "mod.lua"
    path.write_text('function helper() return {name="Wrong"} end\nfunction data() return {info={name="Correct"}} end')
    assert inspect_mod(path).name == "Correct"


@pytest.mark.parametrize("text", [
    'function data() if true then return {name="Branch"} end end',
    'function data() local name="Computed" return {name=name} end',
    'return {name=buildName()}',
])
def test_dynamic_metadata_is_rejected_or_blocked(tmp_path, text):
    path = tmp_path / "mod.lua"
    path.write_text(text)
    try:
        preview = prepare_mod(path)
    except ValueError:
        return
    assert preview.blockers


def test_mod_code_is_never_executed(tmp_path):
    path = tmp_path / "mod.lua"
    marker = tmp_path / "executed"
    path.write_text('os.execute("echo unsafe")\nreturn {name="Executable"}')
    with pytest.raises(ValueError, match="top-level"):
        inspect_mod(path)
    assert not marker.exists()


def test_mixed_json_and_lua_metadata_merges_aliases(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "mod.lua").write_text('return {info={name="Lua Name",minorVersion=5,authors={{name="Creator",tfnetId=12,url="https://example.com"}}},runFn="scripts/main.lua"}')
    (source / "modinfo.json").write_text('{"displayName":"JSON Name"}')
    metadata = inspect_mod(source)
    assert metadata.name == "JSON Name"
    assert metadata.revision == 5
    assert metadata.authors[0]["tfnetId"] == 12
    assert metadata.run_script == "scripts/main.lua"


def test_canonical_empty_values_clear_legacy_fields(tmp_path):
    source = tmp_path / "source"
    json_mod(source, {"name": "Canonical", "tags": [], "runScript": None})
    (source / "mod.lua").write_text('return {info={name="Old",tags={"Train"}},runFn=function() end}')
    preview = prepare_mod(source)
    assert preview.tags == []
    assert preview.run_script is None
    assert not preview.blockers


def test_direct_metadata_file_copies_sibling_assets(tmp_path):
    source = tmp_path / "source"
    path = json_mod(source)
    assets = source / "res" / "textures"
    assets.mkdir(parents=True)
    (assets / "sample.dds").write_bytes(b"asset")
    report = convert_mod(path, tmp_path / "output")
    output = Path(report["destination"])
    assert (output / "content" / "textures" / "sample.dds").read_bytes() == b"asset"
    assert not (output / "res").exists()
    assert (assets / "sample.dds").read_bytes() == b"asset"
    assert json.loads((output / "conversion-report.json").read_text()) == report


def test_replacement_keeps_backup_and_removes_stale_assets(tmp_path):
    source = tmp_path / "source"
    json_mod(source)
    output = tmp_path / "output"
    output.mkdir()
    (output / "stale.txt").write_text("existing")
    with pytest.raises(FileExistsError):
        convert_mod(source, output)
    assert (output / "stale.txt").read_text() == "existing"
    report = convert_mod(source, output, overwrite=True)
    assert (Path(report["backup"]) / "stale.txt").read_text() == "existing"
    assert not (output / "stale.txt").exists()


def test_nested_repeated_outputs_do_not_copy_stages_or_backups(tmp_path):
    source = tmp_path / "source"
    json_mod(source)
    output = source / "exports" / "converted"
    for _ in range(3):
        convert_mod(source, output, overwrite=True)
    assert not (output / "exports" / "converted").exists()
    assert not list(output.rglob(".trf3-stage-*"))
    assert not list(output.rglob("converted.backup-*"))


def test_copy_failure_preserves_existing_output(tmp_path, monkeypatch):
    source = tmp_path / "source"
    json_mod(source)
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep").write_text("unchanged")
    def fail(*args, **kwargs):
        raise OSError("simulated copy failure")
    monkeypatch.setattr(converter.shutil, "copy2", fail)
    with pytest.raises(OSError, match="simulated"):
        convert_mod(source, output, overwrite=True)
    assert (output / "keep").read_text() == "unchanged"
    assert not list(tmp_path.glob(".trf3-stage-*"))
    assert not list(tmp_path.glob("output.backup-*"))


def test_publish_failure_restores_backup(tmp_path, monkeypatch):
    source = tmp_path / "source"
    json_mod(source)
    output = tmp_path / "output"
    output.mkdir()
    (output / "keep").write_text("unchanged")
    rename = Path.rename
    def fail_stage(self, target):
        if self.parent.name.startswith(".trf3-stage-"):
            raise OSError("simulated publish failure")
        return rename(self, target)
    monkeypatch.setattr(Path, "rename", fail_stage)
    with pytest.raises(OSError, match="publish failure"):
        convert_mod(source, output, overwrite=True)
    assert (output / "keep").read_text() == "unchanged"
    assert not list(tmp_path.glob("output.backup-*"))


@pytest.mark.parametrize("payload,error", [
    ({"name": "x", "revision": "1.2.3"}, "revision"),
    ({"name": "x", "revision": True}, "revision"),
    ({"name": "x", "revision": -1}, "revision"),
    ({"name": "x", "modId": "Invalid-ID"}, "modId"),
    ({"name": "x" * 33}, "name"),
    ({"name": "x", "summary": "x" * 101}, "Summary"),
    ({"name": "x", "severityAdd": "unknown"}, "severityAdd"),
    ({"name": "x", "dependencies": ["legacy"]}, "dependencies"),
    ({"name": "x", "visible": "yes"}, "visible"),
])
def test_invalid_metadata_blocked_before_writing(tmp_path, payload, error):
    source = tmp_path / "source"
    json_mod(source, payload)
    preview = prepare_mod(source)
    assert any(error.lower() in issue.lower() for issue in preview.blockers)
    with pytest.raises(ValueError):
        convert_mod(source, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_overrides_repair_invalid_basic_metadata(tmp_path):
    source = tmp_path / "source"
    json_mod(source, {"name": "x" * 33, "modId": "Bad-Id", "revision": "v1", "summary": "x" * 101})
    preview = prepare_mod(source, name="Good", mod_id="good", revision=2, summary="Short")
    assert not preview.blockers
    assert preview.revision == 2


def test_native_script_reference_and_localization_preserved(tmp_path):
    source = tmp_path / "source"
    json_mod(source, {"name": "Native", "modId": "native", "runScript": {"fileName": "native::mod.script@runFn"}, "cosmetic": True})
    content = source / "content"
    content.mkdir()
    (content / "mod.script.lua").write_text("local function runFn(config, params) end\nfunction data() return {runFn=runFn} end")
    (source / "_metadata").mkdir()
    (source / "_metadata" / "modinfo.json").write_text('{"localization":{"en":{"name":"Native"}},"dependencies":["12345"]}')
    preview = prepare_mod(source, mod_id="renamed")
    assert preview.run_script == "renamed::mod.script@runFn"
    assert not preview.blockers
    convert_mod(source, tmp_path / "output", mod_id="renamed")
    info = json.loads((tmp_path / "output" / "_metadata" / "modinfo.json").read_text())
    assert info["localization"]["en"]["name"] == "Native"
    assert info["dependencies"] == ["12345"]


def test_missing_and_legacy_script_references_blocked(tmp_path):
    source = tmp_path / "source"
    for reference in ("scripts/main.lua", "example::missing.script@runFn", "example::../outside@runFn"):
        json_mod(source, {"name": "Example", "modId": "example", "runScript": {"fileName": reference}})
        assert prepare_mod(source).blockers


def test_json_bom_and_object_validation(tmp_path):
    path = tmp_path / "info.json"
    path.write_text('{"name":"BOM"}', encoding="utf-8-sig")
    assert inspect_mod(path).name == "BOM"
    path.write_text("[]")
    with pytest.raises(ValueError, match="object"):
        inspect_mod(path)


def test_cli_errors_are_concise_and_inspection_has_exit_status(tmp_path, capsys):
    assert main(["convert", str(tmp_path / "missing"), str(tmp_path / "out")]) == 2
    captured = capsys.readouterr()
    assert "Error:" in captured.err and "Traceback" not in captured.err
    source = tmp_path / "source"
    json_mod(source, {"name": "Invalid", "modId": "Bad"})
    assert main(["inspect", str(source)]) == 2
    assert json.loads(capsys.readouterr().out)["canConvert"] is False
    assert main(["convert", str(source), str(tmp_path / "out"), "--mod-id", "valid"]) == 0
    assert json.loads(capsys.readouterr().out)["modId"] == "valid"

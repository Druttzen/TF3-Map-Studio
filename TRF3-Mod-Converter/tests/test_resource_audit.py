import json
from pathlib import Path

import pytest

from trf3_mod_converter import convert_mod, prepare_mod
from trf3_mod_converter import converter


def fixture(root, *, callback='function data() return {runFn=function(captureParams) end} end', extra=None):
    (root / 'content').mkdir(parents=True)
    (root / '_metadata').mkdir()
    config = {'fileName': 'original::/mod.script@runFn', 'params': {'mode': 'careful', 'nested': [1, False]}, 'futureField': 7}
    technical = {'modId': 'original', 'revision': 9, 'runScript': config, 'postRunScript': {'fileName': '', 'params': {}},
                 'dependencies': [{'mod': {'modId': 'dependency', 'revision': 2}}], 'customTechnical': {'kept': True}, **(extra or {})}
    browser = {'name': 'Original', 'authors': [{'name': 'Creator', 'role': 'CREATOR', 'url': 'https://example.com'}], 'description': '', 'tags': [], 'url': '',
               'summary': 'Summary', 'localization': {'sv': {'name': 'Ursprung', 'description': 'Text'}},
               'dependencies': ['42'], 'customBrowser': {'kept': True}}
    (root / 'mod.json').write_text(json.dumps(technical), encoding='utf-8')
    (root / '_metadata/modinfo.json').write_text(json.dumps(browser), encoding='utf-8')
    (root / 'content/mod.script.lua').write_text(callback, encoding='utf-8')
    return technical, browser


@pytest.mark.parametrize('selection', ['mod.json', '_metadata/modinfo.json', ''])
def test_metadata_selection_preserves_complete_context(tmp_path, selection):
    source = tmp_path / 'source'
    technical, browser = fixture(source)
    destination = tmp_path / 'output'
    report = convert_mod(source / selection, destination)
    exported = json.loads((destination / 'mod.json').read_text())
    for key, value in technical.items():
        assert exported[key] == value
    assert json.loads((destination / '_metadata/modinfo.json').read_text()) == browser
    assert report['sourceMetadata']['mod.json'] == technical
    assert report['sourceMetadata']['_metadata/modinfo.json'] == browser
    assert report['resourceAudit']['nativeTest'] == 'not_run'
    assert prepare_mod(destination).as_mod_json() == exported


def test_rename_rejected_when_internal_namespace_would_break(tmp_path):
    source = tmp_path / 'source'
    fixture(source, callback='local helper=ug_require "original::/helper"\nfunction data() return {runFn=function() helper.run() end} end')
    (source / 'content/helper.lua').write_text('return {run=function() end}')
    before = (source / 'content/mod.script.lua').read_bytes()
    assert not prepare_mod(source).blockers
    preview = prepare_mod(source, mod_id='new_id')
    assert any('still references original::' in b for b in preview.blockers)
    with pytest.raises(ValueError, match='Cannot change modId'):
        convert_mod(source, tmp_path / 'output', mod_id='new_id')
    assert not (tmp_path / 'output').exists()
    assert (source / 'content/mod.script.lua').read_bytes() == before


def test_safe_metadata_only_id_change_keeps_script_params(tmp_path):
    source = tmp_path / 'source'
    technical, _ = fixture(source)
    descriptor = prepare_mod(source, mod_id='new_id')
    assert not descriptor.blockers
    assert descriptor.as_mod_json()['runScript']['params'] == technical['runScript']['params']
    assert descriptor.as_mod_json()['runScript']['fileName'] == 'new_id::/mod.script@runFn'


@pytest.mark.parametrize('extra', [
    {'customReference': 'original::/asset.mdl'},
    {'runScript': {'fileName': 'original::/mod.script@runFn', 'params': {'resource': 'original::/asset.mdl'}}},
    {'dependencies': [{'mod': {'modId': 'original'}}]},
])
def test_id_change_checks_retained_configuration(tmp_path, extra):
    source = tmp_path / 'source'
    fixture(source, extra=extra)
    assert any('Cannot change modId' in issue for issue in prepare_mod(source, mod_id='new_id').blockers)


@pytest.mark.parametrize('callback,expected', [
    ('function data() return {otherFn=function() end} end', 'missing'),
    ('function data() return {runFn=1} end', 'missing'),
    ('local function runFn() end return {runFn=runFn}', 'missing'),
    ('function data() return {runFn=function() end} end', 'resolved'),
    ('local function runFn() end function data() return {runFn=runFn} end', 'resolved'),
    ('function data() local function runFn() end return {runFn=runFn} end', 'resolved'),
    ('function data() return makeCallbacks() end', 'unverified'),
])
def test_callback_link_checks_global_data(tmp_path, callback, expected):
    source = tmp_path / 'source'
    fixture(source, callback=callback)
    descriptor = prepare_mod(source)
    row = next(r for r in descriptor.resource_audit['references'] if r['source'] == 'mod.json')
    assert row['callbackStatus'] == expected
    assert bool(descriptor.blockers) == (expected == 'missing')
    if expected == 'unverified':
        assert any('could not be proved' in w for w in descriptor.warnings)


def test_reference_resolution_follows_relative_and_absolute_paths(tmp_path):
    source = tmp_path / 'source'
    fixture(source)
    directory = source / 'content/assets'
    directory.mkdir()
    (directory / 'object.mdl').write_text('function data() return {mesh="shape.msh", material="original::/assets/paint.mtl", version=2} end')
    (directory / 'shape.msh').write_text('function data() return {} end')
    (directory / 'shape.msh.blob').write_bytes(b'fictional blob')
    (directory / 'paint.mtl').write_text('function data() return {texture="tex/color.dds", base="::/external.dds"} end')
    (directory / 'tex').mkdir()
    (directory / 'tex/color.dds').write_bytes(b'fictional texture')
    descriptor = prepare_mod(source)
    assert not descriptor.blockers
    rows = descriptor.resource_audit['references']
    assert any(r.get('target') == 'content/assets/shape.msh' for r in rows)
    assert any(r.get('target') == 'content/assets/tex/color.dds' for r in rows)
    assert any(r['status'] == 'external' for r in rows)
    (directory / 'tex/color.dds').unlink()
    assert any('missing local resource' in b for b in prepare_mod(source).blockers)


def test_literal_concatenation_and_comments_not_false_missing_refs(tmp_path):
    source = tmp_path / 'source'
    fixture(source, callback='-- ug_require "original::/missing"\nlocal h=ug_require("original::/" .. "helper")\nfunction data() return {runFn=function() end} end')
    (source / 'content/helper.lua').write_text('return {}')
    assert not prepare_mod(source).blockers


def test_mesh_requires_blob_and_traversal_is_blocked(tmp_path):
    source = tmp_path / 'source'
    fixture(source)
    (source / 'content/shape.msh').write_text('function data() return {texture="../outside.dds"} end')
    errors = prepare_mod(source).blockers
    assert any('companion mesh blob' in b for b in errors)
    assert any('invalid TF3 resource reference' in b for b in errors)


def test_staged_resources_checked_before_existing_output_replaced(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    fixture(source)
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'keep.txt').write_text('keep')
    copy = converter._copy_files
    def corrupt(root, stage, excluded, progress):
        count = copy(root, stage, excluded, progress)
        (stage / 'content/mod.script.lua').write_text('function data() return {} end')
        return count
    monkeypatch.setattr(converter, '_copy_files', corrupt)
    with pytest.raises(ValueError, match='Staged conversion'):
        convert_mod(source, output, overwrite=True)
    assert (output / 'keep.txt').read_text() == 'keep'
    assert not list(tmp_path.glob('output.backup-*'))


def test_display_name_change_preserves_id_and_updates_localized_name(tmp_path):
    source = tmp_path / 'source'
    fixture(source)
    descriptor = prepare_mod(source, name='New name')
    assert descriptor.target_mod_id == 'original'
    assert descriptor.localization['sv'] == {'name': 'New name', 'description': 'Text'}


def test_invalid_localization_and_empty_script_object_blocked(tmp_path):
    source = tmp_path / 'source'
    fixture(source, extra={'runScript': {'params': {}}})
    (source / '_metadata/modinfo.json').write_text('{"name":"Name", "localization":{"sv":{"name":12}}}')
    assert any('fileName' in b for b in prepare_mod(source).blockers)
    assert any('localization.sv.name' in b for b in prepare_mod(source).blockers)


def test_audit_does_not_execute_resource_code(tmp_path):
    source = tmp_path / 'source'
    fixture(source, callback='os.execute("unsafe")\nfunction data() return {runFn=function() end} end')
    assert not prepare_mod(source).blockers
    assert not (source / 'unsafe').exists()


def test_shipped_native_fixture_converts_and_refuses_id_change(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'examples/native_smoke_mod'
    report = convert_mod(source / '_metadata/modinfo.json', tmp_path / 'output')
    assert report['modId'] == 'mapstudio_converter_smoke_030'
    assert not report['resourceAudit']['blockers']
    assert not (tmp_path / 'output/res').exists()
    assert (tmp_path / 'output/content/helper.lua').is_file()
    assert prepare_mod(source, mod_id='renamed').blockers


def test_tf3_numeric_parameter_array_written_as_doubles(tmp_path):
    source = tmp_path / 'source'
    fixture(source, extra={'params': [{'key': 'mode', 'uiType': 'ComboBox', 'values': ['Mode'], 'numbers': [7], 'defaultIndex': 0}]})
    convert_mod(source, tmp_path / 'output')
    text = (tmp_path / 'output/mod.json').read_text()
    exported = json.loads(text)
    assert type(exported['params'][0]['numbers'][0]) is float
    assert exported['params'][0]['numbers'][0] == 7
    assert type(prepare_mod(source).source_metadata['mod.json']['params'][0]['numbers'][0]) is int


@pytest.mark.parametrize('numbers', [[True], ['7'], [], [1, 2]])
def test_invalid_parameter_numbers_blocked(tmp_path, numbers):
    source = tmp_path / 'source'
    fixture(source, extra={'params': [{'key': 'mode', 'uiType': 'ComboBox', 'values': ['Mode'], 'numbers': numbers}]})
    assert any('numbers must' in b for b in prepare_mod(source).blockers)


def test_installed_mod_backup_is_outside_game_mod_directory(tmp_path):
    source = tmp_path / 'source'
    fixture(source)
    output = tmp_path / 'local/mods/installed'
    convert_mod(source, output)
    report = convert_mod(source, output, overwrite=True)
    backup = Path(report['backup'])
    assert backup.parent == tmp_path / 'local/trf3_mod_backups'
    assert (backup / 'mod.json').is_file()
    assert [p.name for p in output.parent.iterdir()] == ['installed']


def test_typed_lua_resource_suffixes_resolve(tmp_path):
    source = tmp_path / 'source'
    fixture(source)
    (source / 'content/definition.lua').write_text('return {cargo="cargo.cargo", unit="original::/unit.mu", names="names.names"}')
    for filename in ['cargo.cargo.lua', 'unit.mu.lua', 'names.names.lua']:
        (source / 'content' / filename).write_text('function data() return {} end')
    assert not prepare_mod(source).blockers


def test_nested_game_mod_output_does_not_copy_external_backups(tmp_path):
    source = tmp_path / 'source'
    fixture(source)
    output = source / 'local/mods/installed'
    for _ in range(3):
        convert_mod(source, output, overwrite=True)
    assert not list(output.rglob('installed.backup-*'))


def test_null_filename_not_silently_converted_into_null_script(tmp_path):
    source = tmp_path / 'source'
    fixture(source, extra={'runScript': {'fileName': None, 'params': {'kept': True}}})
    assert any('fileName must be text' in b for b in prepare_mod(source).blockers)

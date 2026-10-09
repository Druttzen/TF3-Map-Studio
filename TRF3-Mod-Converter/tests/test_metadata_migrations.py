import json

import pytest

from test_tf2_vehicle_port import fixture_mod
from trf3_mod_converter.converter import prepare_mod
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot


@pytest.mark.parametrize('name', [
    'Stake cars 13-401, 13-926, 13-4012',
    'Scandinavian Airlines Systems Airbus A320丨北欧（IATA: SK）',
    '北欧航空公司的特别长的飞机名称需要保留完整原始名称供用户在模组描述中查看',
    'A legacy\nmod title with line breaks',
])
def test_tf2_port_migrates_display_title_without_losing_full_name(fixture_mod, name):
    source, game, output = fixture_mod
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name=name)
    info = json.loads((output/'_metadata/modinfo.json').read_text(encoding='utf-8'))
    assert 1 <= len(info['name']) <= 32
    assert '\n' not in info['name'] and '\r' not in info['name']
    assert f'Original mod name: {name}\n\nOriginal description' == info['description']
    assert report['name'] == info['name']
    assert report['displayName'] == name
    migration = next(row for row in report['migrationAudit']['metadataMigrations'] if row['field'] == 'info.name')
    assert migration['sourceValue'] == name and migration['targetValue'] == info['name']
    assert migration['fullTitleLocation'] == '_metadata/modinfo.json.description'
    assert migration['nativeTest'] == 'not_run'
    assert snapshot(source) == before
    assert not prepare_mod(output).blockers


def test_existing_32_character_name_is_preserved(fixture_mod):
    source, game, output = fixture_mod
    name = 'x'*32
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name=name)
    info = json.loads((output/'_metadata/modinfo.json').read_text(encoding='utf-8'))
    assert info['name'] == name and info['description'] == 'Original description'
    assert not any(row['field'] == 'info.name' for row in report['migrationAudit'].get('metadataMigrations', []))


@pytest.mark.parametrize('visible', [True, False])
def test_root_visibility_migrates_to_native_boolean_with_audit(fixture_mod, visible):
    source, game, output = fixture_mod
    original = load_lua_table((source/'mod.lua').read_text())
    original['visible'] = visible
    (source/'mod.lua').write_text(emit(original))
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    mod = json.loads((output/'mod.json').read_text())
    assert mod['visible'] is visible
    migration = next(row for row in report['migrationAudit']['metadataMigrations'] if row['field'] == 'visible')
    assert migration['sourceValue'] is visible and migration['targetValue'] is visible
    assert migration['targetField'] == 'mod.json.visible'
    assert snapshot(source) == before
    assert load_lua_table((output/'_port_originals/mod.lua').read_text())['visible'] is visible


@pytest.mark.parametrize('root_value,info_value', [('yes', None), (0, None), (True, False)])
def test_unproven_or_conflicting_visibility_keeps_source_and_existing_output(fixture_mod, root_value, info_value):
    source, game, output = fixture_mod
    original = load_lua_table((source/'mod.lua').read_text())
    original['visible'] = root_value
    if info_value is not None:
        original['info']['visible'] = info_value
    (source/'mod.lua').write_text(emit(original))
    output.mkdir()
    (output/'keep.txt').write_text('old output')
    before = snapshot(source)
    with pytest.raises(ValueError, match='visible'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture', overwrite=True)
    assert snapshot(source) == before
    assert (output/'keep.txt').read_text() == 'old output'


@pytest.mark.parametrize('name', ['', '   ', '\n\r'])
def test_blank_title_still_blocks_before_export(fixture_mod, name):
    source, game, output = fixture_mod
    with pytest.raises(ValueError, match='non-blank text'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name=name)
    assert not output.exists()


def test_translation_descriptions_can_use_literal_local_constants(fixture_mod):
    source, game, output = fixture_mod
    (source/'strings.lua').write_text('''function data()
        local lb = "\\n"
        local title = "Original description"
        return {en={key=title .. lb .. "Details"}, sv={key="Svensk text"}}
    end''')
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    info = json.loads((output/'_metadata/modinfo.json').read_text())
    assert info['description'] == 'Original description\nDetails'
    assert json.loads((output/'strings.json').read_text()) == {
        'en': {'key': 'Original description\nDetails'}, 'sv': {'key': 'Svensk text'}}
    assert report['sourceUnchanged'] and snapshot(source) == before


@pytest.mark.parametrize('text', [
    'function data() local title=os.execute("never run") return {en={key=title}} end',
    'function data() info_desc=api.engine.getComponent(1) return {en={key=info_desc}} end',
    'function data() local title="First" if api then title="Other" end return {en={key=title}} end',
])
def test_translation_side_effects_and_unproven_globals_remain_blocked(fixture_mod, text):
    source, game, output = fixture_mod
    (source/'strings.lua').write_text(text)
    output.mkdir()
    (output/'keep.txt').write_text('old output')
    before = snapshot(source)
    with pytest.raises(ValueError):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture', overwrite=True)
    assert snapshot(source) == before and (output/'keep.txt').read_text() == 'old output'


def test_literal_translation_global_binding_exports_with_original_source_and_audit(fixture_mod):
    source, game, output = fixture_mod
    (source/'strings.lua').write_text('''function data()
      info_desc="Shared ".."global"
      return {en={key=info_desc},sv={key="Svensk beskrivning"}}
    end''')
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    assert json.loads((output/'strings.json').read_text()) == {
        'en': {'key': 'Shared global'}, 'sv': {'key': 'Svensk beskrivning'}}
    assert json.loads((output/'_metadata/modinfo.json').read_text())['description'] == 'Shared global'
    assert (output/'_port_originals/strings.lua').read_bytes() == (source/'strings.lua').read_bytes()
    assert snapshot(source) == before and report['sourceUnchanged']
    row = next(row for row in report['migrationAudit']['translationMigrations']
               if row['policy'] == 'fold_literal_translation_binding')
    assert row['sourceName'] == 'info_desc' and row['sourceValue'] == 'Shared global'


def test_numeric_orphan_translation_is_archived_without_guessing_its_description(fixture_mod):
    source, game, output = fixture_mod
    footer = '\n\n[Patreon footer]'
    (source/'strings.lua').write_text(emit({'en':{'key':'Original description', 1:footer}, 'sv':{'key':'Svensk text', 1:footer}}))
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    translations = json.loads((output/'strings.json').read_text())
    assert translations == {'en':{'key':'Original description'}, 'sv':{'key':'Svensk text'}}
    info = json.loads((output/'_metadata/modinfo.json').read_text())
    assert info['description'] == 'Original description'
    rows = report['migrationAudit']['translationMigrations']
    assert [row['language'] for row in rows] == ['en', 'sv']
    assert all(row['sourceKey'] == 1 and row['sourceValue'] == footer for row in rows)
    assert (output/'_port_originals/strings.lua').read_bytes() == (source/'strings.lua').read_bytes()
    assert snapshot(source) == before


def test_named_nontext_translation_remains_blocked(fixture_mod):
    source, game, output = fixture_mod
    (source/'strings.lua').write_text(emit({'en':{'key':5}}))
    with pytest.raises(ValueError, match='must contain literal text'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    assert not output.exists()

from copy import deepcopy

import pytest

from trf3_mod_converter.cargo_port import port_compartments
from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.resource_profiles import (
    TranslatedConcat, load_resource_table, resolve_translation_concatenations,
)


def test_identical_duplicate_literals_preserve_structures_and_localization():
    data = load_resource_table('''function data() return {
      order=3, order=3, fakeBogies={}, fakeBogies={},
      title=_("Title"), title=_("Title"),
      nested={names={"a","b"}}, nested={names={"a","b"}}
    } end''')
    assert data == {'order': 3, 'fakeBogies': [], 'title': 'Title', 'nested': {'names': ['a', 'b']}}
    assert isinstance(data['title'], TranslatedString)


@pytest.mark.parametrize('left,right', [
    ('true', '1'), ('1', '1.0'), ('_("Title")', '"Title"'),
    ('{x=1}', '{x=2}'), ('{1,2}', '{2,1}'),
    ('{x=true}', '{x=1}'), ('_("a").." b"', '"a ".._("b")'),
])
def test_conflicting_or_provenance_different_duplicates_stay_blocked(left, right):
    with pytest.raises(ValueError, match='Duplicate Lua table key'):
        load_resource_table(f'function data() return {{x={left},x={right}}} end')


def test_translation_only_global_literal_bindings_are_folded_without_execution():
    source = '''function data()
    info_name = "Opel Insignia 2014"
    info_desc = "Adds Opel" .. "\u0020and an asset car"
    return {en={[info_name]=info_name,[info_desc]=info_desc}}
    end'''
    data = load_resource_table(source, allow_global_literals=True)
    assert data == {'en': {'Opel Insignia 2014': 'Opel Insignia 2014',
                          'Adds Opel and an asset car': 'Adds Opel and an asset car'}}
    with pytest.raises(ValueError, match='Only local table'):
        load_resource_table(source)


@pytest.mark.parametrize('body', [
    'global = os.execute("no")', 'global = api.engine.getComponent(1)',
    'data = "shadow"', 'require = "shadow"',
    'global = function() return {} end', 'global = require "transf"',
])
def test_global_translation_binding_mode_still_blocks_active_code_or_helper_values(body):
    with pytest.raises(ValueError):
        load_resource_table(f'function data() {body} return {{}} end', allow_global_literals=True)


def test_localized_concatenation_composes_each_locale_and_keeps_missing_fragment_fallback():
    source = 'function data() return {name=_("Wagon").." (".._("Blue")..")"} end'
    data = load_resource_table(source)
    assert isinstance(data['name'], TranslatedConcat)
    assert deepcopy(data)['name'].parts == data['name'].parts
    translations = {'en': {'Wagon': 'Wagon', 'Blue': 'Blue'},
                    'sv': {'Wagon': 'Vagn', 'Blue': 'Blå'},
                    'de': {'Wagon': 'Wagen'}}
    audit = {}
    resolved = resolve_translation_concatenations(data, translations, audit, resource='wagon.mdl')
    key = str(resolved['name'])
    assert type(resolved['name']) is TranslatedString
    assert translations['en'][key] == 'Wagon (Blue)'
    assert translations['sv'][key] == 'Vagn (Blå)'
    assert translations['de'][key] == 'Wagen (Blue)'
    assert audit['translationMigrations'][0]['resource'] == 'wagon.mdl'
    assert load_resource_table(source)['name'] == data['name']
    assert isinstance(data['name'], TranslatedConcat)


def test_localized_concatenation_generates_fallback_and_rejects_source_key_collision():
    data = load_resource_table('return {name=_("Box").." suffix"}')
    tables = {}
    resolved = resolve_translation_concatenations(data, tables)
    assert tables == {'en': {str(resolved['name']): 'Box suffix'}}
    with pytest.raises(ValueError, match='conflicts'):
        resolve_translation_concatenations(data, {'en': {str(data['name']): 'wrong text'}})


@pytest.mark.parametrize('helper', ['constructionutil', 'colliderutil', 'laneutil', 'vehicleutil'])
def test_unread_stock_helper_import_does_not_reject_a_literal_resource(helper):
    assert load_resource_table(f'local unused=require "{helper}" function data() return {{x=1}} end') == {'x': 1}


@pytest.mark.parametrize('source', [
    'local helper=require "custom" function data() return {} end',
    'local c=require "colliderutil" function data() return {c=c} end',
    'local c=require "colliderutil" function data() return {c=c.createBox()} end',
    'local c=require "colliderutil" local c={} function data() return {} end',
    'local require=function() return {} end local c=require "colliderutil" function data() return {} end',
])
def test_unknown_used_shadowed_or_ambiguous_helper_imports_stay_blocked(source):
    with pytest.raises(ValueError):
        load_resource_table(source)


@pytest.mark.parametrize('hidden', [[], {}])
def test_empty_cargo_entry_visibility_list_is_audited_without_mutating_source(hidden):
    source = {'compartmentsList': [{'loadConfigs': [{'cargoEntries': [{'capacity': 0, 'toHide': hidden}]}]}]}
    before = deepcopy(source)
    target, extras, audit = port_compartments(source)
    assert source == before
    assert extras == {}
    assert target['compartments'][0]['loadConfigs'][0]['toHide'] == []
    assert 'toHide' not in target['compartments'][0]['loadConfigs'][0]['cargoEntry']
    assert audit['normalizations'] == [{'compartment': 0, 'loadConfig': 0, 'entry': 0,
                                      'field': 'cargoEntry.toHide', 'sourceValue': hidden,
                                      'policy': 'omit_empty_entry_visibility_list', 'nativeTest': 'not_run'}]


@pytest.mark.parametrize('hidden', [[1], {'node': 1}, '', None, False])
def test_nonempty_or_malformed_cargo_entry_visibility_data_stays_blocked(hidden):
    source = {'compartmentsList': [{'loadConfigs': [{'cargoEntries': [{'capacity': 0, 'toHide': hidden}]}]}]}
    with pytest.raises(ValueError, match='cargoEntry fields'):
        port_compartments(source)

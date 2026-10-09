from copy import deepcopy

import pytest

from trf3_mod_converter.lua_metadata import TranslatedString, UnsupportedValue, load_lua_table
from trf3_mod_converter.resource_profiles import load_resource_table
from trf3_mod_converter.shared_metadata_literals import load_mod_metadata


MOD = 'function data() return {info={name=_("Title"),description=_(info_desc)}} end'


def test_shared_concatenated_key_preserves_complete_locale_tables_and_provenance():
    strings = '''function data()
      local tail = "\nDetails"
      info_desc = "Description" .. tail
      return {en={[info_desc]="English details"}, sv={[info_desc]="Svenska detaljer"}}
    end'''
    tables = load_resource_table(strings, allow_global_literals=True)
    before = deepcopy(tables)
    audit = {}
    result = load_mod_metadata(MOD, strings, audit=audit)
    assert type(result['info']['description']) is TranslatedString
    assert result['info']['description'] == 'Description\nDetails'
    assert tables == before == {'en': {'Description\nDetails': 'English details'},
                               'sv': {'Description\nDetails': 'Svenska detaljer'}}
    assert load_resource_table(strings, allow_global_literals=True) == before
    row, = audit['metadataMigrations']
    assert row['sourceName'] == 'info_desc' and row['sourceValue'] == 'Description\nDetails'
    assert row['policy'] == 'fold_shared_literal_localization_key'
    assert row['nativeTest'] == 'not_run'


def test_empty_language_table_keeps_literal_english_key_as_fallback():
    strings = 'function data() info_desc="Literal fallback" return {} end'
    result = load_mod_metadata(MOD, strings, audit={})
    assert type(result['info']['description']) is TranslatedString
    assert result['info']['description'] == 'Literal fallback'
    assert load_resource_table(strings, allow_global_literals=True) == {}


def test_shared_unicode_and_quotes_are_not_rewritten_or_escaped_as_source():
    strings = '''function data() info_desc = [[Svensk åäö "text"\n第二行]] return {} end'''
    result = load_mod_metadata(MOD, strings, audit={})
    assert result['info']['description'] == 'Svensk åäö "text"\n第二行'


@pytest.mark.parametrize('strings', [
    'function data() local info_desc="local" return {} end',
    'local info_desc="captured" function data() info_desc="changed" return {} end',
    'function data() info_desc="first" info_desc="second" return {} end',
    'function data() info_desc="same" info_desc="same" return {} end',
    'function data() info_desc="key" info_desc.x="mutation" return {} end',
    'function data() info_desc={"mutable"} return {} end',
    'function data() info_desc=api.getDescription() return {} end',
    'function data() info_desc=function() return "behavior" end return {} end',
    'function data(info_desc) return {} end',
    'function info_desc() return "shadow" end function data() info_desc="key" return {} end',
    'function data() local function helper(info_desc) return {} end info_desc="key" return {} end',
    'function data() return {en={info_desc="This locale key is not a global binding"}} end',
    'function data() return {} info_desc="unreachable" end',
    'function data() do return {} end info_desc="unreachable" return {} end',
])
def test_local_shadow_reassignment_mutation_unknown_and_behavior_stay_blocked(strings):
    with pytest.raises(ValueError):
        load_mod_metadata(MOD, strings, audit={})


@pytest.mark.parametrize('mod', [
    'local function info_desc() return "local function" end ' + MOD,
    'function info_desc() return "global function" end ' + MOD,
    'function data(info_desc) return {info={description=_(info_desc)}} end',
    'function data() local function unused(info_desc) return {} end return {info={description=_(info_desc)}} end',
    'function data() return {info={description=_(info_desc)},runFn=function(info_desc) end} end',
    'function data() return {info={description=_(info_desc)},runFn=function() info_desc="mutated" end} end',
    'function data() return {info={description=_(unknown_name)}} end',
])
def test_metadata_shadows_writes_or_unknown_localization_names_stay_blocked(mod):
    with pytest.raises(ValueError):
        load_mod_metadata(mod, 'function data() info_desc="verified key" return {} end', audit={})


def test_missing_strings_source_cannot_supply_global_binding():
    with pytest.raises(ValueError, match='same-package strings.lua'):
        load_mod_metadata(MOD, None, audit={})


def test_ordinary_metadata_keeps_existing_reader_behavior_and_callbacks():
    text = '''function data() return {info={name=_("Literal key"),description=unknown},
      runFn=function() api.performBehavior() end} end'''
    audit = {}
    assert load_mod_metadata(text, None, audit=audit) == load_lua_table(text)
    assert isinstance(load_mod_metadata(text, None, audit={})['runFn'], UnsupportedValue)
    assert audit == {}


def test_plain_global_name_outside_localization_call_remains_unbound():
    text = 'function data() return {info={description=info_desc}} end'
    result = load_mod_metadata(text, 'function data() info_desc="key" return {} end', audit={})
    assert isinstance(result['info']['description'], UnsupportedValue)


@pytest.mark.parametrize('mod', [
    'function _() return "shadow" end ' + MOD,
    'local function _() return "shadow" end ' + MOD,
    'function data() return {info={description=_(info_desc)},runFn=function(_) end} end',
])
def test_shadowed_metadata_localization_helper_stays_blocked(mod):
    with pytest.raises(ValueError):
        load_mod_metadata(mod, 'function data() info_desc="key" return {} end', audit={})


@pytest.mark.parametrize('strings', [
    'function _() return "shadow" end function data() info_desc="key" return {} end',
    'local function _() return "shadow" end function data() info_desc="key" return {} end',
    'function data() local _="shadow" info_desc="key" return {} end',
    'function data() _="shadow" info_desc="key" return {} end',
    'function data(_) info_desc="key" return {} end',
])
def test_shadowed_strings_localization_helper_stays_blocked(strings):
    with pytest.raises(ValueError):
        load_mod_metadata(MOD, strings, audit={})


def test_shared_literal_binding_does_not_omit_active_lifecycle_behavior():
    mod = '''function data() return {info={description=_(info_desc)},
      runFn=function() api.performBehavior() end} end'''
    result = load_mod_metadata(mod, 'function data() info_desc="key" return {} end', audit={})
    assert result['info']['description'] == 'key'
    assert isinstance(result['runFn'], UnsupportedValue)
    assert not result['runFn'].empty_callback


def test_bare_literal_metadata_still_matches_existing_reader():
    text = '{info={name="Title",description="Details"}}'
    assert load_mod_metadata(text, None, audit={}) == load_lua_table(text)

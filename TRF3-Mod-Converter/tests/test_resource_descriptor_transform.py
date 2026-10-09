from copy import deepcopy

import pytest

from trf3_mod_converter.resource_profiles import (
    ConstantCallback, TranslatedConcat, load_resource_table, port_resource,
)


SOURCE = '''function data() return {type="ASSET_DEFAULT",
description={name=_("Name") .. " suffix"},
updateFn=function(params) return {models={{id="asset.mdl"}}} end} end'''


def export(text=SOURCE, **kwargs):
    return port_resource('construction/asset.con', text,
                         lambda path, kind: f'demo::/{kind}/{path}',
                         resource_reference='demo::/construction/asset.con', **kwargs)


def test_preparsed_descriptor_skips_source_reparse_and_hook_can_transform_callback_values():
    original = load_resource_table(SOURCE)
    before = deepcopy(original)
    seen = []

    def scope_dependency(data):
        seen.append(data)
        callback = data['updateFn']
        assert isinstance(callback, ConstantCallback)
        callback.result['models'][0]['id'] = 'dependency/asset.mdl'
        return data

    docs = export('deliberately invalid source that must not be parsed', parsed_data=original,
                  data_transform=scope_dependency, translation_tables={'en': {'Name': 'Name'}})
    result = load_resource_table(docs['construction/asset.script.lua'])['updateFn'].result
    assert result['subconstructions'][0]['models'][0]['id'] == 'demo::/model/dependency/asset.mdl'
    assert len(seen) == 1 and seen[0] is not original
    assert original == before


def test_dependency_key_transform_precedes_per_locale_concatenation():
    translations = {'en': {'dep_Name': 'Imported name'}, 'sv': {'dep_Name': 'Importerat namn'}}
    audit = {}

    def scope_dependency(data):
        name = data['description']['name']
        assert isinstance(name, TranslatedConcat)
        data['description']['name'] = TranslatedConcat(tuple(
            (translated, 'dep_' + value if translated else value) for translated, value in name.parts))
        return data

    docs = export(data_transform=scope_dependency, translation_tables=translations, translation_audit=audit)
    key = next(key for key in translations['en'] if key.startswith('tf2_concat_'))
    assert translations['en'][key] == 'Imported name suffix'
    assert translations['sv'][key] == 'Importerat namn suffix'
    assert f'name = _("{key}")' in docs['construction/asset.con.lua']
    assert audit['translationMigrations'][0]['fragments'] == [
        {'translated': True, 'value': 'dep_Name'}, {'translated': False, 'value': ' suffix'}]


def test_preparsed_descriptor_is_cloned_even_without_a_transform():
    original = load_resource_table(SOURCE)
    before = deepcopy(original)
    export(parsed_data=original, translation_tables={'en': {'Name': 'Name'}})
    assert original == before


def test_external_plain_display_text_does_not_pick_up_root_locale_keys():
    text = SOURCE.replace('_("Name") .. " suffix"', '"Name"')
    docs = export(text, translations=set(), translation_tables={'en': {'Name': 'Root name'}},
                  implicit_translations=False)
    assert 'name = "Name"' in docs['construction/asset.con.lua']
    assert 'name = _("Name")' not in docs['construction/asset.con.lua']


@pytest.mark.parametrize('transform', [lambda data: None, lambda data: [], lambda data: {'bad': object()}])
def test_transform_cannot_introduce_an_unvalidated_descriptor(transform):
    with pytest.raises(ValueError):
        export(data_transform=transform)


def test_preparsed_cycles_are_rejected_before_deepcopy_or_transform():
    cyclic = {}
    cyclic['self'] = cyclic
    with pytest.raises(ValueError, match='cyclic'):
        export(parsed_data=cyclic, data_transform=lambda data: pytest.fail('must reject before transform'))

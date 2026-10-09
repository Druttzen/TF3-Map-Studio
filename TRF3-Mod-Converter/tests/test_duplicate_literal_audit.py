import json

import pytest

from trf3_mod_converter.lua_metadata import load_lua_table, TranslatedString
from trf3_mod_converter.resource_profiles import load_resource_table
from trf3_mod_converter.shared_metadata_literals import load_mod_metadata


@pytest.mark.parametrize('reader', [load_lua_table, load_resource_table])
def test_duplicate_literal_audit_keeps_both_expressions_and_original_lines(reader):
    audit = {}
    source = '''function data() return {
      label=_("Title"),
      label=_("Title"),
      value={active=true, levels={1,2}},
      value={active=true, levels={1,2}}
    } end'''
    data = reader(source, audit=audit, resource='source.lua')
    assert isinstance(data['label'], TranslatedString)
    assert data['value'] == {'active':True, 'levels':[1,2]}
    assert len(audit['literalFieldMigrations']) == 2
    first = audit['literalFieldMigrations'][0]
    assert first == {'resource':'source.lua', 'key':'label',
                     'firstExpression':'_("Title")', 'duplicateExpression':'_("Title")',
                     'firstLine':2, 'duplicateLine':3,
                     'policy':'collapse_proven_equivalent_duplicate_field', 'nativeTest':'not_run'}
    json.dumps(audit)


@pytest.mark.parametrize('reader', [load_lua_table, load_resource_table])
@pytest.mark.parametrize('values', [
    'true, x=1', '1, x=1.0', '_("x"), x="x"',
    '{a=1}, x={a=2}', '{1,2}, x={2,1}',
    'function() return {} end, x=function() return {changed=true} end',
])
def test_differing_duplicate_values_are_never_resolved_by_assignment_order(reader, values):
    with pytest.raises(ValueError, match='Duplicate Lua table key'):
        reader('return {x='+values+'}', **({'strict_duplicates': True} if reader is load_lua_table else {}))


def test_identical_unknown_dynamic_values_are_not_proven_literals():
    with pytest.raises(ValueError, match='Duplicate Lua table key'):
        load_lua_table('return {x=external, x=external}', strict_duplicates=True)
    with pytest.raises(ValueError, match='Duplicate Lua table key'):
        load_lua_table('return {x=function() return {} end, x=function() return {} end}', strict_duplicates=True)


def test_metadata_reader_preserves_legacy_default_without_claiming_conflicting_values_are_equivalent():
    audit = {}
    assert load_lua_table('return {role="CREATOR", role="All"}', audit=audit) == {'role':'All'}
    assert audit == {}


@pytest.mark.parametrize('expression', [
    '{choice=t, choice={}}', '{choice={nested=t}, choice={nested={}}}',
    '{choice=t, choice=t}',
])
def test_equal_current_contents_do_not_hide_mutable_table_aliases(expression):
    source = f'local t={{}} function data() local result={expression} t.changed=true return result end'
    with pytest.raises(ValueError, match='Duplicate Lua table key'):
        load_resource_table(source)


def test_factory_and_constant_callback_duplicate_audits_propagate_to_the_export():
    audit = {}
    source = '''local function factory(name) return {name=name, name=name} end
    function data() return {data=factory("same"), callback=function()
      return {value=1, value=1}
    end} end'''
    load_resource_table(source, audit=audit, resource='model.mdl')
    rows = audit['literalFieldMigrations']
    assert [row['key'] for row in rows] == ['name','value']
    assert {row['resource'] for row in rows} == {'model.mdl'}


def test_mod_metadata_duplicate_proof_is_retained_in_conversion_audit():
    audit = {}
    data = load_mod_metadata('function data() return {info={name="x", name="x"}} end', None, audit=audit)
    assert data == {'info':{'name':'x'}}
    assert audit['literalFieldMigrations'][0]['resource']=='mod.lua'

from copy import deepcopy

import pytest

from trf3_mod_converter.native_projection import UnsupportedProjection, project_native_model
from trf3_mod_converter.resource_profiles import load_resource_table
from trf3_mod_converter.tf2_vehicle_port import emit


def model():
    return {'version': 2, 'boundingInfo': {'bbMin': [-5, -2, 0], 'bbMax': [5, 2, 4]},
            'lods': [{'node': {'name': 'RootNode', 'children': [
                {'name': 'body', 'mesh': 'msh/body.msh', 'materials': ['mat/body.mtl']},
                {'name': 'wheel', 'mesh': 'msh/wheel.msh', 'transf': [1, 0, 0, 0]*4},
            ]}}],
            'metadata': {'landVehicle': {'weightEmpty': 12000, 'weightMaxPayload': 3000,
                                         'engines': [{'type': 'ELECTRIC', 'power': 500}]},
                         'description': {'name': 'Donor'}, 'transportVehicle': {'carrier': 'RAIL'}}}


def test_projection_preserves_literal_selected_fields_and_discards_lods():
    source = model(); expected = {key: deepcopy(source[key]) for key in ('version', 'metadata', 'boundingInfo')}
    text = emit(source)
    assert project_native_model(text) == expected
    assert load_resource_table(text) == source


def test_duplicate_root_fields_use_full_parser_with_unchanged_duplicate_key_policy():
    text = 'function data() return {metadata={name="first"}, lods={}, metadata={name="last"},version=2} end'
    with pytest.raises(UnsupportedProjection, match='Duplicate native root field'):
        project_native_model(text)
    with pytest.raises(ValueError, match='Duplicate Lua table key'):
        load_resource_table(text)


def test_comments_escaped_and_long_strings_cannot_change_balance_or_slice_boundaries():
    text = '''-- function fake() return { end
function data() return {
  lods = {{node={name="escaped \\\"},end"}}}, -- } end
  metadata = {description={name=[==[ }, end function data() "]==]}},
  --[==[ { " malformed-looking comment ' ]==]
  boundingInfo = {bbMin={-1,-2,-3},bbMax={1,2,3}}, version = 2,
} end -- trailing comment
'''
    expected = load_resource_table(text)
    assert project_native_model(text) == {k: expected[k] for k in ('version', 'metadata', 'boundingInfo')}


def test_bom_hidden_comments_and_optional_statement_semicolons():
    assert project_native_model('\ufeff-- hi\nfunction data() return {version=2}; end; -- done') == {'version': 2}


def test_absent_projected_fields_still_return_named_projection_mapping():
    assert project_native_model('function data() return {lods={}} end') == {}


def test_arithmetic_literals_localization_and_nested_computed_literal_keys():
    text = 'function data() return {version=1+1, metadata={description={name=_("Translated")}}, '
    text += 'lods={{node={transf={-1,2*3,(4+5)},animations={["literal"]={}}}}}} end'
    result = project_native_model(text)
    assert result['version'] == 2
    assert result['metadata']['description']['name'] == 'Translated'
    assert type(result['metadata']['description']['name']).__name__ == 'TranslatedString'


@pytest.mark.parametrize('text', [
    'local x=1; function data() return {version=2} end',
    'x=1; function data() return {version=2} end',
    'function data() dangerous(); return {version=2} end',
    'function data() local x=1; return {version=2} end',
    'function data() return {version=2} end dangerous()',
    'function data() return {version=2} end data=nil',
    'function data() return {version=2} end function data() return {} end',
    'function other() return {version=2} end',
    'function data(arg) return {version=2} end',
    'function data() return {version=2},{} end',
    'return {version=2}',
    'function data() return helper() end',
    'function data() return {version=2,lods=unknown} end',
    'function data() return {version=2,lods=dangerous()} end',
    'function data() return {version=2,metadata=dangerous()} end',
    'function data() return {version=2,metadata={weight=unknown}} end',
    'function data() return {version=2,lods={callback=function() return {} end}} end',
    'function data() return {version=2,lods={callback=(function() return {} end)()}} end',
    'function data() return {["metadata"]={x=2},version=2} end',
    'function data() return {{},version=2} end',
])
def test_nonliteral_or_non_direct_shape_requires_full_static_parser(text):
    with pytest.raises(UnsupportedProjection):
        project_native_model(text)


@pytest.mark.parametrize('text', [
    'function data() return {version=2,lods={{}} end',
    'function data() return {version=2,metadata={name="unterminated}} end',
    'function data() return {version=2,lods={x=(1+2]}} end',
    'function data() return {version=2,lods={x={[1=2}}} end',
    'function data() return {version=2 metadata={}} end',
    'function data() return {version=2,lods={}}',
    'function data() return {version=2,metadata={name=[=[unterminated}} end',
])
def test_malformed_literals_are_rejected(text):
    with pytest.raises(UnsupportedProjection):
        project_native_model(text)


def test_safe_depth_and_source_size_limits():
    text = 'function data() return {version=2,lods='+('{'*140)+('}'*140)+'} end'
    with pytest.raises(UnsupportedProjection, match='nesting'):
        project_native_model(text)
    with pytest.raises(UnsupportedProjection, match='nesting'):
        project_native_model('function data() return {lods='+('not '*150)+'true} end')
    with pytest.raises(UnsupportedProjection, match='source limit'):
        project_native_model(' '*(2*1024*1024+1))


def test_large_literal_lod_tree_does_not_enter_existing_ast_parser(monkeypatch):
    import trf3_mod_converter.native_projection as projection
    original = projection.load_resource_table
    seen = []
    def checked(text):
        seen.append(text)
        assert 'lods' not in text and 'mesh' not in text
        return original(text)
    monkeypatch.setattr(projection, 'load_resource_table', checked)
    text = 'function data() return {version=2,lods={'+','.join('{node={mesh="a.msh"}}' for _ in range(3000))+',},metadata={weight=1}} end'
    assert projection.project_native_model(text) == {'version': 2, 'metadata': {'weight': 1}}
    assert len(seen) == 1 and len(seen[0]) < 100

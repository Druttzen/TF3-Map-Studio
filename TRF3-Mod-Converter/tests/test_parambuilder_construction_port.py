from copy import deepcopy

import pytest
from luaparser import ast

from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.resource_profiles import (
    AssetSelectionCallback, load_resource_table, port_resource, verified_parambuilder_helper,
)


def construction(*, offset=True, rotate=False, kind='ASSET_TRACK'):
    imports = 'local ParamBuilder = require "parambuilder_v1_1"\n'
    if rotate:
        imports += 'local constructionutil = require "constructionutil"\n'
    setup = ('local positionx = ParamBuilder.Slider("offsetx",_("Offset"),'
             'ParamBuilder.rangeSymm(1,.5),2,_("Offset tooltip"))\n') if offset else 'local positionx=0\n'
    setup += '''local icons={"ui/a.tga","ui/b.tga","ui/c.tga"}
    local models={"asset/a.mdl","asset/b.mdl","asset/c.mdl"}
    local assetmodel=ParamBuilder.IconButton("type_param",_("Model"),icons,models,1,_("Tooltip"))
    '''
    matrix = '{1,0,0,0,0,1,0,0,0,0,1,0,trax,0,height,1}'
    if rotate:
        matrix = 'constructionutil.rotateTransf(params,' + matrix + ')'
    parameters = '{key="position",name=_("Height"),values={_("Ground"),_("Rail")},defaultIndex=1},'
    if offset:
        parameters += 'positionx.params,'
    parameters += 'assetmodel.params'
    body = '''updateFn=function(params)
    local trax=OFFSET
    local height=0
    if params.position==1 then height=1.05 end
    local result={}
    result.models={}
    table.insert(result.models,{id=assetmodel.getValue(params),transf=MATRIX})
    result.terrainAlignmentLists={{type="EQUAL",faces={}}}
    return result
    end'''.replace('OFFSET', 'positionx.getValue(params)' if offset else '0').replace('MATRIX', matrix)
    return imports + setup + f'''function data() return {{type="{kind}",
    description={{name=_("Wagons")}},params={{{parameters}}},{body}}} end'''


class Native:
    def __init__(self):
        self.dependencies = []

    def read(self, path):
        self.dependencies.append(path)
        return b'-- verified native fixture utility'

    def reference(self, path):
        self.dependencies.append(path)
        return '::/' + path


def export(source, *, native=None):
    return port_resource('construction/wagon.con', source,
                         lambda path, kind: f'demo::/{kind}/{path}', native,
                         resource_reference='demo::/construction/wagon.con',
                         verified_helpers={'parambuilder_v1_1'})


@pytest.mark.parametrize('offset,rotate,kind', [
    (True, False, 'ASSET_TRACK'), (True, True, 'ASSET_TRACK'), (False, False, 'ASSET_DEFAULT'),
])
def test_verified_selection_templates_preserve_choices_defaults_indices_and_native_shape(offset, rotate, kind):
    source = construction(offset=offset, rotate=rotate, kind=kind)
    data = load_resource_table(source, verified_helpers={'parambuilder_v1_1'})
    assert isinstance(data['updateFn'], AssetSelectionCallback)
    before = deepcopy(data)
    native = Native()
    docs = export(source, native=native)
    definition = load_lua_table(docs['construction/wagon.con.lua'])
    params = {entry['key']: entry for entry in definition['params']}
    assert params['type_param']['values'] == ['demo::/texture/ui/a.tga', 'demo::/texture/ui/b.tga', 'demo::/texture/ui/c.tga']
    assert params['type_param']['numbers'] == [0, 1, 2]
    assert params['type_param']['defaultIndex'] == 2
    assert params['position']['numbers'] == [0, 1] and params['position']['defaultIndex'] == 2
    if offset:
        assert params['offsetx']['values'] == ['-1', '-0.5', '0', '0.5', '1']
        assert params['offsetx']['numbers'] == [0, 1, 2, 3, 4]
        assert params['offsetx']['defaultIndex'] == 3
    if rotate:
        assert params['constructOpt56']['location'] == 'Toolbar'
        assert len(params['constructOpt56']['numbers']) == 36
        assert 'scripts/construction/param_util.tl' in native.dependencies
    for text in docs.values():
        ast.parse(text)
    assert data == before
    assert ('snapToBaseEdgeTypes' in docs['construction/wagon.script.lua']) == (kind == 'ASSET_TRACK')


def test_generated_native_code_selects_every_model_and_slider_endpoint_without_running_source_lua():
    lupa = pytest.importorskip('lupa')
    docs = export(construction())
    lua = lupa.LuaRuntime()
    # Only independently generated output is executed; no source Lua/helper is.
    lua.execute(docs['construction/wagon.script.lua'])
    update = lua.globals().data()['updateFn']
    for selection, path in enumerate(('a', 'b', 'c')):
        for offset_index, expected in ((0, -1), (2, 0), (4, 1)):
            result = update(lua.table(), lua.table_from({'type_param': selection, 'offsetx': offset_index, 'position': 1}))
            model = result['subconstructions'][1]['models'][1]
            assert model['id'] == f'demo::/model/asset/{path}.mdl'
            assert model['transf'][13] == expected and model['transf'][15] == 1.05
            assert result['snapPoint']['snapToBaseEdgeTypes'][1] == 'TRACK'
    default = update(lua.table(), lua.table())['subconstructions'][1]['models'][1]
    assert default['id'] == 'demo::/model/asset/b.mdl'
    assert default['transf'][13] == 0 and default['transf'][15] == 0


def test_generated_rotation_uses_native_axes_and_excludes_inherited_randomization():
    lupa = pytest.importorskip('lupa')
    docs = export(construction(rotate=True), native=Native())
    lua = lupa.LuaRuntime()
    rotation = lua.eval('''{rotateTransf=function(params,matrix)
      assert(params.randomRotation==nil)
      matrix[1]=params.constructOpt56
      matrix[6]=params.constructOpt78
      return matrix
    end}''')
    lua.globals().require = lambda path: rotation
    lua.execute(docs['construction/wagon.script.lua'])
    result = lua.globals().data()['updateFn'](lua.table(), lua.table_from({
        'type_param': 0, 'position': 0, 'constructOpt56': .3, 'constructOpt78': .4, 'randomRotation': 1}))
    matrix = result['subconstructions'][1]['models'][1]['transf']
    assert matrix[1] == .3 and matrix[6] == .4


def test_default_asset_without_declared_height_keeps_source_shared_parameter_read():
    source = construction(offset=False, kind='ASSET_DEFAULT')
    source = source.replace('{key="position",name=_("Height"),values={_("Ground"),_("Rail")},defaultIndex=1},', '')
    docs = export(source)
    definition = load_lua_table(docs['construction/wagon.con.lua'])
    assert [entry['key'] for entry in definition['params']] == ['type_param']
    assert 'params.position == 1 and 1.05 or 0' in docs['construction/wagon.script.lua']


@pytest.mark.parametrize('change', [
    lambda text: text.replace('return result', 'print("active side effect") return result'),
    lambda text: text.replace('height=1.05', 'height=2.05'),
    lambda text: text.replace('return result', 'result.extra=true return result'),
    lambda text: text.replace('local result={}', 'local result={} for i=1,2 do print(i) end'),
    lambda text: text.replace('table.insert(result.models', 'custom.insert(result.models'),
])
def test_unverified_callback_changes_are_blocked_instead_of_omitted(change):
    with pytest.raises(ValueError, match='Inline callback'):
        export(change(construction()))


def test_parameter_profile_mismatch_and_unapproved_helper_import_remain_blocked():
    source = construction().replace('positionx.params,', '')
    with pytest.raises(ValueError, match='definitions disagree'):
        export(source)
    with pytest.raises(ValueError, match='Unknown Lua helper'):
        load_resource_table(construction())
    assert not verified_parambuilder_helper('scripts/parambuilder_v1_1.lua', b'return {}')
    assert not verified_parambuilder_helper('scripts/custom.lua', b'return {}')


def test_selection_adapter_records_preserved_behavior_in_audit():
    audit = {}
    source = construction()
    port_resource('construction/wagon.con', source, lambda path, kind: f'demo::/{kind}/{path}',
                  resource_reference='demo::/construction/wagon.con', verified_helpers={'parambuilder_v1_1'},
                  translation_audit=audit)
    row = audit['constructionMigrations'][0]
    assert row['modelChoices'] == 3 and row['offsetChoices'] == 5
    assert row['trackSnappingPreserved'] is True and row['rotationPreserved'] is False
    assert row['nativeTest'] == 'not_run'

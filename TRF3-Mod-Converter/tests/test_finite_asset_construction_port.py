from copy import deepcopy
from dataclasses import replace

import pytest
from luaparser import ast

from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.resource_profiles import FiniteAssetCallback, load_resource_table, port_resource


MATRIX = '{1,0,0,0,0,1,0,0,0,0,1,0,2,3,height,1}'
APPEND = 'result.models[#result.models+1]={id=IDENTITY,transf=' + MATRIX + ',tag="asset"}'


def construction(*, trailers=False, kind='ASSET_DEFAULT'):
    older = ('''if params.older==0 then APPEND_A elseif params.older==1 then APPEND_B end'''
             .replace('APPEND_A', APPEND.replace('IDENTITY', '"old/a.mdl"'))
             .replace('APPEND_B', APPEND.replace('IDENTITY', '"old/b.mdl"'))) if trailers else ''
    branch = '''if params.color==0 then APPEND_A
elseif params.color==1 then APPEND_B
elseif params.color==2 then APPEND_RANDOM end'''
    branch = (branch.replace('APPEND_A', APPEND.replace('IDENTITY', '"asset/red.mdl"'))
              .replace('APPEND_B', APPEND.replace('IDENTITY', '"asset/blue.mdl"'))
              .replace('APPEND_RANDOM', APPEND.replace('IDENTITY', '"asset/" .. colors[math.random(#colors)]')))
    return f'''function data() return {{type="{kind}",description={{name=_("Assets")}},
params={{{{key="color",name=_("Color"),values={{_("Red"),_("Blue"),_("Random")}},defaultIndex=2}},
{{key="height",name=_("Height"),values={{_("Ground"),_("15cm"),_("30cm")}},defaultIndex=1}}}},
updateFn=function(params)
local result={{}} result.models={{}}
local colors={{"red.mdl","red.mdl","blue.mdl"}}
local height=0
if params.height==1 then height=.15 elseif params.height==2 then height=.30 end
{older}
{branch}
result.terrainAlignmentLists={{{{type="EQUAL",faces={{}}}}}}
return result end}} end'''


def export(text, **kwargs):
    return port_resource('construction/asset.con', text, lambda path, kind: f'demo::/{kind}/{path}',
                         resource_reference='demo::/construction/asset.con', **kwargs)


def generated_runtime(docs):
    lua = pytest.importorskip('lupa').LuaRuntime()
    lua.execute('randomCalls=0; randomIndex=1; randomWidth=0; '
                'math.random=function(n) randomCalls=randomCalls+1; randomWidth=n; return randomIndex end')
    # Only independently generated native output runs. Source Workshop Lua,
    # including its callbacks and helpers, is never executed in these tests.
    lua.execute(docs['construction/asset.script.lua'])
    return lua, lua.globals().data()['updateFn']


def test_selection_descriptor_preserves_all_references_weighting_height_and_authored_defaults():
    text = construction(trailers=True, kind='ASSET_TRACK')
    data = load_resource_table(text)
    callback = data['updateFn']
    assert isinstance(callback, FiniteAssetCallback)
    assert callback.selectors[1]['choices'][2]['ids'] == ['asset/red.mdl', 'asset/red.mdl', 'asset/blue.mdl']
    assert [group['key'] for group in callback.selectors] == ['older', 'color']
    before = deepcopy(data)
    audit = {}
    docs = export(text, translation_audit=audit, translations={'Assets', 'Color', 'Random'})
    definition = load_lua_table(docs['construction/asset.con.lua'])
    assert [p['key'] for p in definition['params']] == ['color', 'height']
    assert definition['params'][0]['numbers'] == [0, 1, 2]
    assert definition['params'][0]['defaultIndex'] == 3
    assert definition['params'][1]['defaultIndex'] == 2
    assert 'name = _("Assets")' in docs['construction/asset.con.lua']
    assert data == before
    for emitted in docs.values():
        ast.parse(emitted)
    row = audit['constructionMigrations'][0]
    assert row['selectors'] == 2 and row['conditionalRandomBranches'] == 1
    assert row['heightPreserved'] is True and row['trackSnappingPreserved'] is True
    assert row['nativeTest'] == 'not_run'


def test_generated_native_lua_exhaustively_preserves_choices_height_random_weights_and_rng_execution():
    lua, update = generated_runtime(export(construction(trailers=True)))
    for older in (None, 0, 1, 9):
        for selection in (None, 0, 1, 2, 9):
            for height, expected_height in ((None, 0), (0, 0), (1, .15), (2, .30), (9, 0)):
                for random_index in (1, 2, 3):
                    lua.globals().randomIndex = random_index
                    before_calls = lua.globals().randomCalls
                    params = lua.table_from({key: value for key, value in {
                        'older': older, 'color': selection, 'height': height}.items() if value is not None})
                    result = update(lua.table(), params)
                    models = result['subconstructions'][1]['models']
                    expected = []
                    if older in (0, 1):
                        expected.append('old/' + ('a' if older == 0 else 'b') + '.mdl')
                    if selection in (0, 1):
                        expected.append('asset/' + ('red' if selection == 0 else 'blue') + '.mdl')
                    elif selection == 2:
                        expected.append('asset/' + ('red' if random_index in (1, 2) else 'blue') + '.mdl')
                    assert [models[i]['id'] for i in range(1, len(models) + 1)] == [
                        'demo::/model/' + path for path in expected]
                    assert lua.globals().randomCalls - before_calls == int(selection == 2)
                    if selection == 2:
                        assert lua.globals().randomWidth == 3
                    for i in range(1, len(models) + 1):
                        model = models[i]
                        assert model['transf'][13] == 2 and model['transf'][14] == 3
                        assert model['transf'][15] == expected_height and model['tag'] == 'asset'
                    assert result['subconstructions'][1]['terrainAlignmentLists'][1]['type'] == 'EQUAL'
    # A later call must receive a fresh result table and model transforms.
    previous = update(lua.table(), lua.table_from({'color': 0, 'height': 2}))
    previous['subconstructions'][1]['models'][1]['transf'][15] = 999
    fresh = update(lua.table(), lua.table_from({'color': 0, 'height': 2}))
    assert fresh['subconstructions'][1]['models'][1]['transf'][15] == .30


def indexed_construction():
    return '''function data() return {type="ASSET_DEFAULT",description={name="Vans"},
params={{key="variant",name="Model",values={"A","B","C"},defaultIndex=1}},
updateFn=function(params) local result={} result.models={}
local models={"van/a.mdl","van/b.mdl","van/c.mdl"}
local height=0 local idx=params.variant+1
result.models[#result.models+1]={id=models[idx],transf=''' + MATRIX + '''}
result.terrainAlignmentLists={{type="EQUAL",faces={}}}
return result end} end'''


def test_indexed_model_family_keeps_native_zero_based_values_and_exact_source_lookup():
    docs = export(indexed_construction())
    lua, update = generated_runtime(docs)
    for selection, name in enumerate(('a', 'b', 'c')):
        result = update(lua.table(), lua.table_from({'variant': selection}))
        assert result['subconstructions'][1]['models'][1]['id'] == f'demo::/model/van/{name}.mdl'
    assert lua.globals().randomCalls == 0
    with pytest.raises(Exception):
        update(lua.table(), lua.table())  # Source also requires its indexed parameter.
    with pytest.raises(ValueError, match='declared parameter'):
        export(indexed_construction().replace('"A","B","C"', '"A","B"'))


def test_separate_single_branch_groups_preserve_dc10_model_selection_without_rng():
    text = construction().replace('elseif params.color==1 then', 'end if params.color==1 then')
    text = text.replace('elseif params.color==2 then', 'end if params.color==2 then')
    docs = export(text)
    callback = load_resource_table(text)['updateFn']
    assert [list(group['choices']) for group in callback.selectors] == [[0], [1], [2]]
    lua, update = generated_runtime(docs)
    for choice in (0, 1):
        result = update(lua.table(), lua.table_from({'color': choice, 'height': 0}))
        assert len(result['subconstructions'][1]['models']) == 1
    assert lua.globals().randomCalls == 0


def test_descriptor_transform_scopes_every_model_choice_without_mutating_input():
    data = load_resource_table(construction())
    before = deepcopy(data)

    def transform(value):
        callback = value['updateFn']
        selectors = deepcopy(callback.selectors)
        for selector in selectors:
            for choice in selector['choices'].values():
                choice['ids'] = ['dependency/' + path for path in choice['ids']]
        value['updateFn'] = replace(callback, selectors=selectors)
        return value

    docs = export('not parsed', parsed_data=data, data_transform=transform)
    assert 'demo::/model/dependency/asset/red.mdl' in docs['construction/asset.script.lua']
    assert data == before


@pytest.mark.parametrize('change', [
    lambda text: text.replace('return result', 'print("side effect") return result'),
    lambda text: text.replace('math.random(#colors)', 'math.randomseed(7)'),
    lambda text: text.replace('math.random(#colors)', 'math.random(2)'),
    lambda text: text.replace('local height=0', 'local height=outside.height'),
    lambda text: text.replace('height=.15', 'height=params.state.track.railBase'),
    lambda text: text.replace('height=.15', 'height=os.time()'),
    lambda text: text.replace('2,3,height,1', '2,3,height+1,1'),
    lambda text: text.replace('if params.color==0', 'local alias=height if params.color==0'),
    lambda text: text.replace('tag="asset"', 'tag=height'),
    lambda text: text.replace('return result', 'for i=1,2 do print(i) end return result'),
    lambda text: text.replace('elseif params.color==2', 'else print("active") end if params.color==2'),
])
def test_active_calls_state_captures_rng_changes_height_aliases_and_unknown_behavior_remain_blocked(change):
    with pytest.raises(ValueError, match='Inline callback'):
        export(change(construction()))


@pytest.mark.parametrize('kind', ['WATER_DEPOT', 'RAIL_STATION', 'INDUSTRY'])
def test_finite_selection_cannot_hide_functional_construction_behavior(kind):
    with pytest.raises(ValueError, match='Functional construction'):
        export(construction(kind=kind))


def test_outer_math_shadow_and_captured_params_or_model_arrays_are_rejected():
    cases = [
        'local math={random=function(n) return 1 end}\n' + construction(),
        'local params={color=2,height=1}\n' + construction().replace('function(params)', 'function()'),
        'local colors={"red.mdl","blue.mdl"}\n' + construction().replace(
            'local colors={"red.mdl","red.mdl","blue.mdl"}', ''),
        construction().replace('local colors=', 'local math={random=function(n) return 1 end} local colors='),
        construction().replace('local colors=', 'local params={color=2} local colors='),
    ]
    for text in cases:
        with pytest.raises(ValueError):
            export(text)


def test_array_rebinding_model_aliases_and_active_alias_initializers_are_rejected():
    cases = [
        construction().replace('local height=0', 'colors={"different.mdl"} local height=0'),
        construction().replace('local height=0', 'local active=api.engine.getComponent(1) local height=0'),
        construction().replace('local height=0', 'local models=result.models local height=0').replace(
            'result.models[#result.models+1]', 'models[#models+1]'),
        construction().replace('local height=0', 'local model={id="captured.mdl"} local height=0').replace(
            APPEND.replace('IDENTITY', '"asset/red.mdl"'), 'result.models[#result.models+1]=model'),
    ]
    for text in cases:
        with pytest.raises(ValueError, match='Inline callback'):
            export(text)

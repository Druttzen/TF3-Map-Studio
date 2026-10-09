from copy import deepcopy

import pytest
from luaparser import ast

from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.resource_profiles import ConstantCallback, load_resource_table, port_resource


def source(body, kind='ASSET_DEFAULT'):
    return (f'function data() return {{type="{kind}",description={{name="Asset"}},'
            'updateFn=function(params) ' + body + ' end} end')


LITERAL_BODY = '''local result={}
local height=1.1
local asset={id="asset/wagon.mdl",transf={1,0,0,0,0,1,0,0,0,0,1,0,0,0,height,1}}
result.models={asset}
result.terrainAlignmentLists={{type="EQUAL",faces={}}}
result.cost=4
return result'''


@pytest.mark.parametrize('kind', ['ASSET_DEFAULT', 'ASSET_TRACK'])
def test_callback_local_scaffolding_ports_complete_models_alignment_cost_and_track_snap(kind):
    text = source(LITERAL_BODY, kind)
    parsed = load_resource_table(text)
    assert isinstance(parsed['updateFn'], ConstantCallback)
    before = deepcopy(parsed)
    audit = {}
    docs = port_resource('construction/wagon.con', text, lambda path, type: f'demo::/{type}/{path}',
                         resource_reference='demo::/construction/wagon.con', translation_audit=audit)
    definition = load_lua_table(docs['construction/wagon.con.lua'])
    result = load_resource_table(docs['construction/wagon.script.lua'])['updateFn'].result
    assert definition['updateScript']['fileName'] == 'demo::/construction/wagon.script@updateFn'
    assert result['cost'] == 4
    assert result['subconstructions'][0]['models'] == [{
        'id': 'demo::/model/asset/wagon.mdl', 'transf': [1,0,0,0,0,1,0,0,0,0,1,0,0,0,1.1,1]}]
    assert result['subconstructions'][0]['terrainAlignmentLists'] == [{'type': 'EQUAL', 'faces': []}]
    assert ('snapPoint' in result) == (kind == 'ASSET_TRACK')
    if kind == 'ASSET_TRACK':
        assert result['snapPoint'] == {'transf': [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
                                       'snapToBaseEdgeTypes': ['TRACK'], 'placeAtTerrainHeight': False}
    assert parsed == before
    assert audit['constructionMigrations'] == [{
        'resource': 'construction/wagon.con', 'policy': 'fold_literal_asset_callback',
        'sourceType': kind, 'trackSnappingPreserved': kind == 'ASSET_TRACK', 'nativeTest': 'not_run'}]
    for output in docs.values():
        ast.parse(output)


def test_generated_constant_track_callback_runs_without_reading_runtime_params():
    lua = pytest.importorskip('lupa').LuaRuntime()
    docs = port_resource('construction/wagon.con', source(LITERAL_BODY, 'ASSET_TRACK'),
                         lambda path, type: f'demo::/{type}/{path}',
                         resource_reference='demo::/construction/wagon.con')
    # Execute only independently emitted native code, never the source callback.
    lua.execute(docs['construction/wagon.script.lua'])
    result = lua.globals().data()['updateFn'](None, None)
    assert result['cost'] == 4
    assert result['subconstructions'][1]['models'][1]['transf'][15] == 1.1
    assert result['snapPoint']['snapToBaseEdgeTypes'][1] == 'TRACK'


@pytest.mark.parametrize('body', [
    'local result={} result.height=params.height return result',
    'local result={} result.height=outside.height return result',
    'local result={} global.models={} return result',
    'local result={} print("side effect") return result',
    'local result={} result.height=math.random() return result',
    'local result={} if params.height==1 then result.height=1 end return result',
    'local result={} for i=1,2 do result[i]=i end return result',
    'local result={} result.self=result return result',
    'local result={} return result,params',
    'local result={} result.height=1',
])
def test_dynamic_reads_side_effects_control_flow_cycles_and_missing_final_return_remain_blocked(body):
    with pytest.raises(ValueError, match='Inline callback'):
        load_resource_table(source(body))


def test_callback_cannot_capture_mutable_outer_bindings_or_factories():
    for prefix, body in [
        ('local outside={height=1}', 'local result={} result.height=outside.height return result'),
        ('local function make() return {height=1} end', 'local result=make() return result'),
    ]:
        text = prefix + '\n' + source(body)
        with pytest.raises(ValueError, match='Inline callback'):
            load_resource_table(text)


@pytest.mark.parametrize('kind', ['WATER_DEPOT', 'RAIL_DEPOT', 'RAIL_STATION', 'INDUSTRY'])
def test_literal_results_do_not_turn_functional_constructions_into_decorative_assets(kind):
    with pytest.raises(ValueError, match='Functional construction'):
        port_resource('construction/functional.con', source(LITERAL_BODY, kind),
                      lambda path, type: f'demo::/{type}/{path}',
                      resource_reference='demo::/construction/functional.con')

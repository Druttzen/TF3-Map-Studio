import pytest

from trf3_mod_converter.resource_profiles import load_resource_table


DOORS = '''local slide = .8
local mid_time = 500
local end_time = 1100
local function door_closer(slide, push)
  return {forward=false, type="KEYFRAME", params={keyframes={
    {time=0, transl={0,0,0}},
    {time=mid_time, transl={0,push,0}},
    {time=end_time, transl={slide,push,0}}
  }}}
end
function data()
  return {right=door_closer(-slide,-.12),left=door_closer(slide,.12)}
end'''


def test_literal_door_factories_keep_captured_times_signed_arguments_and_independent_tables():
    result = load_resource_table(DOORS)
    assert result['right']['params']['keyframes'] == [
        {'time': 0, 'transl': [0,0,0]},
        {'time': 500, 'transl': [0,-.12,0]},
        {'time': 1100, 'transl': [-.8,-.12,0]},
    ]
    assert result['left']['params']['keyframes'][-1]['transl'] == [.8,.12,0]
    result['right']['params']['keyframes'][-1]['transl'][0] = 99
    assert result['left']['params']['keyframes'][-1]['transl'][0] == .8


def test_factory_capture_observes_permitted_local_table_field_assignment():
    assert load_resource_table('''local times={ending=1100}
    local function door(value) return {time=times.ending,value=value} end
    times.ending=1200
    function data() return {door=door(85)} end''') == {'door': {'time':1200,'value':85}}


@pytest.mark.parametrize('text', [
    'local function f() print("side effect") return {} end return {x=f()}',
    'local function f() return execute() end return {x=f()}',
    'local function f() return {x=execute()} end return {x=f()}',
    'local function f() return {x=f()} end return {x=f()}',
    'local function f() return {x=function() end} end return {x=f()}',
    'local function f(x) x.value=2 return {} end return {x=f({value=1})}',
    'local function f(x) if x then return {} end end return {x=f(true)}',
    'local function f(...) return {} end return {x=f()}',
    'local function f(x,x) return {} end return {x=f(1,2)}',
    'local function f(_) return {} end return {x=f(1)}',
    'local function math() return {} end return {x=math()}',
    'local function f(x) return {x=x} end return {x=f()}',
    'local function f(x) return {x=x} end return {x=f(1,2)}',
    'local function f() return {} end return {x=f}',
])
def test_factory_side_effects_control_flow_recursion_and_exposed_functions_are_blocked(text):
    with pytest.raises(ValueError):
        load_resource_table(text)

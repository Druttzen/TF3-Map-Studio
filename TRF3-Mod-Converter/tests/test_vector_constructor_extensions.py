import math

import pytest

from trf3_mod_converter.lua_math import evaluate_math
from trf3_mod_converter.resource_profiles import load_resource_table


def test_vec2_and_vec4_literal_constructors_retain_named_components():
    assert evaluate_math('vec2', 'new', [0, .7]) == {'x': 0, 'y': .7}
    assert evaluate_math('vec4', 'new', [.15, .5, 1, 7]) == {'x': .15, 'y': .5, 'z': 1, 'w': 7}


def test_vec4_scale_matches_tf2_xyz_axes_without_scaling_translation():
    result = load_resource_table('''local vec3=require "vec3"
    local vec4=require "vec4.lua"
    local transf=require "transf"
    function data() return {matrix=transf.scaleRotZYXTransl(
      vec4.new(.15,.5,1,7), vec3.new(math.pi/2,0,0), vec3.new(2,3,4))} end''')
    matrix = result['matrix']
    assert matrix[0:4] == pytest.approx([0,.15,0,0])
    assert matrix[4:8] == pytest.approx([-.5,0,0,0])
    assert matrix[8:12] == [0,0,1,0]
    assert matrix[12:16] == [2,3,4,1]


@pytest.mark.parametrize('helper, method, args', [
    ('vec2', 'new', [1]), ('vec2', 'new', [1, True]),
    ('vec4', 'new', [1,2,3]), ('vec4', 'new', [1,2,3,float('nan')]),
    ('vec2', 'componentwiseMul', [{'x':1,'y':2},{'x':3,'y':4}]),
    ('vec4', 'execute', []),
    ('transf', 'scale', [{'x':1,'y':2,'z':3,'w':float('inf')}]),
    ('transf', 'scale', [{'x':1,'y':2,'z':3,'w':4,'extra':5}]),
])
def test_unverified_methods_wrong_shapes_and_nonfinite_vectors_remain_blocked(helper,method,args):
    with pytest.raises(ValueError):
        evaluate_math(helper,method,args)


def test_new_constructor_imports_do_not_admit_dynamic_vehicleutil_calls():
    with pytest.raises(ValueError, match='vehicleutil'):
        load_resource_table('''local vec2=require "vec2"
        local vehicleutil=require "vehicleutil"
        function data() return {animation=vehicleutil.makeCouplingRodAnim(vec2.new(0,.7))} end''')

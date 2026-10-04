"""Authored geometry checks for literal TF2 vector/matrix helper adapters."""
from copy import deepcopy
import math

import pytest

from trf3_mod_converter.lua_math import evaluate_math
from trf3_mod_converter.lua_metadata import UnsupportedValue


def call(method, *args):
    return evaluate_math('transf', method, list(args))


def vector(x, y, z):
    return evaluate_math('vec3', 'new', [x, y, z])


def point(matrix, xyz):
    return [sum(matrix[column * 4 + row] * xyz[column] for column in range(3)) + matrix[12 + row]
            for row in range(3)]


def test_named_vectors_degrees_and_negative_cessna_z_rotation():
    assert vector(2, 3, 4) == {'x': 2, 'y': 3, 'z': 4}
    rotation = call('degToRad', -90, 0, 0)
    assert rotation == {'x': -math.pi / 2, 'y': 0, 'z': 0}
    matrix = call('scaleRotZYXTransl', vector(1, 1, 1), rotation, vector(10, -4, 3))
    assert point(matrix, [2, 5, 7]) == pytest.approx([15, -6, 10])


def test_three_axis_nonuniform_scale_rotation_translation_order():
    rotation = call('degToRad', 90, 90, 90)
    matrix = call('scaleRotZYXTransl', vector(2, 3, 4), rotation, vector(10, 20, 30))
    # The X/Y/Z input axes become -Z/+Y/+X after Rx, then Ry, then Rz.
    assert point(matrix, [1, 0, 0]) == pytest.approx([10, 20, 28])
    assert point(matrix, [0, 1, 0]) == pytest.approx([10, 23, 30])
    assert point(matrix, [0, 0, 1]) == pytest.approx([14, 20, 30])
    assert point(matrix, [1, 2, 3]) == pytest.approx([22, 26, 28])
    assert matrix[12:16] == [10, 20, 30, 1]


def test_non_right_angle_composition_matches_independent_reference_columns():
    matrix = call('rotZYXTransl', call('degToRad', 60, 45, 30), vector(7, 8, 9))
    assert matrix == pytest.approx([
        0.3535533905932738, 0.6123724356957945, -0.7071067811865475, 0,
        -0.5732233047033631, 0.7391989197401166, 0.35355339059327373, 0,
        0.7391989197401165, 0.2803300858899106, 0.6123724356957946, 0,
        7, 8, 9, 1,
    ])


@pytest.mark.parametrize('axis,expected', [('X', [1, -3, 2]), ('Y', [3, 2, -1]), ('Z', [-2, 1, 3])])
def test_axis_rotations_use_radians_and_right_handed_axes(axis, expected):
    assert point(call('rot' + axis, math.pi / 2), [1, 2, 3]) == pytest.approx(expected)


def test_centered_y_rotation_keeps_pivot_then_applies_translation():
    pivot, translation = vector(3, 4, 5), vector(10, 20, 30)
    matrix = call('rotYCntTransl', math.pi / 2, pivot, translation)
    assert point(matrix, [3, 4, 5]) == pytest.approx([13, 24, 35])
    assert point(matrix, [4, 4, 5]) == pytest.approx([13, 24, 34])


def test_uniform_and_xyz_z_scales_preserve_unscaled_translation():
    translation = vector(11, 12, 13)
    assert point(call('rotZTransl', math.pi / 2, translation), [1, 2, 3]) == pytest.approx([9, 13, 16])
    assert point(call('scaleRotZTransl', 2, math.pi / 2, translation), [1, 2, 3]) == pytest.approx([7, 14, 19])
    assert point(call('scaleXYZRotZTransl', vector(-2, 3, 4), math.pi / 2, translation),
                 [1, 2, 3]) == pytest.approx([5, 10, 25])


def test_matrix_multiplication_column_constructor_and_y_reflection():
    columns = [{'x': 1, 'y': 0, 'z': 0, 'w': 0}, {'x': 0, 'y': 1, 'z': 0, 'w': 0},
               {'x': 0, 'y': 0, 'z': 1, 'w': 0}, {'x': 2, 'y': 3, 'z': 4, 'w': 1}]
    matrix = call('new', *columns)
    scaled = call('mul', matrix, call('scale', vector(2, 3, 4)))
    assert point(scaled, [1, 1, 1]) == [4, 6, 8]
    assert point(call('flipY', scaled), [1, 1, 1]) == [4, -6, 8]
    assert call('transl', vector(2, 3, 4)) == matrix


def test_vector_math_and_unit_angle_clamp_preserve_tf2_contract():
    a, b = vector(1, 2, 3), vector(4, -2, 1)
    args = deepcopy([a, b])
    assert evaluate_math('vec3', 'add', args) == vector(5, 0, 4)
    assert evaluate_math('vec3', 'sub', [a, b]) == vector(-3, 4, 2)
    assert evaluate_math('vec3', 'mul', [3, a]) == vector(3, 6, 9)
    assert evaluate_math('vec3', 'dot', [a, b]) == 3
    assert evaluate_math('vec3', 'cross', [a, b]) == vector(8, 11, -10)
    assert evaluate_math('vec3', 'length', [vector(3, 4, 12)]) == 13
    assert evaluate_math('vec3', 'distance', [a, b]) == pytest.approx(math.sqrt(29))
    assert evaluate_math('vec3', 'normalize', [vector(0, 3, 4)]) == vector(0, 0.6, 0.8)
    assert evaluate_math('vec3', 'angleUnit', [vector(1.0000001, 0, 0), vector(1, 0, 0)]) == 0
    assert evaluate_math('vec3', 'xyAngle', [vector(-1, 1, 100)]) == pytest.approx(3 * math.pi / 4)
    assert [a, b] == args


@pytest.mark.parametrize('helper,method,args', [
    ('transf', 'identity', []), ('transf', 'execute', []), ('vec3', 'setmetatable', []),
    ('custom', 'new', [1, 2, 3]), ('vec3', 'new', [1, 2]),
    ('vec3', 'new', [1, True, 3]), ('vec3', 'new', [1, float('nan'), 3]),
    ('vec3', 'new', [1, UnsupportedValue('script'), 3]),
    ('transf', 'scale', [[1, 2, 3]]), ('transf', 'rotX', ['90']),
    ('transf', 'mul', [[1, 2, 3], [1, 2, 3]]),
    ('transf', 'degToRad', [10 ** 1000, 0, 0]),
    ('vec3', 'normalize', [{'x': 0, 'y': 0, 'z': 0}]),
    ('vec3', 'mul', [1e308, {'x': 1e308, 'y': 0, 'z': 0}]),
])
def test_unknown_dynamic_malformed_or_nonfinite_math_is_a_blocker(helper, method, args):
    with pytest.raises(ValueError):
        evaluate_math(helper, method, args)

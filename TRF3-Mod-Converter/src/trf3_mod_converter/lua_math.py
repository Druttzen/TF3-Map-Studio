"""Pure literal adapters for the installed TF2 vec3/transf helper contracts.

No Lua source is loaded or executed here. The matrix implementation uses
standard column-major affine composition, authored independently from the
installed helper files inspected to establish names, arguments and conventions.

TF2's ``rotZYXTransl`` vector is ordered Z/Y/X: ``rot.x`` rotates about Z,
``rot.y`` about Y and ``rot.z`` about X. Angles are radians; ``degToRad``
converts degrees. Scaling acts before rotation and does not scale translation.
"""
from __future__ import annotations

import math


SCHEMA_SOURCES = (
    'https://wiki.transportfever2.com/doku.php?id=modding:constructionbasics',
    'https://wiki.transportfever2.com/doku.php?id=modding:resourcetypes:mdl',
)
VERIFIED_METHODS = {
    'vec3': frozenset({'new', 'add', 'sub', 'mul', 'dot', 'cross', 'length',
                       'distance', 'normalize', 'angleUnit', 'xyAngle'}),
    'transf': frozenset({'new', 'flipY', 'transl', 'scale', 'rotX', 'rotY', 'rotZ',
                        'rotYCntTransl', 'rotZTransl', 'scaleRotZTransl',
                        'scaleXYZRotZTransl', 'rotZYXTransl',
                        'scaleRotZYXTransl', 'degToRad', 'mul'}),
}
_IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
_AXES = ('x', 'y', 'z')


def _number(value, where):
    if type(value) not in (int, float):
        raise ValueError(f'{where}: expected a finite literal number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{where}: expected a finite literal number')
    return value


def _vector(value, where, *, dimension=3):
    fields = _AXES if dimension == 3 else (*_AXES, 'w')
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f'{where}: expected named components {fields}')
    return {field: _number(value[field], f'{where}/{field}') for field in fields}


def _matrix(value, where):
    if not isinstance(value, list) or len(value) != 16:
        raise ValueError(f'{where}: expected a column-major 16-number matrix')
    return [_number(item, where) for item in value]


def _multiply(left, right):
    # Each output column is the left matrix applied to a right-hand column.
    return [sum(left[k * 4 + row] * right[column * 4 + k] for k in range(4))
            for column in range(4) for row in range(4)]


def _translation(vector):
    result = list(_IDENTITY)
    result[12:15] = [vector[axis] for axis in _AXES]
    return result


def _scale(vector):
    result = list(_IDENTITY)
    for axis, index in zip(_AXES, (0, 5, 10)):
        result[index] = vector[axis]
    return result


def _rotation(axis, radians):
    result = list(_IDENTITY)
    cosine, sine = math.cos(radians), math.sin(radians)
    # The cyclic axis pair makes positive rotations right-handed.
    first, second = {'x': (1, 2), 'y': (2, 0), 'z': (0, 1)}[axis]
    result[first * 4 + first] = result[second * 4 + second] = cosine
    result[first * 4 + second] = sine
    result[second * 4 + first] = -sine
    return result


def _zyx_rotation_translation(rotation, translation):
    result = _translation(translation)
    for axis, angle in (('z', rotation['x']), ('y', rotation['y']), ('x', rotation['z'])):
        result = _multiply(result, _rotation(axis, angle))
    return result


def _arity(args, count, where):
    if len(args) != count:
        raise ValueError(f'{where}: expected {count} arguments, got {len(args)}')


def _vec3(method, args):
    where = 'vec3.' + method
    if method == 'new':
        _arity(args, 3, where)
        return {axis: _number(value, where) for axis, value in zip(_AXES, args)}
    if method in ('length', 'normalize', 'xyAngle'):
        _arity(args, 1, where)
        vector = _vector(args[0], where)
        if method == 'xyAngle':
            return math.atan2(vector['y'], vector['x'])
        length = math.sqrt(sum(vector[axis] ** 2 for axis in _AXES))
        if method == 'length':
            return length
        if length == 0:
            raise ValueError('vec3.normalize: zero vector has no finite normalization')
        return {axis: vector[axis] / length for axis in _AXES}
    _arity(args, 2, where)
    if method == 'mul':
        factor, vector = _number(args[0], where), _vector(args[1], where)
        return {axis: factor * vector[axis] for axis in _AXES}
    left, right = _vector(args[0], where), _vector(args[1], where)
    if method in ('add', 'sub'):
        sign = 1 if method == 'add' else -1
        return {axis: left[axis] + sign * right[axis] for axis in _AXES}
    if method == 'cross':
        return {axis: left[a] * right[b] - left[b] * right[a]
                for axis, a, b in (('x', 'y', 'z'), ('y', 'z', 'x'), ('z', 'x', 'y'))}
    if method == 'distance':
        return math.sqrt(sum((left[axis] - right[axis]) ** 2 for axis in _AXES))
    dot = sum(left[axis] * right[axis] for axis in _AXES)
    if method == 'angleUnit':
        # TF2 explicitly clamps round-off; it does not normalize inputs.
        return math.acos(max(-1, min(1, dot)))
    return dot


def _transf(method, args):
    where = 'transf.' + method
    if method == 'new':
        _arity(args, 4, where)
        columns = [_vector(column, where, dimension=4) for column in args]
        return [column[field] for column in columns for field in (*_AXES, 'w')]
    if method == 'degToRad':
        _arity(args, 3, where)
        return {axis: math.radians(_number(value, where)) for axis, value in zip(_AXES, args)}
    if method == 'mul':
        _arity(args, 2, where)
        return _multiply(_matrix(args[0], where), _matrix(args[1], where))
    if method == 'flipY':
        _arity(args, 1, where)
        matrix = _matrix(args[0], where)
        return [-value if index % 4 == 1 else value for index, value in enumerate(matrix)]
    if method in ('transl', 'scale'):
        _arity(args, 1, where)
        vector = _vector(args[0], where)
        return _translation(vector) if method == 'transl' else _scale(vector)
    if method in ('rotX', 'rotY', 'rotZ'):
        _arity(args, 1, where)
        return _rotation(method[-1].lower(), _number(args[0], where))
    if method == 'rotYCntTransl':
        _arity(args, 3, where)
        angle = _number(args[0], where)
        center, translation = _vector(args[1], where), _vector(args[2], where)
        shifted = {axis: center[axis] + translation[axis] for axis in _AXES}
        back = {axis: -center[axis] for axis in _AXES}
        return _multiply(_multiply(_translation(shifted), _rotation('y', angle)), _translation(back))
    if method in ('rotZYXTransl', 'scaleRotZYXTransl'):
        _arity(args, 2 if method == 'rotZYXTransl' else 3, where)
        rotation, translation = _vector(args[-2], where), _vector(args[-1], where)
        matrix = _zyx_rotation_translation(rotation, translation)
        return matrix if method == 'rotZYXTransl' else _multiply(matrix, _scale(_vector(args[0], where)))
    _arity(args, 2 if method == 'rotZTransl' else 3, where)
    angle, translation = _number(args[-2], where), _vector(args[-1], where)
    matrix = _multiply(_translation(translation), _rotation('z', angle))
    if method == 'rotZTransl':
        return matrix
    scale = (_vector(args[0], where) if method == 'scaleXYZRotZTransl'
             else {axis: _number(args[0], where) for axis in _AXES})
    return _multiply(matrix, _scale(scale))


def _finite_result(value, where):
    if isinstance(value, dict):
        for item in value.values():
            _finite_result(item, where)
    elif isinstance(value, list):
        for item in value:
            _finite_result(item, where)
    else:
        _number(value, where)
    return value


def evaluate_math(helper_name: str, method_name: str, literal_args: list):
    """Evaluate only a verified pure helper call with literal finite arguments.

    Vectors are named dictionaries, matrices are column-major lists of sixteen
    numbers. Unsupported methods, wrong argument shapes and non-finite results
    raise ``ValueError``. No module imports, Lua callbacks or metatables run.
    The installed TF2 helper has no ``transf.identity`` method; it is rejected.
    """
    if not isinstance(helper_name, str) or not isinstance(method_name, str):
        raise ValueError('Math helper and method names must be literal strings')
    if method_name not in VERIFIED_METHODS.get(helper_name, ()):
        raise ValueError(f'Unsupported mathematical helper method {helper_name}.{method_name}')
    if not isinstance(literal_args, list):
        raise ValueError('Mathematical helper arguments must be a literal list')
    try:
        result = _vec3(method_name, literal_args) if helper_name == 'vec3' else _transf(method_name, literal_args)
        return _finite_result(result, helper_name + '.' + method_name + ' result')
    except (OverflowError, ZeroDivisionError) as error:
        raise ValueError(f'{helper_name}.{method_name}: result is not finite') from error

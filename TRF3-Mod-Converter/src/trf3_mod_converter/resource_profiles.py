"""Evidence-based TF2 resource adapters; never execute a source Lua program.

The official TF3 resource/model/construction/infrastructure documentation and
the selected installation are the compatibility contract. Unknown fields and
arbitrary callbacks are blockers, not silently discarded functionality.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import operator
from pathlib import PurePosixPath
import re
from typing import Any

from luaparser import ast, astnodes as lua
from .lua_metadata import TranslatedString, UnsupportedValue, _value, record_duplicate_literal


CONFIG_ROOTS = {
    'multiple_unit': 'config/multiple_unit',
    'railroad_crossing': 'config/railroad_crossing',
    'auto_ground_texture': 'config/auto_ground_tex',
    'ground_texture': 'config/ground_texture',
    'terrain_material': 'config/terrain_material',
    'grass': 'config/grass', 'track': 'config/track', 'street': 'config/street',
    'bridge': 'config/bridge', 'tunnel': 'config/tunnel',
}
CONFIG_SUFFIXES = {
    'multiple_unit': '.mu.lua', 'railroad_crossing': '.rcr.lua',
    'auto_ground_texture': '.agt.lua', 'ground_texture': '.gtex.lua',
    'terrain_material': '.tmat.lua', 'grass': '.grass.lua',
    'track': '.street_template.lua', 'street': '.street_template.lua',
    'bridge': '.bridge.lua', 'tunnel': '.tunnel.lua',
}
RESEARCH_SOURCES = (
    'https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes',
    'https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mdl',
    'https://wiki.transportfever3.com/doku.php?id=modding:constructions:basics',
    'https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:tracksstreets',
    'https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:bridgestunnels',
    'https://wiki.transportfever3.com/doku.php?id=modding:environment:landscapeassets',
    'https://wiki.transportfever3.com/doku.php?id=modding:environment:terrainmaterials',
    'https://www.transportfever2.com/wiki/doku.php?id=modding:modcomponents',
    'https://www.transportfever2.com/wiki/doku.php?id=modding:externaltools',
    'https://github.com/eisfeuer/modutram',
    'https://github.com/eisfeuer/tpf2-modular-train-station',
)


@dataclass(frozen=True)
class ConstantCallback:
    result: Any


@dataclass(frozen=True)
class FiniteAssetCallback:
    result: dict
    selectors: list[dict]
    height: dict | None


class TranslatedConcat(TranslatedString):
    """Deferred localized concatenation; never flatten it to one language."""

    def __new__(cls, parts):
        parts = tuple(parts)
        encoded = json.dumps([(localized, value) for localized, value in parts],
                             ensure_ascii=False, separators=(',', ':'))
        key = 'tf2_concat_' + hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        result = super().__new__(cls, key)
        result.parts = parts
        return result

    def __getnewargs__(self):
        return (self.parts,)


def resolve_translation_concatenations(data, translations, audit=None, *, resource=''):
    """Materialize each translated expression separately for every locale.

    TF2 _() falls back to its literal key when that locale has no translation.
    Keep that same fallback for each fragment, plus an English fallback for a
    resource whose package supplies no localization table at all.
    """
    if not isinstance(translations, dict) or any(not isinstance(language, str)
            or not isinstance(table, dict) for language, table in translations.items()):
        raise ValueError('Localized concatenations need literal language/key/text tables')

    def visit(value):
        if isinstance(value, TranslatedConcat):
            _checked(value, 'localized concatenation')
            if not translations:
                translations['en'] = {}
            for language, table in translations.items():
                fragments = [table.get(part, part) if localized else part for localized, part in value.parts]
                if any(not isinstance(part, str) or isinstance(part, TranslatedConcat) for part in fragments):
                    raise ValueError(f'Localized concatenation has non-text translation: {language}')
                if sum(len(part.encode('utf-8')) for part in fragments) > _MAX_EXPANDED_BYTES:
                    raise ValueError('Localized concatenation exceeds the safe export limit')
                text = ''.join(fragments)
                if str(value) in table and table[str(value)] != text:
                    raise ValueError('Generated localized concatenation key conflicts with source translations')
                table[str(value)] = text
            if audit is not None:
                record = {'resource': resource, 'targetKey': str(value),
                          'fragments': [{'translated': flag, 'value': part} for flag, part in value.parts],
                          'policy': 'compose_translation_fragments_per_locale', 'nativeTest': 'not_run'}
                rows = audit.setdefault('translationMigrations', [])
                if record not in rows:
                    rows.append(record)
            return TranslatedString(value)
        if isinstance(value, ConstantCallback):
            return ConstantCallback(visit(value.result))
        if isinstance(value, FiniteAssetCallback):
            return FiniteAssetCallback(visit(value.result), visit(value.selectors), visit(value.height))
        if isinstance(value, BridgeFactory):
            return BridgeFactory(visit(value.params))
        if isinstance(value, AssetSelectionCallback):
            def parameter(item):
                return None if item is None else _BuilderParameter(visit(item.params), item.values, item.default_index)
            return AssetSelectionCallback(parameter(value.model), parameter(value.offset), value.rotate)
        if isinstance(value, list):
            return [visit(part) for part in value]
        if isinstance(value, dict):
            return {visit(key): visit(part) for key, part in value.items()}
        return value

    return visit(data)


def _same_literal(left, right):
    """Equality for duplicate authored values, with Lua/provenance types intact."""
    _check_graph(left, allow_behaviors=True)
    _check_graph(right, allow_behaviors=True)

    def same(a, b):
        if type(a) is not type(b):
            return False
        if isinstance(a, TranslatedConcat):
            return a.parts == b.parts
        if type(a) in (str, TranslatedString, bool, int, float, type(None)):
            return a == b
        if isinstance(a, dict):
            return len(a) == len(b) and all(key in b and same(value, b[key]) for key, value in a.items())
        if isinstance(a, list):
            return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
        if isinstance(a, ConstantCallback):
            return same(a.result, b.result)
        if isinstance(a, FiniteAssetCallback):
            return same(a.result, b.result) and same(a.selectors, b.selectors) and same(a.height, b.height)
        return False

    return same(left, right)


@dataclass(frozen=True)
class BridgeFactory:
    params: dict


@dataclass(frozen=True)
class _Helper:
    name: str


@dataclass(frozen=True)
class _LiteralFactory:
    parameters: tuple[str, ...]
    expression: Any
    captures: dict


@dataclass(frozen=True)
class _BuilderParameter:
    params: dict
    values: tuple
    default_index: int


@dataclass(frozen=True)
class AssetSelectionCallback:
    model: _BuilderParameter
    offset: _BuilderParameter | None
    rotate: bool


class _ResourceEnv(dict):
    def __init__(self, verified_helpers=(), *, audit=None, resource=''):
        super().__init__()
        self.verified_helpers = frozenset(verified_helpers)
        self.audit = audit
        self.resource = resource


def _child_env(env):
    return _ResourceEnv(getattr(env, 'verified_helpers', ()),
                        audit=getattr(env, 'audit', None), resource=getattr(env, 'resource', ''))


def _duplicate_is_alias_free(node, env):
    # Equal contents do not prove equal Lua table identity. A later permitted
    # local-table write could distinguish a captured table from a fresh one.
    for item in ast.walk(node):
        if isinstance(item, lua.Name) and item.id in env:
            if type(env[item.id]) not in (str, TranslatedString, TranslatedConcat, int, float, bool, type(None)):
                return False
    return True


PARAMBUILDER_SHA256 = '38e69b27f76f154ac9f2ca2eb528cc85eb5f7252f78683b9c19b4f41dedcdca9'


def verified_parambuilder_helper(old, payload):
    """Approve only the inspected helper bytes, not another module of that name."""
    return old == 'scripts/parambuilder_v1_1.lua' and hashlib.sha256(payload).hexdigest() == PARAMBUILDER_SHA256


# Canonical AST shapes observed in the inspected packages. A different branch,
# call, assignment, returned field, variable binding or literal stays blocked.
_ASSET_SELECTION_SHAPES = {
    'dc7f1b00180925ff0b73a4e2f565213c6b4974c5bf6e415b2760e6888ae2beba': (True, False),
    '3e03352667333134f0e47196a934b31863e617e610ddfd1bbf9082e186353667': (True, True),
    'd05fd3caa728b3dd9dd2629668f6266e680a98019ff9f47fbb730d622404507a': (False, False),
}


def _asset_selection_callback(node, env):
    if 'parambuilder_v1_1' not in getattr(env, 'verified_helpers', ()):
        return None
    shape = _ASSET_SELECTION_SHAPES.get(hashlib.sha256(ast.to_lua_source(node).encode('utf-8')).hexdigest())
    if shape is None:
        return None
    has_offset, rotate = shape
    model, offset = env.get('assetmodel'), env.get('positionx') if has_offset else None
    if (not isinstance(model, _BuilderParameter) or model.params.get('uiType') != 'ICON_BUTTON'
            or not model.values or any(not isinstance(path, str) or isinstance(path, TranslatedString)
                                     or not path.endswith('.mdl') for path in model.values)
            or has_offset and (not isinstance(offset, _BuilderParameter) or offset.params.get('uiType') != 'SLIDER'
                               or any(type(value) not in (int, float) for value in offset.values))
            or any(name in env for name in ('params', 'table', 'math'))
            or rotate and env.get('constructionutil') != _Helper('constructionutil')):
        raise ValueError('Asset selection callback has unverified or shadowed helper bindings')
    return AssetSelectionCallback(deepcopy(model), deepcopy(offset), rotate)


def _builder_call(name, values):
    if name == 'rangeSymm' and len(values) == 2:
        end, step = values
        _number(end, 'ParamBuilder range end', positive=True)
        _number(step, 'ParamBuilder range step', positive=True)
        if end / step > 4095:
            raise ValueError('ParamBuilder numeric range exceeds the safe limit')
        positive, value = [], 0.0
        # Reproduce the helper's repeated addition, inclusive tolerance and
        # symmetric insertion order instead of rounding source numeric values.
        while value <= end + step * .001 and len(positive) <= 4096:
            positive.append(value)
            value += step
        if len(positive) > 4096:
            raise ValueError('ParamBuilder numeric range exceeds the safe limit')
        return [-value for value in reversed(positive[1:])] + [0] + positive[1:]
    if name == 'Slider' and len(values) in (5, 6):
        key, title, choices, default, tooltip, *labels = values
        choices = _list(choices, 'ParamBuilder slider values')
        if any(type(choice) not in (int, float) for choice in choices):
            raise ValueError('ParamBuilder slider requires finite numeric values')
        for choice in choices:
            _number(choice, 'ParamBuilder slider value')
        display = labels[0] if labels else [format(choice, '.14g') for choice in choices]
        kind = 'SLIDER'
    elif name == 'IconButton' and len(values) == 6:
        key, title, display, choices, default, tooltip = values
        choices = _list(choices, 'ParamBuilder icon values')
        kind = 'ICON_BUTTON'
    else:
        raise ValueError(f'Unsupported ParamBuilder factory: {name}')
    display = _list(display, 'ParamBuilder display values')
    if (not isinstance(key, str) or isinstance(key, TranslatedString) or not key
            or not isinstance(title, str) or not isinstance(tooltip, str)
            or not choices or len(choices) != len(display) or len(choices) > 8191
            or any(not isinstance(label, str) for label in display)
            or type(default) not in (int, float) or not math.isfinite(default)
            or default != int(default) or not 0 <= default < len(choices)):
        raise ValueError('Invalid or unsupported ParamBuilder parameter metadata')
    return _BuilderParameter({'uiType': kind, 'key': key, 'name': title,
                              'tooltip': tooltip, 'values': deepcopy(display), 'defaultIndex': int(default)},
                             tuple(choices), int(default))


@dataclass(frozen=True)
class _FiniteIndex:
    key: str


def _finite_asset_callback(node):
    """Recognize literal asset choices, without running callback control flow.

    Each branch must append exactly one literal model, or choose uniformly from
    a literal model list. Height branches only replace one local numeric value.
    No loops, APIs, track state, captures, helper calls or arbitrary statements
    are admitted. Separate selectors retain their source order and RNG calls.
    """
    if len(node.args) != 1 or not isinstance(node.args[0], lua.Name) or node.args[0].id != 'params':
        raise ValueError('Finite asset selection requires one params argument')
    statements = node.body.body
    if not statements or not isinstance(statements[-1], lua.Return) or len(statements[-1].values) != 1:
        raise ValueError('Finite asset selection requires one final return')
    returned = statements[-1].values[0]
    if not isinstance(returned, lua.Name):
        raise ValueError('Finite asset selection must return its local result table')
    result_name, bindings, selectors, height = returned.id, {}, [], None
    height_name = None

    def parameter(expression):
        if (not isinstance(expression, lua.Index) or not isinstance(expression.value, lua.Name)
                or expression.value.id != 'params'):
            raise ValueError('Finite asset selection cannot read external or track state')
        key = expression.idx.id if expression.notation == lua.IndexNotation.DOT and isinstance(expression.idx, lua.Name) else _evaluate(expression.idx, {})
        if not isinstance(key, str) or not key:
            raise ValueError('Finite asset selection needs a literal parameter key')
        return key

    def index_parameter(expression):
        if isinstance(expression, lua.Name) and isinstance(bindings.get(expression.id), _FiniteIndex):
            return bindings[expression.id].key
        if isinstance(expression, lua.AddOp) and isinstance(expression.right, lua.Number) and expression.right.n == 1:
            return parameter(expression.left)
        raise ValueError('Finite model lookup requires a zero-based parameter plus one')

    def result_field(expression, field=None):
        return (isinstance(expression, lua.Index) and expression.notation == lua.IndexNotation.DOT
                and isinstance(expression.value, lua.Name) and expression.value.id == result_name
                and isinstance(expression.idx, lua.Name) and (field is None or expression.idx.id == field))

    def append_model(statement):
        if not isinstance(statement, lua.Assign) or len(statement.targets) != len(statement.values) or len(statement.targets) != 1:
            raise ValueError('Finite model branch must append exactly one model')
        target = statement.targets[0]
        if not isinstance(target, lua.Index) or not result_field(target.value, 'models'):
            raise ValueError('Finite model branch must append to its local result.models')
        index = target.idx
        if (not isinstance(index, lua.AddOp) or not isinstance(index.left, lua.ULengthOP)
                or not result_field(index.left.operand, 'models')
                or not isinstance(index.right, lua.Number) or index.right.n != 1):
            raise ValueError('Finite model branch requires a consecutive model append')
        return model_spec(statement.values[0])

    def model_spec(expression):
        if not isinstance(expression, lua.Table):
            raise ValueError('Finite model branches require literal model tables')
        fields = {}
        for field in expression.fields:
            if field.between_brackets or not isinstance(field.key, lua.Name) or field.key.id in fields:
                raise ValueError('Finite model tables need unique named fields')
            fields[field.key.id] = field.value
        _unknown(fields, {'id', 'transf', 'tag'}, 'finite construction model')
        if not {'id', 'transf'} <= set(fields):
            raise ValueError('Finite construction models require id and transform')
        identity, prefix = fields['id'], ''
        if isinstance(identity, lua.Concat):
            prefix = _evaluate(identity.left, bindings)
            identity = identity.right
            if not isinstance(prefix, str) or isinstance(prefix, TranslatedString):
                raise ValueError('Finite model prefix must be literal resource text')
        indexed, random = None, False
        if isinstance(identity, lua.Index) and isinstance(identity.idx, lua.Call):
            call = identity.idx
            if (not isinstance(call.func, lua.Index) or call.func.notation != lua.IndexNotation.DOT
                    or not isinstance(call.func.value, lua.Name) or call.func.value.id != 'math'
                    or not isinstance(call.func.idx, lua.Name) or call.func.idx.id != 'random'
                    or len(call.args) != 1 or not isinstance(call.args[0], lua.ULengthOP)
                    or not isinstance(identity.value, lua.Name) or not isinstance(call.args[0].operand, lua.Name)
                    or call.args[0].operand.id != identity.value.id):
                raise ValueError('Finite random choice must be uniform over its literal model array')
            ids = _evaluate(identity.value, bindings)
            random = True
        elif isinstance(identity, lua.Index):
            try:
                indexed = index_parameter(identity.idx)
            except ValueError:
                ids = [_evaluate(identity, bindings)]
            else:
                ids = _evaluate(identity.value, bindings)
        else:
            ids = [_evaluate(identity, bindings)]
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 256
                or any(not isinstance(value, str) or isinstance(value, TranslatedString) or not value.endswith('.mdl') for value in ids)):
            raise ValueError('Finite model choices require 1–256 literal model references')
        ids = [prefix + value for value in ids]
        transform = fields['transf']
        if not isinstance(transform, lua.Table) or len(transform.fields) != 16 or any(f.key is not None for f in transform.fields):
            raise ValueError('Finite model transform requires 16 consecutive literal values')
        matrix, slots = [], []
        for i, field in enumerate(transform.fields, 1):
            if height_name is not None and isinstance(field.value, lua.Name) and field.value.id == height_name:
                slots.append(i)
                matrix.append(height['default'])
            else:
                if height_name is not None and any(isinstance(n, lua.Name) and n.id == height_name for n in ast.walk(field.value)):
                    raise ValueError('Finite height must be used directly in its transform slot')
                matrix.append(_number(_evaluate(field.value, bindings), 'finite model transform'))
        model = {'transf': matrix}
        if 'tag' in fields:
            if height_name is not None and any(isinstance(n, lua.Name) and n.id == height_name for n in ast.walk(fields['tag'])):
                raise ValueError('Finite height is only supported in model transform slots')
            model['tag'] = _checked(_evaluate(fields['tag'], bindings), 'finite model tag')
        return {'ids': ids, 'random': random, 'model': model, 'heightSlots': slots}, indexed

    for statement in statements[:-1]:
        if isinstance(statement, lua.LocalAssign):
            if len(statement.targets) != len(statement.values) or len(statement.targets) != 1 or not isinstance(statement.targets[0], lua.Name):
                raise ValueError('Finite asset selection needs simple initialized local bindings')
            name, expression = statement.targets[0].id, statement.values[0]
            if name in bindings or name in {'params', 'require', '_', 'math', 'data', 'table'}:
                raise ValueError('Finite asset selection has a shadowed binding')
            if height_name is not None and any(isinstance(n, lua.Name) and n.id == height_name for n in ast.walk(expression)):
                raise ValueError('Finite height aliases require an explicit expression adapter')
            try:
                key = index_parameter(expression)
            except ValueError:
                bindings[name] = _checked(_evaluate(expression, bindings), 'finite local binding')
            else:
                bindings[name] = _FiniteIndex(key)
        elif isinstance(statement, lua.If):
            branches, current, key = [], statement, None
            while isinstance(current, (lua.If, lua.ElseIf)):
                condition = current.test
                if not isinstance(condition, lua.EqToOp):
                    raise ValueError('Finite asset selection supports equality branches only')
                branch_key, value = parameter(condition.left), _evaluate(condition.right, {})
                if type(value) is not int or not 0 <= value <= 8190 or key is not None and branch_key != key:
                    raise ValueError('Finite asset branches need one parameter and bounded integer choices')
                key = branch_key
                if len(current.body.body) != 1 or any(value == choice for choice, _ in branches):
                    raise ValueError('Finite asset branch must have one distinct operation')
                branches.append((value, current.body.body[0]))
                current = current.orelse
            if current is not None:
                raise ValueError('Finite asset selection cannot omit else behavior')
            first = branches[0][1]
            if isinstance(first, lua.Assign) and len(first.targets) == 1 and isinstance(first.targets[0], lua.Name):
                name, values = first.targets[0].id, {}
                if height is not None or name not in bindings or type(bindings[name]) not in (int, float):
                    raise ValueError('Finite height must replace one initialized numeric local')
                for choice, operation in branches:
                    if (not isinstance(operation, lua.Assign) or len(operation.targets) != len(operation.values)
                            or len(operation.targets) != 1 or not isinstance(operation.targets[0], lua.Name)
                            or operation.targets[0].id != name):
                        raise ValueError('Finite height branches must replace the same local')
                    values[choice] = _number(_evaluate(operation.values[0], {}), 'finite asset height')
                height_name, height = name, {'key': key, 'default': bindings[name], 'values': values}
            else:
                choices = {}
                for choice, operation in branches:
                    spec, indexed = append_model(operation)
                    if indexed is not None:
                        raise ValueError('Finite branches cannot couple another model parameter')
                    choices[choice] = spec
                selectors.append({'key': key, 'choices': choices, 'indexed': False})
        elif isinstance(statement, lua.Assign) and len(statement.targets) == len(statement.values) == 1:
            target = statement.targets[0]
            if result_field(target):
                field = target.idx.id
                if (result_name not in bindings or not isinstance(bindings[result_name], dict)
                        or field in bindings[result_name] or field == 'models' and selectors):
                    raise ValueError('Finite result fields must be initialized exactly once')
                if height_name is not None and any(isinstance(n, lua.Name) and n.id == height_name for n in ast.walk(statement.values[0])):
                    raise ValueError('Finite height is only supported inside selected model transforms')
                bindings[result_name][field] = _checked(_evaluate(statement.values[0], bindings), 'finite result field')
                if field == 'models' and bindings[result_name][field] not in ({}, []):
                    raise ValueError('Finite selectors require an initially empty models list')
            else:
                spec, indexed = append_model(statement)
                if indexed is None or spec['random']:
                    raise ValueError('Unconditional finite append requires one indexed model parameter')
                selectors.append({'key': indexed, 'choices': {i: {**deepcopy(spec), 'ids': [path]} for i, path in enumerate(spec['ids'])}, 'indexed': True})
        else:
            raise ValueError('Finite asset selection has unsupported statements or active behavior')
    result = bindings.get(result_name)
    if not isinstance(result, dict) or result.get('models') not in ({}, []) or not 1 <= len(selectors) <= 32:
        raise ValueError('Finite asset selection requires an empty literal result and 1–32 selectors')
    callback = FiniteAssetCallback(deepcopy(result), selectors, height)
    _check_graph(callback, allow_behaviors=True)
    return callback


_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_EXPANDED_NODES = 100_000
_MAX_EXPANDED_BYTES = 8 * 1024 * 1024
_MAX_TABLE_DEPTH = 128

# These stock TF2 modules only import utilities, declare local function/table
# exports, and return those exports. No imported function is invoked at module
# initialization. A lexical binding that is never read needs no output helper.
# The exporter separately rejects package-local helpers shadowing these names.
UNUSED_STOCK_HELPERS = frozenset({'constructionutil', 'colliderutil', 'laneutil', 'vehicleutil'})


def _check_graph(value: Any, where='resource', *, allow_behaviors=False):
    """Reject cycles and bound the expanded result while it is still a DAG.

    Repeated aliases are cheap to parse, but cloning/serialization expands each
    reference. Cache subtree sizes and count every occurrence before either
    operation, so a short chain cannot create an exponential output.
    """
    memo, active = {}, set()

    def visit(item, depth):
        if depth > _MAX_TABLE_DEPTH:
            raise ValueError(f'{where}: literal table depth exceeds the safe limit')
        if isinstance(item, UnsupportedValue):
            raise ValueError(f'{where}: {item.reason}')
        if isinstance(item, (ConstantCallback, FiniteAssetCallback, BridgeFactory, _Helper, AssetSelectionCallback)) and not allow_behaviors:
            raise ValueError(f'{where}: behavior has no verified adapter')
        identity = id(item)
        if identity in active:
            raise ValueError(f'{where}: cyclic literal tables cannot be exported')
        if identity in memo:
            nodes, size, height = memo[identity]
            if depth + height > _MAX_TABLE_DEPTH:
                raise ValueError(f'{where}: literal table depth exceeds the safe limit')
            return nodes, size, height
        if isinstance(item, dict):
            children = [part for pair in item.items() for part in pair]
            size = 2 + 4 * len(item)
        elif isinstance(item, list):
            children, size = item, 2 + len(item)
        elif isinstance(item, ConstantCallback):
            children, size = [item.result], 2
        elif isinstance(item, FiniteAssetCallback):
            children, size = [item.result, item.selectors, item.height], 2
        elif isinstance(item, BridgeFactory):
            children, size = [item.params], 2
        elif isinstance(item, AssetSelectionCallback):
            children = [item.model.params, list(item.model.values)]
            if item.offset is not None:
                children.extend([item.offset.params, list(item.offset.values)])
            size = 2
        elif isinstance(item, _Helper):
            children, size = [item.name], 2
        elif isinstance(item, str):
            # Account for worst-case Lua escaping without constructing output.
            children, size = [], 2 + 4 * len(item.encode('utf-8'))
        elif type(item) in (int, float):
            _number(item, where)
            children, size = [], len(str(item))
        elif item is None or type(item) is bool:
            children, size = [], 5
        else:
            raise ValueError(f'{where}: unsupported literal value {type(item).__name__}')
        nodes, height = 1, 0
        active.add(identity)
        for child in children:
            child_nodes, child_size, child_height = visit(child, depth + 1)
            nodes += child_nodes
            size += child_size
            height = max(height, child_height + 1)
            if nodes > _MAX_EXPANDED_NODES or size > _MAX_EXPANDED_BYTES:
                raise ValueError(f'{where}: expanded literal result exceeds the safe export limit')
        active.remove(identity)
        if nodes > _MAX_EXPANDED_NODES or size > _MAX_EXPANDED_BYTES:
            raise ValueError(f'{where}: expanded literal result exceeds the safe export limit')
        memo[identity] = nodes, size, height
        return nodes, size, height

    visit(value, 0)
    return value


def _checked(value: Any, where='resource'):
    return _check_graph(value, where)


def _unknown(data, allowed, where):
    if data == []: return
    if not isinstance(data, dict): raise ValueError(f'{where}: expected a named table')
    unknown = set(data) - set(allowed)
    if unknown: raise ValueError(f'{where}: unsupported fields {sorted(unknown,key=str)}; source preserved')


def _dict(value, where):
    if value == []: return {}
    if not isinstance(value, dict): raise ValueError(f'{where}: expected a named table')
    return value


def _list(value, where):
    if not isinstance(value, list): raise ValueError(f'{where}: expected a list')
    return value


def _number(value, where, *, positive=False):
    try: finite = type(value) in (int,float) and math.isfinite(value)
    except OverflowError: finite = False
    if not finite or (positive and value <= 0):
        raise ValueError(f'{where}: expected a {"positive " if positive else ""}finite number')
    return value


def _evaluate(node, env):
    """Bounded structural interpretation of pure expressions, not a Lua VM."""
    if isinstance(node, lua.Name):
        if node.id == 'math' and node.id not in env:
            return _Helper('math')
        if node.id not in env: raise ValueError(f'Dynamic/unbound Lua name: {node.id}')
        return env[node.id]
    if isinstance(node, lua.Table):
        result, index = {}, 1
        authored = {}
        for field in node.fields:
            if field.key is None: key, index = index, index + 1
            elif isinstance(field.key, lua.Name) and not field.between_brackets: key = field.key.id
            else: key = _evaluate(field.key, env)
            if type(key) not in (str, int): raise ValueError('Unsupported computed Lua table key')
            value = _evaluate(field.value, env)
            if key in result:
                if (not _same_literal(result[key], value)
                        or not _duplicate_is_alias_free(authored[key].value, env)
                        or not _duplicate_is_alias_free(field.value, env)):
                    raise ValueError(f'Duplicate Lua table key: {key}')
                record_duplicate_literal(getattr(env, 'audit', None), getattr(env, 'resource', ''),
                                         key, authored[key], field)
            result[key] = value
            authored.setdefault(key, field)
        # Keep empty tables mutable during straight-line evaluation. Replacing
        # an empty list with a dict on assignment would lose aliased bindings.
        if not result: return {}
        if all(type(k) is int for k in result) and set(result) == set(range(1, len(result) + 1)):
            return [result[i] for i in range(1, len(result) + 1)]
        return result
    if isinstance(node, lua.Index):
        data = _evaluate(node.value, env)
        key = node.idx.id if node.notation == lua.IndexNotation.DOT and isinstance(node.idx, lua.Name) else _evaluate(node.idx, env)
        if isinstance(data, _BuilderParameter) and key == 'params':
            return deepcopy(data.params)
        if isinstance(data, _Helper) and data.name == 'math' and key == 'pi':
            return math.pi
        if isinstance(data, list) and type(key) is int and 1 <= key <= len(data): return data[key-1]
        if isinstance(data, dict) and key in data: return data[key]
        raise ValueError('Unknown or dynamic Lua table lookup')
    ops = {lua.AddOp: operator.add, lua.SubOp: operator.sub, lua.MultOp: operator.mul,
           lua.FloatDivOp: operator.truediv, lua.ExpoOp: operator.pow}
    if type(node) in ops:
        left, right = _evaluate(node.left, env), _evaluate(node.right, env)
        _number(left, 'constant expression'); _number(right, 'constant expression')
        # Prevent pathological exponentiation, including huge integer results.
        if isinstance(node, lua.ExpoOp) and abs(right) > 1024: raise ValueError('Constant exponent is too large')
        try: result = ops[type(node)](left, right)
        except (ArithmeticError, ValueError) as error: raise ValueError('Invalid constant arithmetic') from error
        return _number(result, 'constant expression')
    if isinstance(node, lua.UMinusOp): return -_number(_evaluate(node.operand, env), 'constant expression')
    if isinstance(node, lua.Concat):
        left, right = _evaluate(node.left, env), _evaluate(node.right, env)
        if isinstance(left, TranslatedString) or isinstance(right, TranslatedString):
            if not isinstance(left, str) or not isinstance(right, str):
                raise ValueError('Translated concatenation needs literal text fragments')
            def parts(value):
                return value.parts if isinstance(value, TranslatedConcat) else ((isinstance(value, TranslatedString), str(value)),)
            fragments = parts(left) + parts(right)
            if len(fragments) > _MAX_EXPANDED_NODES or sum(len(part.encode('utf-8')) for _, part in fragments) > _MAX_EXPANDED_BYTES:
                raise ValueError('Translated concatenation exceeds the safe export limit')
            return TranslatedConcat(fragments)
        if not isinstance(left, str) or not isinstance(right, str): raise ValueError('Dynamic Lua concatenation')
        if len(left) + len(right) > _MAX_EXPANDED_BYTES:
            raise ValueError('Constant concatenation exceeds the safe export limit')
        return left + right
    if isinstance(node, lua.AnonymousFunction):
        for parameter in node.args:
            if not isinstance(parameter, lua.Name) or parameter.id in {'_', 'require', 'math', 'data'}:
                raise ValueError('Inline callback parameter shadows a built-in or uses unsupported varargs')
        if callback := _asset_selection_callback(node, env):
            return callback
        statements = node.body.body
        if not statements or not isinstance(statements[-1], lua.Return) or len(statements[-1].values) != 1:
            raise ValueError('Inline callback is dynamic; requires a manual TF3 script module port')
        # Captured locals could be mutated after the closure was declared. Only
        # callback-local literal bindings are safe to fold without emulating
        # lifecycle. No arguments or enclosing bindings enter this environment.
        try:
            result = _statements(statements, _child_env(env))
            return ConstantCallback(_checked(result, 'constant callback'))
        except ValueError as error:
            try:
                return _finite_asset_callback(node)
            except ValueError as finite_error:
                raise ValueError('Inline callback is dynamic; requires a manual TF3 script module port: ' + str(finite_error)) from error
    if isinstance(node, lua.Call):
        if isinstance(node.func, lua.Name) and isinstance(env.get(node.func.id), _LiteralFactory):
            factory = env[node.func.id]
            if len(node.args) != len(factory.parameters):
                raise ValueError('Literal resource factory needs exactly its declared arguments')
            arguments = [_checked(_evaluate(argument, env), 'literal factory argument') for argument in node.args]
            bindings = _child_env(env)
            bindings.update(factory.captures)
            bindings.update(zip(factory.parameters, arguments))
            return _checked(_evaluate(factory.expression, bindings), 'literal factory result')
        if isinstance(node.func, lua.Name) and node.func.id == '_' and len(node.args) == 1 and '_' not in env:
            value = _checked(_evaluate(node.args[0], env), 'translation key')
            if not isinstance(value, str): raise ValueError('Translation key must be a literal string')
            return TranslatedString(value)
        if isinstance(node.func, lua.Name) and node.func.id == 'require' and len(node.args) == 1 and 'require' not in env:
            helper = _value(node.args[0])
            approved = getattr(env, 'verified_helpers', ())
            if (helper in ('parambuilder_v1_1', 'parambuilder_v1_1.lua', 'constructionutil', 'constructionutil.lua')
                    and 'parambuilder_v1_1' in approved):
                return _Helper(str(helper).removesuffix('.lua'))
            if helper in ('bridgeutil', 'bridgeutil.lua', 'texutil', 'texutil.lua', 'vec2', 'vec2.lua', 'vec3', 'vec3.lua', 'vec4', 'vec4.lua', 'transf', 'transf.lua'):
                return _Helper(str(helper).removesuffix('.lua'))
            raise ValueError(f'Unknown Lua helper/API import: {helper}')
        if isinstance(node.func, lua.Index) and node.func.notation == lua.IndexNotation.DOT and isinstance(node.func.idx, lua.Name):
            helper, name = _evaluate(node.func.value, env), node.func.idx.id
            if isinstance(helper, _Helper) and helper.name == 'parambuilder_v1_1':
                return _builder_call(name, [_checked(_evaluate(value, env), 'ParamBuilder argument') for value in node.args])
            if isinstance(helper, _Helper) and helper.name in ('vec2','vec3','vec4','transf'):
                from .lua_math import evaluate_math
                return evaluate_math(helper.name, name, [_checked(_evaluate(v, env)) for v in node.args])
            if isinstance(helper, _Helper) and helper.name == 'math':
                values = [_number(_evaluate(v, env), 'constant math argument') for v in node.args]
                if name in ('rad','deg') and len(values) == 1:
                    return _number(math.radians(values[0]) if name == 'rad' else math.degrees(values[0]), 'constant math result')
                if name == 'pow' and len(values) == 2 and abs(values[1]) <= 1024:
                    try:
                        return _number(math.pow(*values), 'constant math result')
                    except (ArithmeticError,ValueError) as error:
                        raise ValueError('Invalid constant math expression') from error
                raise ValueError(f'Unsupported constant math call: {name}')
            if isinstance(helper, _Helper) and helper.name == 'bridgeutil' and name == 'makeDefaultUpdateFn' and len(node.args) == 1:
                return BridgeFactory(_dict(_checked(_evaluate(node.args[0], env)), 'bridge factory'))
            if isinstance(helper, _Helper) and helper.name == 'texutil' and name == 'makeMaterialIndexTexture' and len(node.args) == 3:
                values = [_evaluate(v, env) for v in node.args]
                if not isinstance(values[0], str) or any(v not in ('REPEAT', 'CLAMP_TO_EDGE') for v in values[1:]):
                    raise ValueError('Invalid material-index texture arguments')
                return dict(type='TWOD', fileName=values[0], magFilter='NEAREST', minFilter='NEAREST',
                            wrapS=values[1], wrapT=values[2], mipmapAlphaScale=0.0,
                            compressionAllowed=False, redGreen=False, scaleDownAllowed=False)
        raise ValueError('Dynamic or unsupported Lua API call; manual script port required')
    return _checked(_value(node, constant_numbers=True))


def _statements(statements, env, *, allow_return=True, allow_global_literals=False, audit=None, resource=''):
    result = None
    for i, statement in enumerate(statements):
        if isinstance(statement, lua.LocalFunction):
            if not isinstance(statement.name, lua.Name) or statement.name.id in {'require', '_', 'math', 'data'} or statement.name.id in env:
                raise ValueError('Shadowed or unsupported literal resource factory binding')
            parameters = statement.args
            if (len(parameters) > 16 or any(not isinstance(p, lua.Name) or p.id in {'require', '_', 'math', 'data'} for p in parameters)
                    or len({p.id for p in parameters}) != len(parameters)):
                raise ValueError('Unsupported literal resource factory parameters')
            body = statement.body.body
            if (len(body) != 1 or not isinstance(body[0], lua.Return) or len(body[0].values) != 1
                    or not isinstance(body[0].values[0], lua.Table)):
                raise ValueError('Literal resource factories must directly return one table without statements or side effects')
            expression = body[0].values[0]
            if any(isinstance(n, (lua.Call, lua.AnonymousFunction, lua.Function, lua.LocalFunction)) for n in ast.walk(expression)):
                raise ValueError('Literal resource factories cannot call functions or contain callbacks')
            # Captured literal tables retain their aliases, so later permitted
            # local-table assignments have the same value at the call site.
            # Calls inside the body are prohibited, preventing recursion.
            env[statement.name.id] = _LiteralFactory(tuple(p.id for p in parameters), expression, dict(env))
        elif isinstance(statement, lua.LocalAssign):
            if len(statement.targets) != len(statement.values) or any(not isinstance(t, lua.Name) for t in statement.targets):
                raise ValueError('Only simple initialized local Lua bindings can be folded')
            values = [_evaluate(v, env) for v in statement.values]
            for target, value in zip(statement.targets, values):
                if target.id in {'require','_','math','data'}:
                    raise ValueError(f'Shadowed Lua built-in/data binding: {target.id}')
                if target.id in env: raise ValueError(f'Shadowed helper/local binding: {target.id}')
                env[target.id] = value
        elif isinstance(statement, lua.Assign):
            if (allow_global_literals and len(statement.targets) == len(statement.values) == 1
                    and isinstance(statement.targets[0], lua.Name)):
                name = statement.targets[0].id
                if name in {'require', '_', 'math', 'data'}:
                    raise ValueError(f'Shadowed Lua built-in/data binding: {name}')
                env[name] = _checked(_evaluate(statement.values[0], env), 'literal translation binding')
                if audit is not None:
                    audit.setdefault('translationMigrations', []).append({
                        'resource': resource, 'sourceName': name, 'sourceValue': deepcopy(env[name]),
                        'policy': 'fold_literal_translation_binding', 'nativeTest': 'not_run'})
                continue
            if len(statement.targets) != 1 or len(statement.values) != 1 or not isinstance(statement.targets[0], lua.Index):
                raise ValueError('Only local table field assignments can be folded')
            target = statement.targets[0]
            if not isinstance(target.value, lua.Name) or target.value.id not in env:
                raise ValueError('Assignments must target a local literal table')
            key = target.idx.id if target.notation == lua.IndexNotation.DOT and isinstance(target.idx, lua.Name) else _evaluate(target.idx, env)
            if type(key) not in (int, str): raise ValueError('Invalid Lua assignment key')
            data = env[target.value.id]
            if data == []:
                data = env[target.value.id] = {}
            if not isinstance(data, dict): raise ValueError('Only named local table assignments are supported')
            data[key] = _evaluate(statement.values[0], env)
        elif allow_return and isinstance(statement, lua.Return) and len(statement.values) == 1 and i == len(statements)-1:
            result = _evaluate(statement.values[0], env)
        else:
            raise ValueError('Lua resource has dynamic statements or side effects; manual script port required')
    return result


def load_resource_table(text: str, *, allow_global_literals=False, audit=None, resource='', verified_helpers=()) -> dict:
    """Fold declarative resources and a narrow set of verified helper factories."""
    if len(text.encode('utf-8')) > _MAX_SOURCE_BYTES:
        raise ValueError('Lua resource exceeds the safe parser input limit')
    try: tree = ast.parse(text.lstrip('\ufeff'))
    except ast.SyntaxException as error: raise ValueError(f'Invalid Lua resource: {error}') from error
    except RecursionError as error: raise ValueError('Lua resource nesting exceeds the safe parser limit') from error
    statements = tree.body.body
    name_counts = {}
    for node in ast.walk(tree):
        if isinstance(node, lua.Name):
            name_counts[node.id] = name_counts.get(node.id, 0) + 1
    unused = set()
    for statement in statements:
        if (isinstance(statement, lua.LocalAssign) and len(statement.targets) == len(statement.values) == 1
                and isinstance(statement.targets[0], lua.Name)
                and statement.targets[0].id not in {'require', '_', 'math', 'data'}
                and name_counts.get(statement.targets[0].id) == 1):
            call = statement.values[0]
            if (isinstance(call, lua.Call) and isinstance(call.func, lua.Name) and call.func.id == 'require'
                    and len(call.args) == 1 and isinstance(call.args[0], lua.String)
                    and call.args[0].s.decode('utf-8').removesuffix('.lua') in UNUSED_STOCK_HELPERS):
                unused.add(id(statement))
    statements = [statement for statement in statements if id(statement) not in unused]
    functions = [s for s in statements if isinstance(s, lua.Function) and isinstance(s.name, lua.Name) and s.name.id == 'data']
    if len(functions) == 1:
        fn = functions[0]
        if statements[-1] is not fn or fn.args:
            raise ValueError('Resource must have one argument-free data function after literal imports')
        env = _ResourceEnv(verified_helpers, audit=audit, resource=resource)
        _statements(statements[:-1], env, allow_return=False)
        result = _statements(fn.body.body, env, allow_global_literals=allow_global_literals,
                             audit=audit, resource=resource)
    else:
        result = _statements(statements, _ResourceEnv(verified_helpers, audit=audit, resource=resource))
    _check_graph(result, allow_behaviors=True)
    def normalize(value):
        if isinstance(value,BridgeFactory): return BridgeFactory(normalize(value.params))
        if isinstance(value,ConstantCallback): return ConstantCallback(normalize(value.result))
        if isinstance(value,FiniteAssetCallback):
            # Choice maps use authored zero-based numbers. A map containing
            # only choice 1 is not a Lua array to normalize to a Python list.
            selectors = [{**selector, 'choices': {key:normalize(spec) for key,spec in selector['choices'].items()}}
                         for selector in value.selectors]
            return FiniteAssetCallback(normalize(value.result), selectors, deepcopy(value.height))
        if isinstance(value,list): return [normalize(v) for v in value]
        if isinstance(value,dict):
            if not value: return []
            if all(type(k) is int for k in value) and set(value) == set(range(1,len(value)+1)):
                return [normalize(value[i]) for i in range(1,len(value)+1)]
            return {k:normalize(v) for k,v in value.items()}
        return value
    return _dict(normalize(result), 'resource return')


def classify_resource(old: str) -> str:
    if old.startswith('construction/') and old.endswith('.con'): return 'construction'
    if old.startswith('construction/') and old.endswith('.module'): return 'module'
    for kind, root in CONFIG_ROOTS.items():
        roots = (root, root+'s') if kind in ('ground_texture','terrain_material') else (root,)
        if any(old.startswith(r+'/') for r in roots) and old.endswith('.lua'): return kind
    if old.startswith('config/sound_set/') and old.endswith('.lua'): return 'sound_set'
    if old.endswith('.mdl'): return 'model'
    if old.endswith(('.msh','.msh.blob','.mtl','.ani','.dds','.tga','.hdr','.wav','.ogg')): return 'render_resource'
    if old.endswith(('.lua','.tl','.script','.gs','.con','.module','.trf','.snd')): return 'script'
    return 'other'


def resource_target(old: str) -> str:
    """Rename resource endings; keep all subfolders and detect collisions upstream."""
    if not old or '\\' in old or ':' in old or old.startswith('/') or any(p in ('','.','..') for p in old.split('/')):
        raise ValueError(f'Unsafe resource path: {old}')
    normalized = '/'.join(re.sub(r'[^a-z0-9_.@-]+','_',p.lower()).strip('_') for p in old.split('/'))
    if any(p in ('', '.', '..') for p in normalized.split('/')):
        raise ValueError(f'Invalid resource path: {old}')
    if old.endswith('~') or old.endswith(('.msh_', '.msh.blob_')):
        # Preserve editor backups under an inert ending instead of turning
        # e.g. model.mdl~ into another live model.mdl.
        return normalized+'.editor_backup'
    kind = classify_resource(old)
    if kind in CONFIG_SUFFIXES:
        suffix = CONFIG_SUFFIXES[kind]
        return normalized if normalized.endswith(suffix) else normalized[:-4]+suffix
    if kind == 'construction': return normalized+'.lua'
    if kind == 'module': return normalized+'.lua'
    if kind == 'sound_set': return normalized[:-4]+'.snd.lua'
    return normalized


def capability_report(paths) -> dict:
    counts = {}
    for path in paths:
        kind = classify_resource(str(path)); counts[kind] = counts.get(kind,0)+1
    return {'resourceClasses':counts, 'nativeTest':'not_run',
            'automaticAdapters':['static_model','tree','rock','multiple_unit','railroad_crossing',
                                 'auto_ground_texture','ground_texture','terrain_material','grass',
                                 'track','street','default_bridge','constant_asset_construction'],
            'manualMigration':['arbitrary_scripts','dynamic_constructions','station/industry/depot functionality',
                               'custom_modules','portal_only_tunnels','custom_cargo_economy'],
            'evidenceSources':list(RESEARCH_SOURCES)}


def _nodes(root):
    yield root
    for child in _list(root.get('children',[]), 'node children'):
        yield from _nodes(_dict(child, 'child node'))


def port_static_model(data: dict, resolve, native=None) -> dict:
    """Convert version-one render assets, including known tree/rock menu metadata."""
    from .model_common import port_common_metadata, resolve_nodes

    result = deepcopy(_checked(data))
    _unknown(result, {'version','boundingInfo','collider','lods','metadata'}, 'static model')
    if result.get('version') != 1: raise ValueError('Expected TF2 version-one static model')
    metadata = _dict(result.get('metadata',{}), 'static metadata'); result['metadata'] = metadata
    _unknown(metadata, {'availability','cost','description','maintenance','category','categoryList','order',
                        'tree','rock','autoGroundTex','cameraConfig','labelList'}, 'static model metadata')
    lods = _list(result.get('lods'), 'model LODs')
    if not lods: raise ValueError('Static model requires at least one LOD')
    first = []
    for li,lod in enumerate(lods):
        _unknown(lod, {'node','static','visibleFrom','visibleTo','textureLodBase'}, 'LOD')
        nodes = list(_nodes(_dict(lod.get('node'), 'LOD node')))
        names = set()
        for index,node in enumerate(nodes):
            _unknown(node, {'name','mesh','materials','transf','children','animations','skin','skinMaterials'}, 'node')
            name = node.get('name') or f'node_{index}'
            if not isinstance(name,str): raise ValueError('Static node name must be a string')
            if name in names and ('mesh' in node or 'skin' in node): name += '_mesh'
            if name in names: raise ValueError(f'Ambiguous static node name {name!r} in LOD {li}')
            names.add(name); node['name'] = name
            for field in ('materials','skinMaterials'):
                if field in node: _list(node[field],field)
        resolve_nodes([nodes],resolve)
        if li == 0: first = nodes
    metadata = port_common_metadata(metadata,first,resolve,native=native)
    result['metadata'] = metadata
    if 'maintenance' in metadata:
        maintenance = _dict(metadata['maintenance'], 'maintenance')
        _unknown(maintenance, {'lifespan','runningCosts','runningCostScale'}, 'maintenance')
        if 'lifespan' in maintenance:
            lifespan = _number(maintenance['lifespan'], 'maintenance/lifespan')
            if lifespan < 0: raise ValueError('maintenance/lifespan must be nonnegative')
            # TF2 counts half-days; TF3 model resources count quarter-days.
            maintenance['lifespan'] = _number(lifespan * 2, 'TF3 maintenance/lifespan')
        metadata['maintenance'] = maintenance
    description = _dict(metadata.get('description',{}),'description')
    _unknown(description, {'name','description','icon','previewIcon'}, 'static description')
    for key in ('icon','previewIcon'):
        if description.get(key): description[key] = resolve(description[key],'texture')
    for marker in ('tree','rock'):
        if marker in metadata and metadata[marker] not in ({},[]):
            raise ValueError(f'Non-empty {marker} metadata has no verified adapter')
    category = metadata.pop('category',{})
    _unknown(category, {'categories'}, 'static category')
    categories = _dict(category,'static category').get('categories',[])
    order = metadata.pop('order',{})
    _unknown(order, {'value'}, 'static order')
    order_value = _dict(order,'static order').get('value',0)
    if categories or 'tree' in metadata or 'rock' in metadata or order:
        menu = 'landscaping_vegetation' if 'tree' in metadata else 'landscaping_assets'
        filters = ['tree'] if 'tree' in metadata else ['rock'] if 'rock' in metadata else []
        if set(categories) - {'tree','rock','asset'}: raise ValueError('Unknown static menu categories require a menu mapping')
        metadata['menuCategory'] = {'categories':[{'category':menu,'filterCategories':filters,'order':order_value}]}
    category_list = _dict(metadata.get('categoryList',{}),'categoryList')
    _unknown(category_list,{'categories'},'categoryList')
    if category_list:
        category_list['categories'] = [v[:-4] if v.endswith('.clima.lua') else v for v in category_list.get('categories',[])]
    result['version'] = 2
    return result


def _common(data, *, menu=None):
    result = deepcopy(data)
    description = _dict(result.pop('description',{}), 'description')
    for old,new in [('name','name'),('desc','description'),('icon','icon')]:
        if old in result:
            if new in description: raise ValueError(f'Conflicting legacy and structured {new}')
            description[new] = result.pop(old)
    if description: result['description'] = description
    availability = _dict(result.pop('availability',{}), 'availability')
    for key in ('yearFrom','yearTo'):
        if key in result:
            if key in availability: raise ValueError(f'Conflicting {key}')
            availability[key] = result.pop(key)
    if availability: result['availability'] = availability
    order = result.pop('order',0)
    if menu: result['menuCategory'] = {'categories':[{'category':menu,'filterCategories':[],'order':order}]}
    elif order: result['menuCategory'] = {'categories':[{'order':order}]}
    return result


def _icon_paths(result, resolve):
    description = _dict(result.get('description',{}),'description')
    _unknown(description, {'name','description','icon','previewIcon'},'description')
    for key in ('icon','previewIcon'):
        if description.get(key): description[key] = resolve(description[key],'texture')


def _material_map(data, resolve):
    result = deepcopy(_dict(data,'materials'))
    for key,value in result.items():
        if isinstance(value,str): result[key] = resolve(value,'material') if value else value
        else:
            _unknown(value, {'name','size','reversed'}, 'material slot')
            if value and value.get('name'): value['name'] = resolve(value['name'],'material')
    return result


def _assets(data,resolve):
    # Native street asset slots have stable keys, which bridge overrides address.
    if isinstance(data,list): data = {f'asset_{i+1}':v for i,v in enumerate(data)}
    result = deepcopy(_dict(data,'assets'))
    for key,value in result.items():
        _unknown(value, {'name','offset','distance','prob','offsetOrth','randRot','oneSideOnly',
                         'alignToElevation','avoidFaceEdges','placeOnBridge'},'asset slot')
        if value and value.get('name'): value['name'] = resolve(value['name'],'model')
    return result


def port_config(old: str, data: dict, resolve, native=None) -> dict:
    """Adapt one resource whose schema needs no additional emitted resources."""
    kind = classify_resource(old)
    result = deepcopy(_checked(data))
    if kind == 'multiple_unit':
        _unknown(result, {'vehicles','name','desc','filterTags','groupFileName'},kind)
        for vehicle in _list(result.get('vehicles'), 'multiple-unit vehicles'):
            _unknown(vehicle, {'name','forward'}, 'multiple-unit vehicle')
            if type(vehicle.get('forward')) is not bool: raise ValueError('Multiple-unit direction must be a boolean')
            vehicle['name'] = resolve(vehicle['name'],'model')
        if not result['vehicles']: raise ValueError('Multiple unit has no vehicles')
        result.setdefault('filterTags',['default'])
        if 'groupFileName' in result:
            parent = result['groupFileName']
            if not isinstance(parent, str) or isinstance(parent, TranslatedString):
                raise ValueError('Multiple-unit groupFileName must be a literal resource reference')
            if parent:
                if parent.endswith('.mdl'):
                    result['groupFileName'] = resolve(parent, 'model')
                elif parent.endswith('.lua'):
                    result['groupFileName'] = resolve(parent, 'multiple_unit')
                else:
                    raise ValueError('Multiple-unit groupFileName must refer to a model or multiple unit')
    elif kind == 'railroad_crossing':
        _unknown(result, {'name','desc','icon','yearFrom','yearTo','order','soundFileName','config','speedLimit','cost'},kind)
        result = _common(result); _icon_paths(result,resolve)
        if result.get('soundFileName'): result['soundFileName'] = resolve(result['soundFileName'],'audio')
        for config in _list(result.get('config',[]),'crossing config'):
            _unknown(config, {'model','modelLeft','modelRight','streetWidth'}, 'crossing model config')
            for key in ('model','modelLeft','modelRight'):
                if config.get(key): config[key] = resolve(config[key],'model')
    elif kind == 'auto_ground_texture':
        _unknown(result, {'category','gridSize','countFrom','countTo','groundTex','individual','individualCategory'},kind)
        result['groundTex'] = resolve(result['groundTex'],'ground_texture')
    elif kind == 'ground_texture':
        _unknown(result, {'texture','texSize','materialIndexMap','priority'},kind)
        texture = _dict(result.get('texture'), 'ground texture sampler')
        _unknown(texture, {'type','fileName','magFilter','minFilter','wrapS','wrapT','mipmapAlphaScale',
                           'compressionAllowed','redGreen','scaleDownAllowed'},'ground texture sampler')
        reference = texture['fileName']
        if reference.startswith('res/textures/'): reference = reference[len('res/textures/'):]
        texture['fileName'] = resolve(reference,'texture')
        materials = result.get('materialIndexMap',{})
        if isinstance(materials,list): materials = {i+1:v for i,v in enumerate(materials)}
        materials = _dict(materials,'materialIndexMap')
        if any(type(i) is not int or not 0 <= i <= 255 for i in materials): raise ValueError('Material mask values must be bytes')
        result['materialIndexMap'] = {i:resolve(v,'terrain_material') for i,v in materials.items()}
    elif kind == 'terrain_material':
        _unknown(result, {'name','desc','icon','previewIcon','categories','order','priority','grass','detailColorTexture',
                          'detailMetalGlossAoHTexture','detailNormalTexture','overlayTexture','detailSize','overlaySize',
                          'overlayStrength','hOffset','categoryList'},kind)
        result = _common(result,menu='landscaping_ground')
        # Preserve old category tags as filters, rather than inventing new ones.
        categories = result.pop('categories',[])
        result['menuCategory']['categories'][0]['filterCategories'] = categories
        if 'previewIcon' in result: result.setdefault('description',{})['previewIcon'] = result.pop('previewIcon')
        _icon_paths(result,resolve)
        for key in ('detailColorTexture','detailMetalGlossAoHTexture','detailNormalTexture','overlayTexture'):
            if result.get(key): result[key] = resolve(result[key],'texture')
        if result.get('grass'): result['grass'] = resolve(result['grass'],'grass')
    elif kind == 'grass':
        _unknown(result, {'colorTexture','metalGlossAoTexture','normalTexture','translucencyTexture','width','height',
                          'density','lodDistance','assets','materials'},kind)
        if result.pop('materials',[]): raise ValueError('Grass material associations must be migrated on terrain materials')
        for key in ('colorTexture','metalGlossAoTexture','normalTexture','translucencyTexture'):
            if result.get(key): result[key] = resolve(result[key],'texture')
        for asset in result.get('assets',[]):
            _unknown(asset, {'filePath','density','scaleMin','scaleMax'},'grass asset')
            asset['filePath'] = resolve(asset['filePath'],'model')
    else:
        raise ValueError(f'{kind}: no single-resource adapter; use port_resource or migrate behavior manually')
    return result


_SLOPES = {'maxSlope','maxSlopeBuild','maxSlopeShape','slopeBuildSteps','embankmentSlopeLow','embankmentSlopeHigh'}
_TRACK_GEOMETRY = {'shapeStep','shapeSleeperStep','ballastHeight','ballastCutOff','sleeperBase','sleeperLength',
                   'sleeperWidth','sleeperHeight','sleeperCutOff','railTrackWidth','railBase','railHeight','railWidth','railCutOff'}
_CATENARY = {'catenaryBase','catenaryHeight','catenaryPoleDistance','catenaryMaxPoleDistanceFactor',
             'catenaryMinPoleDistanceFactor','catenaryPoleModel','catenaryMultiPoleModel',
             'catenaryMultiGirderModel','catenaryMultiInnerPoleModel'}
_TRACK_MODELS = {'railModel','sleeperModel','bumperModel','switchSignalModel','trackStraightModel'}
_TRACK_MATERIALS = {'ballastMaterial','sleeperMaterial','railMaterial','catenaryMaterial'}


def _catenary(data,resolve):
    result = {}
    for key,value in data.items():
        if key not in _CATENARY: continue
        target = {'catenaryMaxPoleDistanceFactor':'catenaryMaxPoleDistance',
                  'catenaryMinPoleDistanceFactor':'catenaryMinPoleDistance'}.get(key,key)
        result[target] = resolve(value,'model') if key.endswith('Model') else deepcopy(value)
    return result


def _track_documents(data, resolve, reference):
    allowed = (_SLOPES | _TRACK_GEOMETRY | _CATENARY | _TRACK_MODELS | _TRACK_MATERIALS |
               {'name','desc','icon','yearFrom','yearTo','order','shapeWidth','trackDistance','speedLimit','speedCoeffs',
                'minCurveRadius','minCurveRadiusBuild','fillGroundTex','borderGroundTex','cost','maintenanceCost','categories',
                'tunnelWallMaterial','tunnelHullMaterial'})
    _unknown(data,allowed,'track')
    if data.get('tunnelWallMaterial') or data.get('tunnelHullMaterial'):
        raise ValueError('TF2 track tunnel wall/hull overrides require a separate TF3 tunnel adapter; no override was dropped')
    template = _common({k:v for k,v in data.items() if k in _SLOPES | {'name','desc','icon','yearFrom','yearTo','order',
                                      'trackDistance','speedCoeffs','minCurveRadius','minCurveRadiusBuild','cost','maintenanceCost'}},menu='tracks')
    _icon_paths(template,resolve)
    speed = _number(data.get('speedLimit'),'track speedLimit',positive=True)
    width = _number(data.get('shapeWidth'),'track shapeWidth',positive=True)
    height = _number(data.get('railBase',0),'railBase') + _number(data.get('railHeight',0),'railHeight')
    template.update(roadType='TRACK',streetStyle=reference[:-len('.street_template')]+'.street',
                    laneConfigs=[dict(forward=True,height=height,offset=0,speed=speed,transportModes=['TRAIN','TRAM_TRACK'],width=width)])
    for key in ('fillGroundTex','borderGroundTex'):
        if data.get(key): template[key] = resolve(data[key],'ground_texture')
    style = {'roadType':'TRACK',**{k:deepcopy(v) for k,v in data.items() if k in _TRACK_GEOMETRY | {'trackDistance'}}}
    if data.get('categories'): style['categoryList'] = {'categories':data['categories']}
    for key in _TRACK_MODELS:
        if key in data:
            style[key] = [resolve(r,'model') for r in data[key]] if isinstance(data[key],list) else resolve(data[key],'model')
    style['materials'] = {k:resolve(data[k],'material') for k in _TRACK_MATERIALS - {'ballastMaterial'} if data.get(k)}
    if data.get('ballastMaterial'):
        # TF3's installed standard/high-speed style contract uses a material
        # tile descriptor. Its native 7 m tile replaces TF2's implicit scaling.
        style['materials']['ballast'] = {'name':resolve(data['ballastMaterial'],'material'),'size':[7,7]}
    docs = {'.street_template.lua':template,'.street.lua':style}
    catenary = _catenary(data,resolve)
    if catenary:
        electric = deepcopy(template); electric_style = deepcopy(style)
        electric_style['catenary'] = catenary
        electric['streetStyle'] = reference[:-len('.street_template')]+'_catenary.street'
        electric['laneConfigs'][0]['transportModes'] += ['ELECTRIC_TRAIN','ELECTRIC_TRAM_TRACK']
        electric['catenaryRemove'] = reference
        template['catenaryAdd'] = reference[:-len('.street_template')]+'_catenary.street_template'
        docs['_catenary.street_template.lua'] = electric; docs['_catenary.street.lua'] = electric_style
    return docs


def _street_documents(data,resolve,reference):
    allowed = (_SLOPES | _CATENARY | {'name','desc','icon','yearFrom','yearTo','order','categories','numLanes',
               'streetWidth','sidewalkWidth','sidewalkHeight','speed','aiLock','country','priority','transportModesStreet',
               'transportModesSidewalk','busAndTramRight','defaultWithCrosswalk','pedestrianWalkPenalty','simBuildable',
               'borderGroundTex','streetFillGroundTex','sidewalkFillGroundTex','materials','assets','cost','maintenanceCost',
               'oneWay','laneConfig'})
    _unknown(data,allowed,'street')
    if data.get('laneConfig'): raise ValueError('Custom TF2 laneConfig requires explicit TF3 lane remapping')
    num = data.get('numLanes')
    if type(num) is not int or not 1 <= num <= 16: raise ValueError('Street numLanes must be 1–16')
    if num % 2 and num > 1 and not data.get('oneWay'): raise ValueError('Asymmetric two-way lanes require explicit lane mapping')
    width = _number(data.get('streetWidth'),'streetWidth',positive=True)
    sidewalk = _number(data.get('sidewalkWidth',0),'sidewalkWidth')
    if sidewalk < 0: raise ValueError('Negative sidewalkWidth')
    speed = _number(data.get('speed'),'street speed',positive=True)/3.6
    road_modes = deepcopy(data.get('transportModesStreet',['CAR','BUS','TRUCK']))
    foot_modes = deepcopy(data.get('transportModesSidewalk',['PERSON']))
    modes = {'CAR','BUS','TRUCK','TRAM','ELECTRIC_TRAM','PERSON','CARGO','SMALL_AIRCRAFT','AIRCRAFT'}
    if any(m not in modes for m in road_modes+foot_modes): raise ValueError('Unknown street transport mode')
    menu = 'roads_country' if data.get('country') else 'roads_small' if num <= 3 else 'roads_medium' if num <= 5 else 'roads_large'
    template_keys = _SLOPES | {'name','desc','icon','yearFrom','yearTo','order','aiLock','country','priority','busAndTramRight',
                    'defaultWithCrosswalk','pedestrianWalkPenalty','simBuildable','cost','maintenanceCost','transportModesStreet'}
    template = _common({k:v for k,v in data.items() if k in template_keys},menu=menu); _icon_paths(template,resolve)
    lanes = []
    if sidewalk and foot_modes:
        lanes.append(dict(forward=False,height=data.get('sidewalkHeight',0),offset=0,speed=speed,transportModes=foot_modes,width=sidewalk))
    for index in range(num):
        lanes.append(dict(forward=bool(data.get('oneWay') or num == 1 or index >= num/2),height=0,offset=0,
                          speed=speed,transportModes=road_modes,width=width/num))
    if sidewalk and foot_modes:
        lanes.append(dict(forward=True,height=data.get('sidewalkHeight',0),offset=0,speed=speed,transportModes=foot_modes,width=sidewalk))
    template.update(roadType='STREET',streetStyle=reference[:-len('.street_template')]+'.street',laneConfigs=lanes)
    for old,new in [('borderGroundTex','borderGroundTex'),('streetFillGroundTex','fillGroundTex'),('sidewalkFillGroundTex','sidewalkFillGroundTex')]:
        if data.get(old): template[new] = resolve(data[old],'ground_texture')
    style = {'roadType':'STREET','materials':_material_map(data.get('materials',{}),resolve),'assets':_assets(data.get('assets',{}),resolve)}
    catenary = _catenary(data,resolve)
    if catenary:
        style['catenary'] = catenary
    if data.get('categories'): style['categoryList'] = {'categories':data['categories']}
    return {'.street_template.lua':template,'.street.lua':style}


def _bridge_document(data,resolve,native,model_bounds):
    allowed = {'name','desc','icon','yearFrom','yearTo','order','carriers','speedLimit','cost','maintenanceCost','costFactors',
               'isAutoSelectable','pillarLen','pillarWidth','pillarMinDist','pillarMaxDist','pillarTargetDist','ignoreWaterCollision',
               'pillarGroundTexture','pillarGroundTextureOffset','abutmentLen','abutmentWidth','noParallelStripSubdivision',
               'autoGeneration','materialsToReplace','assetsToReplace','sidewalkHeight','updateFn'}
    _unknown(data,allowed,'bridge')
    factory = data.get('updateFn')
    if not isinstance(factory,BridgeFactory): raise ValueError('Bridge requires the verified bridgeutil.makeDefaultUpdateFn literal factory')
    if native is None or model_bounds is None: raise ValueError('Bridge requires installed TF3 scripts and verified source model bounds')
    config = deepcopy(factory.params)
    layers = {'pillarBase','pillarRepeat','pillarTop','railingBegin','railingRepeat','railingEnd','abutmentBase','abutmentRepeat','abutmentTop'}
    _unknown(config,layers | {'alwaysAddRailingBeginEnd'},'default bridge configuration')
    if not {'pillarBase','pillarRepeat','pillarTop','railingBegin','railingRepeat','railingEnd'} <= set(config):
        raise ValueError('Bridge factory has incomplete pillar/railing layers')
    for layer in layers & set(config):
        models = _list(config[layer],'bridge layer')
        allowed_lengths = (0,3,5,8) if layer.startswith('railing') else (1,2,3)
        if len(models) not in allowed_lengths: raise ValueError(f'Unsupported bridge {layer} model count')
        converted = []
        for reference in models:
            bounds = model_bounds(reference)
            if not isinstance(bounds,dict) or not {'bbMin','bbMax'} <= set(bounds): raise ValueError('Bridge model bounds are missing')
            minimum,maximum = bounds['bbMin'],bounds['bbMax']
            if any(not isinstance(v,list) or len(v) != 3 for v in (minimum,maximum)): raise ValueError('Invalid bridge model bounds')
            for v in minimum+maximum: _number(v,'bridge model bounds')
            if any(a > b for a,b in zip(minimum,maximum)): raise ValueError('Inverted bridge model bounds')
            converted.append([resolve(reference,'model'),[minimum,maximum]])
        config[layer] = converted
    result = _common({k:v for k,v in data.items() if k != 'updateFn'}); _icon_paths(result,resolve)
    result['updateScript'] = {'fileName':native.reference('infrastructure/bridge/bridge.script@cement.updateFn'),'params':config}
    if result.get('pillarGroundTexture'): result['pillarGroundTexture'] = resolve(result['pillarGroundTexture'],'ground_texture')
    if 'materialsToReplace' in result: result['materialsToReplace'] = _material_map(result['materialsToReplace'],resolve)
    if 'assetsToReplace' in result: result['assetsToReplace'] = _assets(result['assetsToReplace'],resolve)
    return result


def _asset_track_snap():
    # TF3 replaces the legacy ASSET_TRACK construction type with a snap point
    # on the returned construction, outside its decorative subconstruction.
    return {'transf': [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
            'snapToBaseEdgeTypes': ['TRACK'], 'placeAtTerrainHeight': False}


def _constant_construction(data,resolve,script_reference):
    allowed = {'type','description','availability','order','categories','params','updateFn','skipCollision','autoRemovable',
               'buildMode','keepBuildings','heightModView'}
    _unknown(data,allowed,'construction')
    if data.get('type') not in ('ASSET_DEFAULT', 'ASSET_TRACK'):
        raise ValueError('Functional construction needs subconstruction/station/industry/depot migration')
    callback = data.get('updateFn')
    if not isinstance(callback,ConstantCallback): raise ValueError('Asset construction requires a constant-return updateFn')
    result = deepcopy(_dict(callback.result,'asset result'))
    _unknown(result, {'models','groundFaces','terrainAlignmentLists','cost','colliders'}, 'asset construction result')
    for model in result.get('models',[]):
        _unknown(model, {'id','transf','tag'},'construction model')
        model['id'] = resolve(model['id'],'model')
    for face in result.get('groundFaces',[]):
        _unknown(face, {'face','modes','loop','alignmentOffsetMode','alignmentDirMode','alignmentOffset','alignmentDir'},'ground face')
        for mode in face.get('modes',[]):
            _unknown(mode, {'type','key','texCoords'},'ground face mode')
            mode['key'] = resolve(mode['key'],'ground_texture')
    for alignment in result.get('terrainAlignmentLists',[]):
        _unknown(alignment, {'type','faces','slopeLow','slopeHigh','triangles','optional'},'terrain alignment')
    output = _common({k:v for k,v in data.items() if k not in ('type','updateFn','categories','keepBuildings')},menu='landscaping_assets')
    _icon_paths(output,resolve)
    if 'keepBuildings' in data: output['keepBuildingsAndFields'] = data['keepBuildings']
    # Legacy categories are filter tags, not an API/script behavior change.
    if data.get('categories'): output['menuCategory']['categories'][0]['filterCategories'] = data['categories']
    for parameter in output.get('params',[]):
        _unknown(parameter, {'key','name','tooltip','values','defaultIndex','uiType','yearFrom','yearTo'},'construction parameter')
        values = _list(parameter.get('values'), 'parameter values')
        default = parameter.get('defaultIndex',0)
        if type(default) is not int or not 0 <= default < len(values): raise ValueError('Invalid TF2 parameter defaultIndex')
        parameter['defaultIndex'] = default+1
        # Preserve TF2's zero-based selection values for future/manual script edits.
        parameter['numbers'] = list(range(len(values)))
        if 'uiType' in parameter:
            ui = parameter['uiType']
            mapping = {'BUTTON':'Button','SLIDER':'Slider','COMBOBOX':'ComboBox','ICON_BUTTON':'IconButton','CHECKBOX':'CheckBox'}
            if ui not in mapping and ui not in mapping.values(): raise ValueError(f'Unknown parameter UI type: {ui}')
            parameter['uiType'] = mapping.get(ui,ui)
        if parameter.get('uiType') == 'IconButton':
            parameter['values'] = [resolve(v,'texture') for v in values]
    output['updateScript'] = {'fileName':script_reference+'@updateFn','params':{}}
    cost = result.pop('cost',0)
    result['tag'] = 1
    construction = {'cost':cost,'subconstructions':[result]}
    if data['type'] == 'ASSET_TRACK':
        construction['snapPoint'] = _asset_track_snap()
    return output, construction


def _selection_construction(data, resolve, native, script_reference, audit=None, resource=''):
    """Port three verified ParamBuilder model/offset/height callback shapes.

    This generates an independently authored native function. No source helper
    or source callback is executed or copied into an active TF3 script.
    """
    from .tf2_vehicle_port import lua_value
    callback = data.get('updateFn')
    if not isinstance(callback, AssetSelectionCallback):
        raise ValueError('Asset construction callback has no verified selection adapter')
    if data.get('type') not in ('ASSET_DEFAULT', 'ASSET_TRACK'):
        raise ValueError('ParamBuilder selection adapter supports decorative assets only')
    parameters = _list(data.get('params'), 'asset selection parameters')
    by_key = {}
    for parameter in parameters:
        if not isinstance(parameter, dict) or not isinstance(parameter.get('key'), str) or parameter['key'] in by_key:
            raise ValueError('Asset selection parameters need unique literal keys')
        by_key[parameter['key']] = parameter
    for builder in (callback.model, callback.offset):
        if builder is not None and not _same_literal(by_key.get(builder.params['key']), builder.params):
            raise ValueError('Asset selection callback and parameter definitions disagree')
    if any(key in by_key for key in ('constructOpt56', 'constructOpt78', 'randomRotation')):
        raise ValueError('Asset selection has conflicting native rotation parameter keys')
    model_values = [resolve(path, 'model') for path in callback.model.values]
    placeholder = deepcopy(data)
    placeholder['type'] = 'ASSET_DEFAULT'
    placeholder['updateFn'] = ConstantCallback({'models': [], 'terrainAlignmentLists': [{'type': 'EQUAL', 'faces': []}]})
    output, _ = _constant_construction(placeholder, resolve, script_reference)
    model_key = lua_value(callback.model.params['key'])
    offset_values = list(callback.offset.values) if callback.offset is not None else None
    offset_code = ('0' if callback.offset is None else
                   f'offsetValues[(params[{lua_value(callback.offset.params["key"])}] or {callback.offset.default_index}) + 1]')
    imports = ''
    transform = '{ 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, offset, 0, height, 1 }'
    if callback.rotate:
        if native is None:
            raise ValueError('Rotatable asset construction requires the selected TF3 installation')
        helper = native.reference('scripts/construction/constructionutil.lua')
        # Native rotation uses explicit axis parameters. Do not let inherited
        # randomRotation settings from other assets change the source behavior.
        transform = ('rotation.rotateTransf({constructOpt56=params.constructOpt56 or 0, '
                     'constructOpt78=params.constructOpt78 or 0}, ' + transform + ')')
        imports = f'local rotation = require {lua_value(helper)}\n'
        native.read('scripts/construction/param_util.tl')
        step_script = native.reference('scripts/construction/param_util.script@stepRotationValueFn')
        format_script = native.reference('scripts/construction/param_util.script@formatRotationValueFn')
        for key, title in (('constructOpt56', 'Rotation X'), ('constructOpt78', 'Rotation Y')):
            output['params'].append({
                'key': key, 'name': TranslatedString(title),
                'numbers': [i * 10 * math.pi / 180 for i in range(36)],
                'defaultIndex': 1, 'uiType': 'Slider', 'location': 'Toolbar',
                'stepValueScript': {'fileName': step_script},
                'formatValueScript': {'fileName': format_script}})
    declarations = f'local modelValues = {lua_value(model_values)}\n'
    if offset_values is not None:
        declarations += f'local offsetValues = {lua_value(offset_values)}\n'
    track_snap = ''
    if data['type'] == 'ASSET_TRACK':
        track_snap = ', snapPoint = ' + lua_value(_asset_track_snap())
    script = (imports + declarations + 'function data()\nreturn {updateFn=function(captureParams, params)\n'
              + f'local offset = {offset_code}\n'
              + 'local height = params.position == 1 and 1.05 or 0\n'
              + f'local selected = modelValues[(params[{model_key}] or {callback.model.default_index}) + 1]\n'
              + 'return {cost=0, subconstructions={{tag=1, models={{id=selected, transf=' + transform
              + '}}, terrainAlignmentLists={{type="EQUAL",faces={}}}}}' + track_snap + '}\nend}\nend\n')
    if audit is not None:
        audit.setdefault('constructionMigrations', []).append({
            'resource': resource, 'policy': 'verified_parambuilder_model_offset_height',
            'helperSha256': PARAMBUILDER_SHA256, 'modelChoices': len(model_values),
            'offsetChoices': len(offset_values) if offset_values is not None else 0,
            'rotationPreserved': callback.rotate, 'trackSnappingPreserved': data['type'] == 'ASSET_TRACK',
            'sourceParameterIndices': 'zero_based_numbers', 'nativeTest': 'not_run'})
    return output, script


def _finite_construction(data, resolve, script_reference, audit=None, resource=''):
    """Independently generate native code for verified model/height selectors."""
    from .tf2_vehicle_port import lua_value
    callback = data.get('updateFn')
    if not isinstance(callback, FiniteAssetCallback):
        raise ValueError('Asset construction has no verified finite selection descriptor')
    placeholder = deepcopy(data)
    placeholder['updateFn'] = ConstantCallback(deepcopy(callback.result))
    output, result = _constant_construction(placeholder, resolve, script_reference)
    params = {parameter['key']: parameter for parameter in output.get('params', [])}
    models = result['subconstructions'][0].setdefault('models', [])
    if models != []:
        raise ValueError('Finite selection requires an empty initial models list')
    lines = ['function data()', 'return {updateFn=function(captureParams, params)']
    if callback.height is not None:
        height = callback.height
        _unknown(height, {'key', 'default', 'values'}, 'finite height profile')
        lines.append('local height = ' + lua_value(_number(height['default'], 'finite height default')))
        for index, (choice, value) in enumerate(height['values'].items()):
            lines.append(('if ' if index == 0 else 'elseif ') + 'params[' + lua_value(height['key']) + '] == '
                         + lua_value(choice) + ' then height = ' + lua_value(_number(value, 'finite height choice')))
        lines.append('end')
    lines += ['local result = ' + lua_value(result), 'local models = result.subconstructions[1].models']
    random_branches, model_choices = 0, 0

    def append(spec, indexed=None):
        nonlocal random_branches, model_choices
        _unknown(spec, {'ids', 'random', 'model', 'heightSlots'}, 'finite model choice')
        paths = _list(spec['ids'], 'finite model choices')
        if not 1 <= len(paths) <= 256 or type(spec['random']) is not bool:
            raise ValueError('Invalid finite model choice descriptor')
        ids = [resolve(path, 'model') for path in paths]
        model_choices += len(ids)
        template = deepcopy(_dict(spec['model'], 'finite model template'))
        _unknown(template, {'transf', 'tag'}, 'finite model template')
        matrix = _list(template['transf'], 'finite model transform')
        if len(matrix) != 16:
            raise ValueError('Finite model transform must have 16 values')
        for value in matrix:
            _number(value, 'finite model transform')
        lines.append('local model = ' + lua_value(template))
        if indexed is not None:
            lines.append('local ids = ' + lua_value(ids))
            lines.append('model.id = ids[params[' + lua_value(indexed) + '] + 1]')
        elif spec['random']:
            random_branches += 1
            lines.append('local ids = ' + lua_value(ids))
            # Keep the RNG invocation inside its source condition, even for a
            # one-item array. Duplicate IDs retain their authored weighting.
            lines.append('model.id = ids[math.random(#ids)]')
        else:
            if len(ids) != 1:
                raise ValueError('A deterministic branch requires exactly one model')
            lines.append('model.id = ' + lua_value(ids[0]))
        for slot in _list(spec['heightSlots'], 'finite height transform slots'):
            if callback.height is None or type(slot) is not int or not 1 <= slot <= 16:
                raise ValueError('Invalid finite height transform slot')
            lines.append(f'model.transf[{slot}] = height')
        lines.append('models[#models + 1] = model')

    for selector in callback.selectors:
        _unknown(selector, {'key', 'choices', 'indexed'}, 'finite model selector')
        key, choices = selector['key'], _dict(selector['choices'], 'finite model selector choices')
        if not isinstance(key, str) or not choices or len(choices) > 256 or type(selector['indexed']) is not bool:
            raise ValueError('Invalid finite model selector descriptor')
        if selector['indexed']:
            values = [spec for _,spec in sorted(choices.items())]
            parameter = params.get(key)
            if (parameter is None or set(choices) != set(range(len(values)))
                    or len(parameter['values']) != len(values)
                    or any(spec['random'] or len(spec['ids']) != 1 for spec in values)
                    or any(not _same_literal({k:v for k,v in values[0].items() if k != 'ids'},
                                             {k:v for k,v in spec.items() if k != 'ids'}) for spec in values)):
                raise ValueError('Indexed finite model choices must match their declared parameter')
            merged = deepcopy(values[0])
            merged['ids'] = [spec['ids'][0] for spec in values]
            append(merged, key)
        else:
            for index, (choice, spec) in enumerate(choices.items()):
                if type(choice) is not int or not 0 <= choice <= 8190:
                    raise ValueError('Invalid finite model parameter choice')
                lines.append(('if ' if index == 0 else 'elseif ') + 'params[' + lua_value(key)
                             + '] == ' + lua_value(choice) + ' then')
                append(spec)
            lines.append('end')
    lines += ['return result', 'end}', 'end', '']
    script = '\n'.join(lines)
    if len(script.encode('utf-8')) > _MAX_EXPANDED_BYTES:
        raise ValueError('Finite asset selection exceeds the safe generated script limit')
    if audit is not None:
        audit.setdefault('constructionMigrations', []).append({
            'resource': resource, 'policy': 'verified_finite_model_height_selection',
            'selectors': len(callback.selectors), 'modelReferences': model_choices,
            'conditionalRandomBranches': random_branches, 'heightPreserved': callback.height is not None,
            'trackSnappingPreserved': data['type'] == 'ASSET_TRACK',
            'sourceParameterIndices': 'zero_based_numbers', 'nativeTest': 'not_run'})
    return output, script


def port_resource(old: str, text: str, resolve, native=None, *, resource_reference: str, model_bounds=None,
                  translations: set[str] | None = None, translation_tables=None, translation_audit=None,
                  verified_helpers=(), parsed_data=None, data_transform=None, implicit_translations=True) -> dict[str,str]:
    """Return emitted content paths/text; caller stages and audits all results.

    resource_reference is the fully qualified target ref WITHOUT final .lua.
    model_bounds(original_model_reference) returns verified TF2 boundingInfo.
    parsed_data optionally supplies an already audited resource descriptor.
    data_transform receives an independent descriptor graph, including callback
    values, and must return its transformed graph. It runs before localized
    concatenations, so imported translation keys retain their dependency scope.
    """
    # Lazy import avoids a circular dependency with the central exporter.
    from .tf2_vehicle_port import emit, lua_value
    if parsed_data is None:
        data = load_resource_table(text, verified_helpers=verified_helpers,
                                   audit=translation_audit, resource=old)
    else:
        _check_graph(parsed_data, allow_behaviors=True)
        data = deepcopy(_dict(parsed_data, 'parsed resource'))
    if data_transform is not None:
        data = data_transform(data)
        _check_graph(data, allow_behaviors=True)
        data = _dict(data, 'transformed resource')
    if translation_tables is not None:
        data = resolve_translation_concatenations(data, translation_tables, translation_audit, resource=old)
        if implicit_translations:
            translations = set().union(*(table.keys() for table in translation_tables.values()))
    kind = classify_resource(old)
    target = resource_target(old)
    if kind in ('track','street'):
        documents = _track_documents(_checked(data),resolve,resource_reference) if kind == 'track' else _street_documents(_checked(data),resolve,resource_reference)
        stem = target[:-len('.street_template.lua')]
        return {stem+suffix:emit(value,translations) for suffix,value in documents.items()}
    if kind == 'bridge': return {target:emit(_bridge_document(data,resolve,native,model_bounds),translations)}
    if kind == 'construction':
        script = resource_reference[:-len('.con')]+'.script'
        if isinstance(data.get('updateFn'), FiniteAssetCallback):
            output, script_text = _finite_construction(data, resolve, script, translation_audit, old)
            script_target = target[:-len('.con.lua')]+'.script.lua'
            return {target:emit(output,translations),script_target:script_text}
        if isinstance(data.get('updateFn'), AssetSelectionCallback):
            output, script_text = _selection_construction(data, resolve, native, script,
                                                          translation_audit, old)
            script_target = target[:-len('.con.lua')]+'.script.lua'
            return {target:emit(output,translations),script_target:script_text}
        output,result = _constant_construction(data,resolve,script)
        if translation_audit is not None:
            translation_audit.setdefault('constructionMigrations', []).append({
                'resource': old, 'policy': 'fold_literal_asset_callback',
                'sourceType': data['type'], 'trackSnappingPreserved': data['type'] == 'ASSET_TRACK',
                'nativeTest': 'not_run'})
        script_target = target[:-len('.con.lua')]+'.script.lua'
        script_text = 'function data()\nreturn { updateFn = function(captureParams, params)\nreturn '+lua_value(result)+'\nend }\nend\n'
        return {target:emit(output,translations),script_target:script_text}
    if kind == 'tunnel': raise ValueError('TF2 portal-only tunnels need TF3 interior walls and dead-end configuration; manual adapter required')
    if kind == 'module': raise ValueError('TF2 construction modules require TF3 slot/update/get-model script migration')
    if kind == 'script': raise ValueError('Arbitrary TF2 Lua/API behavior requires a manual script module port')
    return {target:emit(port_config(old,data,resolve,native),translations)}

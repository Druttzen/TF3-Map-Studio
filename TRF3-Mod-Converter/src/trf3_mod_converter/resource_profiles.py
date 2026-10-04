"""Evidence-based TF2 resource adapters; never execute a source Lua program.

The official TF3 resource/model/construction/infrastructure documentation and
the selected installation are the compatibility contract. Unknown fields and
arbitrary callbacks are blockers, not silently discarded functionality.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import operator
from pathlib import PurePosixPath
import re
from typing import Any

from luaparser import ast, astnodes as lua
from .lua_metadata import TranslatedString, UnsupportedValue, _value


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
class BridgeFactory:
    params: dict


@dataclass(frozen=True)
class _Helper:
    name: str


_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_EXPANDED_NODES = 100_000
_MAX_EXPANDED_BYTES = 8 * 1024 * 1024
_MAX_TABLE_DEPTH = 128


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
        if isinstance(item, (ConstantCallback, BridgeFactory, _Helper)) and not allow_behaviors:
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
        elif isinstance(item, BridgeFactory):
            children, size = [item.params], 2
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
        for field in node.fields:
            if field.key is None: key, index = index, index + 1
            elif isinstance(field.key, lua.Name) and not field.between_brackets: key = field.key.id
            else: key = _evaluate(field.key, env)
            if type(key) not in (str, int): raise ValueError('Unsupported computed Lua table key')
            if key in result: raise ValueError(f'Duplicate Lua table key: {key}')
            result[key] = _evaluate(field.value, env)
        # Keep empty tables mutable during straight-line evaluation. Replacing
        # an empty list with a dict on assignment would lose aliased bindings.
        if not result: return {}
        if all(type(k) is int for k in result) and set(result) == set(range(1, len(result) + 1)):
            return [result[i] for i in range(1, len(result) + 1)]
        return result
    if isinstance(node, lua.Index):
        data = _evaluate(node.value, env)
        key = node.idx.id if node.notation == lua.IndexNotation.DOT and isinstance(node.idx, lua.Name) else _evaluate(node.idx, env)
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
            raise ValueError('Translated fragments cannot be folded into a static concatenation')
        if not isinstance(left, str) or not isinstance(right, str): raise ValueError('Dynamic Lua concatenation')
        if len(left) + len(right) > _MAX_EXPANDED_BYTES:
            raise ValueError('Constant concatenation exceeds the safe export limit')
        return left + right
    if isinstance(node, lua.AnonymousFunction):
        for parameter in node.args:
            if not isinstance(parameter, lua.Name) or parameter.id in {'_', 'require', 'math', 'data'}:
                raise ValueError('Inline callback parameter shadows a built-in or uses unsupported varargs')
        statements = node.body.body
        if len(statements) != 1 or not isinstance(statements[0], lua.Return) or len(statements[0].values) != 1:
            raise ValueError('Inline callback is dynamic; requires a manual TF3 script module port')
        # Captured locals could be mutated after the closure was declared. Only
        # literal callback bodies are safe to move without emulating lifecycle.
        return ConstantCallback(_checked(_evaluate(statements[0].values[0], {}), 'constant callback'))
    if isinstance(node, lua.Call):
        if isinstance(node.func, lua.Name) and node.func.id == '_' and len(node.args) == 1 and '_' not in env:
            value = _checked(_evaluate(node.args[0], env), 'translation key')
            if not isinstance(value, str): raise ValueError('Translation key must be a literal string')
            return TranslatedString(value)
        if isinstance(node.func, lua.Name) and node.func.id == 'require' and len(node.args) == 1 and 'require' not in env:
            helper = _value(node.args[0])
            if helper in ('bridgeutil', 'bridgeutil.lua', 'texutil', 'texutil.lua', 'vec3', 'vec3.lua', 'transf', 'transf.lua'):
                return _Helper(str(helper).removesuffix('.lua'))
            raise ValueError(f'Unknown Lua helper/API import: {helper}')
        if isinstance(node.func, lua.Index) and node.func.notation == lua.IndexNotation.DOT and isinstance(node.func.idx, lua.Name):
            helper, name = _evaluate(node.func.value, env), node.func.idx.id
            if isinstance(helper, _Helper) and helper.name in ('vec3','transf'):
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


def _statements(statements, env, *, allow_return=True):
    result = None
    for i, statement in enumerate(statements):
        if isinstance(statement, lua.LocalAssign):
            if len(statement.targets) != len(statement.values) or any(not isinstance(t, lua.Name) for t in statement.targets):
                raise ValueError('Only simple initialized local Lua bindings can be folded')
            values = [_evaluate(v, env) for v in statement.values]
            for target, value in zip(statement.targets, values):
                if target.id in {'require','_','math','data'}:
                    raise ValueError(f'Shadowed Lua built-in/data binding: {target.id}')
                if target.id in env: raise ValueError(f'Shadowed helper/local binding: {target.id}')
                env[target.id] = value
        elif isinstance(statement, lua.Assign):
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


def load_resource_table(text: str) -> dict:
    """Fold declarative resources and a narrow set of verified helper factories."""
    if len(text.encode('utf-8')) > _MAX_SOURCE_BYTES:
        raise ValueError('Lua resource exceeds the safe parser input limit')
    try: tree = ast.parse(text.lstrip('\ufeff'))
    except ast.SyntaxException as error: raise ValueError(f'Invalid Lua resource: {error}') from error
    except RecursionError as error: raise ValueError('Lua resource nesting exceeds the safe parser limit') from error
    statements = tree.body.body
    functions = [s for s in statements if isinstance(s, lua.Function) and isinstance(s.name, lua.Name) and s.name.id == 'data']
    if len(functions) == 1:
        fn = functions[0]
        if statements[-1] is not fn or fn.args:
            raise ValueError('Resource must have one argument-free data function after literal imports')
        env = {}
        _statements(statements[:-1], env, allow_return=False)
        result = _statements(fn.body.body, env)
    else:
        result = _statements(statements, {})
    _check_graph(result, allow_behaviors=True)
    def normalize(value):
        if isinstance(value,BridgeFactory): return BridgeFactory(normalize(value.params))
        if isinstance(value,ConstantCallback): return ConstantCallback(normalize(value.result))
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
    if old.endswith('~'):
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
    metadata = port_common_metadata(metadata,first,resolve)
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
        _unknown(result, {'vehicles','name','desc','filterTags'},kind)
        for vehicle in _list(result.get('vehicles'), 'multiple-unit vehicles'):
            _unknown(vehicle, {'name','forward'}, 'multiple-unit vehicle')
            if type(vehicle.get('forward')) is not bool: raise ValueError('Multiple-unit direction must be a boolean')
            vehicle['name'] = resolve(vehicle['name'],'model')
        if not result['vehicles']: raise ValueError('Multiple unit has no vehicles')
        result.setdefault('filterTags',['default'])
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


def _constant_construction(data,resolve,script_reference):
    allowed = {'type','description','availability','order','categories','params','updateFn','skipCollision','autoRemovable',
               'buildMode','keepBuildings','heightModView'}
    _unknown(data,allowed,'construction')
    if data.get('type') != 'ASSET_DEFAULT': raise ValueError('Functional construction needs subconstruction/station/industry/depot migration')
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
    return output, {'cost':cost,'subconstructions':[result]}


def port_resource(old: str, text: str, resolve, native=None, *, resource_reference: str, model_bounds=None,
                  translations: set[str] | None = None) -> dict[str,str]:
    """Return emitted content paths/text; caller stages and audits all results.

    resource_reference is the fully qualified target ref WITHOUT final .lua.
    model_bounds(original_model_reference) returns verified TF2 boundingInfo.
    """
    # Lazy import avoids a circular dependency with the central exporter.
    from .tf2_vehicle_port import emit, lua_value
    data = load_resource_table(text)
    kind = classify_resource(old)
    target = resource_target(old)
    if kind in ('track','street'):
        documents = _track_documents(_checked(data),resolve,resource_reference) if kind == 'track' else _street_documents(_checked(data),resolve,resource_reference)
        stem = target[:-len('.street_template.lua')]
        return {stem+suffix:emit(value,translations) for suffix,value in documents.items()}
    if kind == 'bridge': return {target:emit(_bridge_document(data,resolve,native,model_bounds),translations)}
    if kind == 'construction':
        script = resource_reference[:-len('.con')]+'.script'
        output,result = _constant_construction(data,resolve,script)
        script_target = target[:-len('.con.lua')]+'.script.lua'
        script_text = 'function data()\nreturn { updateFn = function(captureParams, params)\nreturn '+lua_value(result)+'\nend }\nend\n'
        return {target:emit(output,translations),script_target:script_text}
    if kind == 'tunnel': raise ValueError('TF2 portal-only tunnels need TF3 interior walls and dead-end configuration; manual adapter required')
    if kind == 'module': raise ValueError('TF2 construction modules require TF3 slot/update/get-model script migration')
    if kind == 'script': raise ValueError('Arbitrary TF2 Lua/API behavior requires a manual script module port')
    return {target:emit(port_config(old,data,resolve,native),translations)}

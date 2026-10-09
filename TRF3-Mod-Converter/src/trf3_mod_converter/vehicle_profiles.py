"""Literal TF2 vehicle metadata adapters verified against TF3's public schemas.

This module never evaluates Lua or reads/copies game assets. Resource resolution,
literal cargo-compartment conversion and common model metadata are caller-owned.
Unknown simulation/config fields block export rather than silently disappearing.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import math


SCHEMA_SOURCES = (
    'https://wiki.transportfever2.com/doku.php?id=modding:vehicletypes',
    'https://wiki.transportfever2.com/doku.php?id=modding:vehiclebasics',
    'https://wiki.transportfever3.com/doku.php?id=modding:vehicles:types',
    'https://wiki.transportfever3.com/doku.php?id=modding:vehicles:basics',
    'https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mdl',
    'https://wiki.transportfever3.com/doku.php?id=modding:misc:people',
)
ENGINES = {'HORSE', 'STEAM', 'DIESEL', 'ELECTRIC'}
EMISSIONS_POLICIES = frozenset({'strict', 'legacy_noise', 'tf3_automatic', 'class_average'})
COMMON_METADATA = {
    'availability', 'cost', 'description', 'emission', 'maintenance', 'seatProvider',
    'colorConfig', 'labelList', 'particleSystem', 'cameraConfig', 'cargoSlotProvider',
    'versioning', 'lightConfig', 'skinList', 'person', 'category', 'categoryList',
    'order', 'rock', 'tree',
}
VEHICLE_BLOCKS = {'railVehicle', 'roadVehicle', 'waterVehicle', 'airVehicle'}
RAIL_PARTS = ('frontForwardParts', 'frontBackwardParts', 'backForwardParts',
              'backBackwardParts', 'innerForwardParts', 'innerBackwardParts')
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _dict(value, where: str) -> dict:
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'{where}: expected a literal table')
    return value


def _list(value, where: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f'{where}: expected a literal list')
    return value


def _known(value: dict, fields: set[str], where: str) -> None:
    unknown = set(value) - fields
    if unknown:
        raise ValueError(f'Unsupported {where} fields (preserved in source): {sorted(unknown)}')


def _number(value, where: str, *, minimum=None) -> float | int:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{where}: expected a finite number')
    if minimum is not None and value < minimum:
        raise ValueError(f'{where}: must be at least {minimum}')
    return value


def _literal(value, where='metadata'):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, (str, int)):
                raise ValueError(f'{where}: unsupported table key')
            _literal(item, f'{where}/{key}')
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _literal(item, f'{where}/{i}')
    elif type(value) in (int, float):
        _number(value, where)
    elif value is not None and not isinstance(value, (str, bool)):
        raise ValueError(f'{where}: unsupported non-literal value')


@dataclass(frozen=True)
class VehicleProfile:
    family: str
    carrier: str | None
    powered: bool
    engine_types: tuple[str, ...]
    transport_modes: tuple[str, ...]
    engine_transport_modes: tuple[str, ...]
    transformer: str | None
    decorative_physics: str | None = None

    @property
    def key(self) -> str:
        if self.decorative_physics:
            return 'tf2_asset_' + self.decorative_physics.removesuffix('Vehicle').lower()
        if self.family in ('train', 'waggon', 'tram'):
            engine = '_'.join(t.lower() for t in self.engine_types) or 'unpowered'
            return f'tf2_{self.family}_{engine}'
        return f'tf2_{self.family}'


def _cargo_categories(value, *, entry=False) -> set[str]:
    """Read literal cargo type fields, never arbitrary description/name strings."""
    found = set()
    if isinstance(value, dict):
        if entry:
            for field in ('type', 'cargoType'):
                if isinstance(value.get(field), str):
                    found.add(value[field])
        for key, item in value.items():
            if key in ('cargoEntries', 'cargoEntry', 'capacities', 'compartments'):
                found.update(_cargo_categories(item, entry=True))
            elif key == 'cargoTypeSet' and isinstance(item, dict):
                found.update(v for v in item.get('cargoTypesIncluded', []) if isinstance(v, str))
                if 'PASSENGERS' in item.get('cargoClassesIncluded', []):
                    found.add('PASSENGERS')
            elif key in ('cargoBay', 'customCargoModels', 'cargoSlotProvider', 'seats', 'loadIndicator'):
                continue
            else:
                found.update(_cargo_categories(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_cargo_categories(item, entry=entry))
    return found


def classify_model(metadata: dict, model_path: str = '') -> VehicleProfile:
    """Classify by carrier and physical metadata, with conventional folder hints.

    Folder hints distinguish cargo-free auxiliary bus/truck bodies only when the
    TF2 carrier and road simulation block already establish their vehicle class.
    """
    m = _dict(metadata, 'metadata')
    _literal(m)
    blocks = sorted(VEHICLE_BLOCKS & set(m))
    transport = _dict(m.get('transportVehicle', {}), 'transportVehicle')
    if not blocks:
        if transport or 'car' in m:
            raise ValueError('Transport vehicle has no supported physical vehicle metadata')
        family = 'person' if 'person' in m else 'asset'
        return VehicleProfile(family, None, False, (), (), (), None)
    if len(blocks) != 1:
        raise ValueError('Conflicting physical vehicle metadata blocks')
    block = blocks[0]
    physical = _dict(m[block], block)
    expected = {'railVehicle': {'RAIL', 'TRAM'}, 'roadVehicle': {'ROAD'},
                'airVehicle': {'AIR'}, 'waterVehicle': {'WATER'}}[block]
    car = 'car' in m
    carrier = transport.get('carrier')
    decorative = None
    # A construction asset may retain its original vehicle physics/configs for
    # rendering. Preserve those fields without creating a transport/AI marker.
    # An explicit transport table (including an empty one) is never repaired by
    # this path; its missing/conflicting carrier remains an authored error.
    if not car and 'transportVehicle' not in m and 'asset' in model_path.replace('\\', '/').lower().split('/'):
        if block == 'railVehicle':
            raise ValueError('Decorative railVehicle needs an explicit rail/tram animation contract; a carrier cannot be inferred')
        decorative = block
        carrier = {'roadVehicle': 'ROAD', 'waterVehicle': 'WATER', 'airVehicle': 'AIR'}[block]
    if car:
        if block != 'roadVehicle' or transport:
            raise ValueError('AI car must have roadVehicle and no transportVehicle metadata')
        carrier = 'ROAD'
    elif carrier not in expected:
        raise ValueError(f'{block} carrier must be one of {sorted(expected)}')
    if block == 'railVehicle':
        engines = _list(physical.get('engines', []), 'railVehicle/engines')
    elif block == 'roadVehicle':
        engines = [physical['engine']] if physical.get('engine') else []
    else:
        engines = []
    engine_types = []
    for engine in engines:
        engine = _dict(engine, 'engine')
        _known(engine, {'type', 'power', 'tractiveEffort'}, 'engine')
        if engine.get('type') not in ENGINES:
            raise ValueError(f'Unsupported engine type {engine.get("type")!r}')
        for key in ('power', 'tractiveEffort'):
            _number(engine.get(key), f'engine/{key}', minimum=0)
        if engine['type'] not in engine_types:
            engine_types.append(engine['type'])
    electrical_only = bool(engine_types) and set(engine_types) == {'ELECTRIC'}
    if carrier == 'RAIL':
        family = 'train' if engines else 'waggon'
        modes = ('TRAIN', 'ELECTRIC_TRAIN')
        engine_modes = ('ELECTRIC_TRAIN',) if electrical_only else modes if engines else ()
        transformer = 'vehicle/train/shared/default_train.trf'
    elif carrier == 'TRAM':
        family, modes = 'tram', ('TRAM', 'ELECTRIC_TRAM')
        engine_modes = ('ELECTRIC_TRAM',) if electrical_only else modes if engines else ()
        transformer = 'vehicle/tram/shared/default_tram.trf'
    elif carrier == 'ROAD':
        cargos = _cargo_categories(transport)
        hint = '/' + model_path.replace('\\', '/').lower().lstrip('/')
        license_ = _dict(m.get('seatProvider', {}), 'seatProvider').get('drivingLicense')
        if car or decorative:
            family, modes = 'car', ()
        elif 'PASSENGERS' in cargos and cargos - {'PASSENGERS'}:
            family, modes = 'bus', ('BUS', 'TRUCK')
        elif 'PASSENGERS' in cargos:
            family, modes = 'bus', ('BUS',)
        elif cargos:
            family, modes = 'truck', ('TRUCK',)
        elif license_ == 'BUS' or '/vehicle/bus/' in hint:
            family, modes = 'bus', ('BUS',)
        elif license_ == 'TRUCK' or '/vehicle/truck/' in hint:
            family, modes = 'truck', ('TRUCK',)
        else:
            raise ValueError('Road vehicle needs a passenger/cargo class or a conventional bus/truck folder')
        engine_modes = modes if engines else ()
        transformer = 'vehicle/shared/default_road.trf'
    elif carrier == 'WATER':
        if physical.get('type') not in ('SMALL', 'BIG'):
            raise ValueError('waterVehicle/type must be SMALL or BIG')
        family = 'ship'
        modes = ('SMALL_SHIP',) if physical['type'] == 'SMALL' else ('SHIP',)
        engine_modes, transformer = modes, 'vehicle/ship/shared/default_ship.trf'
    else:
        if physical.get('type') not in ('SMALL', 'BIG'):
            raise ValueError('airVehicle/type must be SMALL or BIG')
        family = 'plane'
        modes = ('SMALL_AIRCRAFT',) if physical['type'] == 'SMALL' else ('AIRCRAFT',)
        engine_modes, transformer = modes, 'vehicle/shared/default_air.trf'
    return VehicleProfile('asset' if decorative else family, None if decorative else carrier,
                          bool(engines) or carrier in ('WATER', 'AIR'), tuple(engine_types),
                          () if decorative else modes, () if decorative else engine_modes,
                          transformer, decorative)


def _matrix(value, where):
    if not isinstance(value, list) or len(value) != 16:
        raise ValueError(f'{where}: expected a 16-number transform')
    for item in value:
        _number(item, where)
    if not all(math.isclose(value[i], expected, abs_tol=1e-6)
               for i, expected in ((3, 0), (7, 0), (11, 0), (15, 1))):
        raise ValueError(f'{where}: projective transforms are unsupported')
    return value


def _multiply(a, b):
    return [sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
            for col in range(4) for row in range(4)]


def derive_lod_nodes(lods: list, *, metadata: dict | None = None, report=None,
                     model_path='') -> tuple[list[list[dict]], list[list[list[float]]]]:
    """Name caller-owned nodes and derive their complete model-space transforms.

    The caller must first deep-copy the source model. Names preserve unique TF2
    names and distinguish duplicate mesh/group roles; ambiguous same-role names
    are refused unless metadata is supplied and contains no ambiguous string
    node references. In that case duplicates get deterministic occurrence
    suffixes; all integer references retain their original node positions.
    """
    all_nodes, all_transforms = [], []
    for li, lod in enumerate(_list(lods, 'lods')):
        lod = _dict(lod, f'LOD {li}')
        _known(lod, {'node', 'static', 'visibleFrom', 'visibleTo', 'textureLodBase'}, 'LOD')
        nodes, transforms, names = [], [], set()
        if metadata is not None:
            originals = []
            def collect(node):
                node = _dict(node, 'node')
                if node.get('name'):
                    originals.append(node['name'])
                for child in _list(node.get('children', []), 'node/children'):
                    collect(child)
            collect(lod.get('node'))
            duplicates = {name for name in originals if originals.count(name) > 1}
            def check_refs(value, key=''):
                if isinstance(value, dict):
                    for field, child in value.items():
                        check_refs(child, field)
                elif isinstance(value, list):
                    for child in value:
                        check_refs(child, key)
                elif isinstance(value, str) and key in (
                        'group', 'childId', 'child', 'meshId', 'bone', 'bones',
                        'affectedGroup', 'attachToGroup') and value in duplicates:
                    raise ValueError(f'Ambiguous node name reference {value!r} in metadata/{key}')
            check_refs(metadata)
        def visit(node, parent):
            node = _dict(node, 'node')
            editor_ids = {}
            for field in ('_meshId', '_origMeshId'):
                if field in node:
                    value = node[field]
                    if type(value) is not int or value < 0:
                        raise ValueError(f'node/{field}: expected a nonnegative integer editor ID')
                    editor_ids[field] = node.pop(field)
            if editor_ids and report is not None:
                report.setdefault('modelNodeMigrations', []).append({
                    'model': model_path, 'lod': li, 'nodeIndex': len(nodes),
                    'nodeName': node.get('name', ''), 'sourceFields': editor_ids,
                    'policy': 'omit_editor_mesh_ids_preserve_node_order',
                    'reason': 'TF2 editor IDs are outside the runtime node schema; TF3 node references use unique names.',
                    'nativeTest': 'not_run'})
            _known(node, {'name', 'mesh', 'materials', 'transf', 'children', 'animations',
                          'skin', 'skinMaterials'}, 'node')
            name = node.get('name') or f'node_{len(nodes)}'
            if not isinstance(name, str):
                raise ValueError('Node name must be a string')
            if ('mesh' in node or 'skin' in node) and name in names:
                name += '_mesh'
            if name in names:
                if metadata is None:
                    raise ValueError(f'Ambiguous node name {name!r} in LOD {li}')
                base, occurrence = name, 2
                while name in names:
                    name = f'{base}__{occurrence}'
                    occurrence += 1
            node['name'] = name
            names.add(name)
            world = _multiply(parent, _matrix(node.get('transf', IDENTITY), 'node/transf'))
            nodes.append(node)
            transforms.append(world)
            for child in _list(node.get('children', []), 'node/children'):
                visit(child, world)
        visit(lod.get('node'), IDENTITY)
        all_nodes.append(nodes)
        all_transforms.append(transforms)
    if not all_nodes:
        raise ValueError('A model needs at least one LOD')
    return all_nodes, all_transforms


def _node(nodes, index, where):
    if type(index) is not int or not 0 <= index < len(nodes):
        raise ValueError(f'Invalid {where} node index {index!r}')
    return nodes[index]


def _mesh_nodes(nodes, meshes, where):
    out = []
    for mesh in _list(meshes, where):
        if not isinstance(mesh, str):
            raise ValueError(f'{where}: expected mesh reference strings')
        matches = [n for n in nodes if n.get('mesh') == mesh]
        if not matches:
            raise ValueError(f'{where}: mesh {mesh!r} has no node')
        for node in matches:
            if node not in out:
                out.append(node)
    return out


def _animate(node, event, reference):
    animations = _dict(node.setdefault('animations', {}), 'node/animations')
    node['animations'] = animations
    if event in animations:
        raise ValueError(f'Existing {event} animation requires review')
    animations[event] = {'type': 'FILE_REF', 'params': {'id': reference}}


def _event_pair(nodes, indexes, event, native, *, alternate=False, on_name=None):
    for index in _list(indexes, event):
        node = _node(nodes, index, event)
        for action in ('on', 'off'):
            suffix = '_1' if alternate and action == 'on' else ''
            resource = f'vehicle/shared/ani/{on_name or event}_{action}{suffix}.ani'
            _animate(node, f'{event}_{action}', native.reference(resource))


def _rotation(axis: str, angle: float) -> list[float]:
    c, s = math.cos(angle), math.sin(angle)
    if axis == 'x':
        return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]
    if axis == 'y':
        return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]
    return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _angle_animation(nodes, config, event, axis, native, writer, *, one_way=False):
    config = _dict(config, event)
    _known(config, {'ids', 'maxAngle'}, event)
    ids = _list(config.get('ids', []), event + '/ids')
    angle = _number(config.get('maxAngle', 0), event + '/maxAngle', minimum=0)
    if angle > 180:
        raise ValueError(f'{event}: maximum angle exceeds 180 degrees')
    if not ids:
        return
    if writer is None:
        raise ValueError(f'{event}: preserving TF2 maxAngle requires an animation writer')
    radians = math.radians(angle)
    # Native TF3 rudder curves go +max to -max; x-axis control curves
    # go -max to +max. Flaps go from retracted to positive max angle.
    start, end = (0, radians) if one_way else ((radians, -radians) if axis == 'z' else (-radians, radians))
    times = list(range(0, 1001, 10))
    data = {'times': times, 'transfs': [_rotation(axis, start + (end - start) * t / 1000) for t in times]}
    reference = writer(event, data)
    if not isinstance(reference, str) or not reference:
        raise ValueError('Animation writer returned an invalid resource reference')
    for index in ids:
        _animate(_node(nodes, index, event), event, reference)


def _config_port(physical, profile, lod_nodes, native, transforms, animation_writer, log, model_path):
    configs = _list(physical.get('configs'), profile.family + '/configs')
    if (profile.family == 'ship' or profile.decorative_physics) and len(configs) < len(lod_nodes):
        log.setdefault('vehicleAdaptations', []).append({'model': model_path,
            'field': (profile.decorative_physics or 'waterVehicle') + '/configs',
            'sourceCount': len(configs), 'targetCount': len(lod_nodes),
            'reason': 'Trailing decorative asset LODs have no source config; preserve absence of config-driven animations.' if profile.decorative_physics else
                      'Trailing ship LODs have no source config; preserve absence of config-driven animations.'})
        configs = configs + [{} for _ in range(len(lod_nodes) - len(configs))]
    if len(configs) != len(lod_nodes):
        raise ValueError('Vehicle configs must match the LOD count')
    axle_names, wheel_names, steering_names, bogies = [], [], [], []
    air_radii = {'axles': {}, 'wheels': {}}
    contacts = {'axles': [], 'wheels': []}
    has_flaps = any('flaps' in _dict(node.get('animations', {}), 'node/animations')
                    for nodes in lod_nodes for node in nodes)
    contact_names = {'axles': set(), 'wheels': set()}
    shared = {'axles', 'fakeBogies'}
    rail = set(RAIL_PARTS) | {'brakeLights', 'blinkingLights0', 'blinkingLights1',
                            'blinkLightsLeft0', 'blinkLightsLeft1', 'blinkLightsRight0', 'blinkLightsRight1'}
    road = {'wheels', 'steeringParts', 'headLights', 'brakeLights', 'blinkLightsLeft', 'blinkLightsRight'}
    air = {'wheels', 'steeringParts', 'axleRadii', 'wheelRadii', 'aileronLeft', 'aileronRight',
           'elevator', 'flaps', 'rudder', 'beaconLights', 'landingLight', 'props', 'propsB', 'strobeLights'}
    allowed = {'paddles', 'rudder', 'flags'} if profile.family == 'ship' else shared | (
        rail if profile.family in ('train', 'waggon', 'tram') else air if profile.family == 'plane' else road)
    for li, (raw, nodes) in enumerate(zip(configs, lod_nodes)):
        config = _dict(raw, f'{profile.family} config {li}')
        _known(config, allowed, f'{profile.family} config')
        if profile.family in ('train', 'waggon') and any(config.get(k) for k in (
                'blinkingLights0', 'blinkingLights1', 'blinkLightsLeft0', 'blinkLightsLeft1',
                'blinkLightsRight0', 'blinkLightsRight1')):
            raise ValueError('Non-empty rail blinking lights require a custom TF3 transformator')
        for key, out in (('axles', axle_names), ('wheels', wheel_names)):
            meshes = _list(config.get(key, []), key)
            radii = config.get('axleRadii' if key == 'axles' else 'wheelRadii', [])
            if profile.family == 'plane':
                _list(radii, key + '/radii')
                if len(meshes) != len(radii):
                    raise ValueError(f'{key}: mesh and radius counts differ')
            for mi, mesh in enumerate(meshes):
                matches = [node for node in nodes if node.get('mesh') == mesh]
                if not matches and profile.family != 'plane' and transforms is not None:
                    # TF3 bindings use stable names across LODs. Some TF2
                    # packages declare the main mesh in every config although
                    # the designer kept the same named node with a LOD mesh.
                    # Require explicit names and identical world transforms;
                    # never infer identity from a filename's LOD suffix.
                    anchors = [(node, transforms[j][ni]) for j, other in enumerate(lod_nodes)
                               for ni,node in enumerate(other) if node.get('mesh') == mesh]
                    names = {node['name'] for node, _ in anchors}
                    candidates = [node for node in nodes if 'mesh' in node and node['name'] in names]
                    verified = bool(names) and all(not name.startswith('node_') for name in names) and {n['name'] for n in candidates} == names
                    for candidate in candidates:
                        world = transforms[li][nodes.index(candidate)]
                        verified = verified and any(anchor['name'] == candidate['name'] and all(
                            math.isclose(a,b,rel_tol=1e-7,abs_tol=1e-6) for a,b in zip(world,matrix))
                            for anchor,matrix in anchors)
                    if verified:
                        matches = candidates
                        log.setdefault('vehicleAdaptations', []).append({'model':model_path,'lod':li,
                            'field':key,'sourceMesh':mesh,'nodes':sorted(names),
                            'method':'explicit_corresponding_lod_names_and_identical_world_transforms'})
                if not matches:
                    matches = _mesh_nodes(nodes, [mesh], key)
                for node in matches:
                    if node['name'] not in out:
                        out.append(node['name'])
                    if profile.family == 'plane':
                        radius = _number(radii[mi], key + '/radius', minimum=0)
                        previous = air_radii[key].setdefault(node['name'], radius)
                        if previous != radius:
                            raise ValueError(f'{key}: different radii for a corresponding LOD node')
                        if li == 0 and node['name'] not in contact_names[key]:
                            if transforms is None:
                                raise ValueError('Aircraft wheel positions require complete node transforms')
                            world = transforms[li][nodes.index(node)]
                            # Scaled gear needs scaled radii. Non-uniform scales
                            # cannot describe a circular wheel and are refused.
                            scales = [math.sqrt(sum(world[c * 4 + r] ** 2 for r in range(3))) for c in range(3)]
                            if not all(math.isclose(s, scales[0], abs_tol=1e-5) for s in scales):
                                raise ValueError('Aircraft gear has a non-uniform model transform')
                            contacts[key].append({'position': [world[12], world[14]], 'radius': radius * scales[0]})
                            contact_names[key].add(node['name'])
        for index in _list(config.get('steeringParts', []), 'steeringParts'):
            name = _node(nodes, index, 'steeringParts')['name']
            if name not in steering_names:
                steering_names.append(name)
        lod_bogies = []
        for b in _list(config.get('fakeBogies', []), 'fakeBogies'):
            b = deepcopy(_dict(b, 'fakeBogies'))
            _known(b, {'group', 'offset', 'position', 'upright'}, 'fakeBogie')
            b['group'] = _node(nodes, b.get('group'), 'fakeBogie')['name']
            for key in ('offset', 'position'):
                _number(b.get(key, 0), 'fakeBogie/' + key)
            if 'upright' in b and type(b['upright']) is not bool:
                raise ValueError('fakeBogie/upright must be a boolean')
            lod_bogies.append(b)
        bogies.append(lod_bogies)
        for key in RAIL_PARTS:
            if key in config:
                event = ''.join('_' + c.lower() if c.isupper() else c for c in key)
                _event_pair(nodes, config[key], event, native)
        if 'brakeLights' in config:
            _event_pair(nodes, config['brakeLights'], 'brake_lights', native)
        for side in ('Left', 'Right'):
            event = 'blink_lights_' + side.lower()
            if 'blinkLights' + side in config:
                _event_pair(nodes, config['blinkLights' + side], event, native)
            for phase in (0, 1):
                field = 'blinkLights' + side + str(phase)
                if field in config:
                    _event_pair(nodes, config[field], event, native, alternate=bool(phase))
        for phase in (0, 1):
            field = 'blinkingLights' + str(phase)
            if field in config:
                _event_pair(nodes, config[field], 'blink_lights', native, alternate=bool(phase))
        # TF2 headLights are continuously visible meshes. Keep them visible;
        # root may derive optional actual night lighting separately.
        for index in _list(config.get('headLights', []), 'headLights'):
            _node(nodes, index, 'headLights')
        if profile.family == 'ship':
            if 'flags' in config:
                flags = _dict(config['flags'], 'ship flags')
                _known(flags, {'ids', 'maxAngle'}, 'ship flags')
                if _list(flags.get('ids', []), 'ship flags/ids'):
                    raise ValueError('Non-empty legacy ship flag config requires a separate animation port')
                if 'maxAngle' in flags:
                    _number(flags['maxAngle'], 'ship flags/maxAngle')
            paddle = _dict(config.get('paddles', {}), 'paddles')
            _known(paddle, {'ids', 'maxAngle'}, 'paddles')
            if paddle.get('maxAngle', 0) != 0:
                raise ValueError('Ship paddle maxAngle must be zero for continuous rotation')
            for index in _list(paddle.get('ids', []), 'paddles/ids'):
                _animate(_node(nodes, index, 'paddles'), 'paddles', native.reference('vehicle/shared/ani/paddles.ani'))
            _angle_animation(nodes, config.get('rudder', {}), 'rudder', 'z', native, animation_writer)
        elif profile.family == 'plane':
            for field, event, axis in (('aileronLeft', 'aileron_left', 'x'), ('aileronRight', 'aileron_right', 'x'),
                                       ('elevator', 'elevator', 'x'), ('rudder', 'rudder', 'z'), ('flaps', 'flaps', 'x')):
                detail = config.get(field, {})
                _angle_animation(nodes, detail, event, axis, native, animation_writer, one_way=field == 'flaps')
                if field == 'flaps':
                    has_flaps |= bool(_dict(detail, field).get('ids'))
            for field, event in (('beaconLights', 'beacon_lights'), ('strobeLights', 'strobe_lights')):
                for index in _list(config.get(field, []), field):
                    _animate(_node(nodes, index, field), event, native.reference('vehicle/shared/ani/' + event + '.ani'))
            for field, event in (('landingLight', 'landing_light'), ('props', 'props'), ('propsB', 'props_blurred')):
                _event_pair(nodes, config.get(field, []), event, native)
    combined = {'axles': axle_names, 'fakeBogies': bogies}
    if profile.family not in ('train', 'waggon', 'tram'):
        combined.update(wheels=wheel_names, steeringParts=steering_names)
    if profile.family == 'plane':
        combined.update(axleRadii=[air_radii['axles'][n] for n in axle_names],
                        wheelRadii=[air_radii['wheels'][n] for n in wheel_names])
    return combined, contacts, has_flaps


def normalize_sound_set(sound):
    """TF2 accepts a sound-set filename as well as a table of sound fields."""
    if isinstance(sound, str):
        sound = {'name': sound} if sound else {}
    sound = _dict(sound, 'soundSet')
    _known(sound, {'name', 'horn', 'openDoors', 'closeDoors', 'clacks', 'chuffs'}, 'soundSet')
    for field, value in sound.items():
        if not isinstance(value, str):
            raise ValueError(f'soundSet/{field}: expected a literal resource reference')
    return sound


def _sound_port(sound, resolve):
    sound = normalize_sound_set(sound)
    result = {}
    if sound.get('name'):
        result['soundSet'] = {'name': resolve(sound['name'], 'sound_set')}
    effects = {}
    for key in ('horn', 'openDoors', 'closeDoors', 'clacks', 'chuffs'):
        if sound.get(key):
            effects[key] = [resolve(sound[key], 'audio')]
    if effects:
        result['effects'] = effects
    return result


def _emissions_port(value, policy, model_path):
    """Apply an explicit balancing choice without inventing a pollution split.

    TF3's noise idle/power/speed coefficients use the documented TF2 units.
    Treating the former combined emission as noise is a user choice, not proof
    that either game's pollution behavior is equivalent. Keeping ``strict``
    as the default requires that choice whenever an authored coefficient exists.
    """
    emission = _dict(value, 'emission')
    names = {'idleEmission': ('idle', 100), 'powerEmission': ('power', .0002),
             'speedEmission': ('speed', 2)}
    _known(emission, set(names), 'emission')
    for field, item in emission.items():
        _number(item, 'emission/' + field)
        if item < 0 and item != -1:
            raise ValueError(f'emission/{field}: expected -1 or a non-negative coefficient')
    automatic = {'noise': {'score': -1}, 'pollution': {'score': -1}}
    if all(value == -1 for value in emission.values()):
        return automatic, None
    if policy == 'strict':
        raise ValueError('Explicit TF2 emissions require a noise/pollution balancing decision')
    if policy == 'legacy_noise':
        if set(emission) != set(names) or any(item == -1 for item in emission.values()):
            raise ValueError('Legacy noise choice needs all three explicit TF2 emission coefficients; '
                             'use TF3 automatic emissions or supply an explicit native emission port')
        for field, (_, maximum) in names.items():
            if emission[field] > maximum:
                raise ValueError(f'emission/{field}: exceeds the documented TF3 coefficient range; '
                                 'use TF3 automatic emissions or supply an explicit native emission port')
        target = {'noise': {names[field][0]: item for field, item in emission.items()},
                  'pollution': {'score': -1}}
    else:
        target = automatic
    return target, {'model': model_path, 'field': 'emission',
                    'sourceValue': deepcopy(emission), 'targetValue': deepcopy(target),
                    'emissionsPolicy': policy, 'explicitChoice': True,
                    'policy': 'explicit_legacy_noise_automatic_pollution' if policy == 'legacy_noise'
                              else 'explicit_tf3_automatic_emissions',
                    'noiseCoefficientsPreserved': policy == 'legacy_noise',
                    'pollutionBehaviorPreserved': False,
                    'requiredCheck': 'Verify noise and pollution balancing in TF3.',
                    'schemaSources': [SCHEMA_SOURCES[1], SCHEMA_SOURCES[3]],
                    'nativeTest': 'not_run'}


def adapt_vehicle_metadata(metadata: dict, lod_nodes: list[list[dict]], resolve, native,
                           *, model_path: str = '', weight_max_payload: float | None = 0,
                           node_world_transforms=None, animation_writer=None,
                           report: dict | None = None,
                           emissions_policy: str = 'strict') -> tuple[dict, VehicleProfile]:
    """Migrate verified metadata and mutate caller-owned node animations only.

    Cargo structures and common model extras remain literal and unchanged for
    their dedicated caller adapters. ``weight_max_payload`` is kilograms from
    the caller's cargo analysis. Generated angular animations use an optional
    ``animation_writer(event, {times, transfs})`` returning a resource reference.
    """
    if type(emissions_policy) is not str or emissions_policy not in EMISSIONS_POLICIES:
        raise ValueError('Emissions policy must be strict, legacy_noise, tf3_automatic or class_average')
    emissions_result, emissions_audit = None, None
    source_metadata = _dict(metadata, 'metadata')
    if emissions_policy == 'class_average':
        from .vehicle_mode import class_average_emissions
        emissions_result, emissions_audit = class_average_emissions(
            {'metadata': source_metadata}, native, model_path=model_path)
    elif 'emission' in source_metadata:
        emissions_result, emissions_audit = _emissions_port(source_metadata['emission'], emissions_policy, model_path)
    profile = classify_model(metadata, model_path)
    result = deepcopy(_dict(metadata, 'metadata'))
    _known(result, COMMON_METADATA | VEHICLE_BLOCKS | {'transportVehicle', 'soundConfig', 'car'}, 'model metadata')
    log = report if report is not None else {}
    if profile.carrier is not None or profile.decorative_physics:
        physical_key = profile.decorative_physics or {'train': 'railVehicle', 'waggon': 'railVehicle', 'tram': 'railVehicle',
                        'bus': 'roadVehicle', 'truck': 'roadVehicle', 'car': 'roadVehicle',
                        'plane': 'airVehicle', 'ship': 'waterVehicle'}[profile.family]
        physical = _dict(result[physical_key], physical_key)
        if profile.decorative_physics == 'waterVehicle' and 'engines' in physical:
            if physical['engines'] != []:
                raise ValueError('Decorative waterVehicle engines must be empty; active engine data requires an adapter')
            log.setdefault('vehicleAdaptations', []).append({'model': model_path,
                'field': 'waterVehicle/engines', 'sourceValue': physical.pop('engines'),
                'policy': 'omit_inert_empty_decorative_ship_engine_list', 'nativeTest': 'not_run'})
        allowed = {
            'railVehicle': {'engines', 'configs', 'soundSet', 'topSpeed', 'weight', 'blinkInterval'},
            'roadVehicle': {'engine', 'configs', 'soundSet', 'topSpeed', 'weight', 'blinkInterval'},
            'waterVehicle': {'configs', 'waterLine', 'area', 'availPower', 'weight', 'maxRpm', 'topSpeed', 'type'},
            'airVehicle': {'configs', 'maxPayload', 'maxTakeOffWeight', 'maxThrust', 'idleThrust',
                           'timeToFullThrust', 'topSpeed', 'weight', 'wingArea', 'type'},
        }[physical_key]
        _known(physical, allowed, physical_key)
        _number(physical.get('topSpeed'), physical_key + '/topSpeed', minimum=0)
        _number(physical.get('weight'), physical_key + '/weight', minimum=0)
        if weight_max_payload is not None or physical_key != 'airVehicle':
            _number(weight_max_payload, 'weightMaxPayload', minimum=0)
        if physical.get('blinkInterval', 500) != 500:
            raise ValueError('Non-default blinkInterval requires a custom TF3 transformator')
        config_profile = replace(profile, family={'roadVehicle':'car', 'waterVehicle':'ship', 'airVehicle':'plane'}[physical_key]) if profile.decorative_physics else profile
        combined, contacts, has_flaps = _config_port(physical, config_profile, lod_nodes, native,
                                                    node_world_transforms, animation_writer, log, model_path)
        if profile.decorative_physics:
            log.setdefault('vehicleAdaptations', []).append({'model': model_path,
                'field': physical_key, 'policy': 'preserve_construction_asset_physics_and_animation_config',
                'evidence': 'Explicit asset path with no transportVehicle or car metadata',
                'createdTransportMetadata': False, 'createdCarMetadata': False,
                'nativeTest': 'not_run'})
        if physical_key in ('railVehicle', 'roadVehicle'):
            engines = physical.get('engines', []) if physical_key == 'railVehicle' else [physical['engine']] if physical.get('engine') else []
            result['landVehicle'] = {'engines': deepcopy(engines), 'topSpeed': physical['topSpeed'],
                                     'weightEmpty': physical['weight'] * 1000, 'weightMaxPayload': weight_max_payload}
            result[physical_key] = {'config': combined}
            sound = _sound_port(physical.get('soundSet', {}), resolve)
            if sound:
                if result.get('soundConfig'):
                    raise ValueError('Both vehicle soundSet and model soundConfig require explicit merging')
                result['soundConfig'] = sound
        else:
            target = {key: deepcopy(value) for key, value in physical.items()
                      if key not in ('configs', 'weight', 'maxPayload', 'maxTakeOffWeight')}
            target['weightEmpty'] = physical['weight']
            if weight_max_payload is not None:
                target['weightMaxPayload'] = weight_max_payload
            if physical_key == 'airVehicle':
                for key in ('maxThrust', 'idleThrust', 'timeToFullThrust', 'wingArea'):
                    if key in target:
                        _number(target[key], physical_key + '/' + key, minimum=0)
                target.update(config=combined, axles=contacts['axles'], wheels=contacts['wheels'], hasFlaps=has_flaps)
                for key in ('maxPayload', 'maxTakeOffWeight'):
                    if key in physical:
                        _number(physical[key], physical_key + '/' + key, minimum=0)
                        log.setdefault('legacyVehicleFields', []).append({'model': model_path, 'field': 'airVehicle/' + key,
                            'value': physical[key], 'reason': 'TF2 documented unused value; target payload comes from preserved cargo capacities.'})
            else:
                for key in ('area', 'availPower', 'maxRpm'):
                    _number(target.get(key), physical_key + '/' + key, minimum=0)
                waterline = _list(target.get('waterLine', []), 'waterLine')
                normalized = []
                zero_z_points = 0
                for point in waterline:
                    if not isinstance(point, list) or len(point) not in (2, 3):
                        raise ValueError('waterLine points require x/y pairs')
                    for value in point:
                        _number(value, 'waterLine')
                    # Native TF2 Vandal uses x/y/0 triples for an explicitly
                    # two-dimensional schema. Zero z is redundant; any other
                    # z would require a verified projection and blocks export.
                    if len(point) == 3:
                        if point[2] != 0:
                            raise ValueError('waterLine with nonzero z requires a verified projection')
                        zero_z_points += 1
                    normalized.append(point[:2])
                if 'waterLine' in target:
                    target['waterLine'] = normalized
                if zero_z_points:
                    log.setdefault('vehicleAdaptations', []).append({'model': model_path,
                        'field': 'waterVehicle/waterLine', 'zeroZPoints': zero_z_points,
                        'reason': 'Convert redundant x/y/0 points to the documented two-dimensional x/y schema.'})
            result[physical_key] = target
            if 'soundConfig' in result:
                source_sound = _dict(result['soundConfig'], 'soundConfig')
                _known(source_sound, {'soundSet', 'effects'}, 'soundConfig')
                sound = _sound_port(source_sound.get('soundSet', {}), resolve)
                existing = _dict(source_sound.get('effects', {}), 'soundConfig/effects')
                for event, values in existing.items():
                    values = values if isinstance(values, list) else [values]
                    if not all(isinstance(v, str) for v in values):
                        raise ValueError('soundConfig/effects requires literal audio references')
                    if event in sound.get('effects', {}):
                        raise ValueError(f'Conflicting sound effect {event}')
                    sound.setdefault('effects', {})[event] = [resolve(v, 'audio') for v in values if v]
                result['soundConfig'] = sound
        result['transformatorConfig'] = {'transformator': {'name': native.reference(profile.transformer)}}
        if 'transportVehicle' in result and profile.family != 'car':
            t = _dict(result['transportVehicle'], 'transportVehicle')
            if set(t) & {'maxWeight', 'maxVolume'}:
                from .missing_data import legacy_payload_hints
                hints = legacy_payload_hints({'metadata': {'transportVehicle': t}})
                if (hints['weightMaxPayload'] is None or type(weight_max_payload) not in (int, float)
                        or not math.isfinite(weight_max_payload) or weight_max_payload != hints['weightMaxPayload']):
                    raise ValueError('EMP cargo limits require the native payload to match the authored maxWeight in tonnes; '
                                     'volume alone cannot determine payload or cargo capacity')
                for field, source_value in hints['sourceFields'].items():
                    t.pop(field)
                    log.setdefault('vehicleAdaptations', []).append({
                        'model': model_path, 'field': 'transportVehicle/'+field, 'sourceValue': source_value,
                        'sourceUnit': 't' if field == 'maxWeight' else 'm3',
                        'weightMaxPayload': weight_max_payload if field == 'maxWeight' else None,
                        'method': 'consume_documented_emp_payload_hint' if field == 'maxWeight' else
                                  'archive_emp_volume_hint_preserve_authored_capacity',
                        'schemaSource': hints['schemaSource'], 'nativeTest': 'not_run'})
            _known(t, {'carrier', 'compartmentsList', 'compartments', 'capacities', 'groupFileName', 'loadSpeed',
                       'multipleUnitOnly', 'reversible', 'departureDelay'}, 'transportVehicle')
            if 'departureDelay' in t:
                _number(t['departureDelay'], 'transportVehicle/departureDelay', minimum=0)
            for field in ('multipleUnitOnly', 'reversible'):
                if field in t and type(t[field]) is not bool:
                    raise ValueError(f'transportVehicle/{field} must be a boolean')
            t.update(transportModes=list(profile.transport_modes), engineTransportModes=list(profile.engine_transport_modes),
                     comfortFactor=-1 if 'PASSENGERS' in _cargo_categories(t) else 0,
                     filterTags=[] if t.pop('multipleUnitOnly', False) else ['default'])
            if t.get('groupFileName'):
                t['groupFileName'] = resolve(t['groupFileName'], 'model')
            result['transportVehicle'] = t
    if 'emission' in result or emissions_policy == 'class_average' and emissions_result is not None:
        result.pop('emission', None)
        result['emissions'] = emissions_result
        if emissions_audit is not None:
            log.setdefault('vehicleAdaptations', []).append(emissions_audit)
    if 'maintenance' in result:
        maintenance = _dict(result['maintenance'], 'maintenance')
        _known(maintenance, {'lifespan', 'runningCosts', 'runningCostScale'}, 'maintenance')
        if 'lifespan' in maintenance:
            maintenance['lifespan'] = _number(maintenance['lifespan'], 'maintenance/lifespan', minimum=0) * 2
        result['maintenance'] = maintenance
    if 'seatProvider' in result:
        seats = _dict(result['seatProvider'], 'seatProvider')
        _known(seats, {'crewModels', 'drivingLicense', 'renderDistance', 'seats'}, 'seatProvider')
        if seats.get('drivingLicense') and seats['drivingLicense'] not in {
                'BUS', 'TRUCK', 'TRAM', 'RAIL', 'WATER', 'AIR', 'AIR_OUTDOOR'}:
            raise ValueError('Unsupported seatProvider driving license')
        seats['crewModels'] = [resolve(ref, 'model') for ref in _list(seats.get('crewModels', []), 'crewModels')]
        if not seats['crewModels'] and not seats.get('drivingLicense'):
            license_ = {'bus': 'BUS', 'truck': 'TRUCK', 'tram': 'TRAM', 'train': 'RAIL',
                        'waggon': 'RAIL', 'ship': 'WATER', 'plane': 'AIR'}.get(profile.family)
            if license_:
                seats['drivingLicense'] = license_
        standing_schema_checked = False
        for seat_index, seat in enumerate(_list(seats.get('seats', []), 'seats')):
            seat = _dict(seat, 'seat')
            _known(seat, {'group', 'crew', 'forward', 'animation', 'transf', 'standing'}, 'seat')
            if 'standing' in seat:
                standing, animation = seat['standing'], seat.get('animation')
                if (type(animation) is not str or not
                        ((standing is False and animation == 'sitting')
                         or (standing is True and animation == 'idle'))):
                    raise ValueError('seat/standing requires a matching explicit sitting or idle animation')
                proof = 'vehicle/train/hst_125/hst_125_middle2.mdl'
                if not standing_schema_checked and hasattr(native, 'read'):
                    native.read(proof)
                    standing_schema_checked = True
                # Posture is explicitly selected by animation in both games.
                # Retire only the legacy flag that agrees with that animation.
                del seat['standing']
                log.setdefault('seatMigrations', []).append({
                    'model': model_path, 'seatIndex': seat_index, 'sourceValue': standing,
                    'animation': animation, 'policy': 'preserve_explicit_pose_retire_matching_legacy_standing',
                    'nativeSchemaResource': proof,
                    'schemaSource': 'https://wiki.transportfever3.com/doku.php?id=modding:vehicles:basics#seats',
                    'nativeTest': 'not_run'})
            for field in ('crew', 'forward'):
                if field in seat and type(seat[field]) is not bool:
                    raise ValueError(f'seat/{field} must be a boolean')
            if 'transf' in seat:
                _matrix(seat['transf'], 'seat/transf')
            seat['group'] = _node(lod_nodes[0], seat.get('group'), 'seat')['name']
        result['seatProvider'] = seats
    if profile.family == 'person':
        person = _dict(result['person'], 'person')
        _known(person, {'drivingLicenses', 'gender'}, 'person')
        if person.get('gender') not in ('MALE', 'FEMALE'):
            raise ValueError('Unsupported person gender')
        licenses = _list(person.get('drivingLicenses', []), 'person/drivingLicenses')
        if any(v not in {'BUS', 'TRUCK', 'TRAM', 'RAIL', 'WATER', 'AIR', 'AIR_OUTDOOR'} for v in licenses):
            raise ValueError('Unsupported person driving license')
        result['person'] = person
    log.setdefault('vehicleProfiles', []).append({'model': model_path, 'profile': profile.key,
        'family': profile.family, 'carrier': profile.carrier, 'nativeTest': 'not_run'})
    return result, profile

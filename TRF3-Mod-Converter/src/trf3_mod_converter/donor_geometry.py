"""Complete absent aircraft radii without transferring donor node bindings.

Existing source LOD evidence takes precedence. A native donor is an explicit
estimate, accepted only for compatible named landing gear and body geometry.
The caller owns donor classification, native resource validation and selection.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math

from .vehicle_profiles import derive_lod_nodes


GEAR = (('axles', 'axleRadii'), ('wheels', 'wheelRadii'))


def _positive(value, where):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{where}: landing-gear radius must be positive and finite')
    return value


def _explicit_names(node):
    names = []
    if isinstance(node, dict):
        if isinstance(node.get('name'), str) and node['name']:
            names.append(node['name'])
        for child in node.get('children', []):
            names.extend(_explicit_names(child))
    return names


@dataclass
class _Group:
    lod: int
    index: int
    role: str
    field: str
    mesh: str
    nodes: list
    radius: float | int | None


def _source_groups(model):
    physical = (model.get('metadata') or {}).get('airVehicle')
    if physical is None:
        return [], None
    if not isinstance(physical, dict):
        raise ValueError('airVehicle must be a named literal table')
    configs = physical.get('configs')
    lods = model.get('lods')
    if not isinstance(configs, list) or not isinstance(lods, list) or len(configs) != len(lods):
        raise ValueError('Aircraft configs must match the source LOD count')
    copies = deepcopy(lods)
    node_lists, transforms = derive_lod_nodes(copies, metadata=model.get('metadata') or {})
    originals = [_explicit_names(lod.get('node')) for lod in lods]
    groups = []
    for li, config in enumerate(configs):
        config = {} if config == [] else config
        if not isinstance(config, dict):
            raise ValueError('Aircraft config must be a named literal table')
        for role, field in GEAR:
            meshes = config.get(role, [])
            radii = config.get(field, [])
            if not isinstance(meshes, list) or not all(isinstance(m, str) for m in meshes):
                raise ValueError(f'airVehicle/configs/{role}: expected mesh reference list')
            if not isinstance(radii, list) or len(radii) > len(meshes):
                raise ValueError(f'airVehicle/configs/{field}: excess or invalid radius entries')
            for mi, mesh in enumerate(meshes):
                radius = radii[mi] if mi < len(radii) else None
                if radius is not None:
                    if type(radius) not in (int, float) or not math.isfinite(radius) or radius < 0:
                        raise ValueError(f'{field}: source radius must be finite and nonnegative')
                matches = [(node, transforms[li][ni],
                            originals[li].count(node['name']) == 1 and not node['name'].startswith('node_'))
                           for ni, node in enumerate(node_lists[li]) if node.get('mesh') == mesh]
                if not matches:
                    raise ValueError(f'airVehicle/configs/{role}: mesh {mesh!r} has no source node')
                groups.append(_Group(li, mi, role, field, mesh, matches, radius))
    return groups, physical


def _equivalent(left, right):
    if left.role != right.role or len(left.nodes) != len(right.nodes):
        return False
    if not all(explicit for _, _, explicit in left.nodes + right.nodes):
        return False
    a = {node['name']: world for node, world, _ in left.nodes}
    b = {node['name']: world for node, world, _ in right.nodes}
    return a.keys() == b.keys() and all(all(math.isclose(x, y, rel_tol=1e-7, abs_tol=1e-6)
                                            for x, y in zip(a[name], b[name])) for name in a)


def _bounds(model, *, native=False):
    bounds = (model.get('metadata') or {}).get('extent') if native else None
    if not bounds:
        bounds = model.get('boundingInfo')
    if not isinstance(bounds, dict):
        raise ValueError('Native gear completion needs finite source and donor body bounds')
    lo, hi = bounds.get('bbMin'), bounds.get('bbMax')
    if not isinstance(lo, list) or not isinstance(hi, list) or len(lo) != 3 or len(hi) != 3:
        raise ValueError('Native gear completion needs three-dimensional body bounds')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in lo + hi):
        raise ValueError('Native gear completion needs finite body bounds')
    sizes = [b-a for a, b in zip(lo, hi)]
    if any(v <= 0 for v in sizes):
        raise ValueError('Native gear completion needs positive body dimensions')
    return [(a+b)/2 for a, b in zip(lo, hi)], sizes


def _scale(world, where):
    axes = [[world[c*4+r] for r in range(3)] for c in range(3)]
    scales = [math.sqrt(sum(v*v for v in axis)) for axis in axes]
    if any(s <= 0 for s in scales) or not all(math.isclose(s, scales[0], rel_tol=1e-5, abs_tol=1e-6) for s in scales):
        raise ValueError(f'{where}: donor gear completion requires uniform node scaling')
    if any(abs(sum(a*b for a, b in zip(axes[i], axes[j]))) > scales[i]*scales[j]*1e-5
           for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError(f'{where}: donor gear completion does not accept sheared nodes')
    return scales[0]


def _native_groups(model):
    physical = (model.get('metadata') or {}).get('airVehicle')
    config = physical.get('config') if isinstance(physical, dict) else None
    if not isinstance(config, dict):
        raise ValueError('Chosen TF3 donor has no named aircraft gear config')
    lods = deepcopy(model.get('lods'))
    if not isinstance(lods, list) or not lods:
        raise ValueError('Chosen TF3 donor has no landing-gear geometry')
    original_names = _explicit_names(lods[0].get('node'))
    nodes, worlds = derive_lod_nodes(lods, metadata=model.get('metadata') or {})
    result = {}
    for role, field in GEAR:
        names, radii = config.get(role, []), config.get(field, [])
        if (not isinstance(names, list) or not isinstance(radii, list) or len(names) != len(radii)
                or any(not isinstance(n, str) or not n or n.startswith('node_') for n in names)
                or len(names) != len(set(names))):
            raise ValueError(f'Chosen TF3 donor has invalid named {role} or radii')
        result[role] = {}
        for name, radius in zip(names, radii):
            _positive(radius, 'donor/'+field)
            matches = [(node, worlds[0][ni]) for ni, node in enumerate(nodes[0])
                       if node.get('mesh') and node['name'] == name]
            if len(matches) != 1 or original_names.count(name) != 1:
                raise ValueError(f'Chosen TF3 donor has no unique explicit gear node {name!r}')
            result[role][name] = (radius, matches[0][1])
    return result


def _native_values(model, groups, match):
    donor_model = match.model
    source_center, source_sizes = _bounds(model)
    donor_center, donor_sizes = _bounds(donor_model, native=True)
    ratios = [s/d for s, d in zip(source_sizes, donor_sizes)]
    body_scale = sum(ratios)/3
    if any(abs(ratio/body_scale-1) > 0.05 for ratio in ratios):
        raise ValueError('Chosen TF3 donor body dimensions do not match uniformly within 5%')
    native_groups = _native_groups(donor_model)
    for role, _ in GEAR:
        source_names = {node['name'] for group in groups if group.role == role for node, _, _ in group.nodes}
        if source_names != native_groups[role].keys():
            raise ValueError(f'Chosen TF3 donor has different named {role} roles or counts')
    completed = {}
    for group in groups:
        values = []
        for node, source_world, explicit in group.nodes:
            if not explicit:
                raise ValueError('Native gear completion requires explicit unique source node names')
            donor_radius, donor_world = native_groups[group.role][node['name']]
            source_pos = [(source_world[12+i]-source_center[i])/source_sizes[i] for i in range(3)]
            donor_pos = [(donor_world[12+i]-donor_center[i])/donor_sizes[i] for i in range(3)]
            if any(abs(a-b) > 0.02 for a, b in zip(source_pos, donor_pos)):
                raise ValueError(f'Chosen TF3 donor gear node {node["name"]!r} differs by more than 2% of body extent')
            donor_scale = _scale(donor_world, 'donor/'+node['name'])
            source_scale = _scale(source_world, 'source/'+node['name'])
            values.append(donor_radius*donor_scale*body_scale/source_scale)
        if group.radius is not None:
            continue
        if not values or any(not math.isclose(v, values[0], rel_tol=1e-6, abs_tol=1e-6) for v in values):
            raise ValueError('A source mesh has multiple incompatible donor landing-gear radii')
        completed[(group.lod, group.role, group.index)] = (values[0], body_scale)
    return completed


def air_gear_needs(model):
    """Whether a TF2 aircraft has absent radii; malformed data remains an error."""
    groups, _ = _source_groups(model)
    return any(group.radius is None for group in groups)


def complete_air_gear(source_model, match=None, *, report=None, model_path=''):
    """Return a copied source model with evidenced absent gear radii completed.

    ``match`` is a selected NativeMatch with ``model``, ``resource`` and
    ``evidence`` attributes. Without it, unresolved absent entries are retained
    for donor selection or the existing strict metadata adapter to reject.
    Existing invalid/conflicting entries are never replaced with donor data.
    An authored zero source radius is preserved, as in the TF2 config schema;
    donor estimates must have strictly positive radii.
    """
    result = deepcopy(source_model)
    groups, physical = _source_groups(result)
    if physical is None:
        return result
    for group in groups:
        if group.radius is not None:
            peers = [peer for peer in groups if peer.radius is not None and _equivalent(group, peer)]
            if any(not math.isclose(peer.radius, group.radius, rel_tol=1e-7, abs_tol=1e-6) for peer in peers):
                raise ValueError('Corresponding source LOD gear nodes have conflicting radii')
    changes = []
    for group in groups:
        if group.radius is not None:
            continue
        peers = [peer for peer in groups if peer.radius is not None and _equivalent(group, peer)]
        if peers:
            values = {peer.radius for peer in peers}
            if len(values) != 1:
                raise ValueError('Corresponding source LOD gear nodes have conflicting radii')
            group.radius = peers[0].radius
            changes.append((group, 'exact_source_lod', {'sourceLod': peers[0].lod, 'estimated': False}))
    if match is not None and any(group.radius is None for group in groups):
        values = _native_values(result, groups, match)
        for group in groups:
            key = (group.lod, group.role, group.index)
            if key in values:
                group.radius, scale = values[key]
                changes.append((group, 'approximate_native_geometry_match', {
                    'donor': match.resource, 'evidence': deepcopy(getattr(match, 'evidence', {})),
                    'bodyScale': scale, 'estimated': True, 'needs_native_validation': True}))
    for group, method, detail in changes:
        config = physical['configs'][group.lod]
        values = config.setdefault(group.field, [])
        while len(values) <= group.index:
            values.append(None)
        values[group.index] = group.radius
        if report is not None:
            report.setdefault('dataCompletions', []).append({
                'model': model_path, 'field': f'airVehicle/configs/{group.lod}/{group.field}/{group.index}',
                'value': group.radius, 'method': method, 'nodes': [node['name'] for node, _, _ in group.nodes],
                'nativeTest': 'not_run', **detail})
    return result

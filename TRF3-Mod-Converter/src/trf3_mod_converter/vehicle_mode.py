"""User-selected vehicle drafts with preserved TF2 data and dependency warnings.

Missing external resources stay explicit references. They never stand in for
verified local bytes or count as proof that the vehicle runs without its base.
"""
from copy import deepcopy
import math
from pathlib import Path
import re
import struct
from statistics import fmean

from .vehicle_profiles import VEHICLE_BLOCKS

VEHICLE_PATH = re.compile(r'(?:^|/)(?:vehicle|vehicles)/(?:train|waggon|wagon|tram|bus|truck|car|plane|ship|aircraft)(?:/|$)', re.I)


def vehicle_package(root):
    """Accept vehicle models and appearance patches without loading a base mod."""
    root = Path(root)
    for folder in ('res', 'content'):
        content = root/folder
        if not content.is_dir():
            continue
        for file in content.rglob('*'):
            if not file.is_file():
                continue
            relative = file.relative_to(content).as_posix()
            if VEHICLE_PATH.search(relative):
                return True
            if file.suffix == '.mdl':
                # Path-independent declarations cover unconventional model folders.
                text = file.read_text(encoding='utf-8-sig', errors='replace')
                if any(re.search(r'\b'+key+r'\s*=', text) for key in VEHICLE_BLOCKS):
                    return True
    return False


def warning(audit, message, **evidence):
    row = {'message': message, 'nativeTest': 'not_run', **evidence}
    if row not in audit.setdefault('vehicleWarnings', []):
        audit['vehicleWarnings'].append(row)


def empty_model_metadata(text):
    """Recognize a render helper example with an explicit empty metadata table."""
    from luaparser import ast, astnodes as lua
    tree = ast.parse(text)
    functions = [s for s in tree.body.body if isinstance(s, lua.Function)
                 and isinstance(s.name, lua.Name) and s.name.id == 'data']
    if len(functions) != 1 or len(functions[0].body.body) != 1:
        return False
    returned = functions[0].body.body[0]
    if not isinstance(returned, lua.Return) or len(returned.values) != 1 or not isinstance(returned.values[0], lua.Table):
        return False
    metadata = [f.value for f in returned.values[0].fields if isinstance(f.key, lua.Name) and f.key.id == 'metadata']
    return len(metadata) == 1 and isinstance(metadata[0], lua.Table) and not metadata[0].fields


def _class(model, path):
    from .vehicle_profiles import classify_model
    from .missing_data import classification_view
    profile = classify_model(classification_view(model), path)
    metadata = model.get('metadata') or {}
    physical = next((metadata[k] for k in VEHICLE_BLOCKS if k in metadata), {})
    return profile, physical.get('type')


def prepare_vehicle_model(model, *, model_path, report):
    """Complete a missing carrier only from an explicit physical/path contract."""
    data = deepcopy(model)
    metadata = data.get('metadata') or {}
    palette = metadata.get('colorConfig')
    if isinstance(palette, dict) and isinstance(palette.get('configs'), list):
        colors = [color for config in palette['configs'] if isinstance(config, list) for color in config]
        if (colors and all(isinstance(color, list) and len(color) == 3
                and all(type(v) in (int, float) and math.isfinite(v) for v in color) for color in colors)
                and any(not 0 <= v <= 1 for color in colors for v in color)):
            warning(report, 'A source variation palette outside the supported RGB range stays archived; supplied material textures and colors are retained.',
                    model=model_path, field='colorConfig', sourceValue=metadata.pop('colorConfig'))
    def normalize_children(node):
        numeric = {key for key in node if type(key) is int}
        if (numeric and numeric == set(range(1, len(numeric)+1))
                and isinstance(node.get('mesh'), str) and node['mesh']
                and all(isinstance(node[k], dict) for k in numeric)):
            # A mesh node's documented subtree is in children. Bare numeric
            # fields are not child nodes: moving them there changes the graph
            # and all subsequent integer bindings. Keep the authored mesh and
            # its real children, retaining the stray tables in the audit.
            extras = {k:node.pop(k) for k in sorted(numeric)}
            warning(report, 'Numeric fields outside a mesh node\'s children stay archived; the authored mesh, actual children and node order are retained.',
                    model=model_path, node=node.get('name'), sourceValue=extras)
        matrix = node.get('transf')
        if (isinstance(matrix, list) and len(matrix) == 16
                and all(type(v) in (int, float) and math.isfinite(v) for v in matrix)
                and matrix[15] > 0 and matrix[15] != 1
                and all(matrix[i] == 0 for i in (3,7,11))):
            # Constant homogeneous scale is affine after division by W. No
            # position-dependent perspective term or replacement is inferred.
            normalized = [v/matrix[15] for v in matrix]
            if all(math.isfinite(v) for v in normalized):
                node['transf'] = normalized
                warning(report, 'A constant homogeneous transform is normalized to its equivalent affine matrix; appearance needs a game check.',
                        model=model_path, node=node.get('name'), sourceValue=matrix, targetValue=normalized)
        children = node.get('children', [])
        if isinstance(children, dict):
            numeric = {key for key in children if type(key) is int}
            if numeric == set(range(1, len(numeric)+1)) and all(isinstance(children[k], dict) for k in numeric):
                extras = {k:v for k,v in children.items() if type(k) is not int}
                if extras:
                    warning(report, 'Named fields inside a children array stay archived; numeric child nodes keep their original transforms.',
                            model=model_path, sourceValue=deepcopy(extras))
                children = node['children'] = [children[k] for k in sorted(numeric)]
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict): normalize_children(child)
    for lod in data.get('lods', []):
        if isinstance(lod.get('node'), dict): normalize_children(lod['node'])
    if '/asset/' in '/'+model_path.lower():
        for key in ('roadasset', 'transportasset'):
            if key in metadata:
                warning(report, 'An inactive author asset tag stays archived; the decorative model is retained.',
                        model=model_path, field=key, sourceValue=metadata.pop(key))
    transport = metadata.get('transportVehicle')
    slot_provider = metadata.get('cargoSlotProvider')
    slots = slot_provider.get('slots') if isinstance(slot_provider, dict) else None
    def uses_custom_slots(value):
        if isinstance(value, dict):
            return 'customCargoModels' in value or any(uses_custom_slots(v) for v in value.values())
        return isinstance(value, list) and any(uses_custom_slots(v) for v in value)
    if (isinstance(slots, list) and slots
            and all(isinstance(slot, dict) and slot.get('models') == [] for slot in slots)
            and not uses_custom_slots(transport)):
        warning(report, 'An unused cargo slot table without any source models stays archived; cargo bay displays and capacities are retained.',
                model=model_path, field='cargoSlotProvider', sourceValue=metadata.pop('cargoSlotProvider'))
    rail = metadata.get('railVehicle')
    if (isinstance(transport, dict) and transport.get('carrier') == 'ROAD'
            and isinstance(rail, dict) and rail.get('weight') == rail.get('topSpeed') == 0
            and not rail.get('engines') and transport.get('multipleUnitOnly') is True):
        metadata['roadVehicle'] = metadata.pop('railVehicle')
        metadata['roadVehicle'].pop('engines', None)
        warning(report, 'A stationary road menu placeholder uses its explicit ROAD carrier instead of its empty rail physics tag.',
                model=model_path, sourceValue=deepcopy(rail))
    if isinstance(transport, dict) and transport.get('carrier') is None:
        blocks = VEHICLE_BLOCKS & metadata.keys()
        if len(blocks) == 1:
            block = next(iter(blocks))
            carrier = {'roadVehicle':'ROAD', 'airVehicle':'AIR', 'waterVehicle':'WATER'}.get(block)
            match = VEHICLE_PATH.search(model_path)
            if block == 'railVehicle' and match:
                family = model_path[match.start():match.end()].lower().strip('/').split('/')[-1]
                carrier = 'TRAM' if family == 'tram' else 'RAIL' if family in ('train','waggon','wagon') else None
            if carrier:
                transport['carrier'] = carrier
                warning(report, 'Missing carrier is completed from the declared physical vehicle type and resource folder.',
                        model=model_path, field='transportVehicle/carrier', value=carrier, estimated=True)
    # Invalid optional display attachments must not discard vehicle capacities.
    from .tf2_vehicle_port import flatten
    lods = data.get('lods') or []
    if lods and isinstance(transport, dict):
        count = len(list(flatten(lods[0]['node'])))
        source_refs = {node[key] for lod in lods for node in flatten(lod['node'])
                       for key in ('name','mesh','_source_mesh') if isinstance(node.get(key),str)}
        seat_count = len((metadata.get('seatProvider') or {}).get('seats', []))
        def display(value):
            if isinstance(value, dict):
                if (type(value.get('rt_off')) is bool and 'capacity' in value
                        and ('type' in value or 'cargoTypeSet' in value)):
                    warning(report, 'The Rail & Track Industry extension flag stays archived; its external cargo filtering is inactive while authored vehicle capacities and cargo displays are retained.',
                            model=model_path,field='cargoEntry/rt_off',sourceValue=value.pop('rt_off'))
                hidden = value.get('toHide')
                if isinstance(hidden,list) and ('cargoEntries' in value or 'cargoEntry' in value):
                    valid = [token for token in hidden if not (isinstance(token,str) and token and token not in source_refs)]
                    if valid != hidden:
                        warning(report, 'Cargo visibility names absent from every source LOD stay archived; existing visibility bindings and capacities are retained.',
                                model=model_path,sourceValue=deepcopy(hidden),targetValue=valid)
                        value['toHide'] = valid
                custom = value.get('customCargoModels')
                if isinstance(custom,dict):
                    numeric = {key for key in custom if type(key) is int}
                    if (numeric and set(custom)==numeric|{'configurations'}
                            and numeric==set(range(1,len(numeric)+1))
                            and isinstance(custom.get('configurations'),list) and custom['configurations']
                            and all(isinstance(custom[key],dict) and set(custom[key])=={'slotLevels'}
                                    and isinstance(custom[key]['slotLevels'],list) for key in numeric)):
                        # The installed makeLoadIndicators reads only the
                        # explicit configurations field, never these siblings.
                        extras = {key:custom.pop(key) for key in sorted(numeric)}
                        warning(report, 'Numeric slot tables outside customCargoModels.configurations stay archived; the native adapter uses the authored configurations without adding slots.',
                                model=model_path,sourceValue=extras,policy='native_makeLoadIndicators_explicit_configurations')
                seats = value.get('seats')
                if isinstance(seats, list) and any(type(i) is int and not 0 <= i < seat_count for i in seats):
                    valid = [i for i in seats if type(i) is not int or 0 <= i < seat_count]
                    warning(report, 'Cargo seat references absent from the source seat table stay archived; capacity and all existing seat bindings are retained.',
                            model=model_path, sourceValue=seats, targetValue=valid)
                    value['seats'] = valid
                bay = value.get('cargoBay')
                if (isinstance(bay, dict) and all(isinstance(bay.get(k), list) and len(bay[k]) == 3 for k in ('bbMin','bbMax'))
                        and all(type(v) in (int,float) and math.isfinite(v) for k in ('bbMin','bbMax') for v in bay[k])
                        and any(lo >= hi for lo,hi in zip(bay['bbMin'],bay['bbMax']))):
                    warning(report, 'A cargo display without a valid source volume stays archived; cargo types and capacities are retained.',
                            model=model_path, sourceValue=value.pop('cargoBay'))
                    bay = None
                if isinstance(bay, dict) and type(bay.get('childId')) is int and not 0 <= bay['childId'] < count:
                    warning(report, 'A cargo display with a nonexistent source node stays archived; all cargo types and capacities are retained.',
                            model=model_path, sourceValue=value.pop('cargoBay'))
                if value.get('cargoBay') and value.get('customCargoModels'):
                    warning(report, 'Combined cargo displays follow the installed native adapter: authored custom slot models take precedence; the redundant bay stays archived.',
                            model=model_path, sourceValue=value.pop('cargoBay'),
                            policy='native_makeLoadIndicators_custom_slots_precedence')
                for child in value.values(): display(child)
            elif isinstance(value, list):
                for child in value: display(child)
        display(transport)
    return data


def compatible_gear_configs(metadata, nodes, *, model_path, report):
    """Bind shared TF2 gear lists separately to each actual LOD's meshes."""
    for block in VEHICLE_BLOCKS & metadata.keys():
        physical = metadata[block]
        configs = physical.get('configs')
        if configs == []:
            physical.pop('configs')
            physical['config'] = {}
            report.setdefault('vehicleAdaptations', []).append({'model':model_path,
                'field':block+'/configs', 'sourceValue':[], 'targetValue':{},
                'policy':'empty_legacy_configs_to_empty_single_config', 'nativeTest':'not_run'})
            continue
        if configs is None and isinstance(physical.get('config'), dict):
            configs = [physical.pop('config')]
        if not isinstance(configs, list) or not configs:
            continue
        if len(configs) == 1 and len(nodes) > 1:
            configs = [deepcopy(configs[0]) for _ in nodes]
        for li, config in enumerate(configs):
            if config == []:
                config = configs[li] = {}
            if not isinstance(config, dict):
                raise ValueError('Compatibility gear config must be a named literal table')
            available = {value for node in (nodes[li] if li < len(nodes) else [])
                         for value in (node.get('mesh'), node.get('name')) if value}
            for role, field in (('axles','axleRadii'), ('wheels','wheelRadii')):
                meshes = config.get(role)
                if not isinstance(meshes, list):
                    continue
                radii = config.get(field) or []
                kept, kept_radii = [], []
                for index, mesh in enumerate(meshes):
                    if mesh not in available:
                        warning(report, 'A shared gear binding absent from this LOD stays archived; visible gear bindings are retained.',
                                model=model_path, lod=li, role=role, mesh=mesh)
                        continue
                    kept.append(mesh)
                    kept_radii.append(radii[index] if index < len(radii) else 0)
                config[role], config[field] = kept, kept_radii
        physical['configs'] = configs


def class_average_emissions(model, native, *, model_path=''):
    from .native_donors import NativeDonorCatalog
    profile, size = _class(model, model_path)
    if profile.carrier is None:
        return None, None
    catalog = NativeDonorCatalog.from_native(native)
    family = [d for d in catalog.donors if d._signature.family == profile.family]
    exact = [d for d in family if d._signature.engines == profile.engine_types
             and (size is None or d._signature.size == size)]
    target, populations = {}, {}
    for kind in ('noise', 'pollution'):
        values = []
        for candidates, label in ((exact, 'same_type_and_propulsion'), (family, 'same_vehicle_class')):
            values = [(d.resource, (d.metadata.get('emissions') or {}).get(kind, {}).get('score'))
                      for d in candidates]
            values = [(path, value) for path, value in values
                      if type(value) in (int, float) and math.isfinite(value) and value >= 0]
            if values:
                break
        if not values:
            raise ValueError(f'No explicit installed TF3 {kind} values in vehicle class {profile.family}; '
                             'choose automatic values for this vehicle')
        target[kind] = {'score': fmean(value for _, value in values)}
        populations[kind] = {'selection': label, 'count': len(values),
                             'vehicles': [{'resource': path, 'score': value} for path, value in values]}
    return target, {'model': model_path, 'field': 'emission',
        'sourceValue': deepcopy((model.get('metadata') or {}).get('emission')),
        'targetValue': deepcopy(target), 'emissionsPolicy': 'class_average',
        'policy': 'arithmetic_mean_of_installed_tf3_vehicle_class', 'class': profile.family,
        'populations': populations, 'estimated': True, 'nativeTest': 'not_run'}


def source_gear_radii(model, mesh_reader, *, report, model_path):
    """Use the TF2 gear's own vertex positions when its circular radius is absent."""
    result = deepcopy(model)
    physical = (result.get('metadata') or {}).get('airVehicle')
    if not isinstance(physical, dict):
        return result
    for config in physical.get('configs', []):
        if not isinstance(config, dict):
            continue
        for role, field in (('axles', 'axleRadii'), ('wheels', 'wheelRadii')):
            meshes = config.get(role, [])
            if not meshes:
                continue
            radii = config.setdefault(field, [])
            if not isinstance(meshes, list) or not isinstance(radii, list):
                continue
            for index in range(len(radii), len(meshes)):
                try:
                    descriptor, blob = mesh_reader(meshes[index])
                    attr = descriptor['vertexAttr']['position']
                    offset, count = attr['offset'], attr['count']
                    if (type(offset) is not int or type(count) is not int or offset < 0
                            or count <= 0 or count % 12 or count > 64*1024*1024
                            or offset+count > len(blob) or attr['numComp'] != 3):
                        raise ValueError('Invalid TF2 position buffer')
                    points = list(struct.iter_unpack('<fff', memoryview(blob)[offset:offset+count]))
                    if any(not math.isfinite(v) for point in points for v in point):
                        raise ValueError('Non-finite TF2 gear geometry')
                    x, z = [p[0] for p in points], [p[2] for p in points]
                    sx, sz = max(x)-min(x), max(z)-min(z)
                    if min(sx, sz) <= 0 or max(sx, sz)/min(sx, sz) > 1.2:
                        raise ValueError('The declared gear mesh is not a circular wheel around its Y axis')
                    radius = max(math.hypot(p[0], p[2]) for p in points)
                    if radius <= 0 or max(abs(max(x)+min(x)), abs(max(z)+min(z))) > .2*radius:
                        raise ValueError('Gear origin does not establish the wheel centre')
                except (ValueError, KeyError, TypeError) as exc:
                    warning(report, 'No circular source gear geometry was available; native legacy defaults remain.',
                            model=model_path, mesh=meshes[index], reason=str(exc))
                    break
                radii.append(radius)
                report.setdefault('sourceGeometryCompletions', []).append({'model': model_path,
                    'mesh': meshes[index], 'field': field, 'value': radius,
                    'method': 'radius_from_tf2_wheel_vertex_positions', 'estimated': True,
                    'nativeTest': 'not_run'})
    return result


def compatibility_model(model, resolve, native, *, model_path, report, emissions_policy='class_average'):
    """Generate a TF3 model using its installed, native TF2 metadata adapters.

    The output contains the original literal TF2 model; source Lua is never run
    by this application. Only the installed game's adapter runs inside TF3.
    """
    from .tf2_vehicle_port import literal, lua_value
    from .vehicle_profiles import derive_lod_nodes, _sound_port, _number
    data = deepcopy(literal(model))
    if data.get('version') != 1 or not isinstance(data.get('lods'), list):
        raise ValueError('Vehicle compatibility needs a literal TF2 model with LODs')
    metadata = data.get('metadata') or {}
    profile, _ = _class(data, model_path)
    if profile.carrier is None:
        raise ValueError('Compatibility adaptation is limited to physical vehicles')
    transformer = native.reference(profile.transformer)
    physical_key = next(key for key in VEHICLE_BLOCKS if key in metadata)
    for field in ('weight', 'topSpeed'):
        _number(metadata[physical_key].get(field), physical_key+'/'+field, minimum=0)
    source_sound = (metadata.get('soundConfig') or {}).get('soundSet', metadata[physical_key].get('soundSet', {}))
    sound_config = _sound_port(source_sound, resolve)
    for event, clips in ((metadata.get('soundConfig') or {}).get('effects') or {}).items():
        clips = clips if isinstance(clips, list) else [clips]
        sound_config.setdefault('effects', {})[event] = [resolve(clip, 'audio') for clip in clips if clip]
    adapter_path = 'base/model_metadata_util.lua'
    raw_adapter = native.read(adapter_path)
    calls = ('sortLods', 'toCompartmentList', 'addTransformatorConfig',
             'replaceMeshIdWithNodeName', 'squeezeConfigsToOneConfigForVehicles',
             'turnRoadAndRailToLandVehicle', 'convertWeight', 'landVehicleSoundSetToSoundConfig',
             'makeCargoEntry', 'makeCargoTypeSet', 'convertCargoTypes',
             'addVehicleExtent', 'addTransportVehicleTransportModes', 'convertParticleSystem')
    adapter_text = raw_adapter.decode('utf-8-sig')
    for call in calls:
        if not re.search(r'function\s+model_metadata_util\.'+call+r'\s*\(', adapter_text):
            raise ValueError(f'Installed TF3 compatibility adapter is missing {call}')
    # Fingerprint literal native imports transitively, including mathutil.
    # This reads installed helper bytes; it never executes source or native Lua.
    adapter_dependencies = {adapter_path}
    pending_helpers = [adapter_text]
    while pending_helpers:
        helper_text = pending_helpers.pop()
        for reference in re.findall(r'\brequire\s*(?:\(\s*)?["\'](/[^"\']+\.lua)["\']', helper_text):
            path = reference[1:]
            if '..' in path.split('/') or '\\' in path:
                raise ValueError('Unsafe installed compatibility helper import')
            if path not in adapter_dependencies:
                adapter_dependencies.add(path)
                pending_helpers.append(native.read(path).decode('utf-8-sig'))
    stem = Path(model_path).stem.lower()
    menu = (data['lods'] == [] and (metadata.get('transportVehicle') or {}).get('multipleUnitOnly') is True
            and (metadata[physical_key].get('weight') == metadata[physical_key].get('topSpeed') == 0
                 or stem.startswith('menu_') or stem.endswith('_menu')))
    if menu:
        nodes, worlds = [], []
        warning(report, 'An authored menu model has no source geometry; its grouping and original vehicle metadata use native compatibility.', model=model_path)
    else:
        nodes, worlds = derive_lod_nodes(data['lods'], metadata=metadata, report=report, model_path=model_path)
    compatible_gear_configs(metadata, nodes, model_path=model_path, report=report)
    # The native legacy helper keeps only the first cargo entry in a load
    # configuration. Port compartments statically first so all alternatives,
    # authored capacities and canonical TF3 cargo references survive.
    if isinstance(metadata.get('transportVehicle'), dict):
        from .cargo_port import port_compartments
        transport, additions, cargo_audit = port_compartments(metadata['transportVehicle'],
            native=native, nodes=nodes, resolve=resolve,
            cargo_slot_provider=metadata.get('cargoSlotProvider'),
            seat_count=len((metadata.get('seatProvider') or {}).get('seats', [])), allow_unverified_types=True, allow_legacy_layouts=True)
        for row in cargo_audit.get('legacyScalingPolicies', []):
            warning(report, 'An unrecognized cargo scaling string is retained for the native default; verify the load display in TF3.', model=model_path, **row)
        for row in cargo_audit.get('unverifiedCargoTypes', []):
            warning(report, 'A custom cargo dependency could not be confirmed; its identifier and capacity are retained without substituting another cargo.', model=model_path, **row)
        transport.update(transportModes=list(profile.transport_modes),
                         engineTransportModes=list(profile.engine_transport_modes))
        metadata['transportVehicle'] = transport
        metadata.update(additions)
        metadata.pop('cargoSlotProvider', None)
        report.setdefault('cargoMigrations', []).append({'model': model_path, **cargo_audit})
    contacts = {}
    air = metadata.get('airVehicle')
    if isinstance(air, dict) and nodes:
        config = (air.get('configs') or [{}])[0]
        for role, field in (('axles', 'axleRadii'), ('wheels', 'wheelRadii')):
            contacts[role] = []
            meshes = config.get(role, []) if isinstance(config, dict) else []
            radii = config.get(field, []) if isinstance(config, dict) else []
            for index, mesh in enumerate(meshes):
                radius = radii[index] if index < len(radii) else 0
                for ni, node in enumerate(nodes[0]):
                    if node.get('mesh') == mesh:
                        world = worlds[0][ni]
                        scale = math.sqrt(sum(world[r]**2 for r in range(3)))
                        contacts[role].append({'position': [world[12], world[14]], 'radius': radius*scale})
                if radius == 0:
                    warning(report, 'Source aircraft has no wheel radius; its legacy zero-radius default remains.',
                            model=model_path, mesh=mesh)
    # TF2 references retain their resource type; resolving them before native
    # adaptation also makes mesh bindings refer to the same exported geometry.
    suffixes = {'.msh': 'mesh', '.mtl': 'material', '.mdl': 'model', '.ani': 'animation',
                '.dds': 'texture', '.tga': 'texture', '.hdr': 'texture',
                '.wav': 'audio', '.ogg': 'audio'}
    def references(value, key=''):
        if isinstance(value, dict):
            return {k: references(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [references(v, key) for v in value]
        if isinstance(value, str) and '::' not in value:
            kind = suffixes.get(Path(value).suffix.lower())
            if kind and key not in ('name', 'description', 'desc'):
                return resolve(value, kind)
            if key == 'groupFileName' and value:
                return resolve(value, 'model')
        return value
    data = references(data)
    if emissions_policy == 'class_average':
        averages, row = class_average_emissions(model, native, model_path=model_path)
    else:
        from .vehicle_profiles import _emissions_port
        averages, row = _emissions_port(metadata.get('emission', {}), emissions_policy, model_path)
    data['metadata'].pop('emission', None)
    data['metadata']['emissions'] = averages
    if row is not None:
        report.setdefault('vehicleAdaptations', []).append(row)
    report.setdefault('vehicleProfiles', []).append({'model': model_path, 'profile': profile.key,
        'family': profile.family, 'policy': 'preserve_tf2_with_installed_tf3_adapter', 'nativeTest': 'not_run'})
    report.setdefault('legacyVehicleData', []).append({'model': model_path,
        'sourceMetadata': deepcopy(model.get('metadata')), 'adapter': adapter_path,
        'adapterDependencies': sorted(adapter_dependencies),
        'adapterCalls': list(calls), 'originalPhysicsPreserved': True, 'nativeTest': 'not_run'})
    body = ['local vehicle_util = require "/base/model_metadata_util.lua"', 'function data()',
            'local result = '+lua_value(data), 'local path = '+lua_value('::/'+model_path)]
    for call in calls:
        body.append(f'result = vehicle_util.{call}(path, result)')
    body.append('result.metadata.transformatorConfig.transformator.name = '+lua_value(transformer))
    if sound_config:
        body.append('result.metadata.soundConfig = '+lua_value(sound_config))
    for role, values in contacts.items():
        body.append('result.metadata.airVehicle.'+role+' = '+lua_value(values))
    body.append('if result.metadata.landVehicle and result.metadata.landVehicle.weightMaxPayload == nil then '
                'result.metadata.landVehicle.weightMaxPayload = 0 end')
    body.extend(['result.version = 2', 'return result', 'end', ''])
    warning(report, 'Original TF2 vehicle data uses the installed TF3 compatibility adapter; '
            'test its appearance, animations and physics in TF3.', model=model_path)
    return '\n'.join(body)

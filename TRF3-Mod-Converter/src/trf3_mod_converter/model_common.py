"""Literal common model fields and named-node references for TF3.

These adapters preserve source values. They never evaluate a source callback.
Particle visuals use explicit TF3 curves; source emitters carry no semantic ID,
so engine-dependent particle timing is recorded for native verification.
"""
from copy import deepcopy
import math


def _table(value, where):
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'{where}: expected a named table')
    return value


def _known(value, allowed, where):
    unknown = set(value) - set(allowed)
    if unknown:
        raise ValueError(f'Unsupported {where} fields: {sorted(unknown)}; source preserved')


def _number(value, where):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{where}: expected a finite number')
    return value


def _vector(value, size, where):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f'{where}: expected {size} numbers')
    for item in value:
        _number(item, where)
    return value


def node_name(nodes, reference, where):
    if type(reference) is int and 0 <= reference < len(nodes):
        return nodes[reference]['name']
    if isinstance(reference, str) and sum(n['name'] == reference for n in nodes) == 1:
        return reference
    raise ValueError(f'{where}: invalid or ambiguous node reference {reference!r}')


def resolve_nodes(lod_nodes, resolve):
    for nodes in lod_nodes:
        for node in nodes:
            for field in ('mesh', 'skin'):
                if field in node:
                    node[field] = resolve(node[field], 'mesh')
            for field in ('materials', 'skinMaterials'):
                if field in node:
                    node[field] = [resolve(ref, 'material') for ref in node[field]]
            animations = _table(node.get('animations', {}), 'animations')
            if 'animations' in node:
                node['animations'] = animations
            for event, animation in animations.items():
                _known(animation, {'type', 'params', 'forward'}, 'animation')
                if 'forward' in animation and type(animation['forward']) is not bool:
                    raise ValueError('Animation forward must be a boolean')
                params = _table(animation.get('params'), 'animation params')
                kind = animation.get('type')
                if kind == 'FILE_REF':
                    _known(params, {'id'}, 'animation params')
                    ref = params.get('id')
                    if not isinstance(ref, str):
                        raise ValueError('Animation requires a file reference')
                    if '::/' not in ref:
                        params['id'] = resolve(ref, 'animation')
                elif kind in ('KEYFRAME', 'KEYFRAME_MATRIX'):
                    _known(params, {'origin', 'keyframes'} if kind == 'KEYFRAME' else {'keyframes'}, 'animation params')
                    if 'origin' in params:
                        _vector(params['origin'], 3, 'animation origin')
                    frames = params.get('keyframes')
                    if not isinstance(frames, list) or not frames:
                        raise ValueError('Animation needs non-empty keyframes')
                    previous = -1
                    for frame in frames:
                        _known(frame, {'time', 'rot', 'transl'} if kind == 'KEYFRAME' else {'time', 'transf'}, 'keyframe')
                        time = _number(frame.get('time'), 'keyframe time')
                        if time < 0 or time < previous:
                            raise ValueError('Animation times must be nonnegative and ordered')
                        previous = time
                        if kind == 'KEYFRAME':
                            for field in ('rot', 'transl'):
                                _vector(frame.get(field), 3, 'keyframe ' + field)
                        else:
                            _vector(frame.get('transf'), 16, 'keyframe transform')
                else:
                    raise ValueError(f'Unsupported animation {event}: {kind!r}')


def port_common_metadata(metadata, nodes, resolve, *, report=None, model_path='', vehicle=False):
    result = deepcopy(metadata)
    log = report if report is not None else {}
    # No public/native equivalence has been established for these legacy blocks.
    for field in ('colorConfig', 'lightConfig', 'skinList', 'versioning'):
        if field in result:
            if result[field] not in ({}, []):
                raise ValueError(f'{field}: requires a verified TF3 adapter; source preserved')
            del result[field]
    camera = _table(result.get('cameraConfig', {}), 'cameraConfig')
    _known(camera, {'positions'}, 'cameraConfig')
    for position in camera.get('positions', []):
        _known(position, {'group', 'transf', 'fov'}, 'camera position')
        position['group'] = node_name(nodes, position.get('group'), 'camera')
        if 'transf' in position:
            _vector(position['transf'], 16, 'camera transform')
        if 'fov' in position:
            if not 0 < _number(position['fov'], 'camera fov') < 180:
                raise ValueError('Camera fov must be between 0 and 180')
    if 'cameraConfig' in result:
        result['cameraConfig'] = camera
    labels = _table(result.get('labelList', {}), 'labelList')
    _known(labels, {'labels'}, 'labelList')
    for label in labels.get('labels', []):
        _known(label, {'childId','type','transf','size','color','alpha','alphaMode','fitting',
                      'alignment','verticalAlignment','nLines','filter','params','renderMode','font'}, 'label')
        label['childId'] = node_name(nodes, label.get('childId', 0), 'label')
        if 'font' in label and label['font'] not in ('Lato', 'Noto'):
            raise ValueError('Label font requires an installed TF3 font mapping')
    if 'labelList' in result:
        result['labelList'] = labels
    particle_system = _table(result.get('particleSystem', {}), 'particleSystem')
    _known(particle_system, {'emitters'}, 'particleSystem')
    converted = []
    for emitter in particle_system.get('emitters', []):
        _known(emitter, {'child','position','color','frequency','lifeTime','size01','velocity',
                         'initialAlpha','velocityDampingFactor','albedoTexture','normalMapTexture'}, 'TF2 particle emitter')
        e = deepcopy(emitter)
        e['child'] = node_name(nodes, e.get('child'), 'particle emitter')
        for field in ('position', 'velocity', 'color'):
            if field in e:
                _vector(e[field], 3, 'particle ' + field)
        for field in ('frequency', 'lifeTime'):
            value = _number(e.get(field), 'particle ' + field)
            if value < 0:
                raise ValueError('Particle frequency and lifetime must be nonnegative')
            e[field] = {'value': value}
        if 'velocity' in e:
            e['velocity'] = {'value': e['velocity']}
        color = e.pop('color', [0, 0, 0])
        e['colorOverLifeTime'] = {'curve': [{'time': 1, 'value': color}]}
        alpha = _number(e.pop('initialAlpha', 1), 'particle alpha')
        e['alphaOverLifeTime'] = {'curve': [{'time': 0, 'value': alpha}, {'time': 1, 'value': 0}]}
        sizes = _vector(e.pop('size01'), 2, 'particle size01')
        e['sizeOverLifeTime'] = {'curve': [{'time': 0, 'value': {'value': sizes[0]}},
                                         {'time': 1, 'value': {'value': sizes[1]}, 'easing': 'Linear'}]}
        for field in ('albedoTexture', 'normalMapTexture'):
            if field in e:
                e[field] = resolve(e[field], 'texture')
        if 'velocityDampingFactor' in e:
            _number(e['velocityDampingFactor'], 'particle damping')
        converted.append(e)
    if 'particleSystem' in result:
        result['particleSystem'] = {'emitters': converted}
        if converted:
            log.setdefault('particleMigrations', []).append({'model': model_path, 'emitters': len(converted),
                'policy': 'preserve_source_endpoints_linear_size_and_fade',
                'engineDependentTiming': 'requires_native_verification' if vehicle else 'not_applicable'})
    return result

"""Evidence-based TF2 resource and vehicle export. Never executes source Lua.

Uses the installed TF3 property definitions and resource inventory as the
compatibility target. Unknown metadata and non-empty callbacks are blockers.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from luaparser import ast, astnodes as lua

from .converter import _check_paths, _copy_files, _linked, convert_mod, prepare_mod
from .lua_metadata import UnsupportedValue, TranslatedString, load_lua_table
from .tf2_sound_port import port_sound_set
from .resource_audit import LUA_RESOURCE_ENDINGS
from .resource_profiles import resource_target, classify_resource, load_resource_table, port_resource, capability_report
from .base_resources import BASE_TEXTURES, ROOTS, BaseResourceResolver, TF2Inventory, find_tf2_game, source_resource


def literal(value: Any, where: str = "data") -> Any:
    if isinstance(value, UnsupportedValue):
        raise ValueError(f"{where}: {value.reason}")
    if isinstance(value, dict):
        for k, v in value.items(): literal(v, f"{where}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value): literal(v, f"{where}/{i}")
    return value


def lua_value(value: Any, translations: set[str] | None = None, _path=()) -> str:
    """Emit literals only, with Lua decimal escapes for control characters."""
    if value is None: return "nil"
    if value is True: return "true"
    if value is False: return "false"
    if isinstance(value, str):
        quoted = '"' + ''.join(('\\' + str(ord(c)).zfill(3)) if ord(c) < 32 else
                               ('\\' + c if c in '\\"' else c) for c in value) + '"'
        display_field = (_path in (('name',), ('desc',), ('description',))
                         or _path[-2:] in (('description','name'), ('description','description'), ('description','desc')))
        return f"_({quoted})" if isinstance(value, TranslatedString) or (display_field and translations and value in translations) else quoted
    if isinstance(value, (int, float)):
        if not math.isfinite(value): raise ValueError("Non-finite Lua number")
        return repr(value)
    if isinstance(value, list):
        return "{ " + ", ".join(lua_value(v, translations, _path+(i,)) for i,v in enumerate(value)) + " }"
    if isinstance(value, dict):
        rows = []
        for k, v in value.items():
            key = k if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) else f"[{lua_value(k)}]"
            rows.append(f"{key} = {lua_value(v, translations, _path+(k,))}")
        return "{\n" + ",\n".join(rows) + "\n}"
    raise ValueError(f"Unsupported literal type: {type(value).__name__}")


def emit(data: dict, translations: set[str] | None = None) -> str:
    return "function data()\nreturn " + lua_value(data, translations) + "\nend\n"


def checked_name(path: str) -> str:
    if not path or any(part in ('', '.', '..') for part in path.split('/')):
        raise ValueError(f"Unsafe resource path: {path}")
    parts = PurePosixPath(path).parts
    if any(p in ("..", ".") for p in parts) or path.startswith("/") or "\\" in path:
        raise ValueError(f"Unsafe resource path: {path}")
    normalized = [re.sub(r"[^a-z0-9_.@-]+", "_", p.lower()).strip('_') for p in parts]
    if any(not p or p in ('.', '..') for p in normalized):
        raise ValueError(f"Empty normalized resource name: {path}")
    return '/'.join(normalized)


class NativeInventory:
    def __init__(self, game: Path):
        self.content = game / 'base/content'
        if not self.content.is_dir(): raise ValueError("Choose the TF3 installation folder (with base/content)")
        self.files: dict[str, tuple[Path, str | None]] = {}
        self.references: set[str] = set()
        self.dependencies: dict[str,str] = {}
        self._cache_owner = self
        for f in self.content.rglob('*'):
            if not f.is_file(): continue
            if f.suffix == '.zip':
                with zipfile.ZipFile(f) as z:
                    for n in z.namelist():
                        if not n.endswith('/'):
                            self.files.setdefault((f.parent.relative_to(self.content) / n).as_posix(), (f, n))
            else: self.files[f.relative_to(self.content).as_posix()] = (f, None)

    def fork(self):
        result = object.__new__(type(self))
        result.content, result.files, result.references = self.content, self.files, set()
        result.dependencies = {}
        result._cache_owner = self._cache_owner
        if hasattr(self, '_cargo_catalog'):
            result._cargo_catalog = self._cargo_catalog
        return result

    def read(self, path: str) -> bytes:
        if path not in self.files: raise ValueError(f"Installed TF3 resource missing: {path}")
        f, n = self.files[path]
        if n is None: data=f.read_bytes()
        else:
            with zipfile.ZipFile(f) as z: data=z.read(n)
        self.dependencies[path]=hashlib.sha256(data).hexdigest()
        return data

    def fingerprints(self, paths):
        return {path:hashlib.sha256(self.read(path)).hexdigest() for path in sorted(set(paths))}

    def track_dependencies(self, values):
        self.dependencies.update(values)

    def inventory_fingerprint(self):
        """Cover mount additions/removals and changed zip catalog entries.

        Referenced and donor/cargo input bytes are separately SHA-256 checked.
        This avoids hashing gigabytes of unrelated native textures per mod.
        """
        rows=[];archives={}
        for path,(file,member) in sorted(self.files.items()):
            if member is None:
                stat=file.stat();value=[stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
            else:
                if file not in archives:
                    with zipfile.ZipFile(file) as archive:
                        archives[file]={i.filename:[i.CRC,i.file_size] for i in archive.infolist()}
                value=archives[file][member]
            rows.append([path,value])
        return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()

    def reference(self, path: str) -> str:
        prefix = path.split('@', 1)[0]
        resource = prefix if prefix.endswith(LUA_RESOURCE_ENDINGS) else path
        candidates = [resource+'.lua',resource+'.tl'] if resource.endswith(tuple(LUA_RESOURCE_ENDINGS)) else [resource]
        found = next((p for p in candidates if p in self.files), None)
        if found is None: raise ValueError(f"Installed TF3 resource missing: {resource}")
        self.read(found)
        self.references.add(path)
        return '::/' + path

    def material(self, data: dict, resolve, *, report=None, resource='') -> dict:
        result = deepcopy(data)
        definition = literal(load_lua_table(self.read(f"rendering/{data['type'].lower()}.mat.lua").decode('utf-8-sig'))) or {}
        definitions = {p['name']:p['id'] for p in definition.get('properties', [])}
        result['params'] = {}
        parameters = data.get('params') or {}
        if not isinstance(parameters,dict):
            raise ValueError('Material params must be a named literal table')
        for key, values in parameters.items():
            if key not in definitions:
                raise ValueError(f"Material type {data['type']} does not declare property {key}")
            prop = definitions[key]
            schema = literal(load_lua_table(self.read(f'rendering/{prop}.lua').decode('utf-8')))
            values = deepcopy(values) if values != [] else {}
            if not isinstance(values,dict):
                raise ValueError(f'Material property {key} must be a named literal table')
            if key == 'color_blend':
                props = {p['name']:p for p in schema.get('fragmentProperties', [])}
                count = props.get('albedoScales', {}).get('arrayCount')
                if count not in (2,4):
                    raise ValueError('Installed color-blend schema requires an explicit adapter')
                scalar = values.pop('albedoScale', None)
                if scalar is not None:
                    if 'albedoScales' in values or count != 2 or type(scalar) not in (int,float) or not math.isfinite(scalar):
                        raise ValueError('Conflicting/invalid legacy color-blend scales')
                    values['albedoScales'] = [scalar]
                if 'color' in values:
                    if values.get('colors'):
                        raise ValueError('Conflicting color-blend colors')
                    values['colors'] = [values.pop('color')]
                if 'albedoScales' in values:
                    scales = values['albedoScales']
                    if not isinstance(scales,list) or len(scales) > count or any(type(v) not in (int,float) or not math.isfinite(v) for v in scales):
                        raise ValueError('Invalid color-blend scale array')
                    values['albedoScales'] = scales+[props['albedoScales'].get('defaultValue',0)]*(count-len(scales))
                if 'colors' in values:
                    colors = values['colors']
                    if not isinstance(colors,list) or len(colors)>count or any(not isinstance(c,list) or len(c)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in c) for c in colors):
                        raise ValueError('Invalid color-blend RGB colors')
                    default = props.get('colors', {}).get('defaultValue')
                    if default != [-1,-1,-1]:
                        raise ValueError('Installed color-blend unset-color definition differs')
                    values['colors'] = colors+[deepcopy(default) for _ in range(count-len(colors))]
                if report is not None:
                    report.setdefault('materialMigrations', []).append({'resource':resource, 'property':key,
                        'nativeSchema':f'rendering/{prop}.lua', 'legacyScalar':scalar is not None,
                        'policy':'preserve_source_channels_pad_installed_defaults', 'nativeTest':'not_run'})
            samplers = schema.get('fragmentSamplers', [])
            if samplers:
                if len(samplers) != 1: raise ValueError(f"Cannot port multi-sampler property {key}")
                values = deepcopy(values)
                values['fileName'] = resolve(values['fileName'], 'texture')
                result['params'][key] = {'fragmentSamplers': {samplers[0]['name']: values}}
            else:
                groups = [(g, schema.get(g, [])) for g in ('vertexProperties', 'fragmentProperties')]
                out = {}
                recognized = set()
                for group, props in groups:
                    fields = {p['name']: values[p['name']] for p in props if p['name'] in values}
                    recognized.update(fields)
                    if fields: out[group] = [fields]
                if set(values) - recognized: raise ValueError(f"Unknown {key} properties: {set(values)-recognized}")
                result['params'][key] = out
        if 'light_receiver' in definitions:
            result['params']['light_receiver'] = {'fragmentProperties': [{'isLegacyMaterial': True, 'lightMask': 2}]}
        return result


def flatten(node: dict):
    yield node
    for child in node.get('children', []): yield from flatten(child)


def reject_unknown(data: dict, allowed: set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown: raise ValueError(f"Unsupported {where} fields (preserved in source): {sorted(unknown)}")


def port_model(data: dict, resolve, native: NativeInventory, *, model_path='',
               report=None, animation_writer=None, expand_cargo_classes=True, progress=None) -> dict:
    """Port verified vehicle families and render assets; source remains intact."""
    from .cargo_port import CargoCatalog, port_compartments
    from .vehicle_profiles import classify_model, derive_lod_nodes, adapt_vehicle_metadata
    from .resource_profiles import port_static_model
    from .model_common import port_common_metadata, resolve_nodes
    from .missing_data import complete_missing_model, complete_payload

    result = deepcopy(literal(data))
    if result.get('version') != 1:
        raise ValueError('Only TF2 model version 1 is supported')
    reject_unknown(result, {'version','boundingInfo','collider','lods','metadata'}, 'model')
    log = report if report is not None else {}
    result, donor_match = complete_missing_model(result, native, model_path=model_path, report=log, progress=progress)
    metadata = result.setdefault('metadata', {})
    if metadata == []:
        metadata = result['metadata'] = {}
    profile = classify_model(metadata, model_path)
    if profile.family == 'asset':
        derive_lod_nodes(result['lods'], metadata=metadata)
        extras = {key: metadata.pop(key) for key in
                  ('particleSystem','colorConfig','lightConfig','skinList','versioning') if key in metadata}
        result = port_static_model(result, resolve, native)
        nodes, _ = derive_lod_nodes(result['lods'])
        result['metadata'].update(extras)
        result['metadata'] = port_common_metadata(result['metadata'], nodes[0], resolve,
                                                  report=log, model_path=model_path)
        log.setdefault('vehicleProfiles', []).append({'model':model_path, 'profile':'tf2_asset',
                                                       'family':'asset', 'nativeTest':'not_run'})
        return result
    nodes, transforms = derive_lod_nodes(result['lods'], metadata=metadata)
    for lod_nodes in nodes:
        for node in lod_nodes:
            for animation in (node.get('animations') or {}).values():
                if animation.get('type') == 'FILE_REF':
                    source_resource('animation', animation.get('params', {}).get('id'))
    converted_transport, additions, cargo_audit = None, {}, None
    if 'transportVehicle' in metadata:
        owner = getattr(native, '_cache_owner', native)
        catalog = getattr(owner, '_cargo_catalog', None)
        if catalog is None and hasattr(native, 'files') and any(p.endswith('.cargo.lua') for p in native.files):
            catalog = owner._cargo_catalog = CargoCatalog.from_native(native)
        if catalog is not None:
            catalog = CargoCatalog(catalog.types, classes=catalog.classes, formats=catalog.formats,
                                   aliases=catalog.aliases, native=native)
        seat_provider = metadata.get('seatProvider') or {}
        if not isinstance(seat_provider, dict):
            raise ValueError('seatProvider must be a named literal table')
        converted_transport, additions, cargo_audit = port_compartments(
            metadata['transportVehicle'], catalog=catalog, native=native, nodes=nodes[0], resolve=resolve,
            expand_classes=expand_cargo_classes, cargo_slot_provider=metadata.get('cargoSlotProvider'),
            seat_count=len(seat_provider.get('seats', [])))
    payload, payload_policy = complete_payload(data, native, (cargo_audit or {}).get('maxCapacity', 0),
        match=donor_match, model_path=model_path, report=log)
    metadata, profile = adapt_vehicle_metadata(metadata, nodes, resolve, native, model_path=model_path,
        weight_max_payload=payload, node_world_transforms=transforms, animation_writer=animation_writer, report=log)
    if converted_transport is not None:
        original_fields = ('compartmentsList','compartments','capacities')
        transport = metadata['transportVehicle']
        for field in original_fields:
            transport.pop(field, None)
        transport['compartments'] = converted_transport['compartments']
        metadata.pop('cargoSlotProvider', None)
        metadata.update(additions)
        log.setdefault('cargoMigrations', []).append({'model':model_path, **cargo_audit,
            'payloadPolicy':payload_policy, 'weightMaxPayload':payload})
    metadata = port_common_metadata(metadata, nodes[0], resolve, report=log,
                                    model_path=model_path, vehicle=profile.carrier is not None)
    resolve_nodes(nodes, resolve)
    metadata['extent'] = deepcopy(result.get('boundingInfo', {}))
    result['metadata'], result['version'] = metadata, 2
    return result


def snapshot(root: Path) -> dict[str, str]:
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_file():
            digest = hashlib.sha256()
            with p.open('rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''): digest.update(chunk)
            result[p.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def port_tf2_mod(source: str | Path, destination: str | Path, *, tf3_game: str | Path,
                 mod_id: str, name: str, repairs: dict[str, str] | None = None,
                 overwrite: bool = False, progress=None, author: str | None = None,
                 revision: int | None = None, summary: str | None = None,
                 tf2_game: str | Path | None = None, _native_inventory=None, _tf2_inventory=None) -> dict:
    """Export a separate native-format draft; repairs must be explicitly supplied.

    The report never asserts native game compatibility. Installed game resources
    are referenced, never redistributed. All changed source text is archived.
    """
    if not re.fullmatch(r'[a-z0-9_]+',mod_id): raise ValueError('Invalid TF3 mod ID')
    if not name or len(name) > 32 or '\n' in name or '\r' in name: raise ValueError('Name must contain 1–32 characters and no line breaks')
    source = Path(source).expanduser().absolute(); destination = Path(destination).expanduser().absolute()
    root = _check_paths(source, destination, overwrite)
    destination = destination.resolve()
    _check_paths(source, destination, overwrite)
    if destination.is_relative_to(root):
        raise ValueError('TF2 port output must be outside the source mod')
    if not (root/'res').is_dir() or (root/'content').exists(): raise ValueError("Expected a TF2 mod with only a res resource folder")
    # Check the full tree before following any resource files.
    for p in root.rglob('*'):
        if _linked(p): raise ValueError(f"Linked source is not supported: {p}")
    native = _native_inventory.fork() if _native_inventory is not None else NativeInventory(Path(tf3_game))
    if native.content.resolve() != (Path(tf3_game)/'base/content').resolve():
        raise ValueError('Shared TF3 inventory does not match the selected installation')
    tf2_path = Path(tf2_game) if tf2_game is not None else find_tf2_game(root, Path(tf3_game))
    tf2 = _tf2_inventory if _tf2_inventory is not None else (TF2Inventory(tf2_path) if tf2_path is not None else None)
    if tf2 is not None and tf2.content.resolve() != (tf2_path/'res').resolve():
        raise ValueError('Shared TF2 inventory does not match the selected installation')
    base = BaseResourceResolver(native, tf2, family='train')
    before = snapshot(root)
    repairs = repairs or {}
    if not isinstance(repairs,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in repairs.items()):
        raise ValueError('Repairs must map texture reference strings to source texture paths')
    mapping = {p.relative_to(root/'res').as_posix():resource_target(p.relative_to(root/'res').as_posix())
               for p in (root/'res').rglob('*') if p.is_file()}
    opaque = [old for old in mapping if PurePosixPath(old).suffix.lower() in
              ('.zip','.7z','.rar','.pak','.dll','.exe','.bat','.cmd','.ps1','.sh')]
    if opaque:
        raise ValueError('Opaque resource archive/native executable requires unpacking or manual migration: '+', '.join(sorted(opaque)[:8]))
    for helper in ('bridgeutil', 'texutil', 'vec3', 'transf'):
        if any(old.lower() in (f'scripts/{helper}.lua', f'scripts/{helper}.tl') for old in mapping):
            raise ValueError(f'Local {helper} shadows the built-in helper; manual script migration required')
    sound_files = {old for old in mapping if old.startswith('config/sound_set/') and old.endswith('.lua')}
    if len(set(mapping.values())) != len(mapping): raise ValueError("Normalized resource filenames collide")
    used_repairs = set()
    omitted_borrowed = set()
    borrowed_sound_sets = {}
    # Classify verified descriptors before adapting any of them; a later
    # reference must not reintroduce an omitted TF2 base model/material.
    borrowed_resources = {}
    for old in sorted(mapping):
        kind = 'model' if old.startswith(ROOTS['model']+'/') and old.endswith('.mdl') else (
               'material' if old.startswith(ROOTS['material']+'/') and old.endswith('.mtl') else None)
        if kind:
            reference = old[len(ROOTS[kind])+1:]
            if base.is_borrowed(kind, reference, root/'res'/old):
                borrowed_resources[old] = base.resolve(kind, reference, bundled=True)
                omitted_borrowed.add(old)
    model_data, sound_families, mesh_referrers = {}, {}, {}
    from .missing_data import classify_missing_model
    for old in sorted(mapping):
        if not old.endswith('.mdl') or old in omitted_borrowed:
            continue
        data = literal(load_resource_table((root/'res'/old).read_text(encoding='utf-8-sig')), old)
        model_data[old] = data
        for lod_index, lod in enumerate(data.get('lods', [])):
            for node_index, node in enumerate(flatten(lod['node'])):
                if node.get('mesh'):
                    mesh_referrers.setdefault(source_resource('mesh', node['mesh']), []).append({
                        'modelPath':old, 'nodePath':f'lods[{lod_index}]/node[{node_index}]',
                        'materials':deepcopy(node.get('materials'))})
        metadata = data.get('metadata', {}) or {}
        profile = classify_missing_model(data, old)
        for block in ('railVehicle','roadVehicle','soundConfig'):
            sound = (metadata.get(block) or {}).get('soundSet') or {}
            if sound.get('name'):
                sound_families.setdefault(source_resource('sound_set', sound['name']), set()).add(profile.family)
    def sound_family(old):
        families = sound_families.get(old, set())
        return next(iter(families)) if len(families) == 1 else None
    for old in sorted(sound_files):
        base.family = sound_family(old)
        ref = old[len(ROOTS['sound_set'])+1:-4]
        if base.is_borrowed('sound_set', ref, root/'res'/old):
            borrowed_sound_sets[old] = base.resolve('sound_set', ref, bundled=True)
            omitted_borrowed.add(old)
    def resolve(ref: str, kind: str) -> str:
        if isinstance(ref, TranslatedString):
            raise ValueError(f'Localized resource reference requires manual migration: {ref}')
        source_resource(kind, ref)  # Reject unsafe input before looking up local or base assets.
        if kind == 'texture' and ref in repairs:
            used_repairs.add(ref)
            ref = repairs[ref]
        old = source_resource(kind, ref)
        if old in borrowed_resources:
            return borrowed_resources[old]
        if old in borrowed_sound_sets:
            return borrowed_sound_sets[old]
        if old in mapping:
            if kind != 'sound_set' and base.is_borrowed(kind, ref, root/'res'/old):
                replacement = base.resolve(kind, ref, bundled=True)
                omitted_borrowed.add(old)
                return replacement
            value = mapping[old]
            return mod_id+'::/'+(value[:-4] if value.endswith('.lua') else value)
        return base.resolve(kind, ref)
    translations = literal(load_lua_table((root/'strings.lua').read_text(encoding='utf-8-sig'))) if (root/'strings.lua').exists() else {}
    if any(not isinstance(locale, dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in locale.items()) for locale in translations.values()):
        raise ValueError("Expected literal language/key/text translation tables")
    keys = set().union(*(v.keys() for v in translations.values())) if translations else set()
    raw = load_lua_table((root/'mod.lua').read_text(encoding='utf-8-sig'))
    tree = ast.parse((root/'mod.lua').read_text(encoding='utf-8-sig'))
    reject_unknown(raw, {'info','options','runFn','preRunFn','postRunFn'}, 'mod.lua')
    for callback in ('runFn','preRunFn','postRunFn'):
        if callback in raw:
            fields = [n for n in ast.walk(tree) if isinstance(n,lua.Field) and isinstance(n.key,lua.Name) and n.key.id == callback]
            if len(fields) != 1 or not isinstance(fields[0].value,lua.AnonymousFunction) or fields[0].value.body.body:
                raise ValueError(f"Non-empty {callback} needs a manual script port")
            del raw[callback]
    if raw.get('options'): raise ValueError("TF2 options need a manual port")
    literal(raw)
    info = raw['info']
    migration_audit = {}
    if isinstance(info.get('url'), list) and len(info['url']) <= 1 and all(isinstance(v,str) for v in info['url']):
        source_url = deepcopy(info['url'])
        info['url'] = source_url[0] if source_url else ''
        migration_audit.setdefault('metadataMigrations', []).append({
            'field':'info.url', 'sourceValue':source_url, 'targetValue':info['url'],
            'policy':'unwrap_empty_or_single_literal_url', 'nativeTest':'not_run'})
    english = translations.get('en', {})
    info['name'] = name
    info['description'] = english.get(info.get('description'), info.get('description',''))
    info['modId'] = mod_id
    transformed = {}
    originals = {}
    counts = {'models':0,'materials':0,'meshes':0,'animations':0}
    def bounds(ref):
        old = source_resource('model', ref)
        if old in model_data:
            return model_data[old].get('boundingInfo')
        if tf2 is not None and old in tf2.files:
            return literal(load_resource_table(tf2.read(old).decode('utf-8-sig'))).get('boundingInfo')
        raise ValueError(f'Bridge model bounds cannot be verified: {ref}')
    def save_document(relative, text, *, source_old=None):
        checked_name(relative)
        if relative in transformed or (relative in mapping.values() and relative != mapping.get(source_old)):
            raise ValueError(f'Generated resource filename collision: {relative}')
        transformed[relative] = text
    for old in sorted(mapping):
        if old in omitted_borrowed:
            continue
        p = root/'res'/old
        suffix = p.suffix.lower()
        if old in sound_files:
            base.family = sound_family(old)
            transformed[mapping[old]] = emit(port_sound_set(p.read_text(encoding='utf-8-sig'), resolve, native))
            originals[old] = p.read_bytes()
            counts['soundSets'] = counts.get('soundSets',0)+1
            continue
        if suffix in ('.lua', '.tl', '.script', '.gs', '.con', '.module', '.trf', '.snd'):
            base.family = None
            target = mapping[old]
            reference = mod_id+'::/'+(target[:-4] if target.endswith('.lua') else target)
            for relative, text in port_resource(old, p.read_text(encoding='utf-8-sig'), resolve, native,
                                               resource_reference=reference, model_bounds=bounds, translations=keys).items():
                save_document(relative, text, source_old=old)
            originals[old] = p.read_bytes()
            kind = classify_resource(old)
            counts[kind] = counts.get(kind, 0)+1
            continue
        if suffix not in ('.mdl','.mtl','.msh','.ani'): continue
        d = literal(load_resource_table(p.read_text(encoding='utf-8-sig')), old)
        if suffix == '.mdl':
            base.family = classify_missing_model(d, old).family
            def write_animation(event, value):
                digest = hashlib.sha256(emit(value).encode('utf-8')).hexdigest()[:20]
                path = f'models/animation/_tf3_port/{checked_name(event)}_{digest}.ani'
                text = emit(value)
                if path not in transformed:
                    save_document(path, text)
                    counts['generatedAnimations'] = counts.get('generatedAnimations', 0)+1
                elif transformed[path] != text:
                    raise ValueError('Generated animation hash collision')
                return mod_id+'::/'+path
            d = port_model(model_data[old], resolve, native, model_path=old, report=migration_audit,
                           animation_writer=write_animation, progress=progress); counts['models'] += 1
            model_path = old[len('models/model/'):-4]
            # TF3 defaults use icons beside each model. Retain the original
            # supplied TF2 thumbnails through explicit metadata references.
            for field, folder, suffix in (
                ('iconSmall','models_small','@2x.tga'),('iconSmallCblend','models_small','_cblend@2x.tga'),
                ('icon20','models_20','@2x.tga'),('icon20cblend','models_20','_cblend@2x.tga'),
                ('icon3d','models_small','@2x.tga')):
                icon = f'textures/ui/{folder}/{model_path}{suffix}'
                if icon in mapping: d['metadata'].setdefault('description', {})[field] = mod_id+'::/'+mapping[icon]
        elif suffix == '.mtl':
            d = native.material(d, resolve, report=migration_audit, resource=old); counts['materials'] += 1
        elif suffix == '.msh':
            if not p.with_name(p.name+'.blob').is_file(): raise ValueError(f"Missing mesh blob: {old}")
            counts['meshes'] += 1
            from .mesh_port import port_mesh_descriptor
            migrated = port_mesh_descriptor(d, resolve, mesh_referrers.get(old, []),
                                            report=migration_audit, mesh_path=old)
            if migrated == d:
                continue  # Shared index schema: keep unchanged descriptors byte for byte.
            d = migrated  # Rewrite proven material links only; geometry/blob stay intact.
        else:
            counts['animations'] += 1; continue
        originals[old] = p.read_bytes()
        transformed[mapping[old]] = emit(d, keys)
    if not mapping: raise ValueError("No TF2 content resources found")
    for old,new in repairs.items():
        if ROOTS['texture']+'/'+new not in mapping: raise ValueError(f"Repair target does not exist in source: {new}")
    if set(repairs) - used_repairs: raise ValueError(f'Unused texture repairs: {sorted(set(repairs) - used_repairs)}')
    notify = progress or (lambda _:None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tf2_port_',dir=destination.parent) as tmp:
        stage = Path(tmp)/'draft'; stage.mkdir()
        _copy_files(root,stage,{destination,Path(tmp)},notify)
        # Build fresh directories: case-only file renames on Windows leave
        # uppercase parent folders intact, which TF3 would still reject.
        normalized = stage/'_normalized_content'; normalized.mkdir()
        for old, new in mapping.items():
            if old in omitted_borrowed:
                continue
            target = normalized/new; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(stage/'content'/old,target)
        content = (stage/'content').resolve()
        if content.parent != stage.resolve() or content.name != 'content':
            raise ValueError('Unsafe staged content path')
        shutil.rmtree(content)
        normalized.rename(stage/'content')
        for relative,text in transformed.items():
            target = stage/'content'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text,encoding='utf-8')
        for old,data in originals.items():
            target = stage/'_port_originals/res'/old;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        for old in ('mod.lua','strings.lua'):
            if (stage/old).exists():
                target = stage/'_port_originals'/old;target.parent.mkdir(parents=True,exist_ok=True);(stage/old).rename(target)
        (stage/'mod.lua').write_text(emit({'info':info}),encoding='utf-8')
        (stage/'strings.json').write_text(json.dumps(translations,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (stage/'source-sha256.json').write_text(json.dumps(before,indent=2)+'\n',encoding='utf-8')
        descriptor = prepare_mod(stage)
        if descriptor.blockers: raise ValueError('Port validation failed:\n'+'\n'.join(descriptor.blockers[:25]))
        if snapshot(root) != before: raise ValueError("Source changed during porting; export cancelled")
        profiles = {row['profile'] for row in migration_audit.get('vehicleProfiles', [])}
        port_profile = 'tf2_electric_locomotive' if profiles == {'tf2_train_electric'} else 'tf2_verified_resource_profiles'
        port_report = dict(source=str(root), portProfile=port_profile, sourceUnchanged=True,
                  portCounts=counts, pathMapping={old:new for old,new in mapping.items() if old not in omitted_borrowed}, explicitRepairs=repairs,
                  baseGameResources=sorted(native.references), nativeTest='not_run',
                  nativeResourceFingerprints=dict(native.dependencies),
                  baseResourceReplacements=base.replacements, omittedBorrowedResources=sorted(omitted_borrowed),
                  tf2BaseInventory=str(tf2_path) if tf2_path is not None else None,
                  migrationAudit=migration_audit, capabilities=capability_report(mapping),
                  cargoPolicy='same_verified_class',
                  limitations=['Known literal vehicle/render/config/constant-asset profiles; arbitrary TF2 scripts and dynamic API behavior require manual migration.',
                               'Appearance, animation, audio, purchasing and operation require native TF3 verification.',
                               'The store preview reuses the original small thumbnail; it is not a newly rendered 3D store image.',
                               'Missing default metal/gloss/AO uses the installed TF3 default; TF2 balancing uses TF3 automatic emissions.',
                               'Original changed resource text is retained in _port_originals; source files are untouched.'])
        report = convert_mod(stage,destination,overwrite=overwrite,progress=notify,
                             author=author,revision=revision,summary=summary,_report_fields=port_report)
    return report

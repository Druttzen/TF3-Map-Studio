"""Strict, opt-in TF2 electric-locomotive porting. Never executes source Lua.

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
from .lua_metadata import UnsupportedValue, load_lua_table
from .tf2_sound_port import port_sound_set
from .base_resources import BASE_TEXTURES, ROOTS, BaseResourceResolver, TF2Inventory, find_tf2_game, source_resource


def literal(value: Any, where: str = "data") -> Any:
    if isinstance(value, UnsupportedValue):
        raise ValueError(f"{where}: {value.reason}")
    if isinstance(value, dict):
        for k, v in value.items(): literal(v, f"{where}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value): literal(v, f"{where}/{i}")
    return value


def lua_value(value: Any, translations: set[str] | None = None) -> str:
    """Emit literals only, with Lua decimal escapes for control characters."""
    if value is None: return "nil"
    if value is True: return "true"
    if value is False: return "false"
    if isinstance(value, str):
        quoted = '"' + ''.join(('\\' + str(ord(c)).zfill(3)) if ord(c) < 32 else
                               ('\\' + c if c in '\\"' else c) for c in value) + '"'
        return f"_({quoted})" if translations and value in translations else quoted
    if isinstance(value, (int, float)):
        if not math.isfinite(value): raise ValueError("Non-finite Lua number")
        return repr(value)
    if isinstance(value, list):
        return "{ " + ", ".join(lua_value(v, translations) for v in value) + " }"
    if isinstance(value, dict):
        rows = []
        for k, v in value.items():
            key = k if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) else f"[{lua_value(k)}]"
            rows.append(f"{key} = {lua_value(v, translations)}")
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
        for f in self.content.rglob('*'):
            if not f.is_file(): continue
            if f.suffix == '.zip':
                with zipfile.ZipFile(f) as z:
                    for n in z.namelist():
                        if not n.endswith('/'):
                            self.files[(f.parent.relative_to(self.content) / n).as_posix()] = (f, n)
            else: self.files[f.relative_to(self.content).as_posix()] = (f, None)

    def read(self, path: str) -> bytes:
        if path not in self.files: raise ValueError(f"Installed TF3 resource missing: {path}")
        f, n = self.files[path]
        if n is None: return f.read_bytes()
        with zipfile.ZipFile(f) as z: return z.read(n)

    def reference(self, path: str) -> str:
        resource = path.split('@', 1)[0]
        candidates = [resource+'.lua',resource+'.tl'] if resource.endswith(('.snd','.trf','.script')) else [resource]
        found = next((p for p in candidates if p in self.files), None)
        if found is None: raise ValueError(f"Installed TF3 resource missing: {resource}")
        self.read(found)
        self.references.add(path)
        return '::/' + path

    def material(self, data: dict, resolve) -> dict:
        result = deepcopy(data)
        self.read(f"rendering/{data['type'].lower()}.mat.lua")
        result['params'] = {}
        for key, values in data['params'].items():
            schema = literal(load_lua_table(self.read(f'rendering/properties/{key}.prop.lua').decode('utf-8')))
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
        result['params']['light_receiver'] = {'fragmentProperties': [{'isLegacyMaterial': True, 'lightMask': 2}]}
        return result


def flatten(node: dict):
    yield node
    for child in node.get('children', []): yield from flatten(child)


def reject_unknown(data: dict, allowed: set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown: raise ValueError(f"Unsupported {where} fields (preserved in source): {sorted(unknown)}")


def port_model(data: dict, resolve, native: NativeInventory) -> dict:
    result = deepcopy(data)
    if result.get('version') != 1: raise ValueError("Only TF2 model version 1 is supported")
    reject_unknown(result, {'version','boundingInfo','collider','lods','metadata'}, 'model')
    m = result['metadata']
    reject_unknown(m, {'transportVehicle','availability','cost','description','emission','maintenance','railVehicle','seatProvider'}, 'vehicle metadata')
    rail = m['railVehicle']
    reject_unknown(rail, {'engines','soundSet','topSpeed','weight','configs'}, 'railVehicle')
    if not rail.get('engines') or any(e.get('type') != 'ELECTRIC' for e in rail['engines']):
        raise ValueError("The current port profile supports electric locomotives only")
    configs = rail['configs']
    if len(configs) != len(result['lods']): raise ValueError("Rail configs must match the LOD count")
    all_nodes = []
    wheel_names: list[str] = []
    bogies = []
    for li, (lod, config) in enumerate(zip(result['lods'], configs)):
        reject_unknown(lod, {'node','static','visibleFrom','visibleTo'}, 'LOD')
        reject_unknown(config, {'axles','fakeBogies','frontForwardParts','frontBackwardParts','backForwardParts','backBackwardParts','innerForwardParts','innerBackwardParts','blinkingLights0','blinkingLights1'}, 'rail config')
        for key in ('blinkingLights0','blinkingLights1'):
            if key in config and config[key] != []:
                raise ValueError(f'Non-empty {key} requires a separate animation port')
        nodes = list(flatten(lod['node']))
        names = set()
        for i, node in enumerate(nodes):
            reject_unknown(node, {'name','mesh','materials','transf','children','animations'}, 'node')
            # Duplicate group/mesh names are common in TF2. Distinguish by role,
            # keeping corresponding LOD names stable despite different indices.
            name = node.get('name') or f'node_{i}'
            if 'mesh' in node and name in names: name += '_mesh'
            if name in names: raise ValueError(f"Ambiguous node name {name!r} in LOD {li}")
            names.add(name); node['name'] = name
        def node_name(index):
            if type(index) is not int or not 0 <= index < len(nodes): raise ValueError(f"Invalid node index {index} in LOD {li}")
            return nodes[index]['name']
        for mesh in config.get('axles', []):
            matches = [n['name'] for n in nodes if n.get('mesh') == mesh]
            if not matches: raise ValueError(f"Axle mesh {mesh} has no node in LOD {li}")
            for name in matches:
                if name not in wheel_names: wheel_names.append(name)
        bogies.append([{**b, 'group': node_name(b['group'])} for b in config.get('fakeBogies', [])])
        for key in ('frontForwardParts','frontBackwardParts','backForwardParts','backBackwardParts','innerForwardParts','innerBackwardParts'):
            event = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()
            for index in config.get(key, []):
                node = nodes[index] if type(index) is int and 0 <= index < len(nodes) else None
                if node is None: raise ValueError(f"Invalid {key} node index {index}")
                animations = node.setdefault('animations', {})
                if animations == []: animations = node['animations'] = {}
                for action in ('on','off'):
                    event_name = f'{event}_{action}'
                    if event_name in animations: raise ValueError(f"Existing {event_name} animation requires review")
                    animations[event_name] = {'type':'FILE_REF','params':{'id':native.reference(f'vehicle/shared/ani/{event_name}.ani')}}
        for node in nodes:
            if 'mesh' in node: node['mesh'] = resolve(node['mesh'], 'mesh')
            if 'materials' in node: node['materials'] = [resolve(v, 'material') for v in node['materials']]
            for event, animation in (node.get('animations') or {}).items():
                if animation.get('type') != 'FILE_REF': raise ValueError(f"Unsupported animation {event}")
                ref = animation['params']['id']
                if not ref.startswith('::'): animation['params']['id'] = resolve(ref, 'animation')
        all_nodes.append(nodes)
    m['landVehicle'] = {'engines':rail['engines'], 'topSpeed':rail['topSpeed'], 'weightEmpty':rail['weight']*1000, 'weightMaxPayload':0}
    sound = rail.get('soundSet', {})
    reject_unknown(sound, {'name','horn'}, 'soundSet')
    m['soundConfig'] = {'soundSet':{'name':resolve(sound['name'], 'sound_set')}}
    if sound.get('horn'): m['soundConfig']['effects'] = {'horn':[resolve(sound['horn'], 'audio')]}
    m['railVehicle'] = {'config': {'axles':wheel_names, 'fakeBogies':bogies}}
    m['transformatorConfig'] = {'transformator':{'name':native.reference('vehicle/train/shared/default_train.trf')}}
    m['extent'] = deepcopy(result['boundingInfo'])
    if m.get('emission'):
        if any(v != -1 for v in m['emission'].values()): raise ValueError("Explicit TF2 emissions need a balancing decision")
        del m['emission']
        m['emissions'] = {'noise':{'score':-1}, 'pollution':{'score':-1}}
    if 'lifespan' in m.get('maintenance', {}): m['maintenance']['lifespan'] *= 2
    seat = m.get('seatProvider', {})
    if seat.get('crewModels'): raise ValueError("Custom crew models require a separate port")
    for s in seat.get('seats', []):
        index = s['group']
        if type(index) is not int or not 0 <= index < len(all_nodes[0]): raise ValueError("Invalid crew seat node")
        s['group'] = all_nodes[0][index]['name']
    t = m['transportVehicle']
    reject_unknown(t, {'carrier','compartmentsList','compartments','groupFileName','loadSpeed','multipleUnitOnly','reversible'}, 'transportVehicle')
    if t['carrier'] != 'RAIL': raise ValueError("Only rail transport supported")
    t.update(transportModes=['TRAIN','ELECTRIC_TRAIN'], engineTransportModes=['ELECTRIC_TRAIN'], comfortFactor=0, filterTags=[] if t.pop('multipleUnitOnly', False) else ['default'])
    if 'compartments' in t and 'compartmentsList' in t:
        raise ValueError('Conflicting TF2 compartment schemas need manual review')
    if 'compartments' in t:
        old_compartments = t.pop('compartments')
        if not isinstance(old_compartments,list) or any(not isinstance(c,list) or any(load != [] for load in c) for c in old_compartments):
            raise ValueError('Non-empty legacy TF2 compartments need a capacity/load port')
        compartments = [{'loadConfigs':[{} for load in c]} for c in old_compartments]
    else:
        compartments = t.pop('compartmentsList', [])
    for compartment in compartments:
        for load in compartment.get('loadConfigs', []):
            if load.get('cargoEntries'): raise ValueError("Passenger/cargo capacities are not supported by this locomotive profile")
            load.pop('cargoEntries', None)
            load['cargoEntry'] = {'capacity':0, 'cargoTypeSet':{}, 'loadIndicator':'', 'seats':[]}
            indexes = load.get('toHide', [])
            if any(type(i) is not int or not 0 <= i < len(all_nodes[0]) for i in indexes):
                raise ValueError('Invalid hidden node index')
            load['toHide'] = [all_nodes[0][i]['name'] for i in indexes]
    t['compartments'] = compartments
    if t.get('groupFileName'): t['groupFileName'] = resolve(t['groupFileName'], 'model')
    result['version'] = 2
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
                 tf2_game: str | Path | None = None) -> dict:
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
    native = NativeInventory(Path(tf3_game))
    tf2_path = Path(tf2_game) if tf2_game is not None else find_tf2_game(root, Path(tf3_game))
    tf2 = TF2Inventory(tf2_path) if tf2_path is not None else None
    base = BaseResourceResolver(native, tf2, family='train')
    before = snapshot(root)
    repairs = repairs or {}
    if not isinstance(repairs,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in repairs.items()):
        raise ValueError('Repairs must map texture reference strings to source texture paths')
    mapping = {p.relative_to(root/'res').as_posix():checked_name(p.relative_to(root/'res').as_posix())
               for p in (root/'res').rglob('*') if p.is_file()}
    sound_files = {old for old in mapping if old.startswith('config/sound_set/') and old.endswith('.lua')}
    for old in sound_files:
        mapping[old] = mapping[old][:-4]+'.snd.lua'
    if len(set(mapping.values())) != len(mapping): raise ValueError("Normalized resource filenames collide")
    used_repairs = set()
    omitted_borrowed = set()
    borrowed_sound_sets = {}
    for old in sorted(sound_files):
        ref = old[len(ROOTS['sound_set'])+1:-4]
        if base.is_borrowed('sound_set', ref, root/'res'/old):
            borrowed_sound_sets[old] = base.resolve('sound_set', ref, bundled=True)
            omitted_borrowed.add(old)
    def resolve(ref: str, kind: str) -> str:
        source_resource(kind, ref)  # Reject unsafe input before looking up local or base assets.
        if kind == 'texture' and ref in repairs:
            used_repairs.add(ref)
            ref = repairs[ref]
        old = source_resource(kind, ref)
        if old in borrowed_sound_sets:
            return borrowed_sound_sets[old]
        if old in mapping:
            if kind != 'sound_set' and base.is_borrowed(kind, ref, root/'res'/old):
                replacement = base.resolve(kind, ref, bundled=True)
                omitted_borrowed.add(old)
                return replacement
            return mod_id+'::/'+(mapping[old][:-4] if kind == 'sound_set' else mapping[old])
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
    english = translations.get('en', {})
    info['name'] = name
    info['description'] = english.get(info.get('description'), info.get('description',''))
    info['modId'] = mod_id
    transformed = {}
    originals = {}
    counts = {'models':0,'materials':0,'meshes':0,'animations':0}
    for old in sorted(mapping):
        if old in borrowed_sound_sets:
            continue
        p = root/'res'/old
        suffix = p.suffix.lower()
        if old in sound_files:
            transformed[mapping[old]] = emit(port_sound_set(p.read_text(encoding='utf-8-sig'), resolve, native))
            originals[old] = p.read_bytes()
            counts['soundSets'] = counts.get('soundSets',0)+1
            continue
        if suffix in ('.lua', '.tl', '.script', '.con', '.module', '.trf', '.snd'):
            raise ValueError(f'Custom behavior resource needs a manual port: {old}')
        if suffix not in ('.mdl','.mtl','.msh','.ani'): continue
        d = literal(load_lua_table(p.read_text(encoding='utf-8-sig'), constant_numbers=True), old)
        if suffix == '.mdl':
            d = port_model(d, resolve, native); counts['models'] += 1
            model_path = old[len('models/model/'):-4]
            # TF3 defaults use icons beside each model. Retain the original
            # supplied TF2 thumbnails through explicit metadata references.
            for field, folder, suffix in (
                ('iconSmall','models_small','@2x.tga'),('iconSmallCblend','models_small','_cblend@2x.tga'),
                ('icon20','models_20','@2x.tga'),('icon20cblend','models_20','_cblend@2x.tga'),
                ('icon3d','models_small','@2x.tga')):
                icon = f'textures/ui/{folder}/{model_path}{suffix}'
                if icon in mapping: d['metadata']['description'][field] = mod_id+'::/'+mapping[icon]
        elif suffix == '.mtl':
            d = native.material(d, resolve); counts['materials'] += 1
        elif suffix == '.msh':
            if not p.with_name(p.name+'.blob').is_file(): raise ValueError(f"Missing mesh blob: {old}")
            counts['meshes'] += 1
            continue  # Index schema shared by TF2/TF3; retain mesh bytes exactly.
        else:
            counts['animations'] += 1; continue
        originals[old] = p.read_bytes()
        transformed[mapping[old]] = emit(d, keys)
    if not counts['models']: raise ValueError("No TF2 models found")
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
        for relative,text in transformed.items(): (stage/'content'/relative).write_text(text,encoding='utf-8')
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
        port_report = dict(source=str(root), portProfile='tf2_electric_locomotive', sourceUnchanged=True,
                  portCounts=counts, pathMapping={old:new for old,new in mapping.items() if old not in omitted_borrowed}, explicitRepairs=repairs,
                  baseGameResources=sorted(native.references), nativeTest='not_run',
                  baseResourceReplacements=base.replacements, omittedBorrowedResources=sorted(omitted_borrowed),
                  tf2BaseInventory=str(tf2_path) if tf2_path is not None else None,
                  limitations=['Electric locomotives with literal resources and no cargo only.',
                               'Appearance, animation, audio, purchasing and operation require native TF3 verification.',
                               'The store preview reuses the original small thumbnail; it is not a newly rendered 3D store image.',
                               'Missing default metal/gloss/AO uses the installed TF3 default; TF2 balancing uses TF3 automatic emissions.',
                               'Original changed resource text is retained in _port_originals; source files are untouched.'])
        report = convert_mod(stage,destination,overwrite=overwrite,progress=notify,
                             author=author,revision=revision,summary=summary,_report_fields=port_report)
    return report

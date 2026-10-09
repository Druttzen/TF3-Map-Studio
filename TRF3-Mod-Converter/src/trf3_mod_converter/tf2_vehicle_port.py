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

from .converter import _check_paths, _copy_files, _linked, convert_mod, prepare_mod, migrate_legacy_display_name
from .filesystem import rename_with_retry
from .lua_metadata import UnsupportedValue, TranslatedString, load_lua_table
from .tf2_sound_port import port_sound_set
from .resource_audit import LUA_RESOURCE_ENDINGS
from .resource_profiles import (resource_target, classify_resource, load_resource_table, port_resource,
                                capability_report, TranslatedConcat, resolve_translation_concatenations)
from .base_resources import BASE_TEXTURES, ROOTS, BaseResourceResolver, TF2Inventory, find_tf2_game, source_resource, normalize_reference


def literal(value: Any, where: str = "data") -> Any:
    if isinstance(value, UnsupportedValue):
        raise ValueError(f"{where}: {value.reason}")
    if isinstance(value, dict):
        for k, v in value.items(): literal(v, f"{where}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value): literal(v, f"{where}/{i}")
    return value


def normalize_translation_tables(translations: dict, audit: dict) -> dict:
    """Keep named translations; archive unattached scalar array entries.

    Lua's localization helper addresses string keys. Numeric language-table
    entries cannot represent a TF3 translation key, and may not be guessed to
    belong to any named description. Record their exact values and preserve the
    original strings.lua instead of silently dropping or attaching them.
    """
    result = {}
    for language, table in translations.items():
        if not isinstance(language, str) or not language or not isinstance(table, (dict, list)) or (isinstance(table, list) and table):
            raise ValueError('Expected literal language/key/text translation tables')
        entries = {}
        for key, value in (table.items() if isinstance(table, dict) else []):
            if not isinstance(value, str):
                raise ValueError(f'Translation {language}/{key} must contain literal text')
            if type(key) is int and key >= 1:
                audit.setdefault('translationMigrations', []).append({
                    'language': language, 'sourceKey': key, 'sourceValue': value,
                    'policy': 'archive_unattached_numeric_translation_entry',
                    'originalFile': '_port_originals/strings.lua', 'nativeTest': 'not_run'})
            elif isinstance(key, str):
                entries[key] = value
            else:
                raise ValueError(f'Unsupported translation key in language {language}')
        result[language] = entries
    return result


def lua_value(value: Any, translations: set[str] | None = None, _path=()) -> str:
    """Emit literals only, with Lua decimal escapes for control characters."""
    if isinstance(value, TranslatedConcat):
        raise ValueError('Translation concatenation must be resolved against the locale tables before export')
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
        digest = hashlib.sha256(data).hexdigest()
        if path in self.dependencies and self.dependencies[path] != digest:
            raise ValueError(f'Installed TF3 resource changed during conversion: {path}')
        self.dependencies[path] = digest
        return data

    def fingerprints(self, paths):
        return {path:hashlib.sha256(self.read(path)).hexdigest() for path in sorted(set(paths))}

    def track_dependencies(self, values):
        if any(path in self.dependencies and self.dependencies[path] != digest
               for path, digest in values.items()):
            raise ValueError('Installed TF3 resources changed after their data was parsed')
        self.dependencies.update(values)

    def verify_current(self, expected_inventory, expected_resources):
        """Rebuild mounts so additions and newly shadowing files are checked."""
        try:
            fresh = NativeInventory(self.content.parent.parent)
            return (fresh.inventory_fingerprint() == expected_inventory
                    and fresh.fingerprints(expected_resources) == expected_resources)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return False

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

    def material(self, data: dict, resolve, *, report=None, resource='', vehicle_mode=False) -> dict:
        result = deepcopy(data)
        definition = literal(load_lua_table(self.read(f"rendering/{data['type'].lower()}.mat.lua").decode('utf-8-sig'))) or {}
        definitions = {p['name']:p['id'] for p in definition.get('properties', [])}
        result['params'] = {}
        parameters = data.get('params') or {}
        if not isinstance(parameters,dict):
            raise ValueError('Material params must be a named literal table')
        standard_export_type = (data['type'] == definition.get('legacyName') and data['type'] in {
            'PHYSICAL_NRML_MAP_CBLEND_DIRT', 'PHYS_TRANSPARENT_NRML_MAP_CBLEND_DIRT',
            'PHYS_TRANSPARENT_NRML_MAP'})
        def record_ignored(property_name, source_value, evidence):
            if report is not None:
                report.setdefault('materialMigrations', []).append({
                    'resource': resource, 'property': property_name, 'sourceValue': deepcopy(source_value),
                    'policy': 'omit_unrecognized_tf2_exporter_field', 'materialType': data['type'],
                    'evidence': evidence,
                    'schemaSource': 'https://wiki.transportfever2.com/doku.php?id=modding:resourcetypes:mtl',
                    'nativeTest': 'not_run'})
        for key, values in parameters.items():
            if key not in definitions:
                # Livery authors globally replaced "Sc" with "SK" or "KLM"
                # even in shader parameter names. These exact neutral
                # misspellings were never consumed by the standard TF2 types.
                # Do not turn them into active settings by fixing their names.
                typo_neutral = {'albedo_SKale': {'albedoSKale': [1, 1, 1]},
                                'alpha_SKale': {'alphaSKale': 1},
                                'normal_SKale': {'normalSKale': 1},
                                'albedo_KLMale': {'albedoKLMale': [1, 1, 1]},
                                'alpha_KLMale': {'alphaKLMale': 1},
                                'normal_KLMale': {'normalKLMale': 1}}
                if (standard_export_type and key in typo_neutral and values == typo_neutral[key]
                        and isinstance(values, dict) and all(
                            type(v) in (int, float) for value in values.values()
                            for v in (value if isinstance(value, list) else [value]))):
                    record_ignored(key, values, 'Exact misspelled neutral parameter is absent from the standard TF2 material schema; retain the shader defaults.')
                    continue
                # TF2's PHYSICAL_NRML_MAP shader has no recoloring or aging
                # pass. Older exporters still wrote these inert blocks. Keep
                # the exact source type and archive them rather than enabling
                # a new effect by selecting a different material type.
                inactive_fields = {
                    'color_blend': {'albedoScale', 'albedoScales', 'color', 'colors'},
                    'dirt_rust': {'age', 'dirtColor', 'dirtOpacity', 'dirtScale',
                                  'rustColor', 'rustOpacity', 'rustScale'},
                }
                inactive = (data['type'] == definition.get('legacyName') == 'PHYSICAL_NRML_MAP'
                            and key in inactive_fields and isinstance(values, dict)
                            and not set(values) - inactive_fields[key])
                evidence = 'TF2 PHYSICAL_NRML_MAP has no color-blend or aging shader pass; installed TF3 legacyName and property list agree.'
                if (vehicle_mode and data['type'] == definition.get('legacyName')
                        and data['type'] in ('PHYS_TRANSPARENT','PHYS_TRANSPARENT_NRML_MAP')
                        and definition.get('transparent') is True and key in inactive_fields
                        and isinstance(values, dict) and not set(values) - (inactive_fields[key]
                            | ({'dirtFactor','rustFactor'} if key=='dirt_rust' else set()))):
                    inactive = True
                    shader = 'phys_transp.fs' if data['type']=='PHYS_TRANSPARENT' else 'phys_transp_nm.fs'
                    evidence = f'TF2 {data["type"]} has no recoloring or aging samplers in its installed {shader}; the installed TF3 legacy type declares no {key} property.'
                    from .vehicle_mode import warning
                    warning(report if report is not None else {},
                            'An unused recoloring or aging block absent from the transparent shader stays archived; the original material type and texture inputs are retained.',
                            resource=resource, property=key, sourceValue=deepcopy(values),
                            nativeSchema=f'rendering/{data["type"].lower()}.mat.lua')
                inactive_maps = {'map_cblend_dirt_rust', 'map_dirt', 'map_dirt_normal',
                                 'map_rust', 'map_rust_normal'}
                transparent_inactive = (vehicle_mode and data['type'] == definition.get('legacyName')
                        and data['type'] in ('PHYS_TRANSPARENT','PHYS_TRANSPARENT_NRML_MAP')
                        and definition.get('transparent') is True)
                ignored_maps = inactive_maps | ({'map_normal'} if data['type']=='PHYS_TRANSPARENT' else set())
                if ((data['type'] == definition.get('legacyName') == 'PHYSICAL_NRML_MAP'
                        or transparent_inactive) and key in ignored_maps and isinstance(values, dict)):
                    sampler_fields = {'fileName', 'type', 'wrapS', 'wrapT', 'minFilter', 'magFilter',
                                      'redGreen', 'compressionAllowed', 'mipmapAlphaScale'}
                    # The installed TF2 phys_nm fragment shader reads only
                    # albedo, normal and metal/gloss/AO. Do not resolve or
                    # activate exporter aging maps which that type never used.
                    inactive = (not set(values) - sampler_fields
                                and type(values.get('fileName')) is str and bool(values['fileName'])
                                and values.get('type') == 'TWOD'
                                and all(type(value) is str for field, value in values.items()
                                        if field in ('wrapS', 'wrapT', 'minFilter', 'magFilter'))
                                and all(type(value) is bool for field, value in values.items()
                                        if field in ('redGreen', 'compressionAllowed'))
                                and ('mipmapAlphaScale' not in values or
                                     type(values['mipmapAlphaScale']) in (int, float)
                                     and math.isfinite(values['mipmapAlphaScale'])))
                    evidence = 'Installed TF2 shaders2/mat/fs/normal/phys_nm.fs samples only albedo, normal and metal/gloss/AO; installed TF3 PHYSICAL_NRML_MAP declares no aging samplers.'
                    if inactive and transparent_inactive:
                        shader='phys_transp.fs' if data['type']=='PHYS_TRANSPARENT' else 'phys_transp_nm.fs'
                        evidence=f'Installed TF2 shaders2/mat/fs/normal/{shader} has no sampler for this exporter map; the installed TF3 legacy material does not declare it.'
                        from .vehicle_mode import warning
                        warning(report if report is not None else {},
                                'An unused texture sampler stays archived; the transparent material retains its declared texture inputs.',
                                resource=resource,property=key,sourceValue=deepcopy(values),
                                nativeSchema=f'rendering/{data["type"].lower()}.mat.lua')
                if (data['type'] == definition.get('legacyName')
                        and data['type'] in ('PHYSICAL', 'PHYS_TRANSPARENT')
                        and definition.get('transparent') is (data['type'] == 'PHYS_TRANSPARENT')
                        and key == 'normal_scale' and definition.get('needsTangentVertexAttrib') is False
                        and 'map_normal' not in definitions and isinstance(values, dict)):
                    inactive = (set(values) == {'normalScale'}
                                and type(values['normalScale']) in (int, float)
                                and values['normalScale'] == 1)
                    shader = 'phys_transp.fs' if data['type'] == 'PHYS_TRANSPARENT' else 'phys.fs'
                    evidence = f'Installed TF2 shaders2/mat/fs/normal/{shader} has no normal-map sampler or normalScale; installed TF3 {data["type"]} needs no tangent vertex attributes. Exact neutral exporter scale retained as source audit.'
                if (data['type'] == definition.get('legacyName')
                        and (vehicle_mode or definition.get('transparent') is True
                             and data['type'] in ('PHYS_TRANSPARENT', 'PHYS_TRANSPARENT_NRML_MAP', 'PHYS_TRANSPARENT_NRML_MAP_CBLEND_DIRT'))
                        and key == 'props'
                        and isinstance(values, dict)):
                    coefficients = values.get('coeffs')
                    inactive = (set(values) == {'coeffs'} and isinstance(coefficients, list)
                                and len(coefficients) == 4
                                and all(type(value) in (int, float) and math.isfinite(value)
                                        and (value >= 0 if vehicle_mode else value == 1) for value in coefficients))
                    evidence = 'Installed TF3 material exposes no props property. Retain the original four coefficients in the archive and preserve the material type and texture inputs.'
                    if inactive and vehicle_mode and any(value != 1 for value in coefficients):
                        from .vehicle_mode import warning
                        warning(report if report is not None else {},
                                'Source material coefficients absent from the installed shader stay archived; textures are retained and appearance needs a game check.',
                                resource=resource, property=key, sourceValue=deepcopy(values),
                                nativeSchema=f'rendering/{data["type"].lower()}.mat.lua')
                if (key in ('alpha_scale', 'alpha_test') and isinstance(values, dict)
                        and data['type'] == definition.get('legacyName')
                        and data['type'] in ('PHYSICAL', 'PHYSICAL_NRML_MAP', 'PHYSICAL_NRML_MAP_CBLEND_DIRT')
                        and definition.get('transparent') is False):
                    alpha_schema = literal(load_lua_table(self.read(
                        f'rendering/properties/{key}.prop.lua').decode('utf-8-sig')))
                    defaults = {p['name']: p['defaultValue'] for p in alpha_schema.get('fragmentProperties', [])
                                if 'defaultValue' in p}
                    # Opaque TF2 shaders do not sample a texture's alpha.
                    # Limit this adapter to installed defaults: a custom
                    # threshold or sorting request still requires a review.
                    inactive = bool(defaults) and all(
                        field in defaults and value == defaults[field]
                        and (type(value) is type(defaults[field]) or
                             type(value) in (int, float) and type(defaults[field]) in (int, float))
                        for field, value in values.items())
                    evidence = 'Opaque TF2 material has no texture-alpha shader pass; all fields equal installed TF3 alpha-property defaults.'
                if inactive:
                    literal(values, f'material/{key}')
                    if report is not None:
                        report.setdefault('materialMigrations', []).append({
                            'resource': resource, 'property': key, 'sourceValue': deepcopy(values),
                            'policy': 'omit_inactive_tf2_material_property',
                            'materialType': data['type'],
                            'evidence': evidence,
                            'schemaSource': 'https://wiki.transportfever2.com/doku.php?id=modding:resourcetypes:mtl',
                            'nativeTest': 'not_run'})
                    continue
                raise ValueError(f"Material type {data['type']} does not declare property {key}")
            prop = definitions[key]
            schema = literal(load_lua_table(self.read(f'rendering/{prop}.lua').decode('utf-8')))
            if key == 'map_logo' and values == 'player-logo-array':
                if vehicle_mode and not any(schema.get(group) for group in
                        ('fragmentSamplers', 'fragmentProperties', 'vertexProperties')):
                    from .vehicle_mode import warning
                    warning(report if report is not None else {},
                        'The installed TF3 logo shader exposes no logo inputs; the legacy logo binding stays archived.',
                        resource=resource, sourceValue=values, nativeSchema=f'rendering/{prop}.lua')
                    result['params'][key] = {}
                    continue
                raise ValueError('TF2 player-logo-array requires a verified TF3 player-logo adapter; '
                                 'the source logo was preserved and no target logo was guessed')
            values = deepcopy(values) if values != [] else {}
            if not isinstance(values,dict):
                raise ValueError(f'Material property {key} must be a named literal table')
            if (standard_export_type and key == 'two_sided' and prop == 'properties/two_sided.prop'
                    and type(values.get('order')) is int
                    and type(data.get('order')) is int and values['order'] == data['order']):
                order = values.pop('order')
                record_ignored('two_sided/order', order,
                    'Nested order duplicates the top-level render order; TF2 two_sided defines only twoSided and flipNormal. Preserve the top-level order.')
            typo_fields = {'color_blend': ('albedoSKales', 'albedoKLMales'),
                           'dirt_rust': ('dirtSKale', 'rustSKale', 'dirtKLMale', 'rustKLMale')}
            if standard_export_type and prop == f'properties/{key}.prop':
                for field in typo_fields.get(key, ()):
                    if field in values:
                        value = values[field]
                        components = value if isinstance(value, list) else [value]
                        expected_shape = (isinstance(value, list) and len(value) <= 2 if field in ('albedoSKales', 'albedoKLMales')
                                          else type(value) in (int, float))
                        if not expected_shape or any(type(v) not in (int, float) or not math.isfinite(v) for v in components):
                            raise ValueError(f'Material property {key}/{field} must contain finite literal scales')
                        record_ignored(f'{key}/{field}', values.pop(field),
                            'Exact misspelled scale field is absent from the standard TF2 material schema; preserve the correctly spelled fields and shader defaults.')
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
                if (vehicle_mode and isinstance(values, dict) and type(values.get('fileName')) is str
                        and not values['fileName'].strip()):
                    from .vehicle_mode import warning
                    warning(report if report is not None else {},
                            'An empty source texture binding stays archived; supplied textures are retained and the omitted binding uses shader defaults. Appearance needs a game check.',
                            resource=resource, property=key, sourceValue=deepcopy(values),
                            nativeSchema=f'rendering/{prop}.lua')
                    continue
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
                extra = set(values) - recognized
                if extra:
                    if not vehicle_mode:
                        raise ValueError(f"Unknown {key} properties: {extra}")
                    from .vehicle_mode import warning
                    warning(report if report is not None else {}, 'Material fields absent from the installed property stay archived; declared shader fields are retained.',
                            resource=resource, property=key, sourceValue={name:values[name] for name in sorted(extra)},
                            nativeSchema=f'rendering/{prop}.lua')
                result['params'][key] = out
        if 'light_receiver' in definitions:
            result['params']['light_receiver'] = {'fragmentProperties': [{'isLegacyMaterial': True, 'lightMask': 2}]}
        return result


def flatten(node: dict):
    if not isinstance(node, dict):
        raise ValueError('Model node must be a named literal table')
    yield node
    children = node.get('children', [])
    if children == {}:
        children = []
    if not isinstance(children, list):
        raise ValueError('Model node children must be a contiguous literal list; repair the source node table')
    for child in children:
        yield from flatten(child)


def reject_unknown(data: dict, allowed: set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown: raise ValueError(f"Unsupported {where} fields (preserved in source): {sorted(unknown)}")


def port_model(data: dict, resolve, native: NativeInventory, *, model_path='',
               report=None, animation_writer=None, expand_cargo_classes=True, progress=None,
               emissions_policy='strict', vehicle_policy='strict') -> dict:
    """Port verified vehicle families and render assets; source remains intact."""
    from .cargo_port import CargoCatalog, port_compartments
    from .vehicle_profiles import classify_model, derive_lod_nodes, adapt_vehicle_metadata
    from .conversion_choices import validate_emissions_policy
    validate_emissions_policy(emissions_policy)
    from .resource_profiles import port_static_model
    from .model_common import port_common_metadata, resolve_nodes
    from .missing_data import complete_missing_model, complete_payload

    result = deepcopy(literal(data))
    if result.get('version') != 1:
        raise ValueError('Only TF2 model version 1 is supported')
    reject_unknown(result, {'version','boundingInfo','collider','lods','metadata'}, 'model')
    log = report if report is not None else {}
    result, donor_match = complete_missing_model(result, native, model_path=model_path, report=log,
        progress=progress, preserve_tf2=vehicle_policy == 'tf2_complete')
    metadata = result.setdefault('metadata', {})
    if metadata == []:
        metadata = result['metadata'] = {}
    profile = classify_model(metadata, model_path)
    if profile.family == 'asset' and not profile.decorative_physics:
        derive_lod_nodes(result['lods'], metadata=metadata, report=log, model_path=model_path)
        extras = {key: metadata.pop(key) for key in
                  ('particleSystem','colorConfig','lightConfig','skinList','versioning') if key in metadata}
        result = port_static_model(result, resolve, native)
        nodes, _ = derive_lod_nodes(result['lods'])
        result['metadata'].update(extras)
        result['metadata'] = port_common_metadata(result['metadata'], nodes[0], resolve,
                                                  report=log, model_path=model_path, native=native)
        log.setdefault('vehicleProfiles', []).append({'model':model_path, 'profile':'tf2_asset',
                                                       'family':'asset', 'nativeTest':'not_run'})
        return result
    nodes, transforms = derive_lod_nodes(result['lods'], metadata=metadata, report=log, model_path=model_path)
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
            seat_count=len(seat_provider.get('seats', [])), allow_unverified_types=vehicle_policy == 'tf2_complete',
            allow_legacy_layouts=vehicle_policy == 'tf2_complete')
        if vehicle_policy == 'tf2_complete':
            for row in cargo_audit.get('legacyScalingPolicies', []):
                from .vehicle_mode import warning
                warning(log, 'An unrecognized cargo scaling string is retained for the native default; verify the load display in TF3.', model=model_path, **row)
            for row in cargo_audit.get('unverifiedCargoTypes', []):
                from .vehicle_mode import warning
                warning(log, 'A custom cargo dependency could not be confirmed; its identifier and capacity are retained without substituting another cargo.', model=model_path, **row)
    payload, payload_policy = complete_payload(data, native, (cargo_audit or {}).get('maxCapacity', 0),
        match=donor_match, model_path=model_path, report=log, preserve_tf2=vehicle_policy == 'tf2_complete')
    metadata, profile = adapt_vehicle_metadata(metadata, nodes, resolve, native, model_path=model_path,
        weight_max_payload=payload, node_world_transforms=transforms, animation_writer=animation_writer,
        report=log, emissions_policy=emissions_policy)
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
                                    model_path=model_path, vehicle=profile.carrier is not None, native=native)
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
                 tf2_game: str | Path | None = None, _native_inventory=None, _tf2_inventory=None,
                 emissions_policy='strict', vehicle_policy='strict') -> dict:
    """Export a separate native-format draft; repairs must be explicitly supplied.

    The report never asserts native game compatibility. Installed game resources
    are referenced, never redistributed. All changed source text is archived.
    """
    from .conversion_choices import conversion_choices
    choices = conversion_choices(emissions_policy, vehicle_policy)
    vehicle_mode = vehicle_policy == 'tf2_complete'
    if vehicle_mode and emissions_policy == 'strict':
        emissions_policy = 'class_average'
        choices = conversion_choices(emissions_policy, vehicle_policy)
    from .vehicle_mode import vehicle_package, warning, compatibility_model, source_gear_radii, prepare_vehicle_model
    if not re.fullmatch(r'[a-z0-9_]+',mod_id): raise ValueError('Invalid TF3 mod ID')
    if not isinstance(name, str) or not name.strip(): raise ValueError('Name must contain non-blank text')
    source = Path(source).expanduser().absolute(); destination = Path(destination).expanduser().absolute()
    root = _check_paths(source, destination, overwrite)
    if vehicle_mode and not vehicle_package(root):
        raise ValueError('Vehicle mode skips packages without vehicles or vehicle appearance resources')
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
    native_inventory_start = native.inventory_fingerprint()
    tf2_path = Path(tf2_game) if tf2_game is not None else find_tf2_game(root, Path(tf3_game))
    tf2 = _tf2_inventory if _tf2_inventory is not None else (TF2Inventory(tf2_path) if tf2_path is not None else None)
    if tf2 is not None and tf2.content.resolve() != (tf2_path/'res').resolve():
        raise ValueError('Shared TF2 inventory does not match the selected installation')
    base = BaseResourceResolver(native, tf2, family='train')
    from .source_game_resources import SourceGameResources, verify_source_game_dependencies
    source_game = SourceGameResources(tf2) if tf2 is not None else None
    source_game_origins = set()
    source_game_aliases = {}
    active_resource = None
    from .workshop_resources import (WorkshopResources, verify_workshop_dependencies,
                                    verify_workshop_absences, verify_native_stock_selections,
                                    verify_base_resource_identities)
    workshop = None
    migration_audit = {}
    if root.name.isdecimal() and root.parent.name == '1066780':
        # A retry must see current provider contents and declarations even
        # when the expensive installed-game inventory is shared by a queue.
        try:
            workshop = WorkshopResources(root)
        except ValueError as exc:
            if not vehicle_mode:
                raise
            warning(migration_audit, 'Workshop declarations could not be resolved; vehicle export continues.',
                    reason=str(exc))
    dependency_files, dependency_fingerprints = {}, {}
    dependency_sources = {}
    dependency_origins = {}
    def read_table(text, *, resource='', allow_global_literals=False):
        try:
            return load_resource_table(text, allow_global_literals=allow_global_literals,
                                       audit=migration_audit, resource=resource)
        except ValueError as exc:
            if vehicle_mode and resource.endswith('.mdl') and str(exc) == 'Dynamic/unbound Lua name: f':
                tree = ast.parse(text)
                bound = [target for statement in ast.walk(tree) for target in
                         (statement.targets if isinstance(statement, (lua.LocalAssign,lua.Assign)) else
                          statement.args if isinstance(statement, (lua.Function,lua.LocalFunction,lua.AnonymousFunction)) else [])]
                if any(isinstance(target, lua.Name) and target.id == 'f' for target in bound): raise
                replaced = 0
                for table in ast.walk(tree):
                    if not isinstance(table, lua.Table): continue
                    for field in list(table.fields):
                        if (isinstance(field.key, lua.Name) and field.key.id == 'forward'
                                and isinstance(field.value, lua.Name) and field.value.id == 'f'):
                            table.fields.remove(field); replaced += 1
                if replaced:
                    value = load_resource_table(ast.to_lua_source(tree), audit=migration_audit, resource=resource)
                    warning(migration_audit, 'Unbound optional forward flags stay archived and use the native default; no direction is guessed.',
                            resource=resource, count=replaced, sourceValue='f')
                    return value
            if vehicle_mode and resource.endswith('.mdl') and 'Unknown Lua helper/API import:' in str(exc):
                tree = ast.parse(text)
                functions = [statement for statement in tree.body.body if isinstance(statement, lua.Function)
                             and isinstance(statement.name, lua.Name) and statement.name.id == 'data']
                imports = [statement for statement in tree.body.body if statement not in functions]
                if len(functions) != 1 or any(not isinstance(statement, lua.LocalAssign)
                        or len(statement.values) != 1 or not isinstance(statement.values[0], lua.Call)
                        or not isinstance(statement.values[0].func, lua.Name)
                        or statement.values[0].func.id != 'require' for statement in imports):
                    raise
                value = load_lua_table(ast.to_lua_source(functions[0]), constant_numbers=True)
                def animations(node):
                    if isinstance(node, dict):
                        for event, animation in list((node.get('animations') or {}).items()):
                            try: literal(animation)
                            except ValueError:
                                node['animations'].pop(event)
                                warning(migration_audit, 'An unported helper animation stays archived; the literal vehicle geometry and data are retained.',
                                        resource=resource, event=event, reason=str(exc))
                        for child in node.values(): animations(child)
                    elif isinstance(node, list):
                        for child in node: animations(child)
                animations(value.get('lods', []))
                return literal(value)
            if not vehicle_mode or 'Duplicate Lua table key' not in str(exc):
                raise
            value = load_lua_table(text)
            warning(migration_audit, 'Repeated literal fields use the original Lua last-value rule.', resource=resource)
            return value
    translations = literal(read_table((root/'strings.lua').read_text(encoding='utf-8-sig'),
        allow_global_literals=True, resource='strings.lua')) if (root/'strings.lua').exists() else {}
    translations = normalize_translation_tables(translations, migration_audit)
    from .dependency_context import DependencyContext
    dependency_context = DependencyContext(root, workshop, translations, migration_audit,
                                           dependency_fingerprints) if workshop is not None else None

    def resource_bytes(old):
        return dependency_sources[old] if old in dependency_sources else (root/'res'/old).read_bytes()

    def localize_resource(value, old):
        if old not in dependency_origins:
            return value
        try:
            return dependency_context.localize(value, dependency_origins[old])
        except ValueError as exc:
            if not vehicle_mode:
                raise
            warning(migration_audit, 'Dependency translation text could not be confirmed; original literal labels are retained.',
                    resource=old, reason=str(exc))
            def labels(data):
                if isinstance(data, TranslatedConcat):
                    return ''.join(part for _, part in data.parts)
                if isinstance(data, TranslatedString):
                    return str(data)
                if isinstance(data, dict):
                    return {labels(k): labels(v) for k,v in data.items()}
                if isinstance(data, list):
                    return [labels(v) for v in data]
                return data
            return labels(value)

    def resource_table(old):
        text = resource_bytes(old).decode('utf-8-sig')
        value = read_table(text, resource=old)
        value = localize_resource(value, old)
        value = literal(resolve_translation_concatenations(
            value, translations,
            migration_audit, resource=old), old)
        if vehicle_mode and old.endswith('.mdl'):
            value = prepare_vehicle_model(value, model_path=old, report=migration_audit)
        return value
    before = snapshot(root)
    repairs = repairs or {}
    if not isinstance(repairs,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in repairs.items()):
        raise ValueError('Repairs must map texture reference strings to source texture paths')
    mapping = {p.relative_to(root/'res').as_posix():resource_target(p.relative_to(root/'res').as_posix())
               for p in (root/'res').rglob('*') if p.is_file()}
    from .verified_helpers import HELPER_DIGESTS, HELPER_DIGEST_VARIANTS, helper_digest_verified, verified_legacy_helpers
    verified_helpers = verified_legacy_helpers(root)
    helper_sources = {path.relative_to(root/'res').as_posix() for path in verified_helpers.values()}
    for helper, path in verified_helpers.items():
        migration_audit.setdefault('helperMigrations', []).append({
            'sourceResource':path.relative_to(root).as_posix(), 'helper':helper,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'policy':('replace_exact_legacy_helper_with_native_construction_profile' if helper == 'parambuilder_v1_1'
                      else 'compile_exact_legacy_sound_helper_profile'),
            'originalFile':'_port_originals/'+path.relative_to(root).as_posix(), 'nativeTest':'not_run'})
    opaque = [old for old in mapping if PurePosixPath(old).suffix.lower() in
              ('.zip','.7z','.rar','.pak','.dll','.exe','.bat','.cmd','.ps1','.sh')]
    if opaque:
        raise ValueError('Opaque resource archive/native executable requires unpacking or manual migration: '+', '.join(sorted(opaque)[:8]))
    builtin_helpers = ('bridgeutil', 'texutil', 'vec2', 'vec3', 'vec4', 'transf', 'soundsetutil', 'audioutil',
                       'soundeffectsutil', 'constructionutil', 'colliderutil', 'laneutil', 'vehicleutil')
    for helper in builtin_helpers:
        if any(old.lower() in (f'scripts/{helper}.lua', f'scripts/{helper}.tl') and old not in helper_sources
               for old in mapping):
            if not vehicle_mode:
                raise ValueError(f'Local {helper} shadows the built-in helper; manual script migration required')
            shadow = {old for old in mapping if old.lower() in (f'scripts/{helper}.lua', f'scripts/{helper}.tl')}
            helper_sources.update(shadow)
            warning(migration_audit, 'An unported legacy helper stays archived; the native helper is used.',
                    helper=helper)
    def resource_helpers(old):
        if old in source_game_origins:
            return {}
        if old not in dependency_origins:
            return {module:hashlib.sha256(path.read_bytes()).hexdigest()
                    for module, path in verified_helpers.items()}
        modules = {node.args[0].s.decode('utf-8') if isinstance(node.args[0].s, bytes) else node.args[0].s
                   for node in ast.walk(ast.parse(resource_bytes(old).decode('utf-8-sig')))
                   if isinstance(node, lua.Call) and isinstance(node.func, lua.Name) and node.func.id == 'require'
                   and len(node.args) == 1 and isinstance(node.args[0], lua.String)}
        result = {}
        for module in modules & (set(HELPER_DIGESTS) | set(HELPER_DIGEST_VARIANTS) | set(builtin_helpers)):
            matches = dependency_context.lookup(module, 'helper', owners=dependency_origins[old])
            if not matches:
                continue
            if module in builtin_helpers and not all(helper_digest_verified(module, match['sha256']) for match in matches):
                raise ValueError(f'Dependency author {module} shadows the built-in helper; manual script migration required')
            if (len(matches) != len(dependency_origins[old])
                    or len({match['sha256'] for match in matches}) != 1
                    or not helper_digest_verified(module, matches[0]['sha256'])):
                raise ValueError(f'Dependency helper has no identical verified profile in every author context: {module}')
            for match in matches:
                package = Path(match['lookupSource']).name
                archive = f'_dependencies/{package}/res/scripts/{module}.lua'
                dependency_context.archive[archive] = match['data']
                dependency_context.record([match], None, 'compile_exact_author_dependency_helper',
                                          original_file='_port_originals/'+archive)
            result[module] = matches[0]['sha256']
        return result
    sound_files = {old for old in mapping if old.startswith('config/sound_set/') and old.endswith('.lua')}
    if len(set(mapping.values())) != len(mapping): raise ValueError("Normalized resource filenames collide")
    used_repairs = set()
    omitted_borrowed = set()
    borrowed_sound_sets = {}
    # Classify verified descriptors before adapting any of them; a later
    # reference must not reintroduce an omitted TF2 base model/material.
    borrowed_resources = {}
    unresolved_borrowed = []
    for old in sorted(mapping):
        kind = 'model' if old.startswith(ROOTS['model']+'/') and old.endswith('.mdl') else (
               'material' if old.startswith(ROOTS['material']+'/') and old.endswith('.mtl') else None)
        if kind:
            reference = old[len(ROOTS[kind])+1:]
            if base.is_borrowed(kind, reference, root/'res'/old):
                try:
                    borrowed_resources[old] = base.resolve(kind, reference, bundled=True)
                    omitted_borrowed.add(old)
                except ValueError:
                    unresolved_borrowed.append((reference, kind, old))
    model_data, sound_families, mesh_referrers = {}, {}, {}
    originals = {}
    inactive_models = set()
    from .missing_data import classify_missing_model, classification_view
    from .vehicle_profiles import classify_model
    def source_profile(data, path):
        return classify_model(classification_view(data), path) if vehicle_mode else classify_missing_model(data, path)
    from .vehicle_profiles import normalize_sound_set
    for old in sorted(mapping):
        if not old.endswith('.mdl') or old in omitted_borrowed:
            continue
        try:
            data = resource_table(old)
        except ValueError as exc:
            from .vehicle_mode import empty_model_metadata
            if (not vehicle_mode or 'Unknown Lua helper/API import:' not in str(exc)
                    or not empty_model_metadata(resource_bytes(old).decode('utf-8-sig'))):
                raise
            originals[old] = resource_bytes(old)
            omitted_borrowed.add(old)
            inactive_models.add(old)
            warning(migration_audit, 'An unsupported non-vehicle render helper with empty metadata stays archived; vehicle models continue.',
                    resource=old, originalFile='_port_originals/res/'+old)
            continue
        model_data[old] = data
        for lod_index, lod in enumerate(data.get('lods', [])):
            for node_index, node in enumerate(flatten(lod['node'])):
                if node.get('mesh'):
                    mesh_referrers.setdefault(source_resource('mesh', node['mesh']), []).append({
                        'modelPath':old, 'nodePath':f'lods[{lod_index}]/node[{node_index}]',
                        'materials':deepcopy(node.get('materials'))})
        metadata = data.get('metadata', {}) or {}
        profile = source_profile(data, old)
        for block in ('railVehicle','roadVehicle','soundConfig'):
            sound_owner = metadata.get(block) or {}
            if not isinstance(sound_owner, dict):
                raise ValueError(f'{old}/metadata/{block}: expected a named table')
            sound = normalize_sound_set(sound_owner.get('soundSet', {}))
            if sound.get('name'):
                sound_families.setdefault(source_resource('sound_set', sound['name']), set()).add(profile.family)
    def sound_family(old):
        families = sound_families.get(old, set())
        return next(iter(families)) if len(families) == 1 else None
    for old in sorted(sound_files):
        base.family = sound_family(old)
        ref = old[len(ROOTS['sound_set'])+1:-4]
        if base.is_borrowed('sound_set', ref, root/'res'/old):
            try:
                borrowed_sound_sets[old] = base.resolve('sound_set', ref, bundled=True)
                omitted_borrowed.add(old)
            except ValueError:
                unresolved_borrowed.append((ref, 'sound_set', old))
    def adapt_source_game(ref, kind, old):
        if source_game is None:
            return None
        match = source_game.resolve(ref, kind)
        if match is None:
            return None
        source_old = old
        blob = source_game.resolve(ref+'.blob', 'mesh_blob') if kind == 'mesh' else None
        conflict = old in mapping and resource_bytes(old) != match['data']
        if blob is not None:
            conflict = conflict or old+'.blob' in mapping and resource_bytes(old+'.blob') != blob['data']
        if conflict and vehicle_mode:
            prefix = ROOTS[kind]
            old = prefix+'/tf2_base/'+source_old[len(prefix)+1:]
            warning(migration_audit, 'An authored resource and installed TF2 input share a filename; both are preserved under separate references.',
                    sourceResource=source_old, installedResource=old)
        target = resource_target(old)
        if old in mapping:
            if resource_bytes(old) != match['data']:
                raise ValueError(f'Installed TF2 dependency conflicts with an authored resource: {old}')
        elif target in mapping.values():
            raise ValueError(f'Installed TF2 dependency normalized filename collision: {old}')
        mapping[old] = target
        dependency_sources[old] = match['data']
        source_game_origins.add(old)
        source_game_aliases[source_old] = old
        if kind == 'mesh':
            for row in mesh_referrers.get(source_old, []):
                materials = row.get('materials')
                if not isinstance(materials, list) or len(materials) != match['validation']['submeshCount']:
                    raise ValueError(f'{old}: installed TF2 mesh material slots do not match its model referrer')
            blob_old, blob_target = old+'.blob', target+'.blob'
            if blob_old in mapping:
                if resource_bytes(blob_old) != blob['data']:
                    raise ValueError(f'Installed TF2 geometry conflicts with an authored blob: {blob_old}')
            elif blob_target in mapping.values():
                raise ValueError(f'Installed TF2 dependency normalized filename collision: {blob_old}')
            mapping[blob_old] = blob_target
            dependency_sources[blob_old] = blob['data']
            source_game_origins.add(blob_old)
            source_game_aliases[source_old+'.blob'] = blob_old
        elif kind == 'sound_set':
            sound_files.add(old)
        elif kind == 'model':
            data = resource_table(old)
            model_data[old] = data
            for lod_index, lod in enumerate(data.get('lods', [])):
                for node_index, node in enumerate(flatten(lod['node'])):
                    if node.get('mesh'):
                        mesh_referrers.setdefault(source_resource('mesh', node['mesh']), []).append({
                            'modelPath':old, 'nodePath':f'lods[{lod_index}]/node[{node_index}]',
                            'materials':deepcopy(node.get('materials'))})
            metadata = data.get('metadata', {}) or {}
            profile = source_profile(data, old)
            for block in ('railVehicle','roadVehicle','soundConfig'):
                sound = normalize_sound_set((metadata.get(block) or {}).get('soundSet', {}))
                if sound.get('name'):
                    sound_families.setdefault(source_resource('sound_set', sound['name']), set()).add(profile.family)
        return mod_id+'::/'+(target[:-4] if target.endswith('.lua') else target)

    def resolve_verified(ref: str, kind: str) -> str:
        if isinstance(ref, TranslatedString):
            raise ValueError(f'Localized resource reference requires manual migration: {ref}')
        source_resource(kind, ref)  # Reject unsafe input before looking up local or base assets.
        original_ref = ref
        ref = normalize_reference(ref)
        if original_ref != ref:
            row = {'kind':kind, 'sourceReference':original_ref, 'normalizedReference':ref,
                   'policy':'collapse_repeated_interior_slashes'}
            if row not in migration_audit.setdefault('resourceReferenceNormalizations', []):
                migration_audit['resourceReferenceNormalizations'].append(row)
        if kind == 'texture' and ref in repairs:
            used_repairs.add(ref)
            ref = repairs[ref]
        old = source_resource(kind, ref)
        # Imported base descriptors use their own installed inputs, rather than
        # binding accidentally to an unrelated Workshop author's same path.
        if active_resource in source_game_origins:
            try:
                return base.resolve(kind, ref)
            except ValueError:
                adapted = adapt_source_game(ref, kind, old)
                if adapted is not None:
                    return adapted
                raise
        contextual_matches = None
        installed_path = tf2 is not None and old in tf2.files
        if dependency_context is not None and (dependency_context.owners != [root] or old not in mapping):
            contextual_matches = dependency_context.lookup(ref, kind,
                allow_global=dependency_context.owners != [root] and not installed_path)
            if old in mapping and contextual_matches:
                digest = hashlib.sha256(resource_bytes(old)).hexdigest()
                if digest != contextual_matches[0]['sha256']:
                    raise ValueError(f'Dependency author resource conflicts with an existing export path: {old}')
                if kind not in ('texture','audio','animation') and dependency_context.provider_owners(contextual_matches) != dependency_origins.get(old, [root]):
                    raise ValueError(f'Descriptor path has conflicting dependency author contexts: {old}')
                target = mapping[old]
                dependency_context.record(contextual_matches,
                    mod_id+'::/'+(target[:-4] if target.endswith('.lua') else target),
                    'reuse_identical_resource_in_verified_author_context')
        if old in borrowed_resources:
            return borrowed_resources[old]
        if old in borrowed_sound_sets:
            return borrowed_sound_sets[old]
        if old in inactive_models:
            raise ValueError(f'Model stays archived outside active vehicle content: {old}')
        if old in mapping:
            if vehicle_mode and kind == 'mesh' and old+'.blob' not in mapping:
                # A descriptor cannot supply missing geometry. Keep references
                # external instead of creating an invalid local mesh resource.
                adapted = adapt_source_game(ref, kind, old)
                if adapted is not None:
                    return adapted
                raise ValueError(f'Mesh geometry is unavailable: {old}')
            if old in source_game_origins and kind == 'mesh':
                proof = source_game.resolve(ref, kind)['validation']
                for row in mesh_referrers.get(old, []):
                    if not isinstance(row.get('materials'), list) or len(row['materials']) != proof['submeshCount']:
                        raise ValueError(f'{old}: installed TF2 mesh material slots do not match its model referrer')
            if old not in dependency_sources and kind != 'sound_set' and base.is_borrowed(kind, ref, root/'res'/old):
                try:
                    replacement = base.resolve(kind, ref, bundled=True)
                except ValueError:
                    adapted = adapt_source_game(ref, kind, old)
                    if adapted is not None:
                        return adapted
                    raise
                omitted_borrowed.add(old)
                return replacement
            value = mapping[old]
            return mod_id+'::/'+(value[:-4] if value.endswith('.lua') else value)
        try:
            # The author's exact custom file takes the same precedence as a
            # root-local file. Only proven stock bytes may use a native role.
            if contextual_matches and (tf2 is None or old not in tf2.files
                    or hashlib.sha256(tf2.read(old)).hexdigest() != contextual_matches[0]['sha256']):
                raise ValueError('Use exact resource from the dependency author')
            replacement = base.resolve(kind, ref)
            if contextual_matches == []:
                dependency_context.record_absence(ref, kind)
            elif contextual_matches:
                for match in contextual_matches:
                    package = Path(match['providers'][0]).relative_to(root.parent).parts[0]
                    archive = f"_dependencies/{package}/res/{match['sourceResource']}"
                    dependency_context.archive[archive] = match['data']
                    dependency_context.record([match], None,
                        'verify_stock_provider_selection_for_native_mapping',
                        original_file='_port_originals/'+archive)
            return replacement
        except ValueError:
            matches = contextual_matches if contextual_matches is not None else (
                dependency_context.lookup(ref, kind) if dependency_context is not None else [])
            if not matches and not installed_path and dependency_context is not None:
                matches = dependency_context.lookup(ref, kind)
            stock_match = bool(matches and tf2 is not None and old in tf2.files
                               and hashlib.sha256(tf2.read(old)).hexdigest() == matches[0]['sha256'])
            stock_blob_matches = []
            if stock_match and kind == 'mesh':
                stock_blob_matches = dependency_context.lookup(ref+'.blob', 'mesh_blob',
                    owners=dependency_context.provider_owners(matches))
                provided_blobs = {provider for match in stock_blob_matches for provider in match['providers']}
                if not stock_blob_matches or not all(provider+'.blob' in provided_blobs
                        for match in matches for provider in match['providers']):
                    raise ValueError(f'Workshop stock mesh has no matching provider geometry blob: {ref}')
                stock_match = (old+'.blob' in tf2.files and
                    hashlib.sha256(tf2.read(old+'.blob')).hexdigest() == stock_blob_matches[0]['sha256'])
            if not matches or stock_match:
                adapted = adapt_source_game(ref, kind, old)
                if adapted is not None:
                    if not matches and dependency_context is not None:
                        dependency_context.record_absence(ref, kind)
                    if stock_match:
                        for match in matches+stock_blob_matches:
                            package = Path(match['lookupSource']).name
                            archive = f"_dependencies/{package}/res/{match['sourceResource']}"
                            dependency_context.archive[archive] = match['data']
                            dependency_context.record([match], None,
                                'verify_stock_provider_selection_for_source_game_adaptation',
                                original_file='_port_originals/'+archive)
                    return adapted
                raise
            shared = dict(matches[0])
            shared['providers'] = sorted({provider for match in matches for provider in match['providers']})
            target = ('_dependencies/' + shared['sha256'] + PurePosixPath(ref).suffix.lower()
                      if kind == 'texture' else resource_target(old))
            if kind == 'texture':
                dependency_files[target] = shared['data']
            else:
                if target in mapping.values():
                    raise ValueError(f'Workshop dependency normalized filename collision: {old}')
                mapping[old] = target
                dependency_sources[old] = shared['data']
                dependency_origins[old] = dependency_context.provider_owners(matches)
                if kind == 'sound_set':
                    sound_files.add(old)
                elif kind == 'model':
                    data = resource_table(old)
                    model_data[old] = data
                    for lod_index, lod in enumerate(data.get('lods', [])):
                        for node_index, node in enumerate(flatten(lod['node'])):
                            if node.get('mesh'):
                                mesh_referrers.setdefault(source_resource('mesh', node['mesh']), []).append({
                                    'modelPath':old, 'nodePath':f'lods[{lod_index}]/node[{node_index}]',
                                    'materials':deepcopy(node.get('materials'))})
                    metadata = data.get('metadata', {}) or {}
                    profile = source_profile(data, old)
                    for block in ('railVehicle','roadVehicle','soundConfig'):
                        sound_owner = metadata.get(block) or {}
                        if not isinstance(sound_owner, dict):
                            raise ValueError(f'{old}/metadata/{block}: expected a named table')
                        sound = normalize_sound_set(sound_owner.get('soundSet', {}))
                        if sound.get('name'):
                            sound_families.setdefault(source_resource('sound_set', sound['name']), set()).add(profile.family)
                elif kind == 'mesh':
                    blob_matches = dependency_context.lookup(ref+'.blob', 'mesh_blob',
                                                               owners=dependency_origins[old])
                    if not blob_matches:
                        if vehicle_mode:
                            originals[old] = shared['data']
                            omitted_borrowed.add(old)
                            dependency_context.record(matches, None, 'archive_incomplete_vehicle_mesh_dependency',
                                original_file='_port_originals/res/'+old)
                            warning(migration_audit, 'A mesh dependency without geometry stays archived; its reference remains external.',
                                    resource=old, originalFile='_port_originals/res/'+old)
                            return '::/'+target
                        raise ValueError(f'Workshop mesh has no matching geometry blob: {ref}')
                    blob = dict(blob_matches[0])
                    blob_providers = {provider for match in blob_matches for provider in match['providers']}
                    if not all(provider+'.blob' in blob_providers for provider in shared['providers']):
                        raise ValueError(f'Workshop mesh geometry is not provided by its descriptor packages: {ref}')
                    blob_old = old+'.blob'
                    blob_target = target+'.blob'
                    if blob_target in mapping.values():
                        raise ValueError(f'Workshop dependency normalized filename collision: {blob_old}')
                    mapping[blob_old] = blob_target
                    dependency_sources[blob_old] = blob['data']
                    dependency_origins[blob_old] = dependency_context.provider_owners(blob_matches)
                    dependency_context.record(blob_matches, mod_id+'::/'+blob_target,
                                              'copy_exact_workshop_mesh_geometry')
            reference = mod_id+'::/'+(target[:-4] if target.endswith('.lua') else target)
            dependency_context.record(matches, reference,
                'copy_exact_unambiguous_workshop_texture' if kind == 'texture' else 'port_exact_workshop_resource_dependency')
            return reference
    def resolve(ref: str, kind: str) -> str:
        # Path safety remains mandatory even when unavailable providers are allowed.
        old = source_resource(kind, ref)
        try:
            return resolve_verified(ref, kind)
        except ValueError as exc:
            if not vehicle_mode:
                raise
            target = resource_target(old)
            warning(migration_audit, 'External resource was not confirmed; its reference is retained.',
                    kind=kind, sourceReference=ref, targetReference='::/'+target, reason=str(exc))
            return '::/'+(target[:-4] if target.endswith('.lua') else target)

    for ref, kind, old in unresolved_borrowed:
        if adapt_source_game(ref, kind, old) is None:
            raise ValueError(f'Installed TF2 dependency has no verified adapter: {old}')
    # Translation descriptions often join literal local constants. The shared
    # bounded reader folds those expressions without running source Lua; the
    # language/key/text check below still refuses behavior and helper results.
    keys = set().union(*(v.keys() for v in translations.values())) if translations else set()
    from .shared_metadata_literals import load_mod_metadata
    try:
        raw = load_mod_metadata((root/'mod.lua').read_text(encoding='utf-8-sig'),
            (root/'strings.lua').read_text(encoding='utf-8-sig') if (root/'strings.lua').exists() else None,
            audit=migration_audit)
    except ValueError as exc:
        if not vehicle_mode:
            raise
        raw = load_lua_table((root/'mod.lua').read_text(encoding='utf-8-sig'))
        warning(migration_audit, 'Legacy mod metadata was read as literals without running its behavior.',
                resource='mod.lua', reason=str(exc))
    tree = ast.parse((root/'mod.lua').read_text(encoding='utf-8-sig'))
    reject_unknown(raw, {'info','options','runFn','preRunFn','postRunFn','visible'}, 'mod.lua')
    for callback in ('runFn','preRunFn','postRunFn'):
        if callback in raw:
            fields = [n for n in ast.walk(tree) if isinstance(n,lua.Field) and isinstance(n.key,lua.Name) and n.key.id == callback]
            if len(fields) != 1 or not isinstance(fields[0].value,lua.AnonymousFunction) or fields[0].value.body.body:
                if not vehicle_mode:
                    raise ValueError(f"Non-empty {callback} needs a manual script port")
                warning(migration_audit, 'Vehicle files are exported without the legacy customization callback.',
                        callback=callback, originalFile='_port_originals/mod.lua')
            del raw[callback]
    if raw.get('options'):
        if not vehicle_mode:
            raise ValueError("TF2 options need a manual port")
        warning(migration_audit, 'Legacy mod options remain archived; all supplied vehicle variants are exported.',
                originalFile='_port_originals/mod.lua')
        raw.pop('options')
    info = raw.get('info')
    if not isinstance(info, dict): raise ValueError('mod.lua.info must be a named metadata table')
    if vehicle_mode:
        if info.get('params'):
            warning(migration_audit, 'Legacy selection controls remain archived; all supplied vehicle variants are exported.',
                    originalFile='_port_originals/mod.lua')
            info.pop('params')
        for field in ('dependencies', 'requiredMods', 'incompatibilities'):
            if info.get(field):
                warning(migration_audit, 'A legacy mod requirement does not block this vehicle draft.',
                        field=field, originalFile='_port_originals/mod.lua')
                info.pop(field)
        if revision is None and type(info.get('minorVersion')) is float:
            revision = 1
            warning(migration_audit, 'The separate TF3 draft starts at integer revision 1.',
                    sourceRevision=info['minorVersion'])
    literal(raw)
    if 'visible' in raw:
        visible = raw['visible']
        if type(visible) is not bool: raise ValueError('mod.lua.visible must be a literal boolean')
        if 'visible' in info and (type(info['visible']) is not bool or info['visible'] != visible):
            raise ValueError('Conflicting mod.lua.visible and info.visible require manual migration')
        info['visible'] = visible
        migration_audit.setdefault('metadataMigrations', []).append({
            'field':'visible', 'targetField':'mod.json.visible',
            'sourceValue':visible, 'targetValue':visible,
            'policy':'preserve_literal_mod_visibility', 'nativeTest':'not_run'})
    if isinstance(info.get('url'), list) and len(info['url']) <= 1 and all(isinstance(v,str) for v in info['url']):
        source_url = deepcopy(info['url'])
        info['url'] = source_url[0] if source_url else ''
        migration_audit.setdefault('metadataMigrations', []).append({
            'field':'info.url', 'sourceValue':source_url, 'targetValue':info['url'],
            'policy':'unwrap_empty_or_single_literal_url', 'nativeTest':'not_run'})
    english = translations.get('en', {})
    info['description'] = english.get(info.get('description'), info.get('description',''))
    if not isinstance(info['description'], str): raise ValueError('mod.lua.info.description must be text')
    info['name'], info['description'] = migrate_legacy_display_name(name, info['description'], migration_audit)
    info['modId'] = mod_id
    transformed = {}
    originals.update({old:resource_bytes(old) for old in helper_sources})
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
    def write_sound_script(key, text):
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        relative = f'scripts/_tf3_port/sound_{digest}.script.lua'
        if relative not in transformed:
            save_document(relative, text)
            counts['generatedSoundScripts'] = counts.get('generatedSoundScripts', 0)+1
        elif transformed[relative] != text:
            raise ValueError('Generated sound script hash collision')
        return mod_id+'::/'+relative[:-4]+'@update'
    processed = set()
    while pending := set(mapping)-processed:
        # Dependency models establish mesh material-slot evidence before meshes
        # are adapted. New transitive dependencies join this same work queue.
        old = min(pending, key=lambda value:(not value.endswith('.mdl'), value))
        active_resource = old
        processed.add(old)
        if dependency_context is not None:
            dependency_context.owners = dependency_origins.get(old, [root])
        if old in omitted_borrowed or old in helper_sources:
            continue
        if old in source_game_origins:
            originals[old] = resource_bytes(old)
        p = root/'res'/old
        suffix = p.suffix.lower()
        if old in sound_files:
            base.family = sound_family(old)
            try:
                sound = port_sound_set(resource_bytes(old).decode('utf-8-sig'), resolve, native,
                                                           report=migration_audit, resource=old,
                                                           script_writer=write_sound_script,
                                                           verified_helpers=resource_helpers(old))
            except ValueError as exc:
                if not vehicle_mode:
                    raise
                originals[old] = resource_bytes(old)
                omitted_borrowed.add(old)
                warning(migration_audit, 'A legacy dynamic sound set stays archived; the vehicle export continues with an unresolved sound reference.',
                        resource=old, reason=str(exc), originalFile='_port_originals/res/'+old)
                continue
            transformed[mapping[old]] = emit(sound)
            originals[old] = resource_bytes(old)
            counts['soundSets'] = counts.get('soundSets',0)+1
            continue
        if suffix in ('.lua', '.tl', '.script', '.gs', '.con', '.module', '.trf', '.snd'):
            base.family = None
            target = mapping[old]
            reference = mod_id+'::/'+(target[:-4] if target.endswith('.lua') else target)
            try:
                documents = port_resource(old, resource_bytes(old).decode('utf-8-sig'), resolve, native,
                                               resource_reference=reference, model_bounds=bounds,
                                               translations=set() if old in dependency_origins or old in source_game_origins else keys,
                                               translation_tables=translations, translation_audit=migration_audit,
                                               implicit_translations=old not in dependency_origins and old not in source_game_origins,
                                               verified_helpers=set(resource_helpers(old)),
                                               data_transform=(lambda data: localize_resource(data, old))
                                                   if old in dependency_origins else None)
            except ValueError as exc:
                if not vehicle_mode:
                    raise
                originals[old] = resource_bytes(old)
                omitted_borrowed.add(old)
                warning(migration_audit, 'A legacy behavior resource remains archived outside active vehicle content.',
                        resource=old, reason=str(exc), originalFile='_port_originals/res/'+old)
                continue
            for relative, text in documents.items():
                save_document(relative, text, source_old=old)
            originals[old] = resource_bytes(old)
            kind = classify_resource(old)
            counts[kind] = counts.get(kind, 0)+1
            continue
        if suffix not in ('.mdl','.mtl','.msh','.ani'): continue
        # The prepass already parsed, localized and prepared every model. Keep
        # its immutable input for bounds and copy it for the actual port.
        d = deepcopy(model_data[old]) if suffix == '.mdl' and old in model_data else resource_table(old)
        keys = set().union(*(v.keys() for v in translations.values())) if translations else set()
        emit_keys = set() if old in dependency_origins or old in source_game_origins else keys
        if suffix == '.mdl':
            base.family = source_profile(d, old).family
            signal_construction = None
            if 'signal' in (d.get('metadata') or {}):
                from .signal_port import port_signal
                signal_stem = 'construction/_tf3_signals/'+mapping[old][len('models/model/'):-4]
                signal_reference = mod_id+'::/'+signal_stem+'.con'
                d, signal_construction, signal_script = port_signal(d, mod_id+'::/'+mapping[old],
                    signal_reference, native, report=migration_audit, resource=old)
                save_document(signal_stem+'.script.lua', signal_script)
                counts['generatedSignalConstructions'] = counts.get('generatedSignalConstructions', 0)+1
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
            if vehicle_mode and any(key in (d.get('metadata') or {}) for key in ('railVehicle','roadVehicle','airVehicle','waterVehicle')):
                def empty_hide_targets(value):
                    if isinstance(value, dict):
                        if isinstance(value.get('toHide'), list) and '' in value['toHide']:
                            value['toHide'] = [v for v in value['toHide'] if v != '']
                            warning(migration_audit, 'An empty optional cargo hide target has no node to hide and is omitted.', model=old)
                        for child in value.values():
                            empty_hide_targets(child)
                    elif isinstance(value, list):
                        for child in value:
                            empty_hide_targets(child)
                empty_hide_targets(d.get('metadata', {}).get('transportVehicle', {}))
                def read_source_mesh(reference):
                    resource = source_resource('mesh', reference)
                    if resource not in mapping or resource+'.blob' not in mapping:
                        raise ValueError('TF2 gear mesh and geometry are not present')
                    return resource_table(resource), resource_bytes(resource+'.blob')
                d = source_gear_radii(d, read_source_mesh, report=migration_audit, model_path=old)
                pending_audit = {}
                try:
                    d = port_model(d, resolve, native, model_path=old, report=pending_audit,
                        animation_writer=write_animation, progress=progress,
                        emissions_policy=emissions_policy, vehicle_policy=vehicle_policy)
                except ValueError as exc:
                    transformed[mapping[old]] = compatibility_model(d, resolve, native,
                        model_path=mapping[old], report=migration_audit, emissions_policy=emissions_policy)
                    warning(migration_audit, 'The source vehicle uses native TF2 compatibility rather than donor replacement.',
                            model=old, reason=str(exc))
                    originals[old] = resource_bytes(old)
                    counts['models'] += 1
                    continue
                for key, rows in pending_audit.items():
                    migration_audit.setdefault(key, []).extend(rows)
            else:
                d = port_model(d, resolve, native, model_path=old, report=migration_audit,
                               animation_writer=write_animation, progress=progress,
                               emissions_policy=emissions_policy)
            counts['models'] += 1
            model_path = old[len('models/model/'):-4]
            # TF3 defaults use icons beside each model. Retain the original
            # supplied TF2 thumbnails through explicit metadata references.
            for field, folder, suffix in (
                ('iconSmall','models_small','@2x.tga'),('iconSmallCblend','models_small','_cblend@2x.tga'),
                ('icon20','models_20','@2x.tga'),('icon20cblend','models_20','_cblend@2x.tga'),
                ('icon3d','models_small','@2x.tga')):
                icon = f'textures/ui/{folder}/{model_path}{suffix}'
                if icon in mapping: d['metadata'].setdefault('description', {})[field] = mod_id+'::/'+mapping[icon]
            if signal_construction is not None:
                description = d['metadata'].get('description', {})
                icon = description.get('iconSmall')
                if icon:
                    signal_construction.setdefault('description', {})['icon'] = icon
                save_document(signal_stem+'.con.lua', emit(signal_construction, emit_keys))
        elif suffix == '.mtl':
            d = native.material(d, resolve, report=migration_audit, resource=old, vehicle_mode=vehicle_mode)
            counts['materials'] += 1
        elif suffix == '.msh':
            if old+'.blob' not in mapping:
                if not vehicle_mode: raise ValueError(f"Missing mesh blob: {old}")
                originals[old] = resource_bytes(old)
                omitted_borrowed.add(old)
                warning(migration_audit, ('A referenced mesh descriptor without geometry stays archived; the vehicle uses an external mesh reference.'
                        if mesh_referrers.get(old) else 'An unused mesh descriptor without geometry stays archived outside active vehicle content.'),
                        resource=old, originalFile='_port_originals/res/'+old)
                continue
            from .mesh_port import port_mesh_descriptor
            try:
                migrated = port_mesh_descriptor(d, resolve, mesh_referrers.get(old, []),
                                                report=migration_audit, mesh_path=old,
                                                allow_missing_defaults=vehicle_mode)
            except ValueError as exc:
                if not vehicle_mode or mesh_referrers.get(old): raise
                originals[old] = resource_bytes(old)
                omitted_borrowed.add(old)
                if old+'.blob' in mapping:
                    originals[old+'.blob'] = resource_bytes(old+'.blob')
                    omitted_borrowed.add(old+'.blob')
                warning(migration_audit, 'An unused mesh with unported descriptor fields stays archived; referenced vehicle meshes are retained.',
                        resource=old, originalFile='_port_originals/res/'+old, reason=str(exc))
                continue
            counts['meshes'] += 1
            if migrated == d:
                continue  # Shared index schema: keep unchanged descriptors byte for byte.
            d = migrated  # Rewrite proven material links only; geometry/blob stay intact.
        else:
            counts['animations'] += 1; continue
        originals[old] = resource_bytes(old)
        transformed[mapping[old]] = emit(d, emit_keys)
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
            if old in omitted_borrowed or old in helper_sources:
                continue
            target = normalized/new; target.parent.mkdir(parents=True,exist_ok=True)
            if old in dependency_sources:
                target.write_bytes(dependency_sources[old])
            else:
                shutil.copy2(stage/'content'/old,target)
        content = (stage/'content').resolve()
        if content.parent != stage.resolve() or content.name != 'content':
            raise ValueError('Unsafe staged content path')
        shutil.rmtree(content)
        rename_with_retry(normalized, stage/'content')
        for relative,text in transformed.items():
            target = stage/'content'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text,encoding='utf-8')
        for relative, data in dependency_files.items():
            target = stage/'content'/relative
            if target.exists():
                raise ValueError(f'Workshop dependency filename collision: {relative}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for old,data in originals.items():
            target = stage/'_port_originals/res'/old;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        for relative, data in dependency_context.archive.items() if dependency_context is not None else []:
            target = stage/'_port_originals'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for old in ('mod.lua','strings.lua'):
            if (stage/old).exists():
                target = stage/'_port_originals'/old;target.parent.mkdir(parents=True,exist_ok=True);rename_with_retry(stage/old,target)
        (stage/'mod.lua').write_text(emit({'info':info}),encoding='utf-8')
        (stage/'strings.json').write_text(json.dumps(translations,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (stage/'source-sha256.json').write_text(json.dumps(before,indent=2)+'\n',encoding='utf-8')
        descriptor = prepare_mod(stage, revision=revision)
        if vehicle_mode:
            from .converter import allow_missing_vehicle_dependencies
            allow_missing_vehicle_dependencies(descriptor)
        if descriptor.blockers: raise ValueError('Port validation failed:\n'+'\n'.join(descriptor.blockers[:25]))
        if snapshot(root) != before: raise ValueError("Source changed during porting; export cancelled")
        if not verify_workshop_dependencies(root, migration_audit.get('workshopDependencies', []), dependency_fingerprints):
            raise ValueError('A referenced Workshop dependency changed during conversion; export cancelled')
        if not verify_workshop_absences(root, migration_audit.get('workshopAbsentDependencies', [])):
            raise ValueError('A new authored Workshop dependency appeared during conversion; export cancelled')
        if not verify_native_stock_selections(root, tf3_game, migration_audit.get('workshopDependencies', []),
                                              tf2_game=tf2_path):
            raise ValueError('A native-mapped Workshop input changed its installed TF2 stock identity; export cancelled')
        if not verify_base_resource_identities(root, tf3_game, base.replacements, tf2_game=tf2_path):
            raise ValueError('An installed TF2 input used to select native data changed; export cancelled')
        game_rows = [row for row in source_game.rows if row['sourceResource'][4:] in source_game_aliases] if source_game is not None else []
        game_fingerprints = {row['sourceResource']:row['sha256'] for row in game_rows}
        game_inventory = source_game.inventory_fingerprint() if game_rows else None
        game_installation = str(tf2_path.resolve()) if game_rows else None
        for row in game_rows:
            old = source_game_aliases[row['sourceResource'][4:]]
            target = mapping[old]
            row.update(targetReference=mod_id+'::/'+(target[:-4] if target.endswith('.lua') else target),
                       originalFile='_port_originals/res/'+old,
                       policy='adapt_exact_installed_tf2_resource')
        if not verify_source_game_dependencies(game_installation, game_rows, game_fingerprints, game_inventory):
            raise ValueError('Referenced installed TF2 resources changed during conversion; export cancelled')
        def verify_native_publication():
            if not native.verify_current(native_inventory_start, port_report['nativeResourceFingerprints']):
                raise ValueError('Installed TF3 resources or mounts changed during conversion; export cancelled')
        profiles = {row['profile'] for row in migration_audit.get('vehicleProfiles', [])}
        port_profile = 'tf2_electric_locomotive' if profiles == {'tf2_train_electric'} else 'tf2_verified_resource_profiles'
        port_report = dict(source=str(root), portProfile=port_profile, sourceUnchanged=True,
                  displayName=name,
                  portCounts=counts, pathMapping={old:new for old,new in mapping.items()
                                                if old not in omitted_borrowed and old not in helper_sources}, explicitRepairs=repairs,
                  baseGameResources=sorted(native.references), nativeTest='not_run',
                  nativeResourceFingerprints=dict(native.dependencies),
                  nativeInventoryFingerprint=native_inventory_start,
                  workshopResourceFingerprints=dict(dependency_fingerprints),
                  workshopAbsentDependencies=migration_audit.get('workshopAbsentDependencies', []),
                  sourceGameDependencies=game_rows,
                  sourceGameResourceFingerprints=game_fingerprints,
                  sourceGameInventoryFingerprint=game_inventory,
                  sourceGameInstallation=game_installation,
                  baseResourceReplacements=base.replacements, omittedBorrowedResources=sorted(omitted_borrowed),
                  tf2BaseInventory=str(tf2_path) if tf2_path is not None else None,
                  migrationAudit=migration_audit, capabilities=capability_report(mapping),
                  conversionChoices=choices,
                  cargoPolicy='same_verified_class_where_representable',
                  limitations=['Known literal vehicle/render/config/constant-asset profiles; arbitrary TF2 scripts and dynamic API behavior require manual migration.',
                               'Appearance, animation, audio, purchasing and operation require native TF3 verification.',
                               'The store preview reuses the original small thumbnail; it is not a newly rendered 3D store image.',
                               'Missing default metal/gloss/AO uses the installed TF3 default.',
                               {'strict': 'Automatic legacy emissions use TF3 automatic noise and pollution; authored coefficients require an explicit choice.',
                                'legacy_noise': 'Explicit legacy noise coefficients are retained where representable; TF3 calculates pollution.',
                                'tf3_automatic': 'The selected policy lets TF3 calculate noise and pollution; authored legacy coefficients remain archived.',
                                'class_average': 'Noise and pollution use separate arithmetic means from installed TF3 vehicles in the same class.'}[emissions_policy],
                               'Original changed resource text is retained in _port_originals; source files are untouched.'])
        report = convert_mod(stage,destination,overwrite=overwrite,progress=notify,
                             author=author,revision=revision,summary=summary,_report_fields=port_report,
                             _before_publish=verify_native_publication, _allow_missing_resources=vehicle_mode)
    return report

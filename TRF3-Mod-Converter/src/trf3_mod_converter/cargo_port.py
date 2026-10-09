"""Static TF2 compartment migration using the selected TF3 installation.

The TF3 cargo and vehicle schemas are documented at
https://wiki.transportfever3.com/doku.php?id=modding:misc:cargo and
https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mdl.
TF2 cargoEntries/cargoSlotProvider are documented at
https://wiki.transportfever2.com/doku.php?id=modding:vehiclebasics and
https://wiki.transportfever2.com/doku.php?id=modding:vehicleadvancedtopics.
This module is independently authored; no mod or native Lua is executed.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import re
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from .lua_metadata import TranslatedString, UnsupportedValue, load_lua_table


SPECIFIC_FREIGHT_CLASSES = frozenset({'BULK', 'LIQUID', 'GOODS', 'FLATBED'})
# These are semantic migration choices, not interchangeable TF2 resource IDs.
# TF2 FOOD/GOODS/OIL describe broader categories than an individual TF3 cargo.
LEGACY_FAMILIES = {
    'FOOD': ('fish', 'meat', 'tinned_food', 'vegetables'),
    'CONSTRUCTION_MATERIALS': ('bricks',),
    'CRUDE': ('crude_oil',),
}
LEGACY_CLASSES = {'GOODS': 'GOODS', 'OIL': 'LIQUID'}


def _literal(value: Any, where: str) -> None:
    if isinstance(value, UnsupportedValue):
        raise ValueError(f'{where}: {value.reason}')
    if isinstance(value, dict):
        for key, item in value.items():
            _literal(item, f'{where}/{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _literal(item, f'{where}/{index}')


def _dict(value: Any, where: str) -> dict:
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'{where} must be a literal named table')
    return value


def _list(value: Any, where: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f'{where} must be a literal list')
    return value


def _unknown(data: dict, allowed: set[str], where: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise ValueError(f'Unsupported {where} fields (preserved in source): {sorted(extra)}')


def _number(value: Any, where: str, *, integer: bool = False) -> int | float:
    if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
            or (integer and value != int(value))):
        raise ValueError(f'{where} must be a finite non-negative {"integer" if integer else "number"}')
    return value


@dataclass(frozen=True)
class CargoType:
    key: str
    path: str
    classes: frozenset[str]
    weight_factor: float = 1.0


class CargoCatalog:
    """Verified installed resources; share this read-only catalog between models.

    ``aliases`` provides explicit mappings for custom TF2 IDs when a human has
    verified equivalent installed TF3 cargo types. Values are catalog keys.
    """

    def __init__(self, types: Mapping[str, CargoType], *, classes: Mapping[str, str],
                 formats: Mapping[str, str], native=None,
                 aliases: Mapping[str, list[str]] | None = None, resource_dependencies=None):
        self.types = dict(types)
        self.classes = dict(classes)
        self.formats = dict(formats)
        self.native = native
        self.aliases = dict(aliases or {})
        self.resource_dependencies = dict(resource_dependencies or {})
        if self.resource_dependencies and hasattr(native, 'track_dependencies'):
            native.track_dependencies(self.resource_dependencies)
        self._paths = {entry.path: entry.key for entry in self.types.values()}
        for key, entry in self.types.items():
            if key != entry.key or not entry.classes or entry.classes - self.classes.keys():
                raise ValueError(f'Invalid installed cargo classes for {key}')
        for alias, targets in self.aliases.items():
            if not targets or any(key not in self.types for key in targets):
                raise ValueError(f'Custom cargo mapping {alias!r} needs verified installed cargo keys')

    @classmethod
    def from_native(cls, native, *, aliases=None):
        """Read loose/zipped resources through NativeInventory, never copy them."""
        types, classes, formats, dependencies = {}, {}, {}, []
        for path in sorted(native.files):
            if not path.endswith(('.cargo.lua', '.cargoclass.lua', '.cmf.lua')):
                continue
            dependencies.append(path)
            data = load_lua_table(native.read(path).decode('utf-8-sig'), constant_numbers=True)
            resource = path[:-4]
            if path.endswith('.cargo.lua'):
                key = PurePosixPath(path).name[:-len('.cargo.lua')]
                cargo_classes = _list(data.get('cargoClasses'), f'{path}/cargoClasses')
                if not cargo_classes or any(not isinstance(tag, str) for tag in cargo_classes):
                    raise ValueError(f'Installed cargo {path} has invalid classes')
                factor = _number(data.get('weightFactor', 1), f'{path}/weightFactor')
                if key in types:
                    raise ValueError(f'Ambiguous installed cargo key {key!r}; use unique definitions')
                types[key] = CargoType(key, resource, frozenset(cargo_classes), factor)
            else:
                tag = data.get('tag')
                if not isinstance(tag, str) or not tag:
                    raise ValueError(f'Installed cargo definition {path} has no literal tag')
                target = classes if path.endswith('.cargoclass.lua') else formats
                if tag in target:
                    raise ValueError(f'Ambiguous installed cargo tag {tag!r}')
                target[tag] = resource
        if not types:
            raise ValueError('Selected TF3 installation has no verified cargo definitions')
        fingerprints = native.fingerprints(dependencies) if hasattr(native, 'fingerprints') else {}
        return cls(types, classes=classes, formats=formats, native=native, aliases=aliases,
                   resource_dependencies=fingerprints)

    def reference(self, key: str) -> str:
        entry = self.types[key]
        # NativeInventory.reference currently supports the original .snd/.trf
        # suffixes; cargo schemas are verified here before registering the URI.
        if self.native is not None:
            self.native.read(entry.path + '.lua')
            references = getattr(self.native, 'references', None)
            if references is not None:
                references.add(entry.path)
        return '::/' + entry.path

    def class_types(self, tag: str) -> set[str]:
        if tag not in self.classes:
            raise ValueError(f'Cargo class {tag!r} is absent from the selected TF3 installation')
        return {key for key, value in self.types.items() if tag in value.classes}

    def keys(self, old_type: Any) -> tuple[set[str], str]:
        if not isinstance(old_type, str) or not old_type:
            raise ValueError('Cargo entry requires a literal cargo type; no class can be inferred from a vehicle name')
        if old_type in self.aliases:
            return set(self.aliases[old_type]), 'explicit custom cargo mapping'
        if old_type in LEGACY_CLASSES:
            return self.class_types(LEGACY_CLASSES[old_type]), f'legacy category {old_type} -> {LEGACY_CLASSES[old_type]}'
        if old_type in LEGACY_FAMILIES:
            keys = set(LEGACY_FAMILIES[old_type]) & self.types.keys()
            if not keys:
                raise ValueError(f'TF2 cargo {old_type!r} has no verified TF3 equivalent in this installation')
            return keys, f'legacy category mapping {old_type}'
        path = old_type.removeprefix('::/')
        if path in self._paths:
            return {self._paths[path]}, 'installed resource reference'
        key = old_type.lower().removesuffix('.cargo')
        if key in self.types:
            return {key}, 'same cargo identifier'
        raise ValueError(f'Unknown/custom TF2 cargo {old_type!r}; provide an explicit verified TF3 cargo mapping')

    def evaluate_set(self, data: dict) -> tuple[set[str], dict, set[str], set[str]]:
        """Apply TF3's ordered class/type filters without registering references.

        Explicit types can restore members removed by a class exclusion. Only
        the final type exclusions remove those explicitly restored members.
        Donor matching and export must use exactly the same eligibility rule.
        """
        data = _dict(data, 'cargoTypeSet')
        allowed = {'cargoClassesIncluded', 'cargoClassesExcluded', 'cargoTypesIncluded', 'cargoTypesExcluded'}
        _unknown(data, allowed, 'cargoTypeSet')
        normalized = {field: _list(deepcopy(data.get(field, [])), f'cargoTypeSet/{field}') for field in allowed}
        for field, tokens in normalized.items():
            if any(not isinstance(token, str) or not token or isinstance(token, TranslatedString) for token in tokens):
                raise ValueError(f'cargoTypeSet/{field}: requires non-localized literal cargo identifiers')
        keys, excluded_classes, excluded_keys = set(), set(), set()
        for tag in normalized['cargoClassesIncluded']:
            keys.update(self.class_types(tag))
        for tag in normalized['cargoClassesExcluded']:
            excluded_classes.add(tag)
            keys.difference_update(self.class_types(tag))
        for token in normalized['cargoTypesIncluded']:
            selected, _ = self.keys(token)
            keys.update(selected)
        for token in normalized['cargoTypesExcluded']:
            selected, _ = self.keys(token)
            excluded_keys.update(selected)
            keys.difference_update(selected)
        return keys, normalized, excluded_classes, excluded_keys

    def resolve_set(self, data: dict) -> tuple[set[str], dict, set[str], set[str]]:
        keys, normalized, excluded_classes, excluded_keys = self.evaluate_set(data)
        # Retain exclusions and their ordering semantics; canonical references
        # prevent relative cargo paths from resolving beside the vehicle.
        for field in ('cargoTypesIncluded', 'cargoTypesExcluded'):
            normalized[field] = list(dict.fromkeys(self.reference(key) for token in normalized[field]
                                                   for key in sorted(self.keys(token)[0])))
        return keys, normalized, excluded_classes, excluded_keys


def _node_names(nodes, reference: Any, where: str, *, multiple: bool = False) -> list[str]:
    if nodes is None:
        raise ValueError(f'{where} needs a verified model node map')
    if isinstance(nodes, dict):
        value = nodes.get(reference)
        names = value if isinstance(value, list) else [value] if value is not None else []
    else:
        values = nodes[0] if nodes and isinstance(nodes[0], list) else nodes
        if type(reference) is int:
            if reference < 0 or reference >= len(values):
                raise ValueError(f'{where}: invalid node index {reference}')
            node = values[reference]
            names = [node if isinstance(node, str) else node.get('name')]
        elif isinstance(reference, str):
            names = [node if isinstance(node, str) else node.get('name') for node in values
                     if reference == (node if isinstance(node, str) else node.get('name'))
                     or isinstance(node, dict) and reference in (node.get('mesh'), node.get('_source_mesh'))]
        else:
            names = []
    names = list(dict.fromkeys(names))
    if not names or any(not isinstance(name, str) or not name for name in names):
        raise ValueError(f'{where}: missing node {reference!r}')
    if not multiple and len(names) != 1:
        raise ValueError(f'{where}: ambiguous node {reference!r}')
    return names


def _source_compartments(transport: dict) -> tuple[list[dict], str]:
    populated = [field for field in ('compartmentsList', 'compartments', 'capacities') if transport.get(field)]
    if len(populated) > 1:
        raise ValueError('Conflicting TF2 compartment/capacity schemas need review')
    field = populated[0] if populated else next((f for f in ('compartmentsList', 'compartments', 'capacities') if f in transport), 'compartmentsList')
    entries = _list(transport.get(field, []), field)
    if field == 'compartmentsList':
        return entries, field
    if field == 'capacities':
        return ([{'loadConfigs': [{'cargoEntries': [entry]} for entry in entries]}] if entries else []), field
    if all(isinstance(entry, dict) and 'loadConfigs' in entry for entry in entries):
        return entries, field
    return [{'loadConfigs': [{'cargoEntries': _list(config, f'{field}/{ci}/{li}')} for li, config in enumerate(_list(compartment, f'{field}/{ci}'))]}
            for ci, compartment in enumerate(entries)], field


def port_compartments(transport_vehicle: dict, *, catalog: CargoCatalog | None = None,
                      native=None, nodes=None, resolve: Callable | None = None,
                      expand_classes: bool = True, cargo_slot_provider=None,
                      seat_count: int | None = None, allow_unverified_types: bool = False,
                      allow_legacy_layouts: bool = False) -> tuple[dict, dict, dict]:
    """Return ``(transportVehicle, metadata additions, cargo audit)``.

    Pass flattened original nodes with their final ``name`` and original ``mesh``
    (or a reference-to-name map). Numeric TF2 node and seat indices are zero
    based. ``resolve(path, 'model')`` migrates authored slot models. A native
    catalog is required only when a nonempty cargo entry is actually present.
    No source dictionary is mutated, and unsupported layouts raise before any
    export can be published. Expansion appends alternatives with verified generic
    visuals; unrepresentable inferred alternatives are audited and withheld.
    Original capacities, cargo mappings and load configurations remain intact.
    """
    _literal(transport_vehicle, 'transportVehicle')
    result = deepcopy(transport_vehicle)
    source_compartments, source_schema = _source_compartments(result)
    provider = _dict(cargo_slot_provider or {}, 'cargoSlotProvider')
    _literal(provider, 'cargoSlotProvider')
    _unknown(provider, {'slots'}, 'cargoSlotProvider')
    slots = []
    for index, source_slot in enumerate(_list(provider.get('slots', []), 'cargoSlotProvider/slots')):
        slot = deepcopy(_dict(source_slot, f'cargoSlotProvider/slots/{index}'))
        _unknown(slot, {'group', 'models', 'randomId', 'transf'}, 'cargo slot')
        slot['group'] = _node_names(nodes, slot.get('group'), 'cargo slot/group')[0]
        matrix = _list(slot.get('transf'), 'cargo slot/transf')
        if len(matrix) != 16 or any(type(v) not in (int, float) or not math.isfinite(v) for v in matrix):
            raise ValueError('Cargo slot transf requires 16 finite numbers')
        models = _list(slot.get('models'), 'cargo slot/models')
        if not models:
            raise ValueError('Cargo slot models must not be empty')
        migrated = []
        for model in models:
            if not isinstance(model, str):
                raise ValueError('Cargo slot model must be a literal resource reference')
            if model.startswith('#'):
                if catalog is None and native is not None:
                    catalog = CargoCatalog.from_native(native)
                if catalog is None or model[1:] not in catalog.formats:
                    raise ValueError(f'Cargo model format {model!r} is absent from selected TF3 installation')
                migrated.append(model)
            elif resolve is not None:
                migrated.append(resolve(model, 'model'))
            else:
                raise ValueError(f'Cargo slot model {model!r} needs a verified resource resolver')
        slot['models'] = migrated
        slots.append(slot)
    indicators, compartments, audit = {}, [], {
        'sourceSchema': source_schema, 'policy': 'same_verified_class' if expand_classes else 'preserve_types',
        'entries': [], 'additions': [], 'warnings': [], 'maxCapacity': 0,
        'nativeTest': 'not_run',
    }

    def get_catalog() -> CargoCatalog:
        nonlocal catalog
        if catalog is None and native is not None:
            catalog = CargoCatalog.from_native(native)
        if catalog is None:
            raise ValueError('Cargo export requires the selected TF3 installation and verified cargo definitions')
        return catalog

    def migrate_entry(entry, ci, li, ei):
        entry = deepcopy(_dict(entry, 'cargoEntry'))
        if 'toHide' in entry and entry['toHide'] in ([], {}):
            audit.setdefault('normalizations', []).append({
                'compartment': ci, 'loadConfig': li, 'entry': ei, 'field': 'cargoEntry.toHide',
                'sourceValue': deepcopy(entry.pop('toHide')),
                'policy': 'omit_empty_entry_visibility_list', 'nativeTest': 'not_run'})
        _unknown(entry, {'type', 'capacity', 'seats', 'cargoBay', 'customCargoModels', 'cargoTypeSet', 'loadIndicator'}, 'cargoEntry')
        capacity = _number(entry.get('capacity', 0), 'cargoEntry/capacity')
        seats = _list(deepcopy(entry.get('seats', [])), 'cargoEntry/seats')
        for seat in seats:
            _number(seat, 'cargoEntry/seat', integer=True)
            if seat_count is not None and seat >= seat_count:
                raise ValueError(f'Invalid cargo seat index {seat}')
        if 'type' in entry and 'cargoTypeSet' in entry:
            raise ValueError('Cargo entry mixes TF2 type and TF3 cargoTypeSet')
        restrictions, excluded_classes, excluded_keys = None, set(), set()
        external = None
        if 'cargoTypeSet' in entry:
            c = get_catalog()
            keys, restrictions, excluded_classes, excluded_keys = c.resolve_set(entry['cargoTypeSet'])
            reason = 'existing cargo type set'
        elif entry.get('type') is not None:
            try:
                keys, reason = get_catalog().keys(entry['type'])
            except ValueError:
                token = entry['type']
                if not allow_unverified_types or type(token) is not str or not re.fullmatch(r'[A-Za-z0-9_]+', token):
                    raise
                keys, reason = set(), 'unverified external TF2 cargo retained without substitution'
                external = '::/cargos/'+token.lower()+'/'+token.lower()+'.cargo'
                audit.setdefault('unverifiedCargoTypes', []).append({'sourceType':token, 'reference':external,
                    'capacity':capacity, 'nativeTest':'not_run'})
        elif capacity == 0 and not seats:
            keys, reason = set(), 'empty locomotive compartment'
        else:
            raise ValueError('A nonempty cargo compartment has no type; refusing to infer it from vehicle names')
        if capacity and not keys and external is None:
            raise ValueError('Nonempty cargo compartment has an empty verified cargo type set')
        if keys and seats and any('PASSENGERS' not in get_catalog().types[key].classes for key in keys):
            raise ValueError('Passenger seats assigned to a freight-only cargo entry need review')
        target = {'capacity': capacity, 'cargoTypeSet': restrictions or {
            'cargoClassesIncluded': [], 'cargoClassesExcluded': [],
            'cargoTypesIncluded': [external] if external else [get_catalog().reference(key) for key in sorted(keys)],
            'cargoTypesExcluded': [],
        }, 'loadIndicator': entry.get('loadIndicator', ''), 'seats': seats}
        indicator = {}
        bay = entry.get('cargoBay')
        if bay:
            if target['loadIndicator']:
                raise ValueError('Existing and legacy load indicators cannot be combined implicitly')
            bay = deepcopy(_dict(bay, 'cargoBay'))
            _unknown(bay, {'bbMin', 'bbMax', 'cargoFormat', 'cargoFormats', 'childId', 'gridSize', 'sizePolicy', 'type'}, 'cargoBay')
            for field in ('bbMin', 'bbMax'):
                values = _list(bay.get(field), f'cargoBay/{field}')
                if len(values) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                    raise ValueError(f'cargoBay/{field} needs three finite numbers')
            if any(lo >= hi for lo, hi in zip(bay['bbMin'], bay['bbMax'])):
                raise ValueError('Cargo bay has an inverted or empty bounding box')
            bay['childId'] = _node_names(nodes, bay.get('childId', 0), 'cargoBay/childId')[0]
            if 'cargoFormats' in bay and 'cargoFormat' in bay:
                raise ValueError('Cargo bay mixes old and new cargo format fields')
            cargo_format = bay.pop('cargoFormat', None)
            default_formats = ['MEDIUM4x1', 'MEDIUM2x1'] if bay.get('type') == 'LEVEL' else ['BIG', 'SMALL']
            bay['cargoFormats'] = _list(bay.get('cargoFormats', [cargo_format] if cargo_format else default_formats), 'cargoBay/cargoFormats')
            for tag in bay['cargoFormats']:
                if tag not in get_catalog().formats:
                    raise ValueError(f'Cargo bay format {tag!r} is absent from selected TF3 installation')
            if bay.get('type', 'DISCRETE') not in ('DISCRETE', 'LEVEL'):
                raise ValueError(f'Unsupported cargo bay type {bay["type"]!r}')
            if bay.get('sizePolicy') not in (None, '', 'STRETCH', 'STRETCH_HEIGHT_SCALEY', 'STRETCH_HEIGHT_NONE', 'BEST_FIT'):
                if not allow_legacy_layouts or type(bay['sizePolicy']) is not str:
                    raise ValueError('Unsupported cargo bay scaling policy')
                audit.setdefault('legacyScalingPolicies', []).append({'value':bay['sizePolicy'],
                    'policy':'preserve_literal_native_default_scaling', 'nativeTest':'not_run'})
            grid = _list(bay.get('gridSize', []), 'cargoBay/gridSize')
            if len(grid) > 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in grid):
                raise ValueError('Cargo bay gridSize needs up to three finite numbers')
            indicator['cargoBay'] = bay
        custom = entry.get('customCargoModels')
        if custom:
            if target['loadIndicator']:
                raise ValueError('Existing and legacy load indicators cannot be combined implicitly')
            custom = _dict(custom, 'customCargoModels')
            _unknown(custom, {'configurations'}, 'customCargoModels')
            configs = []
            for config in _list(custom.get('configurations'), 'customCargoModels/configurations'):
                config = _dict(config, 'customCargoModels/configuration')
                _unknown(config, {'slotLevels'}, 'customCargoModels/configuration')
                levels = deepcopy(_list(config.get('slotLevels'), 'customCargoModels/slotLevels'))
                for level in levels:
                    for index in _list(level, 'customCargoModels/slotLevel'):
                        if type(index) is not int or not 0 <= index < len(slots):
                            raise ValueError(f'Invalid cargo slot index {index}')
                configs.append(levels)
            if not configs:
                raise ValueError('Custom cargo models need at least one slot configuration')
            if 'cargoBay' in indicator:
                raise ValueError('Combined TF2 cargoBay and customCargoModels require a verified TF3 indicator layout; neither visual system was discarded')
            indicator['cargoSlots'] = {'configurations': configs}
        if indicator:
            name = f'tf2_cargo_{ci}_{li}_{ei}'
            indicators[name] = indicator
            target['loadIndicator'] = name
        record = {'compartment': ci, 'loadConfig': li, 'entry': ei, 'sourceType': entry.get('type'),
                  'cargoTypes': sorted(keys), 'capacity': capacity, 'mapping': reason}
        if keys:
            record['nativeEvidence'] = {
                key: {'definition': get_catalog().types[key].path + '.lua',
                      'cargoClasses': sorted(get_catalog().types[key].classes)}
                for key in sorted(keys)
            }
        audit['entries'].append(record)
        return target, keys, excluded_classes, excluded_keys, record

    for ci, source_compartment in enumerate(source_compartments):
        source_compartment = _dict(source_compartment, 'compartment')
        _unknown(source_compartment, {'loadConfigs'}, 'compartment')
        loads = _list(source_compartment.get('loadConfigs', []), 'compartment/loadConfigs')
        converted, records = [], []
        for li, source_load in enumerate(loads):
            source_load = _dict(source_load, 'loadConfig')
            _unknown(source_load, {'cargoEntries', 'cargoEntry', 'toHide'}, 'loadConfig')
            if 'cargoEntries' in source_load and 'cargoEntry' in source_load:
                raise ValueError('Load configuration mixes cargoEntries and cargoEntry')
            entries = ([source_load['cargoEntry']] if 'cargoEntry' in source_load else
                       _list(source_load.get('cargoEntries', []), 'loadConfig/cargoEntries'))
            hidden = []
            for token in _list(source_load.get('toHide', []), 'loadConfig/toHide'):
                hidden.extend(_node_names(nodes, token, 'loadConfig/toHide', multiple=True))
            hidden = list(dict.fromkeys(hidden))
            if len(entries) > 1:
                # Independent native compartments preserve a single fixed mixed
                # load. Alternatives with coupled capacities cannot be modeled
                # by one native cargoEntry without changing the load rules.
                if len(loads) != 1:
                    raise ValueError('Coupled mixed-cargo alternatives require a TF3 load-layout adaptation; no capacities were discarded')
                audit['warnings'].append(f'Compartment {ci}: fixed mixed load split into independent compartments; class expansion withheld to retain cargo restrictions')
                for ei, entry in enumerate(entries):
                    target, keys, _, _, _ = migrate_entry(entry, ci, li, ei)
                    compartments.append({'loadConfigs': [{'cargoEntry': target, 'toHide': deepcopy(hidden)}]})
                    audit['maxCapacity'] += target['capacity']
                continue
            target, keys, excluded_classes, excluded_keys, record = migrate_entry(entries[0] if entries else {}, ci, li, 0)
            converted.append({'cargoEntry': target, 'toHide': hidden})
            records.append((keys, excluded_classes, excluded_keys, record))
        if not converted:
            if not loads:
                compartments.append({'loadConfigs': []})
            continue
        if expand_classes:
            already = set().union(*(r[0] for r in records))
            templates = list(zip(list(converted), records))

            def generic_visual(template):
                name = template['cargoEntry']['loadIndicator']
                if not name:
                    return True
                indicator = indicators.get(name)
                if indicator is None:
                    return False
                if 'cargoBay' in indicator:
                    return True
                indices = {index for levels in indicator['cargoSlots']['configurations']
                           for level in levels for index in level}
                return all(all(model.startswith('#') for model in slots[index]['models']) for index in indices)

            # A generic template can represent new class members faithfully;
            # fixed authored loads are retained exclusively for their originals.
            templates.sort(key=lambda pair: not generic_visual(pair[0]))
            unavailable = set()
            for template, (keys, excluded_classes, excluded_keys, record) in templates:
                if not keys or template['cargoEntry']['capacity'] == 0:
                    continue
                c = get_catalog()
                classes = set().union(*(c.types[key].classes for key in keys)) & SPECIFIC_FREIGHT_CLASSES
                classes.difference_update(excluded_classes)
                for tag in sorted(classes):
                    for key in sorted(c.class_types(tag) - already - excluded_keys):
                        if c.types[key].classes & excluded_classes:
                            continue
                        if not generic_visual(template):
                            unavailable.add(key)
                            continue
                        added = deepcopy(template)
                        # Explicit exclusions remain on the added alternative.
                        added['cargoEntry']['cargoTypeSet'] = {
                            'cargoClassesIncluded': [],
                            'cargoClassesExcluded': sorted(excluded_classes),
                            'cargoTypesIncluded': [c.reference(key)],
                            'cargoTypesExcluded': [c.reference(k) for k in sorted(excluded_keys)],
                        }
                        converted.append(added)
                        already.add(key)
                        audit['additions'].append({
                            'compartment': ci, 'templateLoadConfig': record['loadConfig'],
                            'cargoType': key, 'cargoClass': tag, 'capacity': added['cargoEntry']['capacity'],
                            'evidence': c.types[key].path + '.lua',
                            'inferredFrom': record['cargoTypes'], 'nativeTest': 'not_run',
                        })
            omitted = sorted(unavailable - already)
            if omitted:
                audit['policy'] = 'same_verified_class_where_representable'
                for key in omitted:
                    audit.setdefault('omittedInferredExpansions', []).append({
                        'compartment': ci, 'cargoType': key,
                        'cargoClasses': sorted(c.types[key].classes & SPECIFIC_FREIGHT_CLASSES),
                        'evidence': c.types[key].path + '.lua',
                        'reason': 'no_verified_generic_visual_template',
                        'policy': 'preserve_authored_cargo_coverage', 'nativeTest': 'not_run',
                    })
                audit['warnings'].append(
                    f'Compartment {ci}: inferred cargo alternatives withheld because no verified generic visual exists; '
                    'all authored cargo types, capacities and visuals retained: ' + ', '.join(omitted))
        compartments.append({'loadConfigs': converted})
        audit['maxCapacity'] += max((load['cargoEntry']['capacity'] for load in converted), default=0)
    for field in ('compartmentsList', 'compartments', 'capacities'):
        result.pop(field, None)
    result['compartments'] = compartments
    additions = {'loadIndicator': {'configs': indicators, 'slots': slots}} if indicators or slots else {}
    audit['cargoTypes'] = sorted(set().union(*(set(r['cargoTypes']) for r in audit['entries']),
                                            {r['cargoType'] for r in audit['additions']}))
    return result, additions, audit

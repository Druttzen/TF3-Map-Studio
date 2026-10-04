"""Complete absent cargo capacities from a selected, verified TF3 model.

Only literal capacities are donated. Source cargo identities, seats, visual
definitions and compartment layout remain authoritative. No Lua is executed and
no capacity is inferred from a vehicle name, seat count or bounding box.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any

from .cargo_port import CargoCatalog, SPECIFIC_FREIGHT_CLASSES
from .lua_metadata import TranslatedString


@dataclass
class _Entry:
    value: dict
    path: str

    @property
    def missing(self) -> bool:
        return ('type' in self.value or 'cargoTypeSet' in self.value) and self.value.get('capacity') is None


def _named(value, path: str) -> dict:
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected a literal named table')
    return value


def _list(value, path: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f'{path}: expected a literal list')
    return value


def _capacity(value, path: str) -> int | float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{path}: capacity must be a finite non-negative number; invalid supplied data cannot be replaced')
    return value


def _source_slots(model: dict) -> list[list[_Entry]]:
    metadata = _named(model.get('metadata', {}), 'metadata')
    transport = _named(metadata.get('transportVehicle', {}), 'metadata/transportVehicle')
    populated = [key for key in ('compartmentsList', 'compartments', 'capacities') if transport.get(key)]
    if len(populated) > 1:
        raise ValueError('Conflicting TF2 compartment/capacity schemas need review before donor completion')
    field = populated[0] if populated else next((key for key in ('compartmentsList', 'compartments', 'capacities')
                                                if key in transport), 'compartmentsList')
    values = _list(transport.get(field, []), f'metadata/transportVehicle/{field}')
    base = f'metadata/transportVehicle/{field}'
    if field == 'capacities':
        return [[_Entry(_named(entry, f'{base}/{index}'), f'{base}/{index}')
                 for index, entry in enumerate(values)]] if values else []
    slots = []
    for ci, compartment in enumerate(values):
        cp = f'{base}/{ci}'
        if isinstance(compartment, dict):
            loads = _list(compartment.get('loadConfigs', []), f'{cp}/loadConfigs')
            configs = []
            for li, load in enumerate(loads):
                lp = f'{cp}/loadConfigs/{li}'
                load = _named(load, lp)
                if 'cargoEntries' in load and 'cargoEntry' in load:
                    raise ValueError(f'{lp}: conflicting cargoEntry/cargoEntries fields')
                if 'cargoEntry' in load:
                    configs.append([_Entry(_named(load['cargoEntry'], f'{lp}/cargoEntry'), f'{lp}/cargoEntry')])
                else:
                    entries = _list(load.get('cargoEntries', []), f'{lp}/cargoEntries')
                    configs.append([_Entry(_named(entry, f'{lp}/cargoEntries/{ei}'), f'{lp}/cargoEntries/{ei}')
                                    for ei, entry in enumerate(entries)])
        else:
            loads = _list(compartment, cp)
            configs = [[_Entry(_named(entry, f'{cp}/{li}/{ei}'), f'{cp}/{li}/{ei}')
                        for ei, entry in enumerate(_list(config, f'{cp}/{li}'))]
                       for li, config in enumerate(loads)]
        if any(len(config) > 1 for config in configs):
            if len(configs) != 1:
                raise ValueError(f'{cp}: coupled mixed-cargo alternatives cannot borrow capacities safely')
            # The existing cargo exporter splits a single fixed mixed load into
            # independent native compartments. Preserve the original nesting.
            slots.extend([[entry] for entry in configs[0]])
        else:
            slots.append([entry for config in configs for entry in config])
    return slots


def missing_cargo_requirements(source_model: dict) -> tuple[str, ...]:
    """Native capacity/layout policy, excluding unrelated donor visual bindings."""
    return ('nativeCargoCapacityPolicy',) if any(entry.missing for slot in _source_slots(source_model)
                                               for entry in slot) else ()


def validate_source_cargo_identifiers(source_model: dict) -> None:
    """Reject locale-dependent cargo identities in each supported source layout.

    Inspect only actual cargo entries and their type-set fields. Display names
    and visual metadata may contain translations without defining cargo roles.
    """
    for slot in _source_slots(source_model):
        for entry in slot:
            for field in ('type', 'cargoType'):
                if isinstance(entry.value.get(field), TranslatedString):
                    raise ValueError(f'{entry.path}/{field}: localized cargo identifiers cannot establish cargo compatibility')
            if 'cargoTypeSet' not in entry.value:
                continue
            config = _named(entry.value['cargoTypeSet'], f'{entry.path}/cargoTypeSet')
            for field in ('cargoClassesIncluded', 'cargoClassesExcluded', 'cargoTypesIncluded', 'cargoTypesExcluded'):
                for token in _list(config.get(field, []), f'{entry.path}/cargoTypeSet/{field}'):
                    if isinstance(token, TranslatedString):
                        raise ValueError(f'{entry.path}/cargoTypeSet/{field}: localized cargo identifiers cannot establish cargo compatibility')


def has_payload_declaration(source_model: dict) -> bool:
    """Read active typed cargo entries without mistaking visual ``type`` fields.

    Empty type sets on native locomotive placeholders declare no payload, even
    when their inactive capacity is positive. Missing typed capacities need
    completion; supplied zero capacities do not require payload balancing.
    """
    def identifier(value):
        return isinstance(value, str) and bool(value) and not isinstance(value, TranslatedString)

    for slot in _source_slots(source_model):
        for entry in slot:
            value = entry.value
            declared = any(identifier(value.get(field)) for field in ('type', 'cargoType'))
            if 'cargoTypeSet' in value:
                config = _named(value['cargoTypeSet'], f'{entry.path}/cargoTypeSet')
                declared = declared or any(identifier(token)
                    for field in ('cargoClassesIncluded', 'cargoTypesIncluded')
                    for token in _list(config.get(field, []), f'{entry.path}/cargoTypeSet/{field}'))
            capacity = value.get('capacity')
            if declared and (capacity is None or type(capacity) in (int, float)
                             and math.isfinite(capacity) and capacity > 0):
                return True
    return False


def _keys(entry: dict, catalog: CargoCatalog, path: str) -> set[str]:
    if 'type' in entry and 'cargoTypeSet' in entry:
        raise ValueError(f'{path}: conflicting type/cargoTypeSet fields')
    if 'type' in entry:
        if isinstance(entry['type'], TranslatedString):
            raise ValueError(f'{path}: localized cargo identifiers cannot establish donor compatibility')
        return catalog.keys(entry['type'])[0]
    if 'cargoTypeSet' not in entry:
        if entry.get('capacity', 0) == 0 and not entry.get('seats'):
            return set()
        raise ValueError(f'{path}: missing cargo identity cannot be inferred from a donor')
    config = _named(entry['cargoTypeSet'], f'{path}/cargoTypeSet')
    fields = {'cargoClassesIncluded', 'cargoClassesExcluded', 'cargoTypesIncluded', 'cargoTypesExcluded'}
    if set(config) - fields:
        raise ValueError(f'{path}: unknown cargoTypeSet fields')
    included, excluded = set(), set()
    for field in fields:
        tokens = _list(config.get(field, []), f'{path}/cargoTypeSet/{field}')
        selected = set()
        for token in tokens:
            if not isinstance(token, str) or not token or isinstance(token, TranslatedString):
                raise ValueError(f'{path}/cargoTypeSet/{field}: requires literal cargo identifiers')
            selected.update(catalog.class_types(token) if field.startswith('cargoClasses') else catalog.keys(token)[0])
        (included if field.endswith('Included') else excluded).update(selected)
    return included - excluded


def _classes(keys: set[str], catalog: CargoCatalog) -> set[str]:
    # UNIVERSAL alone says nothing about the physical class of the load.
    specific = SPECIFIC_FREIGHT_CLASSES | {'PASSENGERS'}
    return set.intersection(*(set(catalog.types[key].classes) & specific for key in keys)) if keys else set()


def _native_slots(match, catalog: CargoCatalog) -> list[list[dict]]:
    metadata = getattr(match, 'metadata', None)
    if metadata is None:
        model = getattr(match, 'model', None)
        if isinstance(model, dict):
            metadata = model.get('metadata')
    metadata = _named(metadata, 'selected native donor/metadata')
    transport = _named(metadata.get('transportVehicle'), 'selected native donor/transportVehicle')
    slots = []
    for ci, compartment in enumerate(_list(transport.get('compartments'), 'selected native donor/compartments')):
        compartment = _named(compartment, f'selected native donor/compartments/{ci}')
        entries = []
        for li, config in enumerate(_list(compartment.get('loadConfigs', []), 'native donor/loadConfigs')):
            config = _named(config, 'native donor/loadConfig')
            entry = _named(config.get('cargoEntry'), 'native donor/cargoEntry')
            capacity = _capacity(entry.get('capacity'), 'native donor/cargoEntry/capacity')
            keys = _keys(entry, catalog, 'native donor/cargoEntry')
            if capacity > 0 and not keys:
                raise ValueError('Native donor has positive capacity without verified cargo identities')
            entries.append({'capacity': capacity, 'keys': keys, 'classes': _classes(keys, catalog),
                            'path': f'metadata/transportVehicle/compartments/{ci}/loadConfigs/{li}/cargoEntry/capacity'})
        slots.append(entries)
    return slots


def _candidate(source: list[_Entry], native: list[dict], catalog: CargoCatalog) -> dict | None:
    completed = {'_rank': 0}
    for entry in source:
        keys = _keys(entry.value, catalog, entry.path)
        if not keys:
            if entry.missing:
                raise ValueError(f'{entry.path}: absent capacity has an empty verified cargo type set')
            if native and not any(not item['keys'] and item['capacity'] == 0 for item in native):
                return None
            continue
        exact = [item for item in native if item['keys'] == keys]
        if exact:
            relevant, method = exact, 'exact_verified_cargo_set'
            rank = 0
        elif len(keys) == 1 and any(keys <= item['keys'] for item in native):
            relevant = [item for item in native if keys <= item['keys']]
            method = 'exact_verified_cargo_type_in_native_set'
            rank = 1
        else:
            classes = _classes(keys, catalog)
            if not classes:
                return None
            relevant = [item for item in native if any(classes & (set(catalog.types[key].classes)
                                                                  - {'UNIVERSAL'}) for key in item['keys'])]
            method = 'same_verified_cargo_class'
            rank = 2
        if not relevant:
            return None
        completed['_rank'] += rank
        if entry.missing:
            values = {item['capacity'] for item in relevant}
            if len(values) != 1:
                return None
            completed[entry.path] = {'entry': entry, 'value': next(iter(values)), 'method': method,
                                    'donorPaths': [item['path'] for item in relevant]}
    return completed


def complete_missing_cargo(source_model: dict, match, *, report: dict | None = None,
                           model_path: str = '', catalog: CargoCatalog | None = None) -> dict:
    """Fill only absent/None typed capacities from an unambiguous native layout.

    A catalog from the selected installation verifies both cargo aliases and
    physical load classes. Every source independent compartment must have a
    compatible native counterpart; reordered compartments are allowed only when
    all valid one-to-one mappings give each missing field the same capacity.
    Invalid supplied capacities, missing cargo identities and unknown types are
    never repaired. Ambiguities stop conversion without changing the source or
    appending partial completion records.
    """
    result = deepcopy(source_model)
    source = _source_slots(result)
    missing = [entry for slot in source for entry in slot if entry.missing]
    if not missing:
        return result
    if catalog is None:
        raise ValueError('Missing cargo capacity needs the selected TF3 cargo catalog; cargo classes cannot be guessed')
    for slot in source:
        for entry in slot:
            if not entry.missing and 'capacity' in entry.value:
                _capacity(entry.value['capacity'], f'{entry.path}/capacity')
            _keys(entry.value, catalog, entry.path)
    native = _native_slots(match, catalog)
    if len(source) != len(native):
        raise ValueError('Missing cargo capacity requires matching independent compartment counts in the native donor')
    if len(source) > 32:
        raise ValueError('Missing cargo capacity has more than 32 independent compartments; requires explicit layout review')
    # Avoid factorial search. For each candidate edge, a small augmenting-path
    # matching proves whether it participates in any complete one-to-one map.
    candidates = [[_candidate(slot, donor, catalog) for donor in native] for slot in source]
    # An exact cargo identity is stronger evidence than a merely compatible
    # class. Do not create a spurious alternative mapping by ignoring it.
    for row in candidates:
        best = min((candidate['_rank'] for candidate in row if candidate is not None), default=None)
        for index, candidate in enumerate(row):
            if candidate is not None and candidate['_rank'] != best:
                row[index] = None

    def possible(forced_source=None, forced_native=None):
        owners = {forced_native: forced_source} if forced_source is not None else {}

        def assign(si, visited):
            for ni, candidate in enumerate(candidates[si]):
                if candidate is None or ni in visited or ni == forced_native:
                    continue
                visited.add(ni)
                if ni not in owners or assign(owners[ni], visited):
                    owners[ni] = si
                    return True
            return False

        return all(assign(si, set()) for si in range(len(source)) if si != forced_source)

    if not possible():
        raise ValueError('Missing cargo capacity has no unambiguous compatible native compartment layout; matching alternatives must agree')
    completions = []
    for si, slot in enumerate(source):
        participating = [candidate for ni, candidate in enumerate(candidates[si])
                         if candidate is not None and possible(si, ni)]
        for entry in slot:
            if not entry.missing:
                continue
            choices = [candidate[entry.path] for candidate in participating]
            values = {choice['value'] for choice in choices}
            if len(values) != 1:
                raise ValueError(f'{entry.path}/capacity: ambiguous capacities in matching native compartments; no source data was changed')
            value = next(iter(values))
            entry.value['capacity'] = value
            record = {'model': model_path, 'sourcePath': entry.path + '/capacity', 'targetValue': value,
                      'donorValue': value, 'inferredFromSimilar': True,
                      'donorResource': getattr(match, 'resource', ''),
                      'donorPaths': sorted({path for choice in choices for path in choice['donorPaths']}),
                      'matchingMethod': sorted({choice['method'] for choice in choices}),
                      'matchEvidence': deepcopy(getattr(match, 'evidence', {})), 'nativeTest': 'not_run'}
            if getattr(match, 'score', None) is not None:
                record['matchScore'] = match.score
            completions.append(record)
    if report is not None:
        report.setdefault('donorCompletions', []).extend(completions)
    return result

"""Match missing-data donors against literal models in the selected TF3 install.

Matching is deliberately separate from completion. A compatible model is not
permission to transplant its meshes, node names, cargo geometry, or callbacks.
Only the caller's explicitly permitted missing fields may be filled. Native
definitions are read, never executed or copied into an exported mod.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import math
from pathlib import PurePosixPath
from typing import Any

from .cargo_port import CargoCatalog, SPECIFIC_FREIGHT_CLASSES
from .lua_metadata import TranslatedString, UnsupportedValue
from .resource_profiles import load_resource_table


_ENGINES = frozenset({'HORSE', 'STEAM', 'DIESEL', 'ELECTRIC'})
_PHYSICAL = ('railVehicle', 'roadVehicle', 'waterVehicle', 'airVehicle')
_SOUND_PROPULSION = {
    'aircraft_jet_modern': 'JET', 'aircraft_jet_old': 'JET',
    'aircraft_prop_modern': 'PROPELLER', 'aircraft_prop_old': 'PROPELLER',
    'aircraft_turboprop': 'TURBOPROP',
    'ship_diesel_modern': 'DIESEL', 'ship_diesel_old': 'DIESEL',
    'ship_electric': 'ELECTRIC', 'ship_hovercraft': 'HOVERCRAFT',
    'ship_paddle_steamer': 'PADDLE_STEAM', 'ship_steamer': 'STEAM',
}
_TF2_PROPULSION_SOUNDS = frozenset(_SOUND_PROPULSION) - {'aircraft_turboprop', 'ship_electric'}
_FREIGHT = SPECIFIC_FREIGHT_CLASSES | {'UNIVERSAL'}
_MISSING = object()


def _table(value, where):
    if value == []:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'{where}: expected a literal named table')
    return value


def _array(value, where):
    if not isinstance(value, list):
        raise ValueError(f'{where}: expected a literal list')
    return value


def _number(value, where, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        qualifier = 'positive' if positive else 'non-negative'
        raise ValueError(f'{where}: expected a finite {qualifier} number; invalid supplied data cannot be replaced')
    return float(value)


def _literal(value, where='model', depth=0):
    if depth > 128:
        raise ValueError(f'{where}: literal nesting limit exceeded')
    if isinstance(value, UnsupportedValue):
        raise ValueError(f'{where}: {value.reason}')
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) not in (str, int):
                raise ValueError(f'{where}: unsupported literal key')
            _literal(item, f'{where}/{key}', depth + 1)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _literal(item, f'{where}/{i}', depth + 1)
    elif type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError(f'{where}: non-finite supplied data cannot be replaced')
    elif value is not None and not isinstance(value, (str, bool)):
        raise ValueError(f'{where}: unsupported non-literal data')


def _dimensions(model):
    metadata = _table(model.get('metadata', {}), 'metadata')
    # TF3 boundingInfo often includes lights/effects beyond the actual vehicle.
    bounds = metadata.get('extent', model.get('boundingInfo', _MISSING))
    if bounds is _MISSING:
        raise ValueError('Missing verified vehicle bounds; a donor cannot supply source geometry')
    bounds = _table(bounds, 'vehicle bounds')
    lo, hi = bounds.get('bbMin'), bounds.get('bbMax')
    if not isinstance(lo, list) or not isinstance(hi, list) or len(lo) != 3 or len(hi) != 3:
        raise ValueError('Vehicle bounds require supplied bbMin/bbMax 3-number vectors')
    values = []
    for axis, (low, high) in enumerate(zip(lo, hi)):
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high)) or high <= low:
            raise ValueError(f'Invalid vehicle bounds on axis {axis}; source geometry cannot be replaced')
        size = float(high - low)
        if not math.isfinite(size):
            raise ValueError(f'Invalid vehicle bounds on axis {axis}; body extent must remain finite')
        values.append(size)
    return tuple(values)


def _sound_propulsion(metadata, family, *, native):
    config = _table(metadata.get('soundConfig', {}), 'soundConfig')
    sound = _table(config.get('soundSet', {}), 'soundConfig/soundSet').get('name')
    if sound is None:
        physical = _table(metadata.get('waterVehicle' if family == 'ship' else 'airVehicle', {}), 'physical vehicle')
        sound = _table(physical.get('soundSet', {}), 'physical vehicle/soundSet').get('name')
    if sound is None:
        return None
    if not isinstance(sound, str) or isinstance(sound, TranslatedString):
        raise ValueError('Propulsion sound marker must be a non-localized literal resource name')
    token = sound.removeprefix('::/').lstrip('/')
    if native:
        prefix = 'vehicle/ship/shared/sound/' if family == 'ship' else 'vehicle/plane/shared/sound/'
        if not token.startswith(prefix) or not token.endswith('.snd'):
            return None
        token = token[len(prefix):-4]
    else:
        # These exact standard TF2 sound IDs were verified in the installation.
        # A custom filename containing "jet" or "steam" establishes nothing.
        if token.startswith('config/sound_set/'):
            token = token[len('config/sound_set/'):]
        token = token.removesuffix('.lua')
        if '/' in token or token not in _TF2_PROPULSION_SOUNDS:
            return None
    return _SOUND_PROPULSION.get(token)


def _cargo_set(value, catalog):
    data = _table(value, 'cargoTypeSet')
    allowed = {'cargoClassesIncluded', 'cargoClassesExcluded', 'cargoTypesIncluded', 'cargoTypesExcluded'}
    if set(data) - allowed:
        raise ValueError('Unknown cargoTypeSet fields cannot be used to identify a donor class')
    selected = set()
    for field in allowed:
        tokens = _array(data.get(field, []), f'cargoTypeSet/{field}')
        if any(not isinstance(token, str) or not token or isinstance(token, TranslatedString) for token in tokens):
            raise ValueError(f'cargoTypeSet/{field}: expected non-localized literal cargo identifiers')
    for tag in data.get('cargoClassesIncluded', []):
        selected.update(catalog.class_types(tag))
    for token in data.get('cargoTypesIncluded', []):
        selected.update(catalog.keys(token)[0])
    for tag in data.get('cargoClassesExcluded', []):
        selected.difference_update(catalog.class_types(tag))
    for token in data.get('cargoTypesExcluded', []):
        selected.difference_update(catalog.keys(token)[0])
    return selected


def _cargo_entry(entry, catalog, *, native):
    entry = _table(entry, 'cargo entry')
    # A missing numeric capacity can itself be completed; it cannot be used as
    # similarity evidence. A malformed supplied value still stops matching.
    capacity = 0.0 if not native and entry.get('capacity') is None else _number(entry.get('capacity'), 'cargo entry/capacity')
    if native:
        if 'cargoTypeSet' not in entry:
            raise ValueError('Native cargo entry has no explicit cargoTypeSet')
        keys = _cargo_set(entry['cargoTypeSet'], catalog)
    else:
        token = entry.get('type', entry.get('cargoType', _MISSING))
        if token is _MISSING:
            if 'cargoTypeSet' not in entry:
                if capacity == 0 and not entry.get('seats'):
                    return set(), 0.0, True, set()
                raise ValueError('Source cargo entry has no declared type; a donor cannot invent its class')
            keys = _cargo_set(entry['cargoTypeSet'], catalog)
        else:
            if isinstance(token, TranslatedString):
                raise ValueError('Localized cargo identifiers cannot establish a donor class')
            keys = catalog.keys(token)[0]
    classes = set()
    for key in keys:
        classes.update(catalog.types[key].classes)
    # UNIVERSAL is membership on individual freight definitions, not proof that
    # a declared bulk tank is a generic body. Keep explicit native UNIVERSAL
    # only when its class declaration actually selected that broad category.
    if native and isinstance(entry.get('cargoTypeSet'), dict):
        included = set(entry['cargoTypeSet'].get('cargoClassesIncluded', []))
        if included == {'UNIVERSAL'} and not entry['cargoTypeSet'].get('cargoTypesIncluded'):
            classes = {'UNIVERSAL'} if keys else set()
        else:
            classes.discard('UNIVERSAL')
    else:
        classes.discard('UNIVERSAL')
    complete = native or entry.get('capacity') is not None
    return classes, capacity, complete, keys


def _cargo_signature(transport, catalog, *, native):
    transport = _table(transport, 'transportVehicle')
    possible = ('compartments',) if native else ('compartmentsList', 'compartments', 'capacities')
    present = [key for key in possible if transport.get(key)]
    if len(present) > 1:
        raise ValueError('Conflicting cargo schemas cannot establish a donor class')
    if not present:
        for key in possible:
            if key in transport:
                _array(transport[key], key)
        return frozenset(), 0.0, frozenset()
    key = present[0]
    values = _array(transport[key], key)
    if key == 'capacities':
        groups = [{'loadConfigs': [{'cargoEntries': [entry]} for entry in values]}]
    elif key == 'compartments' and not native and not all(isinstance(c, dict) and 'loadConfigs' in c for c in values):
        groups = [{'loadConfigs': [{'cargoEntries': _array(entry, 'legacy cargo configuration')} for entry in _array(c, 'legacy compartment')]} for c in values]
    else:
        groups = values
    found, found_keys, raw_capacity, complete = set(), set(), 0.0, True
    for compartment in groups:
        compartment = _table(compartment, 'compartment')
        configs = _array(compartment.get('loadConfigs'), 'compartment/loadConfigs')
        totals = []
        for config in configs:
            config = _table(config, 'loadConfig')
            if not native and 'cargoEntries' in config and 'cargoEntry' in config:
                raise ValueError('Source load configuration mixes cargoEntry and cargoEntries')
            entries = [_table(config.get('cargoEntry'), 'cargoEntry')] if native or 'cargoEntry' in config else _array(config.get('cargoEntries', []), 'cargoEntries')
            total = 0.0
            for entry in entries:
                classes, capacity, has_capacity, keys = _cargo_entry(entry, catalog, native=native)
                found.update(classes)
                found_keys.update(keys)
                complete = complete and has_capacity
                # Native empty cargoTypeSet is an inactive 4-seat placeholder
                # on some locomotives, not a passenger/freight payload.
                if classes:
                    total += capacity
            totals.append(total)
        raw_capacity += max(totals, default=0.0)
    # A partial total is not the source's actual capacity and must never bias
    # selection toward a smaller donor when another compartment is missing.
    return frozenset(found), raw_capacity if complete else 0.0, frozenset(found_keys)


@dataclass(frozen=True)
class _Signature:
    family: str
    carrier: str
    size: str | None
    engines: tuple[str, ...]
    powered: bool
    propulsion: str | None
    classes: frozenset[str]
    role: str
    dimensions: tuple[float, float, float]
    features: tuple[tuple[str, float], ...]
    raw_capacity: float
    cargo_keys: frozenset[str]


def _signature(model, catalog, *, native=False):
    model = _table(model, 'model')
    _literal(model)
    metadata = _table(model.get('metadata', {}), 'metadata')
    blocks = [block for block in _PHYSICAL if block in metadata]
    if len(blocks) != 1:
        raise ValueError('Missing or conflicting physical vehicle class; a donor cannot invent the carrier')
    block = blocks[0]
    physical = _table(metadata[block], block)
    car = 'car' in metadata
    transport = _table(metadata.get('transportVehicle', {}), 'transportVehicle')
    carrier = 'ROAD' if car and not transport else transport.get('carrier')
    expected = {'railVehicle': {'RAIL', 'TRAM'}, 'roadVehicle': {'ROAD'}, 'waterVehicle': {'WATER'}, 'airVehicle': {'AIR'}}[block]
    if not isinstance(carrier, str) or isinstance(carrier, TranslatedString) or carrier not in expected or (car and block != 'roadVehicle'):
        raise ValueError('Invalid or missing explicit carrier; a donor cannot invent the vehicle class')
    classes, capacity, cargo_keys = _cargo_signature(transport, catalog, native=native)
    passenger = 'PASSENGERS' in classes
    freight = bool(classes & _FREIGHT)
    role = 'mixed' if passenger and freight else 'passenger' if passenger else 'freight' if freight else 'none'
    engine_block = _table(metadata.get('landVehicle', {}), 'landVehicle') if native and carrier in ('RAIL', 'TRAM', 'ROAD') else physical
    if carrier in ('RAIL', 'TRAM') or native and carrier == 'ROAD':
        if 'engines' not in engine_block:
            raise ValueError('Missing engine list; powered/unpowered status must come from the source')
        engines = _array(engine_block['engines'], 'engines')
    elif carrier == 'ROAD':
        if 'engine' not in engine_block:
            raise ValueError('Missing road engine; propulsion must come from the source')
        engine = _table(engine_block['engine'], 'engine')
        engines = [engine] if engine else []
    else:
        engines = []
    kinds, features = [], []
    for index, engine in enumerate(engines):
        engine = _table(engine, 'engine')
        kind = engine.get('type')
        if not isinstance(kind, str) or isinstance(kind, TranslatedString) or kind not in _ENGINES:
            raise ValueError('Missing/invalid engine type; a donor cannot invent propulsion')
        kinds.append(kind)
        for field in ('power', 'tractiveEffort'):
            if field in engine and (native or engine[field] is not None):
                value = _number(engine[field], f'engine/{index}/{field}')
                features.append((f'engine.{index}.{field}', value))
    size, propulsion = None, None
    if carrier == 'RAIL':
        family = 'train' if engines else 'waggon'
    elif carrier == 'TRAM':
        family = 'tram'
    elif carrier == 'ROAD':
        if car:
            family = 'car'
        elif role in ('passenger', 'mixed'):
            family = 'bus'
        elif role == 'freight':
            family = 'truck'
        else:
            raise ValueError('Missing passenger/freight declaration; a donor cannot invent a bus/truck class')
    else:
        family = 'ship' if carrier == 'WATER' else 'plane'
        if native:
            modes = set(_array(transport.get('transportModes'), 'transportModes'))
            small, big = ('SMALL_SHIP', 'SHIP') if family == 'ship' else ('SMALL_AIRCRAFT', 'AIRCRAFT')
            if (small in modes) == (big in modes):
                raise ValueError('Native vehicle has missing/conflicting SMALL/BIG transport modes')
            size = 'SMALL' if small in modes else 'BIG'
        else:
            size = physical.get('type')
            if not isinstance(size, str) or isinstance(size, TranslatedString) or size not in ('SMALL', 'BIG'):
                raise ValueError('Missing/invalid SMALL/BIG type; a donor cannot invent infrastructure restrictions')
        propulsion = _sound_propulsion(metadata, family, native=native)
    for field in ('topSpeed', 'weightEmpty' if native else 'weight', 'availPower', 'maxRpm', 'maxThrust', 'wingArea', 'timeToFullThrust', 'area'):
        if field in engine_block and (native or engine_block[field] is not None):
            value = _number(engine_block[field], f'{block}/{field}', positive=field in ('weight', 'weightEmpty', 'wingArea', 'area'))
            if field == 'weight' and carrier in ('RAIL', 'TRAM', 'ROAD'):
                value *= 1000
                _number(value, 'converted weightEmpty', positive=True)
            features.append(('weightEmpty' if field == 'weight' else field, value))
    return _Signature(family, carrier, size, tuple(kinds), bool(engines) or carrier in ('WATER', 'AIR'),
                      propulsion, classes, role, _dimensions(model), tuple(features), capacity, cargo_keys)


def _lookup(model, path):
    if not isinstance(path, str) or not path or any(not item for item in path.split('.')):
        raise ValueError('Donor requirement needs a canonical native dotted field path')
    if path == 'nativePayloadRatio':
        raise ValueError('nativePayloadRatio requires the donor capacity context')
    current = model if path.startswith('metadata.') or path.startswith('boundingInfo.') else model.get('metadata', {})
    for part in path.split('.'):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdecimal() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f'Installed donor does not declare required native field {path}')
    if current is None or isinstance(current, UnsupportedValue):
        raise ValueError(f'Installed donor has no verified value for {path}')
    _literal(current, path)
    return current


@dataclass(frozen=True)
class NativeDonor:
    resource: str
    _model: dict
    _signature: _Signature
    _cargo_catalog: CargoCatalog | None = None
    _source_text: str | None = None
    _full_model: dict | None = None

    @property
    def model(self):
        # The catalog only needs metadata/bounds. Full LOD/node tables are read
        # by the strict literal parser only if a selected donor's verified gear
        # correspondence actually needs them.
        if self._source_text is not None and self._full_model is None:
            full = load_resource_table(self._source_text)
            if full.get('metadata') != self._model.get('metadata') or full.get('boundingInfo') != self._model.get('boundingInfo'):
                raise ValueError('Native donor projection differs from the full literal model; rescan the installation')
            object.__setattr__(self, '_full_model', full)
        return deepcopy(self._full_model if self._full_model is not None else self._model)

    @property
    def metadata(self):
        return deepcopy(self._model['metadata'])

    @property
    def dimensions(self):
        return self._signature.dimensions

    @property
    def body_bounds(self):
        return deepcopy(self._model['metadata'].get('extent', self._model.get('boundingInfo')))

    @property
    def raw_capacity(self):
        return self._signature.raw_capacity

    def value(self, path):
        if path == 'nativeGearRadiusPolicy':
            if self._signature.carrier != 'AIR':
                raise ValueError('Native gear radius policy requires an aircraft donor')
            config = _table(_lookup(self._model, 'airVehicle.config'), 'native airVehicle/config')
            result = {}
            for role, field in (('axles', 'axleRadii'), ('wheels', 'wheelRadii')):
                names = _array(config.get(role, []), f'native airVehicle/config/{role}')
                radii = _array(config.get(field, []), f'native airVehicle/config/{field}')
                if len(names) != len(radii):
                    raise ValueError(f'Native gear radius policy requires matching {role}/{field} lengths')
                if any(not isinstance(name, str) or not name or isinstance(name, TranslatedString)
                       or name.startswith('node_') for name in names) or len(set(names)) != len(names):
                    raise ValueError(f'Native gear radius policy requires explicit unique {role} node IDs')
                result[role] = sorted(({'node': name, 'radius': _number(radius, f'native airVehicle/config/{field}', positive=True)}
                                       for name, radius in zip(names, radii)), key=lambda item: item['node'])
            return result
        if path == 'nativeCargoCapacityPolicy':
            if self._cargo_catalog is None:
                raise ValueError('Native cargo capacity policy requires the verified installation cargo catalog')
            transport = _table(self._model['metadata'].get('transportVehicle', {}), 'native transportVehicle')
            compartments = []
            for compartment in _array(transport.get('compartments', []), 'native compartments'):
                compartment = _table(compartment, 'native compartment')
                configs = {}
                for config in _array(compartment.get('loadConfigs', []), 'native loadConfigs'):
                    config = _table(config, 'native loadConfig')
                    _, capacity, _, keys = _cargo_entry(config.get('cargoEntry'), self._cargo_catalog, native=True)
                    classes = set().union(*(self._cargo_catalog.types[key].classes for key in keys)) if keys else set()
                    classes.discard('UNIVERSAL')
                    value = {'capacity': capacity, 'cargoTypes': sorted(keys), 'cargoClasses': sorted(classes)}
                    # Duplicate visual alternatives do not change capacity or
                    # eligibility, unlike independent repeated compartments.
                    configs[json.dumps(value, sort_keys=True)] = value
                summary = {'loadConfigs': [configs[key] for key in sorted(configs)]}
                compartments.append(summary)
            return {'compartments': sorted(compartments, key=lambda value: json.dumps(value, sort_keys=True))}
        if path == 'nativePayloadPolicy':
            block = {'WATER': 'waterVehicle', 'AIR': 'airVehicle'}.get(self._signature.carrier, 'landVehicle')
            field = f'{block}.weightMaxPayload'
            physical = self._model['metadata'][block]
            if self._signature.carrier == 'AIR' and physical.get('weightMaxPayload') is None:
                return {'field': field, 'policy': 'omit_as_selected_native_profile', 'ratio': None}
            return {'field': field, 'policy': 'matched_native_capacity_ratio', 'ratio': self.value('nativePayloadRatio')}
        if path == 'nativePayloadRatio':
            capacity = self.raw_capacity
            if capacity <= 0:
                raise ValueError('Installed donor has no positive declared cargo capacity for payload balancing')
            block = {'WATER': 'waterVehicle', 'AIR': 'airVehicle'}.get(self._signature.carrier, 'landVehicle')
            payload = _lookup(self._model, f'{block}.weightMaxPayload')
            payload = _number(payload, 'native weightMaxPayload', positive=True)
            return payload / capacity
        return deepcopy(_lookup(self._model, path))


@dataclass(frozen=True)
class NativeMatch:
    donor: NativeDonor
    score: float
    evidence: tuple[dict, ...]
    confidence: str
    runner_up: dict | None = None
    equivalent_resources: tuple[str, ...] = ()

    @property
    def resource(self):
        return self.donor.resource

    @property
    def model(self):
        return self.donor.model

    @property
    def metadata(self):
        return self.donor.metadata

    @property
    def dimensions(self):
        return self.donor.dimensions

    @property
    def body_bounds(self):
        return self.donor.body_bounds

    @property
    def raw_capacity(self):
        return self.donor.raw_capacity

    def value(self, path):
        return self.donor.value(path)

    def audit(self):
        return {'resource': self.resource, 'score': self.score, 'confidence': self.confidence,
                'evidence': deepcopy(list(self.evidence)), 'runnerUp': deepcopy(self.runner_up),
                'equivalentResources': list(self.equivalent_resources), 'nativeTest': 'not_run'}


class NativeDonorCatalog:
    """Cached parsed donor models with per-mod native-reference provenance.

    ``score`` is a weighted logarithmic distance, so smaller is closer. Exact
    filenames and display names never contribute. When close alternatives would
    supply different requested data, conversion stops with an ambiguity error.
    """

    AMBIGUITY_MARGIN = 0.08
    MAX_DIMENSION_RATIO = 1.65
    MAX_PHYSICAL_RATIO = 2.0
    MAX_SCORE = 0.40

    def __init__(self, donors, cargo_catalog, *, native=None, diagnostics=()):
        self.donors = tuple(donors)
        self.cargo_catalog = cargo_catalog
        self.native = native
        self.diagnostics = tuple(deepcopy(list(diagnostics)))

    def for_native(self, native):
        return type(self)(self.donors, self.cargo_catalog, native=native, diagnostics=self.diagnostics)

    @classmethod
    def from_native(cls, native):
        from .native_projection import UnsupportedProjection, project_native_model
        owner = getattr(native, '_cache_owner', native)
        cached = getattr(owner, '_native_donor_catalog', None)
        if cached is not None:
            return cached.for_native(native)
        cargo = CargoCatalog.from_native(native)
        donors, diagnostics = [], []
        for path in sorted(native.files):
            if not path.startswith('vehicle/') or not path.endswith(('.mdl', '.mdl.lua', '.mdl.tl')):
                continue
            resource = path[:-4] if path.endswith(('.lua', '.tl')) else path
            if not resource.endswith('.mdl'):
                continue
            if path != resource and resource in native.files:
                # NativeInventory mounts the bare descriptor when it exists.
                # A second suffixed descriptor must not supply a hidden donor
                # whose provenance would resolve to different native bytes.
                continue
            try:
                text = native.read(path).decode('utf-8-sig')
                projected = True
                try:
                    data = project_native_model(text)
                except UnsupportedProjection:
                    data = load_resource_table(text)
                    projected = False
                signature = _signature(data, cargo, native=True)
                donors.append(NativeDonor(resource, deepcopy(data), signature, cargo, text if projected else None))
            except Exception as exc:
                diagnostics.append({'resource': resource, 'reason': str(exc), 'action': 'excluded_from_donor_catalog'})
        if not donors:
            raise ValueError('Selected TF3 installation contains no verified literal vehicle donors')
        # The cached object has no writable reference-tracking binding. Parsed
        # immutable records are shared; each match returns defensive data copies.
        cached = cls(donors, cargo, native=None, diagnostics=diagnostics)
        owner._native_donor_catalog = cached
        return cached.for_native(native)

    def source_signature(self, source_model, *, model_path=''):
        """Classify incomplete numeric metadata without inventing class markers."""
        return _signature(source_model, self.cargo_catalog)

    def match(self, source_model, *, model_path='', requirements=()):
        if isinstance(requirements, str):
            raise ValueError('Donor requirements must be a list/tuple of canonical native dotted paths')
        requirements = tuple(requirements)
        if any(not isinstance(path, str) for path in requirements):
            raise ValueError('Donor requirements must be canonical native dotted paths')
        requirements = tuple(dict.fromkeys(requirements))
        source = self.source_signature(source_model, model_path=model_path)
        propulsion_fields = {'airVehicle.maxThrust', 'airVehicle.idleThrust', 'airVehicle.timeToFullThrust',
                             'waterVehicle.availPower', 'waterVehicle.maxRpm'}
        if source.carrier in ('AIR', 'WATER') and source.propulsion is None and any(path.removeprefix('metadata.') in propulsion_fields for path in requirements):
            raise ValueError('Source aircraft/ship propulsion is not verified; provide an explicit standard propulsion marker before completing physical data')
        results = []
        for donor in self.donors:
            target = donor._signature
            if (source.family, source.carrier, source.size, source.powered, source.engines, source.role) != (target.family, target.carrier, target.size, target.powered, target.engines, target.role):
                continue
            if source.propulsion is not None and target.propulsion != source.propulsion:
                continue
            # A native UNIVERSAL freight vehicle can inform scalar balancing,
            # but this never changes the source's cargo class or visuals.
            universal = target.classes == frozenset({'UNIVERSAL'}) and source.role == 'freight'
            if source.classes != target.classes and not universal:
                continue
            if not source.cargo_keys.issubset(target.cargo_keys):
                # Explicit native exclusions remain binding, including on a
                # nominally UNIVERSAL vehicle. Matching cannot undo them.
                continue
            try:
                requested = [donor.value(path) for path in requirements]
            except ValueError:
                continue
            ratios = [max(a / b, b / a) for a, b in zip(source.dimensions, target.dimensions)]
            if max(ratios) > self.MAX_DIMENSION_RATIO:
                continue
            evidence = [{'gate': 'compatible_metadata', 'family': source.family, 'carrier': source.carrier,
                         'size': source.size, 'engines': list(source.engines), 'powered': source.powered,
                         'sourceCargoClasses': sorted(source.classes), 'donorCargoClasses': sorted(target.classes),
                         'sourceCargoTypes': sorted(source.cargo_keys), 'donorCargoTypes': sorted(target.cargo_keys),
                         'propulsion': source.propulsion, 'donorPropulsion': target.propulsion,
                         'propulsionVerified': source.propulsion is not None or source.carrier not in ('AIR', 'WATER'),
                         'universalFreightDonor': universal},
                        {'feature': 'body_dimensions', 'source': list(source.dimensions),
                         'donor': list(target.dimensions), 'axisRatios': ratios}]
            distance, weight = sum(math.log(r) for r in ratios) / 3 * 3, 3.0
            target_features = dict(target.features)
            reject = False
            for name, value in source.features:
                if name not in target_features:
                    continue
                other = target_features[name]
                if value == 0 or other == 0:
                    if value != other:
                        reject = True
                        break
                    ratio = 1.0
                else:
                    ratio = max(value / other, other / value)
                if ratio > self.MAX_PHYSICAL_RATIO:
                    reject = True
                    break
                distance += math.log(ratio)
                weight += 1
                evidence.append({'feature': name, 'source': value, 'donor': other, 'ratio': ratio})
            if reject:
                continue
            if source.raw_capacity > 0 and target.raw_capacity > 0:
                ratio = max(source.raw_capacity / target.raw_capacity, target.raw_capacity / source.raw_capacity)
                distance += math.log(ratio) * .2
                weight += .2
                evidence.append({'feature': 'raw_capacity', 'source': source.raw_capacity, 'donor': target.raw_capacity, 'ratio': ratio})
            score = distance / weight
            if score > self.MAX_SCORE:
                continue
            results.append((score, donor.resource, donor, tuple(evidence), requested))
        if not results:
            raise ValueError('No sufficiently similar installed TF3 donor with the same verified class, propulsion and requested data; complete this mod manually')
        results.sort(key=lambda row: (row[0], row[1]))
        best = results[0]
        close = [row for row in results if row[0] - best[0] <= self.AMBIGUITY_MARGIN]
        equivalents = []
        for row in close[1:]:
            # Without explicit requirements, claiming interchangeable donors
            # would allow later reads to select arbitrary physical differences.
            comparable = row[4] == best[4] if requirements else row[2].metadata == best[2].metadata
            if not comparable:
                names = ', '.join(row[1] for row in close[:4])
                raise ValueError(f'Ambiguous installed TF3 donors supply different required values ({names}); add verified source data before automatic completion')
            equivalents.append(row[1])
        runner = None if len(results) < 2 else {'resource': results[1][1], 'score': round(results[1][0], 8), 'scoreGap': round(results[1][0] - best[0], 8)}
        confidence = 'equivalent_required_values' if equivalents else 'close_physical_match' if best[0] <= .18 else 'compatible_physical_match'
        # Reads to construct the catalog must not leak provenance across mods.
        # Only the selected donor is registered on this catalog's native fork.
        if self.native is not None:
            self.native.reference(best[2].resource)
        return NativeMatch(best[2], round(best[0], 8), best[3], confidence, runner, tuple(equivalents))

"""Complete permitted missing fields using an installed, compatible TF3 donor.

Authored data remains authoritative. Missing simulation values are estimates
from a comparable object, not reconstructed historical specifications. No donor
scripts, identities, node bindings or asset files are copied into the export.
"""
from __future__ import annotations

from copy import deepcopy
import math

from .cargo_port import CargoCatalog
from .donor_cargo import (complete_missing_cargo, missing_cargo_requirements,
                          has_payload_declaration, validate_source_cargo_identifiers)
from .donor_geometry import air_gear_needs, complete_air_gear
from .native_donors import NativeDonorCatalog
from .lua_metadata import TranslatedString
from .vehicle_profiles import classify_model


PHYSICAL = {
    'railVehicle': 'landVehicle', 'roadVehicle': 'landVehicle',
    'waterVehicle': 'waterVehicle', 'airVehicle': 'airVehicle',
}

EMP_PAYLOAD_SCHEMA = 'https://www.transportfever.net/lexicon/entry/339-calculated-vehicle-capacites-with-payload-and-loading-volume/'


def _number(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{field}: invalid supplied value cannot be replaced with donor data')
    return value


def legacy_payload_hints(model):
    """Read documented CCW/EMP payload tonnes and volume m3 without mutation.

    Compartment arrays need an explicit migration; only scalar whole-vehicle
    limits are supported. Volume does not determine native cargo capacities.
    """
    metadata = model.get('metadata') or {}
    if not isinstance(metadata, dict):
        raise ValueError('Model metadata must be a named literal table')
    transport = metadata.get('transportVehicle') or {}
    if not isinstance(transport, dict):
        raise ValueError('transportVehicle must be a named literal table')
    fields = {key: transport[key] for key in ('maxWeight', 'maxVolume') if key in transport}
    if not fields:
        return None
    for field, value in fields.items():
        if isinstance(value, list):
            raise ValueError(f'transportVehicle.{field}: EMP compartment arrays require an explicit payload/volume adapter')
        _number(value, f'transportVehicle.{field}')
        if value <= 0:
            raise ValueError(f'transportVehicle.{field}: documented EMP limit must be positive')
    payload = fields.get('maxWeight')
    if payload is not None:
        payload *= 1000
        _number(payload, 'authored EMP payload in kilograms')
    return {'sourceFields': deepcopy(fields), 'weightMaxPayload': payload, 'schemaSource': EMP_PAYLOAD_SCHEMA}


def classification_view(model):
    """Permit absent engine numbers during preflight without inventing engines.

    Zero placeholders exist only in this defensive classification copy. Actual
    export completion must obtain the requested values from a checked donor.
    Explicit engine arrays, propulsion types, carrier and size stay unchanged.
    """
    result = deepcopy(model.get('metadata', {}) or {})
    if not isinstance(result, dict):
        raise ValueError('Model metadata must be a named literal table')
    for key in ('railVehicle', 'roadVehicle'):
        physical = result.get(key)
        if not isinstance(physical, dict):
            continue
        engines = physical.get('engines', []) if key == 'railVehicle' else (
            [physical['engine']] if physical.get('engine') else [])
        if not isinstance(engines, list):
            continue  # Strict classifier supplies the actionable schema error.
        for engine in engines:
            if isinstance(engine, dict):
                for field in ('power', 'tractiveEffort'):
                    if engine.get(field) is None:
                        engine[field] = 0
    return result


def classify_missing_model(model, model_path=''):
    metadata = classification_view(model)
    validate_source_cargo_identifiers(model)
    transport = metadata.get('transportVehicle') or {}
    if isinstance(transport,dict) and isinstance(transport.get('carrier'),TranslatedString):
        raise ValueError('Carrier must be a non-localized literal identifier')
    for key in PHYSICAL:
        physical = metadata.get(key)
        if not isinstance(physical,dict):
            continue
        if isinstance(physical.get('type'),TranslatedString):
            raise ValueError(f'{key}.type must be a non-localized literal identifier')
        engines = physical.get('engines',[]) if key=='railVehicle' else ([physical['engine']] if key=='roadVehicle' and physical.get('engine') else [])
        if isinstance(engines,list) and any(isinstance(e,dict) and isinstance(e.get('type'),TranslatedString) for e in engines):
            raise ValueError('Engine type must be a non-localized literal identifier')
    return classify_model(metadata, model_path)


def cargo_catalog(native):
    owner = getattr(native, '_cache_owner', native)
    catalog = getattr(owner, '_cargo_catalog', None)
    if catalog is None:
        catalog = owner._cargo_catalog = CargoCatalog.from_native(native)
    return CargoCatalog(catalog.types, classes=catalog.classes, formats=catalog.formats,
                        aliases=catalog.aliases, native=native, resource_dependencies=catalog.resource_dependencies)


def _scalar_fields(model):
    metadata = model.get('metadata', {}) or {}
    fields = []
    for source_block, native_block in PHYSICAL.items():
        if source_block not in metadata:
            continue
        physical = metadata[source_block]
        if not isinstance(physical, dict):
            raise ValueError(f'{source_block}: expected a named literal table')
        factor = .001 if native_block == 'landVehicle' else 1
        fields.extend([(physical, 'topSpeed', f'{source_block}.topSpeed', f'{native_block}.topSpeed', 1),
                       (physical, 'weight', f'{source_block}.weight', f'{native_block}.weightEmpty', factor)])
        required = {'waterVehicle': ('area', 'availPower', 'maxRpm'),
                    'airVehicle': ('maxThrust', 'timeToFullThrust', 'wingArea')}.get(source_block, ())
        fields.extend((physical, field, f'{source_block}.{field}', f'{native_block}.{field}', 1)
                      for field in required)
        if source_block in ('railVehicle', 'roadVehicle'):
            engines = physical.get('engines', []) if source_block == 'railVehicle' else (
                [physical['engine']] if physical.get('engine') else [])
            for index, engine in enumerate(engines):
                path = f'{source_block}.engines.{index}' if source_block == 'railVehicle' else f'{source_block}.engine'
                for field in ('power', 'tractiveEffort'):
                    fields.append((engine, field, f'{path}.{field}', f'landVehicle.engines.{index}.{field}', 1))
    if 'transportVehicle' in metadata:
        transport = metadata['transportVehicle']
        if not isinstance(transport, dict):
            raise ValueError('transportVehicle must be a named literal table')
        # Native cargo-free locomotives omit this optional loading field.
        # Validate an authored value, but donate one only for an active load.
        if transport.get('loadSpeed') is not None or _has_load(model):
            fields.append((transport, 'loadSpeed', 'transportVehicle.loadSpeed', 'transportVehicle.loadSpeed', 1))
    return fields


def _has_load(model):
    """Inspect declared cargo entries, excluding visual metadata and empty bays."""
    return has_payload_declaration(model)


def _aircraft_payload_omission(model, native, model_path):
    metadata = model.get('metadata') or {}
    if 'airVehicle' not in metadata or classify_missing_model(model, model_path).carrier != 'AIR':
        return None
    return NativeDonorCatalog.from_native(native).aircraft_payload_omission(model, model_path=model_path)


def _audit(match, model_path, source_field, native_field, value, donor_value, **extra):
    return {'model': model_path, 'field': source_field, 'value': deepcopy(value),
            'sourceValue': None, 'donorField': native_field, 'donorValue': deepcopy(donor_value),
            'donorResource': match.resource, 'match': match.audit(), 'estimated': True,
            'method': 'matched_installed_tf3_missing_field',
            'requiredCheck': 'Verify the completed vehicle in TF3.', 'nativeTest': 'not_run', **extra}


def _waterline(model, match, report, model_path):
    physical = (model.get('metadata') or {}).get('waterVehicle')
    if not isinstance(physical, dict) or physical.get('waterLine') is not None:
        return
    source = model.get('boundingInfo') or {}
    # Bounds and points were already validated in the donor signature. Reading
    # metadata avoids parsing unrelated donor meshes for a scalar hull outline.
    bounds = match.body_bounds
    ratios = [(b-a)/(d-c) for a,b,c,d in zip(source['bbMin'],source['bbMax'],bounds['bbMin'],bounds['bbMax'])]
    scale = sum(ratios)/3
    if scale <= 0 or any(abs(value/scale-1) > .05 for value in ratios):
        raise ValueError('Missing waterLine requires a donor with uniformly comparable hull dimensions')
    points = match.value('waterVehicle.waterLine')
    if not isinstance(points,list) or len(points) < 3 or any(
            not isinstance(point,list) or len(point)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in point)
            for point in points):
        raise ValueError('Matched native ship has no valid waterLine polygon')
    source_center = [(a+b)/2 for a,b in zip(source['bbMin'],source['bbMax'])]
    donor_center = [(a+b)/2 for a,b in zip(bounds['bbMin'],bounds['bbMax'])]
    completed = [[source_center[axis]+(point[axis]-donor_center[axis])*scale for axis in range(2)] for point in points]
    physical['waterLine'] = completed
    report.setdefault('dataCompletions', []).append(_audit(match,model_path,'waterVehicle.waterLine',
        'waterVehicle.waterLine',completed,points,bodyScale=scale,method='approximate_native_hull_waterline'))


def complete_missing_model(model, native, *, model_path='', report=None, progress=None, preserve_tf2=False):
    """Return (completed copy, selected match), preserving all supplied fields.

    One selected donor supplies the requested scalar, cargo and payload values.
    A matching failure or incompatible gear/hull stops export before staging.
    """
    result = deepcopy(model)
    profile = classify_missing_model(result, model_path)
    if profile.carrier is None:
        return result, None
    payload_hints = legacy_payload_hints(result)
    pending_report = {}
    fields = _scalar_fields(result)
    missing = []
    for table, field, source_path, donor_path, factor in fields:
        if table.get(field) is None:
            missing.append((table,field,source_path,donor_path,factor))
        else:
            _number(table[field],source_path)
    requirements = [row[3] for row in missing]
    requirements.extend(missing_cargo_requirements(result))
    result = complete_air_gear(result, report=pending_report, model_path=model_path)
    needs_gear = air_gear_needs(result)
    if needs_gear:
        requirements.append('nativeGearRadiusPolicy')
    water = (result.get('metadata') or {}).get('waterVehicle')
    needs_waterline = isinstance(water,dict) and water.get('waterLine') is None
    if needs_waterline:
        requirements.append('waterVehicle.waterLine')
    if not preserve_tf2 and _has_load(model) and not (payload_hints and payload_hints['weightMaxPayload'] is not None):
        omission = _aircraft_payload_omission(result, native, model_path)
        if omission is None:
            requirements.append('nativePayloadPolicy')
    match = None
    if requirements:
        if progress:
            progress('Completing vehicle data from installed TF3 objects…')
        catalog = NativeDonorCatalog.from_native(native)
        candidate_validator = None
        if needs_gear or needs_waterline:
            def candidate_validator(candidate):
                # Validate a private copy with the same strict geometry rules
                # used during completion. Reject unusable candidates before
                # ranking rather than failing after selecting the closest one.
                checked = complete_air_gear(result, candidate) if needs_gear else deepcopy(result)
                values = {}
                if needs_gear:
                    values['airVehicleGearRadii'] = [
                        {field: deepcopy(config.get(field, [])) for field in ('axleRadii', 'wheelRadii')}
                        for config in checked['metadata']['airVehicle']['configs']]
                if needs_waterline:
                    _waterline(checked, candidate, {}, model_path)
                    values['waterVehicleWaterLine'] = checked['metadata']['waterVehicle']['waterLine']
                return values
        match = catalog.match(model,model_path=model_path,requirements=tuple(requirements),
                              candidate_validator=candidate_validator)
        # Reacquire mutable field owners after geometry's defensive deepcopy.
        owners = {row[2]:row for row in _scalar_fields(result)}
        for _,field,source_path,donor_path,factor in missing:
            value = _number(match.value(donor_path),donor_path)
            completed = value*factor
            owners[source_path][0][field] = completed
            pending_report.setdefault('dataCompletions', []).append(_audit(match,model_path,
                source_path,donor_path,completed,value,unitMultiplier=factor))
        result = complete_missing_cargo(result,match,report=pending_report,model_path=model_path,
                                        catalog=cargo_catalog(native))
        result = complete_air_gear(result,match,report=pending_report,model_path=model_path)
        _waterline(result,match,pending_report,model_path)
        pending_report.setdefault('nativeDonorMatches', []).append({'model':model_path,
            'requirements':list(dict.fromkeys(requirements)), **match.audit()})
    classify_model(result.get('metadata', {}) or {}, model_path)
    if report is not None:
        for key, rows in pending_report.items():
            report.setdefault(key, []).extend(rows)
    return result, match


def complete_payload(model, native, raw_capacity, *, match=None, model_path='', report=None, preserve_tf2=False):
    """Use a donor's declared ratio or its verified optional air-field omission."""
    _number(raw_capacity,'raw maximum cargo capacity')
    hints = legacy_payload_hints(model)
    if raw_capacity == 0:
        return 0, 'no_payload_for_zero_capacity'
    if hints and hints['weightMaxPayload'] is not None:
        profile = classify_missing_model(model, model_path)
        block = {'RAIL': 'landVehicle', 'TRAM': 'landVehicle', 'ROAD': 'landVehicle',
                 'AIR': 'airVehicle', 'WATER': 'waterVehicle'}.get(profile.carrier)
        if block is None:
            raise ValueError('Authored EMP payload requires a verified physical vehicle carrier')
        value, label = hints['weightMaxPayload'], 'authored_emp_payload_tonnes_to_kg'
        if report is not None:
            report.setdefault('dataCompletions', []).append({
                'model': model_path, 'field': block+'.weightMaxPayload', 'sourceField': 'transportVehicle.maxWeight',
                'sourceValue': hints['sourceFields']['maxWeight'], 'value': value,
                'unitMultiplier': 1000, 'sourceUnit': 't', 'targetUnit': 'kg',
                'schemaSource': hints['schemaSource'], 'estimated': False, 'method': label,
                'nativeTest': 'not_run'})
        return value, label
    if preserve_tf2:
        air = (model.get('metadata') or {}).get('airVehicle') or {}
        supplied = air.get('maxPayload')
        value = _number(supplied, 'airVehicle.maxPayload') if supplied is not None else 0
        label = 'preserve_tf2_authored_payload' if supplied is not None else 'preserve_tf2_constant_vehicle_mass'
        if report is not None:
            report.setdefault('dataCompletions', []).append({'model': model_path,
                'field': 'weightMaxPayload', 'value': value, 'sourceValue': supplied,
                'rawCapacity': raw_capacity, 'method': label, 'estimated': supplied is None,
                'nativeTest': 'not_run'})
        return value, label
    omission = _aircraft_payload_omission(model, native, model_path)
    if omission is not None:
        label = 'native_air_profile_omits_optional_payload'
        if report is not None:
            report.setdefault('dataCompletions', []).append({
                'model': model_path, 'field': 'airVehicle.weightMaxPayload',
                'sourceValue': None, 'value': None, 'donorValue': None,
                'estimated': False, 'method': label, 'rawCapacity': raw_capacity,
                'nativeClassPolicy': omission,
                'requiredCheck': 'Verify the aircraft load behavior in TF3.',
                'nativeTest': 'not_run'})
        return None, label
    if match is None:
        match = NativeDonorCatalog.from_native(native).match(model,model_path=model_path,
                                                           requirements=('nativePayloadPolicy',))
    policy = match.value('nativePayloadPolicy')
    if policy['policy'] == 'omit_as_selected_native_profile':
        value, label = None, 'native_air_profile_omits_optional_payload'
    else:
        ratio = _number(policy['ratio'],'native payload per raw capacity')
        if ratio <= 0:
            raise ValueError('Matched native payload ratio must be positive')
        value, label = ratio*raw_capacity, 'matched_native_capacity_ratio'
        _number(value,'completed native payload')
    if report is not None:
        report.setdefault('dataCompletions', []).append(_audit(match,model_path,policy['field'],
            policy['field'],value,match.metadata.get(policy['field'].split('.')[0],{}).get('weightMaxPayload'),
            method=label,rawCapacity=raw_capacity,donorRawCapacity=match.raw_capacity,
            donorPolicy=policy))
    return value, label

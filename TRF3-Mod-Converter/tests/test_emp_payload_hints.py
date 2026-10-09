from copy import deepcopy
import json

import pytest

from trf3_mod_converter.missing_data import complete_missing_model, complete_payload, legacy_payload_hints
from trf3_mod_converter.tf2_vehicle_port import port_tf2_mod, snapshot
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.vehicle_profiles import adapt_vehicle_metadata, derive_lod_nodes
from test_missing_data import pair
from test_tf2_vehicle_port import fixture_mod, model, Native
from test_export_profiles import cargo_files, native_files, write_model


def with_hints(source):
    source['metadata']['transportVehicle'].update(maxWeight=62.5, maxVolume=163.85)
    return source


def test_authored_emp_payload_uses_documented_tonnes_instead_of_guessing_a_donor():
    source, _ = pair(cargo='COAL')
    with_hints(source)
    before, report = deepcopy(source), {}
    assert legacy_payload_hints(source)['weightMaxPayload'] == 62500
    completed, match = complete_missing_model(source, object(), report=report)
    value, policy = complete_payload(source, object(), 40, match=match, report=report, model_path='wagon.mdl')
    assert value == 62500 and policy == 'authored_emp_payload_tonnes_to_kg'
    assert match is None and source == before and completed == before
    row = report['dataCompletions'][0]
    assert row['sourceValue'] == 62.5 and row['unitMultiplier'] == 1000
    assert row['estimated'] is False and row['targetUnit'] == 'kg' and 'donorResource' not in row


@pytest.mark.parametrize('field,value', [
    ('maxWeight', True), ('maxWeight', 0), ('maxWeight', -1), ('maxWeight', float('nan')),
    ('maxWeight', float('inf')), ('maxWeight', '62.5'), ('maxWeight', [30, 32.5]),
    ('maxWeight', 1e308), ('maxVolume', False), ('maxVolume', 0), ('maxVolume', -1),
    ('maxVolume', float('nan')), ('maxVolume', [100, 63.85]),
])
def test_invalid_or_compartment_limits_are_not_guessed(field, value):
    source = with_hints(model())
    source['metadata']['transportVehicle'][field] = value
    before = deepcopy(source)
    with pytest.raises(ValueError):
        legacy_payload_hints(source)
    assert source == before


@pytest.mark.parametrize('max_weight,provided_payload,max_volume', [
    ([30, 32.5], 62500, 163.85), (True, 62500, 163.85), (62.5, None, 163.85),
    (62.5, 10000, 163.85), (62.5, 62500, [163.85]),
])
def test_direct_vehicle_adapter_requires_valid_hints_and_exact_payload(max_weight, provided_payload, max_volume):
    source = with_hints(model())
    source['metadata']['transportVehicle'].update(maxWeight=max_weight, maxVolume=max_volume)
    nodes, transforms = derive_lod_nodes(deepcopy(source['lods']), metadata=source['metadata'])
    before = deepcopy(source)
    with pytest.raises(ValueError):
        adapt_vehicle_metadata(source['metadata'], nodes, lambda ref, kind: ref, Native(),
                               weight_max_payload=provided_payload, node_world_transforms=transforms)
    assert source == before


def test_volume_alone_cannot_invent_payload_or_native_capacities():
    source = model()
    source['metadata']['transportVehicle']['maxVolume'] = 163.85
    assert legacy_payload_hints(source)['weightMaxPayload'] is None
    nodes, transforms = derive_lod_nodes(deepcopy(source['lods']), metadata=source['metadata'])
    with pytest.raises(ValueError, match='volume alone'):
        adapt_vehicle_metadata(source['metadata'], nodes, lambda ref, kind: ref, Native(),
                               weight_max_payload=62500, node_world_transforms=transforms)


def test_full_cargo_export_preserves_capacities_and_archives_extension_hints(fixture_mod):
    source, game, output = fixture_mod
    native_files(game, cargo_files())
    data = with_hints(model())
    data['metadata']['seatProvider'] = []
    data['metadata']['transportVehicle']['compartmentsList'] = [{'loadConfigs': [{
        'cargoEntries': [{'type': 'COAL', 'capacity': 40}], 'toHide': []}]}]
    write_model(source, data)
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture', name='Fixture')
    exported = load_lua_table((output/'content/models/model/vehicle/train/test.mdl').read_text())
    assert snapshot(source) == before
    assert exported['metadata']['landVehicle']['weightEmpty'] == 79500
    assert exported['metadata']['landVehicle']['weightMaxPayload'] == 62500
    assert exported['metadata']['landVehicle']['engines'][0]['power'] == 1220
    transport = exported['metadata']['transportVehicle']
    assert 'maxWeight' not in transport and 'maxVolume' not in transport
    loads = transport['compartments'][0]['loadConfigs']
    assert all(load['cargoEntry']['capacity'] == 40 for load in loads)
    audit = report['migrationAudit']
    assert audit['cargoMigrations'][0]['payloadPolicy'] == 'authored_emp_payload_tonnes_to_kg'
    volume = next(row for row in audit['vehicleAdaptations'] if row['field'] == 'transportVehicle/maxVolume')
    assert volume['sourceValue'] == 163.85 and volume['sourceUnit'] == 'm3'
    assert volume['method'] == 'archive_emp_volume_hint_preserve_authored_capacity'
    assert not any('donor' in ref for ref in report['baseGameResources'])
    archived = load_lua_table((output/'_port_originals/res/models/model/vehicle/train/test.mdl').read_text())
    assert archived['metadata']['transportVehicle']['maxWeight'] == 62.5
    assert json.loads((output/'conversion-report.json').read_text()) == report

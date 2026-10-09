from copy import deepcopy
import json
import zipfile

import pytest

from test_tf2_vehicle_port import fixture_mod
from test_vehicle_profiles import adapt, lods, plane, road, ship
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.missing_data import complete_missing_model
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot
from trf3_mod_converter.vehicle_profiles import classify_model


@pytest.mark.parametrize('factory,block,path', [
    (road, 'roadVehicle', 'models/model/asset/car/example.mdl'),
    (plane, 'airVehicle', 'models/model/vehicle/asset/example.mdl'),
    (ship, 'waterVehicle', 'models/model/asset/example.mdl'),
])
def test_decorative_physics_keeps_authored_config_without_creating_transport(factory, block, path):
    source = factory()
    del source['transportVehicle']
    before = deepcopy(source)
    report = {}
    target, profile, nodes, generated = adapt(source, model_path=path, report=report)
    assert source == before
    assert profile.family == 'asset' and profile.carrier is None
    assert profile.decorative_physics == block
    assert profile.transport_modes == profile.engine_transport_modes == ()
    assert 'transportVehicle' not in target and 'car' not in target
    assert target['transformatorConfig']['transformator']['name'].endswith(profile.transformer)
    if block != 'waterVehicle':
        assert target[block]['config']
    assert report['vehicleAdaptations'][-1]['createdTransportMetadata'] is False
    assert report['vehicleAdaptations'][-1]['createdCarMetadata'] is False
    if block == 'roadVehicle':
        assert target['landVehicle']['engines'][0]['power'] == source[block]['engine']['power']
        assert target['landVehicle']['weightEmpty'] == source[block]['weight']*1000
        assert 'brake_lights_on' in nodes[0][4]['animations']
    elif block == 'airVehicle':
        assert target[block]['wingArea'] == source[block]['wingArea']
        assert 'elevator' in generated
    else:
        assert target[block]['waterLine'] == source[block]['waterLine']
        assert 'rudder' in generated


def test_decorative_models_never_receive_donor_simulation_data():
    metadata = road()
    del metadata['transportVehicle']
    model = {'version':1, 'metadata':metadata}
    report = {}
    # There is no donor inventory on this sentinel: a donor query would fail.
    copied, match = complete_missing_model(model, object(), model_path='asset/car/example.mdl', report=report)
    assert copied == model and copied is not model
    assert match is None and report == {}


@pytest.mark.parametrize('mutation,path,error', [
    (lambda m: m.pop('transportVehicle'), 'vehicle/bus/example.mdl', 'carrier'),
    (lambda m: m.update(transportVehicle={}), 'asset/car/example.mdl', 'carrier'),
    (lambda m: m['transportVehicle'].update(carrier='RAIL'), 'asset/car/example.mdl', 'carrier'),
])
def test_asset_hint_cannot_repair_missing_or_conflicting_transport_identity(mutation, path, error):
    metadata = road()
    mutation(metadata)
    with pytest.raises(ValueError, match=error):
        classify_model(metadata, path)


def test_decorative_path_does_not_hide_authored_behavior_or_missing_physics():
    source = road()
    del source['transportVehicle']
    source['emission'] = {'idleEmission':70, 'powerEmission':0, 'speedEmission':.8}
    with pytest.raises(ValueError, match='balancing decision'):
        adapt(source, model_path='asset/car/example.mdl')
    del source['emission']
    source['roadVehicle']['customSimulation'] = 1
    with pytest.raises(ValueError, match='Unsupported roadVehicle fields'):
        adapt(source, model_path='asset/car/example.mdl')
    del source['roadVehicle']['customSimulation']
    del source['roadVehicle']['weight']
    with pytest.raises(ValueError, match='weight'):
        adapt(source, model_path='asset/car/example.mdl')


def test_trailing_decorative_lods_retain_absence_of_config_driven_animation():
    source = road()
    del source['transportVehicle']
    models = lods() + deepcopy(lods())
    report = {}
    target, _, nodes, _ = adapt(source, models=models, model_path='asset/car/example.mdl', report=report)
    assert 'brake_lights_on' in nodes[0][4]['animations']
    assert 'animations' not in nodes[1][4]
    assert target['roadVehicle']['config']['fakeBogies'] == [[], []]
    assert any(row.get('sourceCount') == 1 and row.get('targetCount') == 2 for row in report['vehicleAdaptations'])
    source['transportVehicle'] = {'carrier':'ROAD', 'compartmentsList':[]}
    with pytest.raises(ValueError, match='configs must match'):
        adapt(source, models=models, model_path='vehicle/bus/example.mdl')


def test_only_empty_decorative_ship_engine_lists_are_omitted_with_audit():
    source = ship()
    del source['transportVehicle']
    source['waterVehicle']['engines'] = []
    report = {}
    target = adapt(source, model_path='asset/ship.mdl', report=report)[0]
    assert 'engines' not in target['waterVehicle']
    assert source['waterVehicle']['engines'] == []
    assert any(row.get('field') == 'waterVehicle/engines' and row.get('sourceValue') == [] for row in report['vehicleAdaptations'])
    source['waterVehicle']['engines'] = [{'power': 5}]
    with pytest.raises(ValueError, match='active engine data'):
        adapt(source, model_path='asset/ship.mdl')


def test_full_package_ports_decorative_road_config_and_preserves_source(fixture_mod):
    source, game, output = fixture_mod
    original = source/'res/models/model/vehicle/train/test.mdl'
    data = load_lua_table(original.read_text())
    data['metadata'] = {
        'availability': {'yearFrom':2002, 'yearTo':0},
        'roadVehicle': {'engine':{'type':'DIESEL','power':102,'tractiveEffort':6},
                        'topSpeed':27.78, 'weight':1.35,
                        'configs':[{'wheels':['wheel.msh'], 'brakeLights':[4]}],
                        'soundSet':{'name':''}},
    }
    asset = source/'res/models/model/asset/car/example.mdl'
    asset.parent.mkdir(parents=True)
    asset.write_text(emit(data))
    original.unlink()
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('vehicle/shared/default_road.trf.lua','return {}')
        for event in ('brake_lights_on','brake_lights_off'):
            archive.writestr(f'vehicle/shared/ani/{event}.ani','return {}')
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    target = load_lua_table((output/'content/models/model/asset/car/example.mdl').read_text())
    assert target['version'] == 2
    assert 'transportVehicle' not in target['metadata'] and 'car' not in target['metadata']
    assert target['metadata']['landVehicle']['weightEmpty'] == 1350
    assert target['metadata']['roadVehicle']['config']['wheels'] == ['wheel']
    assert 'brake_lights_on' in target['lods'][0]['node']['children'][2]['animations']
    assert snapshot(source) == before and report['sourceUnchanged']
    assert json.loads((output/'conversion-report.json').read_text()) == report
    assert report['migrationAudit']['vehicleProfiles'][0]['profile'] == 'tf2_asset_road'

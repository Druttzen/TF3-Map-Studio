from copy import deepcopy
import math

import pytest

from trf3_mod_converter.lua_metadata import UnsupportedValue, TranslatedString
from trf3_mod_converter.vehicle_profiles import (
    adapt_vehicle_metadata, classify_model, derive_lod_nodes,
)


class Native:
    def reference(self, path):
        return '::/' + path


def resolve(ref, kind):
    return 'fixture::/' + kind + '/' + ref


def lods():
    return [{'node': {'name': 'root', 'children': [
        {'name': 'body', 'children': [{'name': 'body', 'mesh': 'body.msh'}]},
        {'name': 'wheel', 'mesh': 'wheel.msh'},
        {'name': 'light', 'mesh': 'light.msh'},
        {'name': 'control', 'mesh': 'control.msh'},
    ]}}]


def cargo(type_):
    return [{'loadConfigs': [{'cargoEntries': [{'type': type_, 'capacity': 20}]}]}]


def rail(engine='ELECTRIC', carrier='RAIL'):
    return {'transportVehicle': {'carrier': carrier, 'compartmentsList': cargo('PASSENGERS')},
            'railVehicle': {'engines': [] if engine is None else [{'type': engine, 'power': 150, 'tractiveEffort': 30}],
                            'topSpeed': 22, 'weight': 14, 'soundSet': {'name': 'train_sound', 'horn': 'horn.wav'},
                            'configs': [{'axles': ['wheel.msh'], 'fakeBogies': [{'group': 1, 'position': 0, 'offset': 0}],
                                         'frontForwardParts': [4]}]}}


def road(type_='PASSENGERS', car=False):
    result = {'roadVehicle': {'engine': {'type': 'DIESEL', 'power': 120, 'tractiveEffort': 30},
                              'topSpeed': 18, 'weight': 4.5,
                              'configs': [{'wheels': ['wheel.msh'], 'steeringParts': [3],
                                           'brakeLights': [4], 'headLights': [4], 'blinkLightsLeft': [5]}]}}
    if car:
        result['car'] = []
    else:
        result['transportVehicle'] = {'carrier': 'ROAD', 'compartmentsList': cargo(type_)}
    return result


def ship(type_='SMALL'):
    return {'transportVehicle': {'carrier': 'WATER', 'compartmentsList': cargo('COAL')},
            'waterVehicle': {'configs': [{'paddles': {'ids': [3], 'maxAngle': 0},
                                         'rudder': {'ids': [5], 'maxAngle': 22}}],
                             'waterLine': [[-5, 0], [0, 2], [5, 0]], 'area': 5, 'availPower': 294000,
                             'weight': 135000, 'maxRpm': 55, 'topSpeed': 7.5, 'type': type_},
            'soundConfig': {'effects': [], 'soundSet': {'name': 'ship_sound', 'horn': 'horn.wav'}}}


def plane(type_='BIG'):
    return {'transportVehicle': {'carrier': 'AIR', 'compartmentsList': cargo('PASSENGERS')},
            'airVehicle': {'configs': [{'axles': ['wheel.msh'], 'axleRadii': [0.6], 'wheels': [], 'wheelRadii': [],
                                       'elevator': {'ids': [5], 'maxAngle': 20}, 'landingLight': [4]}],
                           'maxPayload': 0, 'maxTakeOffWeight': 78000, 'maxThrust': 236000,
                           'idleThrust': 11800, 'timeToFullThrust': 3, 'topSpeed': 230,
                           'weight': 44000, 'wingArea': 122.6, 'type': type_},
            'soundConfig': {'soundSet': {'name': 'aircraft_sound'}}}


def adapt(metadata, *, models=None, **kwargs):
    models = lods() if models is None else models
    nodes, transfs = derive_lod_nodes(models)
    generated = {}
    def writer(event, data):
        generated[event] = deepcopy(data)
        return f'fixture::/models/animation/generated/{event}.ani'
    result, profile = adapt_vehicle_metadata(metadata, nodes, resolve, Native(), node_world_transforms=transfs,
                                              animation_writer=writer, **kwargs)
    return result, profile, nodes, generated


@pytest.mark.parametrize('engine, expected', [('ELECTRIC', ['ELECTRIC_TRAIN']), ('DIESEL', ['TRAIN', 'ELECTRIC_TRAIN']),
                                            ('STEAM', ['TRAIN', 'ELECTRIC_TRAIN']), ('HORSE', ['TRAIN', 'ELECTRIC_TRAIN']), (None, [])])
def test_rail_engine_modes_units_and_unpowered_wagons(engine, expected):
    source = rail(engine); before = deepcopy(source)
    result, profile, nodes, _ = adapt(source, weight_max_payload=8000)
    assert source == before
    physics = result['landVehicle']
    assert physics['weightEmpty'] == 14000 and physics['weightMaxPayload'] == 8000
    assert physics['topSpeed'] == 22
    assert (physics['engines'][0]['power'], physics['engines'][0]['tractiveEffort']) == (150, 30) if engine else not physics['engines']
    assert result['transportVehicle']['engineTransportModes'] == expected
    assert profile.family == ('waggon' if engine is None else 'train')
    assert result['railVehicle']['config']['axles'] == ['wheel']
    assert result['railVehicle']['config']['fakeBogies'][0][0]['group'] == 'body'
    assert nodes[0][2]['name'] == 'body_mesh'
    assert 'front_forward_parts_on' in nodes[0][4]['animations']


@pytest.mark.parametrize('source,family,mode', [(road(), 'bus', 'BUS'), (road('COAL'), 'truck', 'TRUCK'),
                                              (road(car=True), 'car', None), (rail(carrier='TRAM'), 'tram', 'ELECTRIC_TRAM')])
def test_road_tram_car_profiles(source, family, mode):
    result, profile, nodes, _ = adapt(source)
    assert profile.family == family
    if mode:
        assert mode in result['transportVehicle']['engineTransportModes']
    else:
        assert 'transportVehicle' not in result and result['car'] == []
    assert '/default_road.trf' in result['transformatorConfig']['transformator']['name'] if family != 'tram' else '/default_tram.trf' in result['transformatorConfig']['transformator']['name']
    if family != 'tram':
        assert result['roadVehicle']['config']['wheels'] == ['wheel']
        assert nodes[0][4]['animations']['brake_lights_on']['params']['id'].endswith('brake_lights_on.ani')


def test_ship_keeps_si_physics_and_generates_exact_rudder_angle():
    result, profile, nodes, generated = adapt(ship(), weight_max_payload=30000)
    physics = result['waterVehicle']
    assert profile.family == 'ship'
    assert physics['weightEmpty'] == 135000 and physics['availPower'] == 294000
    assert physics['weightMaxPayload'] == 30000
    assert 'configs' not in physics and physics['waterLine'] == ship()['waterVehicle']['waterLine']
    assert result['transportVehicle']['transportModes'] == ['SMALL_SHIP']
    assert nodes[0][3]['animations']['paddles']['params']['id'].endswith('paddles.ani')
    assert generated['rudder']['times'] == list(range(0, 1001, 10))
    assert math.atan2(generated['rudder']['transfs'][0][1], generated['rudder']['transfs'][0][0]) == pytest.approx(math.radians(22))
    assert math.atan2(generated['rudder']['transfs'][-1][1], generated['rudder']['transfs'][-1][0]) == pytest.approx(-math.radians(22))


def test_aircraft_world_gear_positions_and_preserves_inert_legacy_values_in_report():
    models = lods()
    models[0]['node']['transf'] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 0, 1, 1]
    models[0]['node']['children'][1]['transf'] = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 4, 0, 0.6, 1]
    report = {}
    result, profile, nodes, generated = adapt(plane(), models=models, report=report)
    physics = result['airVehicle']
    assert profile.family == 'plane'
    assert physics['weightEmpty'] == 44000 and physics['maxThrust'] == 236000
    assert physics['axles'] == [{'position': [14, 1.6], 'radius': 0.6}]
    assert physics['config']['axleRadii'] == [0.6]
    assert physics['config']['axles'] == ['wheel']
    assert [entry['field'] for entry in report['legacyVehicleFields']] == ['airVehicle/maxPayload', 'airVehicle/maxTakeOffWeight']
    assert 'elevator' in generated and 'landing_light_on' in nodes[0][4]['animations']
    assert result['transportVehicle']['transportModes'] == ['AIRCRAFT']


@pytest.mark.parametrize('factory,mode', [(lambda: ship('BIG'), 'SHIP'), (lambda: plane('SMALL'), 'SMALL_AIRCRAFT')])
def test_small_big_infrastructure_restrictions(factory, mode):
    assert adapt(factory())[0]['transportVehicle']['transportModes'] == [mode]


def test_seats_crew_refs_maintenance_and_automatic_emissions():
    source = rail()
    source.update(seatProvider={'crewModels': ['characters/driver.mdl'], 'seats': [{'group': 1, 'crew': True}]},
                  maintenance={'lifespan': 40 * 730, 'runningCosts': -1},
                  emission={'idleEmission': -1, 'powerEmission': -1, 'speedEmission': -1})
    result, _, _, _ = adapt(source)
    assert result['seatProvider']['crewModels'] == ['fixture::/model/characters/driver.mdl']
    assert result['seatProvider']['seats'][0]['group'] == 'body'
    assert result['maintenance']['lifespan'] == 40 * 365 * 4
    assert result['emissions'] == {'noise': {'score': -1}, 'pollution': {'score': -1}}


@pytest.mark.parametrize('factory,license_', [
    (road, 'BUS'), (lambda: road('COAL'), 'TRUCK'), (lambda: rail(carrier='TRAM'), 'TRAM'),
    (rail, 'RAIL'), (lambda: rail(None), 'RAIL'), (ship, 'WATER'), (plane, 'AIR'),
])
def test_missing_crew_license_uses_verified_vehicle_family(factory, license_):
    source = factory()
    source['seatProvider'] = {'crewModels': [], 'seats': [{'group': 1, 'crew': True}]}
    assert adapt(source)[0]['seatProvider']['drivingLicense'] == license_
    source['seatProvider']['drivingLicense'] = 'AIR_OUTDOOR'
    assert adapt(source)[0]['seatProvider']['drivingLicense'] == 'AIR_OUTDOOR'
    del source['seatProvider']['drivingLicense']
    source['seatProvider']['crewModels'] = ['characters/custom_driver.mdl']
    assert 'drivingLicense' not in adapt(source)[0]['seatProvider']


def test_departure_delay_preserves_milliseconds_and_rejects_invalid_values():
    source = road()
    source['transportVehicle']['departureDelay'] = 2500
    assert adapt(source)[0]['transportVehicle']['departureDelay'] == 2500
    for invalid in (-1, True, '2500'):
        source['transportVehicle']['departureDelay'] = invalid
        with pytest.raises(ValueError, match='departureDelay'):
            adapt(source)


def test_aircraft_control_surfaces_do_not_falsely_enable_flaps():
    source = plane()
    assert adapt(source)[0]['airVehicle']['hasFlaps'] is False
    source['airVehicle']['configs'][0]['flaps'] = {'ids': [3], 'maxAngle': 20}
    assert adapt(source)[0]['airVehicle']['hasFlaps'] is True


def test_native_ship_redundant_zero_z_waterline_projects_without_guessing():
    source = ship()
    source['waterVehicle']['waterLine'] = [[-5, 0, 0], [0, 2], [5, 0, 0]]
    report = {}
    assert adapt(source, report=report)[0]['waterVehicle']['waterLine'] == [[-5, 0], [0, 2], [5, 0]]
    assert report['vehicleAdaptations'][0]['zeroZPoints'] == 2
    source['waterVehicle']['waterLine'][0][2] = 1
    with pytest.raises(ValueError, match='nonzero z'):
        adapt(source)


def test_invalid_seat_anchors_and_crew_fields_stop_export():
    source = road()
    source['seatProvider'] = {'drivingLicense': 'UNKNOWN', 'seats': []}
    with pytest.raises(ValueError, match='driving license'):
        adapt(source)
    source['seatProvider'] = {'seats': [{'group': 1, 'crew': 1}]}
    with pytest.raises(ValueError, match='crew must be a boolean'):
        adapt(source)
    source['seatProvider'] = {'seats': [{'group': 1, 'transf': [1, 2, 3]}]}
    with pytest.raises(ValueError, match='seat/transf'):
        adapt(source)


def test_literal_auxiliary_models_and_people_do_not_become_fake_transport_vehicles():
    for metadata, family in [({}, 'asset'), ({'description': {'name': 'Scenery'}}, 'asset'),
                             ({'person': {'gender': 'FEMALE', 'drivingLicenses': ['RAIL']}}, 'person')]:
        target, profile, _, _ = adapt(metadata)
        assert profile.family == family
        assert target == metadata
        assert 'landVehicle' not in target and 'transportVehicle' not in target


def test_translated_literal_display_strings_preserve_translation_markers():
    source = road()
    source['description'] = {'name': TranslatedString('BUS_NAME')}
    target = adapt(source)[0]
    assert isinstance(target['description']['name'], TranslatedString)
    assert target['description']['name'] == 'BUS_NAME'


def test_road_capacity_evidence_overrides_folder_hint_and_shared_extras_survive():
    source = road('COAL')
    source['particleSystem'] = {'emitters': [{'child': 1, 'frequency': 5}]}
    source['labelList'] = {'labels': [{'childId': 'body', 'type': 'LINE_NAME'}]}
    # Existing capacity evidence wins over a path incorrectly labelled bus.
    target, profile, _, _ = adapt(source, model_path='vehicle/bus/freight.mdl')
    assert profile.family == 'truck'
    assert target['particleSystem'] == source['particleSystem']
    assert target['labelList'] == source['labelList']


def test_visual_cargo_bay_type_does_not_turn_a_passenger_bus_into_a_truck():
    source = road()
    source['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['cargoBay'] = {'type': 'LEVEL'}
    assert classify_model(source).transport_modes == ('BUS',)
    source['transportVehicle'] = {'carrier': 'ROAD', 'capacities': [{'type': 'PASSENGERS', 'capacity': 20}]}
    assert adapt(source)[1].family == 'bus'


@pytest.mark.parametrize('mutation,error', [
    (lambda m: m.update(customCallback=UnsupportedValue('callback')), 'non-literal'),
    (lambda m: m.update(customScript={}), 'Unsupported model metadata'),
    (lambda m: m['railVehicle'].update(somePhysics=12), 'railVehicle fields'),
    (lambda m: m['railVehicle']['engines'][0].update(type='MAGIC'), 'engine type'),
    (lambda m: m['railVehicle']['engines'][0].update(power=float('inf')), 'finite number'),
    (lambda m: m['railVehicle']['configs'][0].update(axles=['missing.msh']), 'no node'),
    (lambda m: m['railVehicle']['configs'][0].update(frontForwardParts=[99]), 'node index'),
    (lambda m: m.update(emission={'idleEmission': 20}), 'noise/pollution'),
    (lambda m: m['railVehicle'].update(blinkInterval=700), 'blinkInterval'),
    (lambda m: m.update(roadVehicle={}), 'Conflicting'),
    (lambda m: m['transportVehicle'].update(carrier='AIR'), 'carrier'),
])
def test_unknown_unsafe_behavior_is_never_accepted(mutation, error):
    source = rail(); mutation(source)
    with pytest.raises(ValueError, match=error):
        adapt(source)


def test_air_gear_rejects_missing_radii_nonuniform_scale_and_animation_collision():
    source = plane(); source['airVehicle']['configs'][0]['axleRadii'] = []
    with pytest.raises(ValueError, match='radius counts'):
        adapt(source)
    models = lods(); models[0]['node']['transf'] = [2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    with pytest.raises(ValueError, match='non-uniform'):
        adapt(plane(), models=models)
    models = lods(); models[0]['node']['children'][2]['animations'] = {'front_forward_parts_on': {}}
    with pytest.raises(ValueError, match='Existing front_forward_parts_on'):
        adapt(rail(), models=models)


def test_ambiguous_names_invalid_transforms_and_vehicleless_car_are_refused():
    models = lods(); models[0]['node']['children'].append({'name': 'wheel', 'mesh': 'second.msh'})
    models[0]['node']['children'].append({'name': 'wheel', 'mesh': 'third.msh'})
    with pytest.raises(ValueError, match='Ambiguous'):
        derive_lod_nodes(models)
    models = lods(); models[0]['node']['transf'] = [1] * 16
    with pytest.raises(ValueError, match='projective'):
        derive_lod_nodes(models)
    with pytest.raises(ValueError):
        classify_model({'car': [], 'transportVehicle': {'carrier': 'ROAD'}})


def test_duplicate_numeric_node_references_can_be_named_but_ambiguous_string_references_block():
    models = lods()
    models[0]['node']['children'] += [{'name': 'bogie'}, {'name': 'bogie'}]
    nodes, _ = derive_lod_nodes(models, metadata={'cameraConfig': {'positions': [{'group': 7}]}})
    assert nodes[0][6]['name'] == 'bogie' and nodes[0][7]['name'] == 'bogie__2'
    models = lods()
    models[0]['node']['children'] += [{'name': 'bogie'}, {'name': 'bogie'}]
    with pytest.raises(ValueError, match='Ambiguous node name reference'):
        derive_lod_nodes(models, metadata={'cameraConfig': {'positions': [{'group': 'bogie'}]}})


def test_empty_legacy_ship_flags_and_trailing_unconfigured_lods_are_safe():
    source = ship()
    source['waterVehicle']['configs'][0]['flags'] = {'ids': [], 'maxAngle': 0}
    models = lods() * 2
    report = {}
    target, _, _, _ = adapt(source, models=models, report=report)
    assert 'flags' not in target['waterVehicle']
    assert report['vehicleAdaptations'][0]['sourceCount'] == 1
    assert report['vehicleAdaptations'][0]['targetCount'] == 2
    source['waterVehicle']['configs'][0]['flags']['ids'] = [5]
    with pytest.raises(ValueError, match='Non-empty legacy ship flag'):
        adapt(source)

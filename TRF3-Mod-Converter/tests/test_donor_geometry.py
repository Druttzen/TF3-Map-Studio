from copy import deepcopy
from types import SimpleNamespace

import pytest

from trf3_mod_converter.donor_geometry import air_gear_needs, complete_air_gear
from trf3_mod_converter.vehicle_profiles import IDENTITY


def source(*, lods=1, radii=None, scale=1):
    transform = list(IDENTITY)
    transform[0] = transform[5] = transform[10] = scale
    transform[12:15] = [4*scale, 0, scale]
    result = {
        'version': 1, 'boundingInfo': {'bbMin': [-10*scale, -5*scale, 0], 'bbMax': [10*scale, 5*scale, 8*scale]},
        'lods': [{'node': {'name': 'root', 'children': [
            {'name': 'main_gear', 'mesh': f'gear_lod{i}.msh', 'transf': deepcopy(transform)},
            {'name': 'nose_gear', 'mesh': f'nose_lod{i}.msh', 'transf': deepcopy(transform)},
        ]}} for i in range(lods)],
        'metadata': {'transportVehicle': {'carrier': 'AIR'}, 'airVehicle': {
            'type': 'BIG', 'configs': [{'axles': [f'gear_lod{i}.msh'], 'wheels': [f'nose_lod{i}.msh'],
                                       'wheelRadii': [0.25], 'steeringParts': [2]}
                                      for i in range(lods)]}},
    }
    if radii is not None:
        result['metadata']['airVehicle']['configs'][0]['axleRadii'] = radii
    return result


def donor(*, radius=0.6):
    result = source(radii=[radius])
    physical = result['metadata']['airVehicle']
    del physical['configs']
    physical['config'] = {'axles': ['main_gear'], 'axleRadii': [radius],
                          'wheels': ['nose_gear'], 'wheelRadii': [0.25], 'fakeBogies': [], 'steeringParts': []}
    result['metadata']['extent'] = deepcopy(result['boundingInfo'])
    result['version'] = 2
    return SimpleNamespace(model=result, resource='vehicle/plane/donor/donor.mdl', evidence={'sameSubtype': True})


def test_missing_radius_copies_corresponding_source_lod_and_preserves_input():
    model = source(lods=2, radii=[0.6]); before = deepcopy(model); log = {}
    result = complete_air_gear(model, report=log, model_path='plane.mdl')
    assert model == before
    assert result['metadata']['airVehicle']['configs'][1]['axleRadii'] == [0.6]
    assert not air_gear_needs(result)
    assert log['dataCompletions'][0]['method'] == 'exact_source_lod'
    assert log['dataCompletions'][0]['estimated'] is False
    assert result['metadata']['airVehicle']['configs'][1]['steeringParts'] == [2]


def test_source_lod_different_world_position_does_not_complete():
    model = source(lods=2, radii=[0.6])
    model['lods'][1]['node']['children'][0]['transf'][12] += 0.1
    result = complete_air_gear(model)
    assert air_gear_needs(result)
    assert 'axleRadii' not in result['metadata']['airVehicle']['configs'][1]


def test_source_existing_conflicting_lod_radius_is_not_overwritten():
    model = source(lods=2, radii=[0.6]); model['metadata']['airVehicle']['configs'][1]['axleRadii'] = [0.8]
    with pytest.raises(ValueError, match='conflicting radii'):
        complete_air_gear(model, donor())


def test_named_geometry_donor_completes_only_absent_radius_and_records_estimate():
    model = source(); before = deepcopy(model); selected = donor(); donor_before = deepcopy(selected.model); log = {}
    result = complete_air_gear(model, selected, report=log)
    assert model == before and selected.model == donor_before
    assert result['metadata']['airVehicle']['configs'][0]['axleRadii'] == [0.6]
    assert result['metadata']['airVehicle']['configs'][0]['wheelRadii'] == [0.25]
    assert result['lods'] == model['lods']
    assert log['dataCompletions'][0]['method'] == 'approximate_native_geometry_match'
    assert log['dataCompletions'][0]['needs_native_validation'] is True
    assert log['dataCompletions'][0]['donor'] == selected.resource


def test_uniform_body_and_node_scaling_converts_donor_world_radius_to_source_local_radius():
    model = source(scale=2)
    result = complete_air_gear(model, donor())
    assert result['metadata']['airVehicle']['configs'][0]['axleRadii'] == pytest.approx([0.6])
    model['lods'][0]['node']['children'][0]['transf'][0] = 1
    model['lods'][0]['node']['children'][0]['transf'][5] = 1
    model['lods'][0]['node']['children'][0]['transf'][10] = 1
    result = complete_air_gear(model, donor())
    assert result['metadata']['airVehicle']['configs'][0]['axleRadii'] == pytest.approx([1.2])


@pytest.mark.parametrize('field,value', [('axleRadii', [-1]), ('axleRadii', [float('nan')]),
                                        ('axleRadii', [0.2, 0.3]), ('axleRadii', '0.6')])
def test_existing_invalid_or_excess_radii_remain_blockers(field, value):
    model = source(); model['metadata']['airVehicle']['configs'][0][field] = value
    with pytest.raises(ValueError):
        complete_air_gear(model, donor())


@pytest.mark.parametrize('change', ['name', 'role', 'position', 'nonuniform_body', 'nonuniform_node', 'shear', 'missing_bounds'])
def test_incompatible_geometry_donor_is_rejected(change):
    model = source(); selected = donor()
    if change == 'name':
        model['lods'][0]['node']['children'][0]['name'] = 'other_gear'
    elif change == 'role':
        config = selected.model['metadata']['airVehicle']['config']
        config['axles'], config['wheels'] = config['wheels'], config['axles']
    elif change == 'position':
        model['lods'][0]['node']['children'][0]['transf'][12] += 1
    elif change == 'nonuniform_body':
        model['boundingInfo']['bbMax'][2] = 20
    elif change == 'nonuniform_node':
        model['lods'][0]['node']['children'][0]['transf'][5] = 2
    elif change == 'shear':
        model['lods'][0]['node']['children'][0]['transf'][1] = 0.25
    else:
        del model['boundingInfo']
    with pytest.raises(ValueError):
        complete_air_gear(model, selected)


def test_anonymous_source_node_cannot_borrow_donor_radius():
    model = source(); del model['lods'][0]['node']['children'][0]['name']
    with pytest.raises(ValueError):
        complete_air_gear(model, donor())


def test_partial_arrays_fill_only_none_and_keep_existing_values():
    model = source(); config = model['metadata']['airVehicle']['configs'][0]
    config['axleRadii'] = [None]
    result = complete_air_gear(model, donor())
    assert result['metadata']['airVehicle']['configs'][0]['axleRadii'] == [0.6]
    assert config['axleRadii'] == [None]


def test_donor_invalid_radius_rejected_and_existing_source_gear_not_replaced():
    with pytest.raises(ValueError, match='positive'):
        complete_air_gear(source(), donor(radius=-1))
    model = source(radii=[0.9])
    assert complete_air_gear(model, donor(radius=0.6)) == model
    model = source(radii=[0])
    assert complete_air_gear(model, donor(radius=0.6)) == model


def test_other_existing_gear_geometry_still_must_match_donor():
    model = source()
    model['lods'][0]['node']['children'][1]['transf'][12] += 2
    with pytest.raises(ValueError, match='2%'):
        complete_air_gear(model, donor())


def test_shared_source_mesh_needs_same_donor_radius_for_all_corresponding_nodes():
    model = source()
    model['lods'][0]['node']['children'].append(deepcopy(model['lods'][0]['node']['children'][0]))
    model['lods'][0]['node']['children'][-1]['name'] = 'main_gear_right'
    selected = donor()
    selected.model['lods'][0]['node']['children'].append(deepcopy(selected.model['lods'][0]['node']['children'][0]))
    selected.model['lods'][0]['node']['children'][-1]['name'] = 'main_gear_right'
    config = selected.model['metadata']['airVehicle']['config']
    config['axles'].append('main_gear_right'); config['axleRadii'].append(0.6)
    assert complete_air_gear(model, selected)['metadata']['airVehicle']['configs'][0]['axleRadii'] == [0.6]
    config['axleRadii'][-1] = 0.8
    with pytest.raises(ValueError, match='multiple incompatible'):
        complete_air_gear(model, selected)


def test_prefix_array_completes_later_mesh_without_reordering_present_entries():
    model = source(radii=[0.8]); selected = donor()
    for current in (model, selected.model):
        node = deepcopy(current['lods'][0]['node']['children'][0])
        node.update(name='rear_gear', mesh='rear_gear.msh')
        current['lods'][0]['node']['children'].append(node)
    config = model['metadata']['airVehicle']['configs'][0]
    config['axles'].append('rear_gear.msh')
    native_config = selected.model['metadata']['airVehicle']['config']
    native_config['axles'].append('rear_gear'); native_config['axleRadii'].append(0.7)
    result = complete_air_gear(model, selected)
    assert result['metadata']['airVehicle']['configs'][0]['axleRadii'] == [0.8, 0.7]


def test_non_aircraft_returns_copy_without_completion():
    model = {'version': 1, 'metadata': {'tree': {}}, 'lods': []}
    result = complete_air_gear(model, donor())
    assert result == model and result is not model and not air_gear_needs(model)

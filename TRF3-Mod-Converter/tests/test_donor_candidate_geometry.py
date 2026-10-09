from copy import deepcopy

import pytest

from trf3_mod_converter.missing_data import complete_missing_model
from trf3_mod_converter.native_donors import NativeDonorCatalog
from test_donor_geometry import source as gear_source, donor as gear_donor
from test_missing_data import pair
from test_native_donors import Native, source, donor


def aircraft_pair():
    src, dst = pair(carrier='AIR')
    geometry, native_geometry = gear_source(), gear_donor().model
    src['boundingInfo'], src['lods'] = geometry['boundingInfo'], geometry['lods']
    src['metadata']['airVehicle'].update(type='BIG', configs=geometry['metadata']['airVehicle']['configs'])
    dst['lods'] = native_geometry['lods']
    dst['metadata']['extent'] = native_geometry['metadata']['extent']
    dst['metadata']['transportVehicle']['transportModes'] = ['AIRCRAFT']
    dst['metadata']['airVehicle']['config'] = native_geometry['metadata']['airVehicle']['config']
    return src, dst


def scale_aircraft_geometry(model, scale):
    for key in ('bbMin', 'bbMax'):
        model['metadata']['extent'][key] = [value*scale for value in model['metadata']['extent'][key]]
    for node in model['lods'][0]['node']['children']:
        node['transf'][12:15] = [value*scale for value in node['transf'][12:15]]


def test_unusable_closest_aircraft_does_not_mask_compatible_geometric_candidate():
    src, bad = aircraft_pair()
    good = deepcopy(bad)
    bad['lods'][0]['node']['children'][0]['transf'][12] += 1
    scale_aircraft_geometry(good, 1.03)
    native = Native({'vehicle/plane/a_bad.mdl': bad, 'vehicle/plane/b_good.mdl': good})
    before, report = deepcopy(src), {}
    completed, match = complete_missing_model(src, native, report=report)
    assert match.resource == 'vehicle/plane/b_good.mdl'
    assert src == before and completed['lods'] == before['lods']
    assert completed['metadata']['airVehicle']['configs'][0]['axleRadii'] == pytest.approx([0.6/1.03])
    assert completed['metadata']['airVehicle']['configs'][0]['wheelRadii'] == [0.25]
    assert 'vehicle/plane/a_bad.mdl' not in native.references
    gate = next(row for row in match.evidence if row.get('gate') == 'exclude_incompatible_geometry')
    assert gate['candidates'][0]['resource'] == 'vehicle/plane/a_bad.mdl'
    assert '2%' in gate['candidates'][0]['reason']
    assert all(row.get('donor', match.resource) == match.resource for row in report['dataCompletions'])


def test_identical_native_radii_with_different_completed_source_radii_remain_ambiguous():
    src, first = aircraft_pair()
    second = deepcopy(first)
    scale_aircraft_geometry(second, 1.03)
    native = Native({'vehicle/plane/first.mdl': first, 'vehicle/plane/second.mdl': second})
    before, report = deepcopy(src), {}
    with pytest.raises(ValueError, match='Ambiguous installed TF3 donors'):
        complete_missing_model(src, native, report=report)
    assert src == before and report == {} and native.references == set()


def test_invalid_closest_waterline_does_not_mask_valid_uniform_hull_candidate():
    src, bad = pair(carrier='WATER')
    src['metadata']['waterVehicle'].pop('waterLine')
    good = deepcopy(bad)
    bad['metadata']['waterVehicle']['waterLine'] = [[0, 0], [1, 1]]
    for key in ('bbMin', 'bbMax'):
        good['metadata'].setdefault('extent', deepcopy(good['boundingInfo']))[key] = [
            value*1.03 for value in good['metadata']['extent'][key]]
    native = Native({'vehicle/ship/a_bad.mdl': bad, 'vehicle/ship/b_good.mdl': good})
    before, report = deepcopy(src), {}
    completed, match = complete_missing_model(src, native, report=report)
    assert match.resource == 'vehicle/ship/b_good.mdl' and src == before
    assert len(completed['metadata']['waterVehicle']['waterLine']) == 4
    assert completed['boundingInfo'] == before['boundingInfo']
    assert report['dataCompletions'][0]['method'] == 'approximate_native_hull_waterline'


def test_all_geometry_failures_preserve_atomicity_and_actionable_reason():
    src, dst = aircraft_pair()
    dst['lods'][0]['node']['children'][0]['transf'][12] += 1
    before, report = deepcopy(src), {}
    native = Native({'vehicle/plane/invalid.mdl': dst})
    with pytest.raises(ValueError, match='required geometry checks:.*2%'):
        complete_missing_model(src, native, report=report)
    assert src == before and report == {} and native.references == set()


def test_candidate_validation_cannot_bypass_propulsion_or_vehicle_class_gates():
    native = Native({'vehicle/train/electric.mdl': donor(engine='ELECTRIC')})
    catalog = NativeDonorCatalog.from_native(native)
    called = []
    with pytest.raises(ValueError, match='No sufficiently similar'):
        catalog.match(source(engine='DIESEL'), requirements=('nativePayloadPolicy',),
                      candidate_validator=lambda candidate: called.append(candidate.resource))
    assert called == [] and native.references == set()


def test_invalid_candidate_validator_is_reported_as_validation_error():
    catalog = NativeDonorCatalog.from_native(Native({'vehicle/train/donor.mdl': donor()}))
    with pytest.raises(ValueError, match='validator must be callable'):
        catalog.match(source(), requirements=('nativePayloadPolicy',), candidate_validator=True)

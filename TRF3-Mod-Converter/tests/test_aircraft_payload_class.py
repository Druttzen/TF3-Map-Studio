"""Optional aircraft load mass is a class contract, not donor physics."""
from copy import deepcopy
import hashlib

import pytest

from trf3_mod_converter.missing_data import complete_missing_model, complete_payload
from trf3_mod_converter.native_donors import NativeDonorCatalog
from trf3_mod_converter.tf2_vehicle_port import emit
from test_missing_data import pair
from test_native_donors import Native, bounds, donor


def aircraft(size='SMALL', cargo='PASSENGERS'):
    result = donor(carrier='AIR', size=size, cargo=cargo)
    result['metadata']['airVehicle'].pop('weightMaxPayload')
    return result


def test_unanimous_aircraft_omission_does_not_require_unrelated_physical_similarity():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    native_aircraft = aircraft(size='BIG', cargo='COAL')
    native_aircraft['metadata']['extent'] = bounds(100, 80, 30)
    native_aircraft['metadata']['airVehicle']['maxThrust'] = 800000
    native = Native({'vehicle/plane/large/large.mdl': native_aircraft})
    before = deepcopy(source); report = {}
    result, match = complete_missing_model(source, native, report=report)
    assert source == before and result == before and match is None
    value, method = complete_payload(result, native, 40, match=match, report=report)
    assert value is None and method == 'native_air_profile_omits_optional_payload'
    row = report['dataCompletions'][-1]
    assert row['estimated'] is False and row['value'] is None
    assert row['nativeClassPolicy']['policy'] == 'omit_as_verified_installed_aircraft_class'
    assert row['nativeClassPolicy']['nativeProfiles'] == ['vehicle/plane/large/large.mdl']
    assert row['nativeClassPolicy']['allProfilesOmitField'] is True
    assert 'nativeDonorMatches' not in report


def test_one_explicit_aircraft_payload_invalidates_the_class_omission_proof():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    omitted = aircraft(); explicit = donor(carrier='AIR', size='BIG')
    native = Native({'vehicle/plane/a/a.mdl': omitted, 'vehicle/plane/b/b.mdl': explicit})
    catalog = NativeDonorCatalog.from_native(native)
    assert catalog.aircraft_payload_omission(source) is None
    # The old compatible selected-profile omission remains usable.
    _, match = complete_missing_model(source, native)
    assert match.resource == 'vehicle/plane/a/a.mdl'


@pytest.mark.parametrize('suffix', ['.lua', '.tl'])
def test_suffixed_aircraft_cannot_hide_a_contradictory_explicit_payload(suffix):
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    omitted = aircraft(); explicit = donor(carrier='AIR', size='BIG')
    path = 'vehicle/plane/b/b.mdl' + suffix
    native = Native({'vehicle/plane/a/a.mdl': omitted, path: explicit})
    catalog = NativeDonorCatalog.from_native(native)
    assert path in native.reads
    assert {entry.resource for entry in catalog.donors} == {'vehicle/plane/a/a.mdl', 'vehicle/plane/b/b.mdl'}
    assert catalog.aircraft_payload_omission(source) is None


@pytest.mark.parametrize('suffix', ['.lua', '.tl'])
def test_malformed_suffixed_aircraft_cannot_disappear_from_class_completeness(suffix):
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    malformed = donor(carrier='AIR'); malformed.pop('boundingInfo'); malformed['metadata'].pop('extent')
    path = 'vehicle/plane/b/b.mdl' + suffix
    native = Native({'vehicle/plane/a/a.mdl': aircraft(), path: malformed})
    catalog = NativeDonorCatalog.from_native(native)
    assert path in native.reads
    assert any(row['resource'] == 'vehicle/plane/b/b.mdl' for row in catalog.diagnostics)
    assert catalog.aircraft_payload_omission(source) is None


def test_excluded_unclassified_native_definition_cannot_hide_an_explicit_aircraft_payload():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    broken = donor(carrier='AIR'); broken.pop('boundingInfo'); broken['metadata'].pop('extent')
    native = Native({'vehicle/plane/a/a.mdl': aircraft(), 'vehicle/plane/broken/broken.mdl': broken})
    catalog = NativeDonorCatalog.from_native(native)
    assert len(catalog.diagnostics) == 1
    assert catalog.aircraft_payload_omission(source) is None


def test_malformed_plane_cannot_hide_a_payload_in_a_helicopter_directory():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    broken = donor(carrier='AIR'); broken.pop('boundingInfo'); broken['metadata'].pop('extent')
    native = Native({'vehicle/plane/a/a.mdl': aircraft(), 'vehicle/helicopter/deceptive.mdl': broken})
    catalog = NativeDonorCatalog.from_native(native)
    assert catalog.aircraft_payload_omission(source) is None


def test_verified_literal_helicopter_is_not_an_aircraft_payload_profile_regardless_of_directory():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    helicopter = donor(carrier='AIR'); helicopter['metadata']['airVehicle']['isHelicopter'] = True
    helicopter['metadata']['transportVehicle']['transportModes'] = ['HELICOPTER']
    native = Native({'vehicle/plane/a/a.mdl': aircraft(), 'vehicle/plane/unrelated.mdl': helicopter})
    catalog = NativeDonorCatalog.from_native(native)
    assert catalog.diagnostics[0]['verifiedOutsideAircraftClass'] is True
    assert catalog.aircraft_payload_omission(source)['profileCount'] == 1


def test_no_installed_aircraft_and_non_air_source_do_not_claim_optional_air_payload():
    air, _ = pair(carrier='AIR', cargo='PASSENGERS'); rail, _ = pair(cargo='PASSENGERS')
    catalog = NativeDonorCatalog.from_native(Native({'vehicle/train/train.mdl': donor()}))
    assert catalog.aircraft_payload_omission(air) is None
    assert catalog.aircraft_payload_omission(rail) is None


def test_authored_emp_payload_stays_authoritative_without_accessing_native_class_data():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    source['metadata']['transportVehicle']['maxWeight'] = 7.5
    complete_missing_model(source, object())
    value, method = complete_payload(source, object(), 40)
    assert (value, method) == (7500, 'authored_emp_payload_tonnes_to_kg')


@pytest.mark.parametrize('invalid', [0, -1, True, float('inf')])
def test_class_omission_does_not_repair_invalid_source_geometry_or_weight(invalid):
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    source['metadata']['airVehicle']['weight'] = invalid
    report = {}
    with pytest.raises(ValueError):
        complete_missing_model(source, Native({'vehicle/plane/a/a.mdl': aircraft()}), report=report)
    assert report == {}


def test_class_payload_omission_keeps_missing_gear_geometry_a_required_donor_check():
    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    source['lods'][0]['node']['children'] = [{'name': 'source_wheel', 'mesh': 'wheel.msh'}]
    source['metadata']['airVehicle']['configs'] = [{'wheels': ['wheel.msh'], 'axles': []}]
    native_aircraft = aircraft()
    native_aircraft['metadata']['airVehicle']['config'] = {'wheels': [], 'wheelRadii': [],
                                                          'axles': [], 'axleRadii': []}
    report = {}
    with pytest.raises(ValueError, match='geometry checks'):
        complete_missing_model(source, Native({'vehicle/plane/a/a.mdl': native_aircraft}), report=report)
    assert report == {}


def test_aircraft_policy_bytes_are_kept_as_catalog_provenance_when_parsed_cache_is_reused():
    class FingerprintedNative(Native):
        def fingerprints(self, paths):
            return {path: hashlib.sha256(self.files[path]).hexdigest() for path in paths}

        def track_dependencies(self, values):
            self.dependencies = dict(values)

    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    resource = 'vehicle/plane/a/a.mdl'; native = FingerprintedNative({resource: aircraft()})
    catalog = NativeDonorCatalog.from_native(native)
    original_digest = hashlib.sha256(native.files[resource]).hexdigest()
    proof = catalog.aircraft_payload_omission(source)
    assert proof['nativeProfileFingerprints'] == {resource: original_digest}
    changed = donor(carrier='AIR'); native.files[resource] = emit(changed).encode()
    reused = NativeDonorCatalog.from_native(native)
    proof = reused.aircraft_payload_omission(source)
    assert proof['nativeProfileFingerprints'][resource] == original_digest
    assert native.dependencies[resource] == original_digest  # Final fresh hashing will reject changed bytes.


def test_class_proof_hashes_the_bytes_parsed_before_a_contradictory_file_change():
    resource = 'vehicle/plane/a/a.mdl'
    class ChangedAfterReadNative(Native):
        def read(self, path):
            original = super().read(path)
            if path == resource and not getattr(self, 'changed', False):
                self.changed = True
                self.files[path] = emit(donor(carrier='AIR')).encode()
            return original

        def fingerprints(self, paths):
            return {path: hashlib.sha256(self.files[path]).hexdigest() for path in paths}

        def track_dependencies(self, values):
            self.dependencies = dict(values)

    source, _ = pair(carrier='AIR', cargo='PASSENGERS')
    native = ChangedAfterReadNative({resource: aircraft()})
    parsed_digest = hashlib.sha256(native.files[resource]).hexdigest()
    catalog = NativeDonorCatalog.from_native(native)
    proof = catalog.aircraft_payload_omission(source)
    assert proof is not None
    assert proof['nativeProfileFingerprints'] == {resource: parsed_digest}
    assert catalog.resource_dependencies[resource] == parsed_digest
    assert native.dependencies[resource] == parsed_digest
    assert native.fingerprints(catalog.resource_dependencies) != catalog.resource_dependencies


@pytest.mark.parametrize('conflicting', [False, True])
def test_cargo_provenance_merge_cannot_replace_a_parsed_vehicle_digest(monkeypatch, conflicting):
    from trf3_mod_converter.cargo_port import CargoCatalog
    resource = 'vehicle/plane/a/a.mdl'
    native = Native({resource: aircraft()})
    parsed_digest = hashlib.sha256(native.files[resource]).hexdigest()
    cargo = CargoCatalog.from_native(native)
    cargo.resource_dependencies[resource] = '0' * 64 if conflicting else parsed_digest
    monkeypatch.setattr(CargoCatalog, 'from_native', lambda native: cargo)
    if conflicting:
        with pytest.raises(ValueError, match='changed between its cargo and vehicle interpretations'):
            NativeDonorCatalog.from_native(native)
        assert not hasattr(native, '_native_donor_catalog')
    else:
        catalog = NativeDonorCatalog.from_native(native)
        assert catalog.resource_dependencies[resource] == parsed_digest

"""An authored combined TF2 emission never acquires a silent TF3 split."""
from copy import deepcopy

import pytest

from trf3_mod_converter.lua_metadata import TranslatedString
from test_vehicle_profiles import adapt, rail


def model(emission=None):
    result = rail()
    result['emission'] = {'idleEmission': 68.5, 'powerEmission': 0,
                          'speedEmission': .8} if emission is None else emission
    return result


def test_explicit_noise_choice_keeps_coefficients_but_does_not_claim_pollution_equivalence():
    source = model(); before = deepcopy(source); report = {}
    target, _, _, _ = adapt(source, emissions_policy='legacy_noise', report=report,
                            model_path='vehicle/train/authored.mdl')
    assert source == before
    assert target['emissions'] == {'noise': {'idle': 68.5, 'power': 0, 'speed': .8},
                                   'pollution': {'score': -1}}
    assert 'score' not in target['emissions']['noise']  # Score would override the coefficients.
    choice = next(row for row in report['vehicleAdaptations'] if row['field'] == 'emission')
    assert choice['sourceValue'] == before['emission']
    assert choice['targetValue'] == target['emissions']
    assert choice['model'] == 'vehicle/train/authored.mdl'
    assert choice['emissionsPolicy'] == 'legacy_noise' and choice['explicitChoice'] is True
    assert choice['noiseCoefficientsPreserved'] is True
    assert choice['pollutionBehaviorPreserved'] is False and choice['nativeTest'] == 'not_run'


def test_automatic_choice_records_replaced_coefficients_and_can_handle_old_out_of_range_balancing():
    source = model({'idleEmission': 124.94, 'powerEmission': 0, 'speedEmission': .8})
    before = deepcopy(source); report = {}
    target, _, _, _ = adapt(source, emissions_policy='tf3_automatic', report=report)
    assert source == before
    assert target['emissions'] == {'noise': {'score': -1}, 'pollution': {'score': -1}}
    choice = next(row for row in report['vehicleAdaptations'] if row['field'] == 'emission')
    assert choice['sourceValue'] == before['emission']
    assert choice['emissionsPolicy'] == 'tf3_automatic'
    assert choice['noiseCoefficientsPreserved'] is False and choice['pollutionBehaviorPreserved'] is False


def test_default_strict_choice_keeps_explicit_source_blocked_before_mutating_report_or_animations():
    source = model(); before = deepcopy(source); report = {'previous': [1]}
    with pytest.raises(ValueError, match='noise/pollution balancing decision'):
        adapt(source, report=report)
    assert source == before and report == {'previous': [1]}


@pytest.mark.parametrize('emission', [
    {'idleEmission': 20},
    {'idleEmission': -1, 'powerEmission': 0, 'speedEmission': .8},
    {'idleEmission': 101, 'powerEmission': 0, 'speedEmission': .8},
    {'idleEmission': 20, 'powerEmission': .00021, 'speedEmission': .8},
    {'idleEmission': 20, 'powerEmission': 0, 'speedEmission': 2.1},
])
def test_noise_choice_does_not_guess_missing_or_automatic_coefficients_or_clamp(emission):
    source = model(emission); report = {}; before = deepcopy(source)
    with pytest.raises(ValueError, match='coefficient'):
        adapt(source, emissions_policy='legacy_noise', report=report)
    assert report == {} and source == before


@pytest.mark.parametrize('policy', ['strict', 'legacy_noise', 'tf3_automatic'])
@pytest.mark.parametrize('value', [True, None, '30', -2, float('inf'), float('nan')])
def test_explicit_choice_does_not_replace_malformed_or_non_finite_source_coefficients(policy, value):
    source = model({'idleEmission': value, 'powerEmission': 0, 'speedEmission': .8})
    report = {'previous': [1]}
    with pytest.raises(ValueError):
        adapt(source, emissions_policy=policy, report=report)
    assert report == {'previous': [1]}


@pytest.mark.parametrize('policy', [None, '', 'automatic', False, [], {}, TranslatedString('tf3_automatic')])
def test_invalid_or_localized_choice_is_rejected_even_without_emission_data(policy):
    source = rail(); report = {}
    with pytest.raises(ValueError, match='Emissions policy'):
        adapt(source, emissions_policy=policy, report=report)
    assert report == {}


@pytest.mark.parametrize('policy', ['strict', 'legacy_noise', 'tf3_automatic'])
def test_existing_automatic_values_continue_to_use_both_native_automatic_scores(policy):
    source = model({'idleEmission': -1, 'powerEmission': -1, 'speedEmission': -1})
    result = adapt(source, emissions_policy=policy)[0]
    assert result['emissions'] == {'noise': {'score': -1}, 'pollution': {'score': -1}}


def test_unknown_source_emission_fields_cannot_disappear_under_an_explicit_choice():
    source = model(); source['emission']['exhaustColor'] = [1, 0, 0]; report = {}
    with pytest.raises(ValueError, match='Unsupported emission fields'):
        adapt(source, emissions_policy='tf3_automatic', report=report)
    assert report == {}

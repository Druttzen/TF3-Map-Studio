"""Explicit draft choices shared by the CLI, queue and desktop app."""
from .vehicle_profiles import EMISSIONS_POLICIES


def validate_emissions_policy(value):
    if type(value) is not str or value not in EMISSIONS_POLICIES:
        raise ValueError('Choose a supported noise and pollution policy.')
    return value


VEHICLE_POLICIES = frozenset({'strict', 'tf2_complete'})


def validate_vehicle_policy(value):
    if type(value) is not str or value not in VEHICLE_POLICIES:
        raise ValueError('Choose a supported vehicle conversion policy.')
    return value


def conversion_choices(emissions_policy='strict', vehicle_policy='strict'):
    result = {'emissionsPolicy': validate_emissions_policy(emissions_policy)}
    if validate_vehicle_policy(vehicle_policy) != 'strict':
        result.update(vehiclePolicy=vehicle_policy, dependenciesPolicy='continue_with_warnings',
                      scope='vehicles')
    return result

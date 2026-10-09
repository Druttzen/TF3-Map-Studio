"""Audited sound helper identities and their authored brake parameters.

The helpers are identified by their complete file digest. Source Lua is neither
executed nor copied: the sound adapter uses the supported algorithms below.
"""
from collections.abc import Mapping


SOUND_HELPER_PROFILES = {
    'bbs2util': {
        '80b7d45c5df3adefcea88226e80e463300b848a968ad1c5b8ff99e9430fc1918': {
            'brake': {'threshold': .5, 'maxBrakeDecel': 2.5, 'fadeStart': 3., 'fadeEnd': 7.},
            'slow': {'threshold': .7, 'maxBrakeDecel': 2., 'fadeStart': 10., 'fadeEnd': 40.},
        },
        '2377f9c3ceeb9c782b4ae654308be7c166570b872a6553cd49eb01e1b2d0f027': {
            'brake': {'threshold': .5, 'maxBrakeDecel': 2.25, 'fadeStart': 3.75, 'fadeEnd': 6.75},
            'slow': {'threshold': .7, 'maxBrakeDecel': 2.5, 'fadeStart': 10., 'fadeEnd': 40.},
        },
    },
    'soundeffectsutil2': {
        '66370d4962c3fd8436197af6184b4eeb5635449b8e1ef75da31156b882a02f10': {
            'brake': {'threshold': .1, 'maxBrakeDecel': 2.5, 'fadeStart': 3., 'fadeEnd': 7.},
            'slow': {'threshold': .7, 'maxBrakeDecel': 2., 'fadeStart': 10., 'fadeEnd': 40.},
        },
    },
    'soundeffectsutil': {
        'a5f00cd3e74bcd6e29f4242a43e52ee38ed15e10eac8f6eb4ba99e196a0281e0': {
            'brake': {'threshold': .1, 'maxBrakeDecel': 5., 'fadeStart': 2., 'fadeEnd': 4.},
        },
    },
}


def verified_sound_helper_profiles(verified_helpers):
    """Return only exact profiles attested by the resource resolver.

The caller must hash the helper selected for this sound resource, including its
Workshop provider scope. Names alone do not establish the helper's behavior.
"""
    if verified_helpers is None:
        return {}
    if not isinstance(verified_helpers, Mapping):
        raise ValueError('Verified sound helpers require a module-to-SHA256 mapping')
    result = {}
    for module, digest in verified_helpers.items():
        if module in SOUND_HELPER_PROFILES and isinstance(digest, str):
            profile = SOUND_HELPER_PROFILES[module].get(digest)
            if profile is not None:
                result[module] = (digest, profile)
    return result


def authored_brake_script():
    """Compile the verified brake/slow formula for a TF3 Custom track.

Legacy math.min(brakeDecel/maxBrakeDecel) has one argument, so it does not
clamp the square-root gain to one. The authored raw brakeDecel input and the
two speed fades are preserved, rather than using TF3's smoothed Brake input.
"""
    return (
        'function data()\n'
        ' return { update = function(result, captureParams, currentInfo)\n'
        '  local speed = currentInfo.vehicle.speed\n'
        '  local brakeDecel = currentInfo.vehicle.brakeDecel\n'
        '  local gain = 0.0\n'
        '  if brakeDecel > captureParams.threshold then\n'
        '   local brakeGain = math.sqrt(brakeDecel / captureParams.maxBrakeDecel)\n'
        '   local speed1 = captureParams.fadeStart * (brakeGain + 1.0)\n'
        '   local speed2 = captureParams.fadeEnd * (brakeGain + 1.0)\n'
        '   local fadeIn = 1.0 - math.min(math.max((speed - speed1) / (speed2 - speed1), 0.0), 1.0)\n'
        '   local fadeOut = math.min(math.max(speed, 0.0), 1.0)\n'
        '   gain = fadeIn * fadeOut * brakeGain * captureParams.maxGain\n'
        '  end\n'
        '  result.gain = gain\n'
        '  result.pitch = 1.0\n'
        ' end }\n'
        'end\n'
    )


def authored_squeal_script():
    """Preserve the audited scalar squeal formula and literal force limit.

The native Squeal operation reads the vehicle's dynamic maxSideForce. An
authored constant must instead remain the constant supplied by the source.
TF3 exposes sideForce under railVehicle; its native squeal treats an absent
force as zero. Raw brakeDecel belongs to vehicle and remains separate.
"""
    return (
        'function data()\n'
        ' return { update = function(result, captureParams, currentInfo)\n'
        '  local speed = currentInfo.vehicle.speed\n'
        '  local railVehicle = currentInfo.railVehicle\n'
        '  local sideForce = (railVehicle and railVehicle.sideForce) or 0.0\n'
        '  local speedGain = 1.0 - math.min(math.max((speed - 20.0) / 20.0, 0.0), 1.0)\n'
        '  local diff = math.max(captureParams.maxSideForce - sideForce, 0.0)\n'
        '  result.gain = math.min(math.max(1.0 - 2.0 * diff, 0.0), 1.0) * speedGain\n'
        '  result.pitch = 1.0\n'
        ' end }\n'
        'end\n'
    )

import pytest

from trf3_mod_converter.tf2_sound_port import port_sound_set
from test_tf2_sound_port import SOUND, Native


def test_speed_ratio_alias_preserves_curve_and_other_controls():
    original = port_sound_set(SOUND, lambda r, k: r, Native())
    text = SOUND.replace('local axleRefWeight=10',
                         'local speed01=input.speed/input.topSpeed\n local axleRefWeight=5*2')
    text = text.replace('input.speed01', 'speed01')
    assert port_sound_set(text, lambda r, k: r, Native()) == original


def test_power_gain_and_speed_pitch_keep_separate_native_parameters():
    text = SOUND.replace('input.speed01),\n     pitch=', 'input.power01),\n     pitch=')
    result = port_sound_set(text, lambda r, k: r, Native())
    params = result['updateScript']['params']['updateFunctions'][0]['params']
    assert params['gainParamName'] == 'power01'
    assert params['pitchParamName'] == 'speed01'
    assert params['gainScriptingInfoKey'] == params['pitchScriptingInfoKey'] == 'vehicle'


@pytest.mark.parametrize('expression', [
    'input.speed/input.weight', 'input.topSpeed/input.speed',
    '2*input.speed/input.topSpeed', 'input.mystery', 'executeMod()',
])
def test_arbitrary_runtime_alias_is_still_rejected(expression):
    text = SOUND.replace('local axleRefWeight=10', 'local speed01='+expression+'\n local axleRefWeight=10')
    with pytest.raises(ValueError):
        port_sound_set(text.replace('input.speed01', 'speed01'), lambda r, k: r, Native())


def test_alias_cannot_be_reassigned_or_shadowed():
    text = SOUND.replace('local axleRefWeight=10',
                         'local speed01=input.speed/input.topSpeed\n speed01=0\n local axleRefWeight=10')
    with pytest.raises(ValueError):
        port_sound_set(text, lambda r, k: r, Native())

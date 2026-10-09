"""Explicit balancing choices must survive real exports and verified retries."""
import json

import pytest

from test_tf2_vehicle_port import fixture_mod
from trf3_mod_converter.batch import STATE_NAME, convert_queue, scan_mods
from trf3_mod_converter.cli import build_parser, main
from trf3_mod_converter.lua_metadata import TranslatedString, load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot


MODEL_RESOURCE = 'models/model/vehicle/train/test.mdl'
AUTHORED_EMISSIONS = {'idleEmission': 68.5, 'powerEmission': .0001, 'speedEmission': .8}
TARGET_EMISSIONS = {
    'legacy_noise': {'noise': {'idle': 68.5, 'power': .0001, 'speed': .8},
                     'pollution': {'score': -1}},
    'tf3_automatic': {'noise': {'score': -1}, 'pollution': {'score': -1}},
}


@pytest.fixture
def explicit_emissions_mod(fixture_mod):
    source, game, output = fixture_mod
    path = source / 'res' / MODEL_RESOURCE
    data = load_lua_table(path.read_text())
    data['metadata']['emission'] = dict(AUTHORED_EMISSIONS)
    path.write_text(emit(data), encoding='utf-8')
    return source, game, output


def assert_native_emissions_and_audit(target, report, policy, source):
    model = load_lua_table((target / 'content' / MODEL_RESOURCE).read_text())
    assert model['version'] == 2
    assert model['metadata']['emissions'] == TARGET_EMISSIONS[policy]
    assert 'emission' not in model['metadata']
    if policy == 'legacy_noise':
        assert 'score' not in model['metadata']['emissions']['noise']
    assert report['conversionChoices'] == {'emissionsPolicy': policy}
    assert report['nativeTest'] == 'not_run' and report['sourceUnchanged'] is True
    audit = [row for row in report['migrationAudit']['vehicleAdaptations'] if row.get('field') == 'emission']
    assert len(audit) == 1
    assert audit[0]['model'] == MODEL_RESOURCE
    assert audit[0]['sourceValue'] == AUTHORED_EMISSIONS
    assert audit[0]['targetValue'] == TARGET_EMISSIONS[policy]
    assert audit[0]['emissionsPolicy'] == policy and audit[0]['explicitChoice'] is True
    assert audit[0]['noiseCoefficientsPreserved'] is (policy == 'legacy_noise')
    assert audit[0]['pollutionBehaviorPreserved'] is False
    assert audit[0]['nativeTest'] == 'not_run'
    assert (target / '_port_originals/res' / MODEL_RESOURCE).read_bytes() == (source / 'res' / MODEL_RESOURCE).read_bytes()
    assert json.loads((target / 'conversion-report.json').read_text()) == report


@pytest.mark.parametrize('kwargs', [{}, {'emissions_policy': 'strict'}])
def test_public_export_defaults_to_strict_and_keeps_explicit_source_intact(explicit_emissions_mod, kwargs):
    source, game, output = explicit_emissions_mod
    before = snapshot(source)
    native_before = snapshot(game)
    with pytest.raises(ValueError, match='noise/pollution balancing decision'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='choice_fixture', name='Choice fixture', **kwargs)
    assert not output.exists()
    assert snapshot(source) == before and snapshot(game) == native_before


@pytest.mark.parametrize('policy', ['legacy_noise', 'tf3_automatic'])
def test_public_export_persists_explicit_policy_native_data_and_original_model(explicit_emissions_mod, policy):
    source, game, output = explicit_emissions_mod
    before = snapshot(source)
    native_before = snapshot(game)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='choice_fixture', name='Choice fixture',
                          emissions_policy=policy)
    assert_native_emissions_and_audit(output, report, policy, source)
    assert snapshot(source) == before and snapshot(game) == native_before


@pytest.mark.parametrize('policy', [None, False, '', 'automatic', [], {}, TranslatedString('legacy_noise')])
def test_invalid_policy_is_rejected_before_native_inventory_or_export(explicit_emissions_mod, monkeypatch, policy):
    source, game, output = explicit_emissions_mod
    before = snapshot(source)
    def unexpected_native_access(*args, **kwargs):
        raise AssertionError('Invalid choice reached native inventory access')
    monkeypatch.setattr('trf3_mod_converter.tf2_vehicle_port.NativeInventory', unexpected_native_access)
    with pytest.raises(ValueError, match='supported noise and pollution policy'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='choice_fixture', name='Choice fixture',
                      emissions_policy=policy)
    assert not output.exists() and snapshot(source) == before


@pytest.mark.parametrize('policy', ['legacy_noise', 'tf3_automatic'])
def test_batch_persists_choices_and_reuses_only_the_same_verified_export(explicit_emissions_mod, policy):
    source, game, output = explicit_emissions_mod
    original = snapshot(source)
    item = scan_mods(source)['items'][0]
    assert item.emissions_policy == 'strict'
    item.emissions_policy = policy
    state = convert_queue([item], output, tf3_game=game)
    assert state['counts'] == {'completed': 1, 'failed': 0, 'pending': 0}
    saved = json.loads((output / STATE_NAME).read_text())
    assert saved['items'][0]['emissions_policy'] == policy
    assert saved['receipts'][item.key]['conversionChoices'] == {'emissionsPolicy': policy}
    target = output / item.mod_id
    report = json.loads((target / 'conversion-report.json').read_text())
    assert_native_emissions_and_audit(target, report, policy, source)
    exported = snapshot(target)

    retry = scan_mods(source)['items'][0]
    retry.emissions_policy = saved['items'][0]['emissions_policy']
    resumed = convert_queue([retry], output, tf3_game=game)
    assert resumed['counts'] == {'completed': 1, 'failed': 0, 'pending': 0}
    assert resumed['items'][0]['message'].startswith('Previous export verified')
    assert snapshot(target) == exported and snapshot(source) == original

    retry.emissions_policy = 'tf3_automatic' if policy == 'legacy_noise' else 'legacy_noise'
    changed = convert_queue([retry], output, tf3_game=game)
    assert changed['counts'] == {'completed': 0, 'failed': 1, 'pending': 0}
    assert 'not overwritten' in changed['items'][0]['message']
    assert changed['receipts'][item.key]['conversionChoices'] == {'emissionsPolicy': policy}
    assert snapshot(target) == exported and snapshot(source) == original


def test_batch_default_remains_strict_and_publishes_no_success_receipt(explicit_emissions_mod):
    source, game, output = explicit_emissions_mod
    before = snapshot(source)
    item = scan_mods(source)['items'][0]
    state = convert_queue([item], output, tf3_game=game)
    assert state['counts'] == {'completed': 0, 'failed': 1, 'pending': 0}
    assert 'noise/pollution balancing decision' in state['items'][0]['message']
    assert state['items'][0]['emissions_policy'] == 'strict'
    assert item.key not in state['receipts'] and not (output / item.mod_id).exists()
    assert snapshot(source) == before


@pytest.mark.parametrize('command', ['batch', 'port-tf2'])
def test_cli_parser_exposes_strict_default_and_explicit_supported_choices(command):
    arguments = [command, 'source', 'destination']
    if command == 'port-tf2':
        arguments += ['--tf3-game', 'game', '--name', 'Fixture', '--mod-id', 'fixture']
    assert build_parser().parse_args(arguments).emissions_policy == 'strict'
    for policy in ('strict', 'legacy_noise', 'tf3_automatic'):
        assert build_parser().parse_args(arguments + ['--emissions-policy', policy]).emissions_policy == policy


@pytest.mark.parametrize('command', ['batch', 'port-tf2'])
@pytest.mark.parametrize('policy', [None, 'legacy_noise', 'tf3_automatic'])
def test_cli_default_and_explicit_choices_reach_the_real_exporter(explicit_emissions_mod, capsys, command, policy):
    source, game, output = explicit_emissions_mod
    before = snapshot(source)
    arguments = [command, str(source), str(output), '--tf3-game', str(game)]
    if command == 'port-tf2':
        arguments += ['--name', 'Choice fixture', '--mod-id', 'choice_fixture']
    if policy is not None:
        arguments += ['--emissions-policy', policy]
    code = main(arguments)
    captured = capsys.readouterr()
    if policy is None:
        assert code == 2
        if command == 'batch':
            report = json.loads(captured.out)
            assert report['counts']['failed'] == 1 and not report['receipts']
            assert 'noise/pollution balancing decision' in report['items'][0]['message']
            assert not (output / report['items'][0]['mod_id']).exists()
        else:
            assert 'noise/pollution balancing decision' in captured.err
            assert not output.exists()
    else:
        assert code == 0 and not captured.err
        result = json.loads(captured.out)
        if command == 'batch':
            assert result['counts']['completed'] == 1
            assert result['items'][0]['emissions_policy'] == policy
            target = output / result['items'][0]['mod_id']
            result = json.loads((target / 'conversion-report.json').read_text())
        else:
            target = output
        assert_native_emissions_and_audit(target, result, policy, source)
    assert snapshot(source) == before


@pytest.mark.parametrize('command', ['batch', 'port-tf2'])
def test_cli_unknown_choice_creates_no_export(explicit_emissions_mod, command):
    source, game, output = explicit_emissions_mod
    before = snapshot(source)
    arguments = [command, str(source), str(output), '--tf3-game', str(game), '--emissions-policy', 'invented']
    if command == 'port-tf2':
        arguments += ['--name', 'Choice fixture', '--mod-id', 'choice_fixture']
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert not output.exists() and snapshot(source) == before

"""Authored mesh fallback evidence; no installed game data is copied here."""
from copy import deepcopy

import pytest

from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.mesh_port import port_mesh_descriptor


def descriptor():
    return {'subMeshes': [
        {'indices': {'position': {'count': 30, 'offset': 40}, 'uv0': {'count': 30, 'offset': 70}},
         'materials': ['old/interior.mtl', 'old/other_variant.mtl']},
        {'indices': {'position': {'count': 15, 'offset': 100}}, 'materials': ['old/glass.mtl']},
    ], 'vertexAttr': {'position': {'count': 16, 'offset': 0, 'numComp': 3},
                       'uv0': {'count': 8, 'offset': 48, 'numComp': 2}},
        'matConfigs': [[0, 0], [1, 0]],
        'animations': {'door': {'type': 'KEYFRAME', 'params': {'origin': [0, 0, 0],
             'keyframes': [{'time': 0, 'rot': [0, 0, 0], 'transl': [0, 0, 0]},
                           {'time': 1100, 'rot': [-90, 0, 0], 'transl': [0, 0.5, 0]}]}}},
        'authoredExtra': {'untouched': True}}


def resolver(refs):
    def resolve(reference, kind):
        assert kind == 'material'
        if reference not in refs:
            raise ValueError('Missing verified material ' + reference)
        return refs[reference]
    return resolve


def referrers():
    return [{'modelPath': 'model/bus/first.mdl', 'nodePath': 'LOD0/door',
             'materials': ['new/interior.mtl', 'new/glass.mtl']},
            {'modelPath': 'model/bus/second.mdl', 'nodePath': 'LOD1/door',
             'materials': ['new/interior.mtl', 'new/glass.mtl']}]


def test_direct_material_defaults_resolve_without_referrer_inference():
    source = descriptor(); before = deepcopy(source); report = {}
    refs = {'old/interior.mtl': 'package::/mat/interior.mtl',
            'old/other_variant.mtl': 'package::/mat/other.mtl', 'old/glass.mtl': '::/mat/glass.mtl'}
    result = port_mesh_descriptor(source, resolver(refs), [], report, 'door.msh')
    assert result['subMeshes'][0]['materials'] == ['package::/mat/interior.mtl', 'package::/mat/other.mtl']
    assert result['subMeshes'][1]['materials'] == ['::/mat/glass.mtl']
    assert all(row['method'] == 'direct_verified_reference' for row in report['meshMigrations'])
    assert source == before


def test_unanimous_complete_model_slots_bind_missing_defaults_without_geometry_changes():
    source = descriptor(); before = deepcopy(source); provenance = referrers(); report = {}
    refs = {'new/interior.mtl': 'package::/mat/interior.mtl', 'new/glass.mtl': 'package::/mat/glass.mtl'}
    result = port_mesh_descriptor(source, resolver(refs), provenance, report, 'door.msh')
    assert result['subMeshes'][0]['materials'] == ['package::/mat/interior.mtl'] * 2
    assert result['subMeshes'][1]['materials'] == ['package::/mat/glass.mtl']
    for slot in range(2):
        assert result['subMeshes'][slot]['indices'] == before['subMeshes'][slot]['indices']
    for key in ('vertexAttr', 'matConfigs', 'animations', 'authoredExtra'):
        assert result[key] == before[key]
    assert source == before and provenance == referrers()
    assert all(row['nativeTest'] == 'not_run' for row in report['meshMigrations'])
    assert all(len(row['referrers']) == 2 for row in report['meshMigrations'])
    assert report['meshMigrations'][0]['sourceReference'] == 'old/interior.mtl'
    assert report['meshMigrations'][0]['targetReference'] == 'package::/mat/interior.mtl'


def test_different_source_spellings_may_agree_only_after_verified_resolution():
    provenance = referrers(); provenance[1]['materials'][0] = 'alias/interior.mtl'
    refs = {'new/interior.mtl': 'package::/mat/interior.mtl', 'alias/interior.mtl': 'package::/mat/interior.mtl',
            'new/glass.mtl': 'package::/mat/glass.mtl'}
    result = port_mesh_descriptor(descriptor(), resolver(refs), provenance)
    assert result['subMeshes'][0]['materials'][0] == 'package::/mat/interior.mtl'


@pytest.mark.parametrize('mutation,expected', [
    (lambda refs: refs.clear(), 'no explicit model referrers'),
    (lambda refs: refs[1].update(materials=['new/other.mtl', 'new/glass.mtl']), 'conflicting'),
    (lambda refs: refs[1].update(materials=['new/interior.mtl']), 'incomplete'),
    (lambda refs: refs[1].update(materials=[]), 'incomplete'),
    (lambda refs: refs[1].update(materials=['new/interior.mtl', 'missing/unverified.mtl']), 'Missing verified'),
    (lambda refs: refs[1].pop('nodePath'), 'explicit modelPath'),
])
def test_incomplete_or_conflicting_evidence_stops_without_partial_audit(mutation, expected):
    source = descriptor(); before = deepcopy(source); provenance = referrers(); mutation(provenance); report = {}
    refs = {'new/interior.mtl': 'package::/mat/interior.mtl', 'new/other.mtl': 'package::/mat/other.mtl',
            'new/glass.mtl': 'package::/mat/glass.mtl'}
    with pytest.raises(ValueError, match=expected):
        port_mesh_descriptor(source, resolver(refs), provenance, report, 'door.msh')
    assert source == before and report == {}


@pytest.mark.parametrize('unsafe', ['../escape.mtl', '::/already_native.mtl', 'C:/escape.mtl',
                                    'a\\b.mtl', TranslatedString('TRANSLATED')])
def test_unsafe_material_default_cannot_be_replaced_using_model_evidence(unsafe):
    source = descriptor(); source['subMeshes'][0]['materials'] = [unsafe]
    refs = {'new/interior.mtl': 'package::/mat/interior.mtl', 'new/glass.mtl': 'package::/mat/glass.mtl'}
    with pytest.raises(ValueError):
        port_mesh_descriptor(source, resolver(refs), referrers())


def test_native_geometry_only_descriptor_is_preserved_without_material_invention():
    source = descriptor()
    for submesh in source['subMeshes']:
        del submesh['materials']
    report = {}
    result = port_mesh_descriptor(source, resolver({}), [], report)
    assert result == source and result is not source and report == {}

from copy import deepcopy
import zipfile

import pytest

from trf3_mod_converter.lua_metadata import UnsupportedValue
from trf3_mod_converter.tf2_vehicle_port import NativeInventory, emit
from test_tf2_vehicle_port import fixture_mod


def native_nrml_map(game, *, legacy_name='PHYSICAL_NRML_MAP'):
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('rendering/physical_nrml_map.mat.lua', emit({
            'legacyName': legacy_name, 'properties': [{'name': 'map_albedo', 'id': 'properties/map_albedo.prop'}]}))
    return NativeInventory(game)


def test_inert_exporter_blocks_keep_exact_type_active_maps_and_source(fixture_mod):
    _, game, _ = fixture_mod
    native = native_nrml_map(game)
    source = {'type': 'PHYSICAL_NRML_MAP', 'params': {
        'color_blend': {'albedoScale': 1.8},
        'dirt_rust': {'dirtOpacity': 0.1, 'rustColor': [0.2, 0.1, 0.1]},
        'map_albedo': {'fileName': 'body.dds'},
    }}
    before = deepcopy(source)
    report = {}
    result = native.material(source, lambda ref, kind: 'fixture::/' + ref, report=report, resource='body.mtl')
    assert source == before and result['type'] == source['type']
    assert set(result['params']) == {'map_albedo'}
    assert result['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName'] == 'fixture::/body.dds'
    assert [row['property'] for row in report['materialMigrations']] == ['color_blend', 'dirt_rust']
    assert report['materialMigrations'][0]['sourceValue'] == source['params']['color_blend']
    assert all(row['policy'] == 'omit_inactive_tf2_material_property' for row in report['materialMigrations'])


@pytest.mark.parametrize('params', [
    {'color_blend': {'unknown': 0}}, {'dirt_rust': {'customAgeCallback': 'fn'}},
    {'map_cblend': {'fileName': 'mask.dds'}}, {'color_blend': [0.5]},
])
def test_unverified_material_properties_remain_blocked(fixture_mod, params):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='does not declare'):
        native_nrml_map(game).material({'type': 'PHYSICAL_NRML_MAP', 'params': params}, lambda ref, kind: ref)


def test_installed_legacy_type_must_agree(fixture_mod):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='does not declare'):
        native_nrml_map(game, legacy_name='CUSTOM').material({
            'type': 'PHYSICAL_NRML_MAP', 'params': {'color_blend': {'albedoScale': 1}}}, lambda ref, kind: ref)


def test_inactive_blocks_still_must_be_literal(fixture_mod):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='dynamic'):
        native_nrml_map(game).material({'type': 'PHYSICAL_NRML_MAP', 'params': {
            'color_blend': {'albedoScale': UnsupportedValue('dynamic expression')}}}, lambda ref, kind: ref)


def opaque_alpha_fixture(game, type_):
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('rendering/'+type_.lower()+'.mat.lua', emit({
            'legacyName': type_, 'transparent': False, 'properties': []}))
        archive.writestr('rendering/properties/alpha_scale.prop.lua', emit({
            'fragmentProperties': [{'name': 'alphaScale', 'defaultValue': 1.0}]}))
        archive.writestr('rendering/properties/alpha_test.prop.lua', emit({
            'fragmentProperties': [{'name': 'alphaThreshold', 'defaultValue': 0.5},
                                   {'name': 'cutout', 'defaultValue': False}]}))
    return NativeInventory(game)


@pytest.mark.parametrize('type_', ['PHYSICAL_NRML_MAP', 'PHYSICAL_NRML_MAP_CBLEND_DIRT'])
def test_default_alpha_exporter_blocks_on_verified_opaque_types_are_audited(fixture_mod, type_):
    _, game, _ = fixture_mod
    native = opaque_alpha_fixture(game, type_)
    source = {'type': type_, 'params': {'alpha_scale': {'alphaScale': 1},
                                      'alpha_test': {'alphaThreshold': 0.5, 'cutout': False}}}
    before = deepcopy(source)
    report = {}
    assert native.material(source, lambda ref, kind: ref, report=report)['params'] == {}
    assert source == before
    assert {row['property'] for row in report['materialMigrations']} == {'alpha_scale', 'alpha_test'}
    assert all('defaults' in row['evidence'] for row in report['materialMigrations'])


@pytest.mark.parametrize('params', [
    {'alpha_scale': {'alphaScale': 0.5}}, {'alpha_scale': {'alphaScale': True}},
    {'alpha_test': {'cutout': True}}, {'alpha_test': {'alphaThreshold': 0.2}},
    {'alpha_test': {'custom': False}},
])
def test_nondefault_or_unknown_alpha_fields_remain_blocked(fixture_mod, params):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='does not declare'):
        opaque_alpha_fixture(game, 'PHYSICAL_NRML_MAP').material({
            'type': 'PHYSICAL_NRML_MAP', 'params': params}, lambda ref, kind: ref)


def standard_exporter_fixture(game, type_='PHYSICAL_NRML_MAP_CBLEND_DIRT'):
    schemas = {
        'two_sided': [{'name': 'twoSided'}, {'name': 'flipNormal'}],
        'color_blend': [{'name': 'albedoScales', 'arrayCount': 2, 'defaultValue': 0},
                        {'name': 'colors', 'arrayCount': 2, 'defaultValue': [-1, -1, -1]}],
        'dirt_rust': [{'name': 'dirtOpacity'}, {'name': 'rustOpacity'}],
    }
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('rendering/'+type_.lower()+'.mat.lua', emit({
            'legacyName': type_, 'properties': [{'name': key, 'id': 'properties/'+key+'.prop'} for key in schemas]}))
        for key, fields in schemas.items():
            archive.writestr('rendering/properties/'+key+'.prop.lua', emit({'fragmentProperties': fields}))
    return NativeInventory(game)


def test_repeated_nested_order_preserves_top_level_order_and_two_sided(fixture_mod):
    _, game, _ = fixture_mod
    native = standard_exporter_fixture(game, 'PHYS_TRANSPARENT_NRML_MAP_CBLEND_DIRT')
    source = {'type': 'PHYS_TRANSPARENT_NRML_MAP_CBLEND_DIRT', 'order': -1,
              'params': {'two_sided': {'order': -1, 'twoSided': True}}}
    before = deepcopy(source)
    report = {}
    result = native.material(source, lambda ref, kind: ref, report=report)
    assert result['order'] == -1
    assert result['params']['two_sided']['fragmentProperties'] == [{'twoSided': True}]
    assert source == before
    assert report['materialMigrations'][0]['property'] == 'two_sided/order'
    assert report['materialMigrations'][0]['sourceValue'] == -1


@pytest.mark.parametrize('root_order,nested_order', [(None, -1), (0, -1), (-1, '-1'), (1, True)])
def test_ambiguous_or_nonliteral_nested_order_remains_blocked(fixture_mod, root_order, nested_order):
    _, game, _ = fixture_mod
    source = {'type': 'PHYSICAL_NRML_MAP_CBLEND_DIRT',
              'params': {'two_sided': {'order': nested_order, 'twoSided': True}}}
    if root_order is not None:
        source['order'] = root_order
    with pytest.raises(ValueError, match='Unknown two_sided properties'):
        standard_exporter_fixture(game).material(source, lambda ref, kind: ref)


def test_exact_livery_parameter_typos_keep_active_fields_and_do_not_activate_scales(fixture_mod):
    _, game, _ = fixture_mod
    native = standard_exporter_fixture(game)
    source = {'type': 'PHYSICAL_NRML_MAP_CBLEND_DIRT', 'params': {
        'albedo_SKale': {'albedoSKale': [1, 1, 1]},
        'alpha_SKale': {'alphaSKale': 1},
        'normal_SKale': {'normalSKale': 1},
        'color_blend': {'albedoSKales': [1.5], 'colors': [[0, 0, 0]]},
        'dirt_rust': {'dirtSKale': 9, 'rustSKale': 4.8, 'dirtOpacity': 0.01, 'rustOpacity': 0.3},
    }}
    before = deepcopy(source)
    report = {}
    result = native.material(source, lambda ref, kind: ref, report=report)
    assert source == before
    assert set(result['params']) == {'color_blend', 'dirt_rust'}
    assert result['params']['color_blend']['fragmentProperties'][0] == {'colors': [[0, 0, 0], [-1, -1, -1]]}
    assert result['params']['dirt_rust']['fragmentProperties'][0] == {'dirtOpacity': 0.01, 'rustOpacity': 0.3}
    assert {row['property'] for row in report['materialMigrations'] if 'sourceValue' in row} == {
        'albedo_SKale', 'alpha_SKale', 'normal_SKale', 'color_blend/albedoSKales', 'dirt_rust/dirtSKale', 'dirt_rust/rustSKale'}


@pytest.mark.parametrize('params', [
    {'albedo_SKale': {'albedoSKale': [0.5, 1, 1]}},
    {'albedo_SKale': {'albedoSKale': [True, 1, 1]}},
    {'alpha_SKale': {'alphaSKale': 0.5}},
    {'color_blend': {'albedoSKales': 'dynamic'}},
    {'dirt_rust': {'dirtSKale': True}},
    {'dirt_rust': {'anotherTypo': 1}},
])
def test_unverified_typo_values_and_unknown_names_remain_blocked(fixture_mod, params):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError):
        standard_exporter_fixture(game).material({
            'type': 'PHYSICAL_NRML_MAP_CBLEND_DIRT', 'params': params}, lambda ref, kind: ref)

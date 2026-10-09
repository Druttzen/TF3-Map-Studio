from copy import deepcopy
import zipfile

import pytest

from trf3_mod_converter.tf2_vehicle_port import NativeInventory, emit
from test_tf2_vehicle_port import fixture_mod
from test_legacy_material_params import opaque_alpha_fixture, standard_exporter_fixture


def material_inventory(game, type_, properties=(), *, transparent=False, tangent=False):
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('rendering/'+type_.lower()+'.mat.lua', emit({
            'legacyName': type_, 'transparent': transparent, 'needsTangentVertexAttrib': tangent,
            'properties': [{'name': key, 'id': 'properties/'+key+'.prop'} for key in properties]}))
        for key in properties:
            if key.startswith('map_'):
                definition = {'fragmentSamplers': [{'name': key+'Tex'}]}
            elif key == 'polygon_offset':
                definition = {'fragmentProperties': [{'name': field} for field in (
                    'factor', 'units', 'forceDepthWrite', 'forceColorWrite')]}
            else:
                definition = {'fragmentProperties': [{'name': 'alphaScale'}]}
            archive.writestr('rendering/properties/'+key+'.prop.lua', emit(definition))
    return NativeInventory(game)


def test_vehicle_coefficients_are_archived_only_when_absent_from_native_material(fixture_mod):
    _, game, _ = fixture_mod
    native = material_inventory(game, 'PHYSICAL_NRML_MAP_CBLEND_DIRT')
    source = {'type':'PHYSICAL_NRML_MAP_CBLEND_DIRT','params':{'props':{'coeffs':[1,1,1,1]}}}
    with pytest.raises(ValueError, match='does not declare'):
        native.material(source, lambda r,k:r)
    audit = {}
    result = native.material(source, lambda r,k:r, vehicle_mode=True, report=audit)
    assert result['params'] == {} and source['params']['props']['coeffs'] == [1,1,1,1]
    assert audit['materialMigrations'][0]['sourceValue'] == source['params']['props']
    source['params']['props']['coeffs'] = [1,1,1.1,10]
    audit = {}
    result = native.material(source, lambda r,k:r, vehicle_mode=True, report=audit)
    assert result['params'] == {} and source['params']['props']['coeffs'] == [1,1,1.1,10]
    assert audit['vehicleWarnings'][0]['sourceValue'] == source['params']['props']
    source['params']['props']['coeffs'][0] = -1
    with pytest.raises(ValueError, match='does not declare'):
        native.material(source, lambda r,k:r, vehicle_mode=True)


@pytest.mark.parametrize('type_',['PHYS_TRANSPARENT','PHYS_TRANSPARENT_NRML_MAP'])
def test_vehicle_transparent_unused_recoloring_preserves_actual_shader_inputs(fixture_mod,type_):
    _, game, _ = fixture_mod
    active=('map_albedo_opacity','map_normal') if type_=='PHYS_TRANSPARENT_NRML_MAP' else ('map_albedo_opacity',)
    native = material_inventory(game,type_,active,transparent=True,tangent=type_=='PHYS_TRANSPARENT_NRML_MAP')
    source={'type':type_,'params':{'color_blend':{'albedoScales':[1.46],'colors':[]},
        'map_albedo_opacity':{'fileName':'logos.dds'}}}
    if 'map_normal' in active:source['params']['map_normal']={'fileName':'normal.dds'}
    before=deepcopy(source)
    with pytest.raises(ValueError,match='does not declare property color_blend'):
        native.material(source,lambda r,k:r)
    audit={}
    result=native.material(source,lambda r,k:'fixture::/'+r,vehicle_mode=True,report=audit)
    assert source==before and result['type']==source['type']
    assert set(result['params'])==set(active)
    assert result['params']['map_albedo_opacity']['fragmentSamplers']['map_albedo_opacityTex']['fileName']=='fixture::/logos.dds'
    if 'map_normal' in active:assert result['params']['map_normal']['fragmentSamplers']['map_normalTex']['fileName']=='fixture::/normal.dds'
    assert audit['vehicleWarnings'][0]['sourceValue']==source['params']['color_blend']
    assert audit['materialMigrations'][0]['policy']=='omit_inactive_tf2_material_property'


@pytest.mark.parametrize('value',[{'unknown':1},[1.46]])
@pytest.mark.parametrize('type_',['PHYS_TRANSPARENT','PHYS_TRANSPARENT_NRML_MAP'])
def test_vehicle_transparent_unverified_recoloring_remains_blocked(fixture_mod,value,type_):
    _,game,_=fixture_mod
    native=material_inventory(game,type_,transparent=True)
    with pytest.raises(ValueError,match='does not declare'):
        native.material({'type':type_,'params':{'color_blend':value}},lambda r,k:r,vehicle_mode=True)


def test_vehicle_transparent_recoloring_must_still_be_literal(fixture_mod):
    from trf3_mod_converter.lua_metadata import UnsupportedValue
    _,game,_=fixture_mod
    native=material_inventory(game,'PHYS_TRANSPARENT_NRML_MAP',transparent=True)
    with pytest.raises(ValueError,match='dynamic'):
        native.material({'type':'PHYS_TRANSPARENT_NRML_MAP','params':{'color_blend':{'albedoScales':UnsupportedValue('dynamic expression')}}},lambda r,k:r,vehicle_mode=True)


@pytest.mark.parametrize('type_',['PHYS_TRANSPARENT','PHYS_TRANSPARENT_NRML_MAP'])
def test_transparent_aging_without_shader_inputs_preserves_active_textures(fixture_mod,type_):
    _,game,_=fixture_mod
    native=material_inventory(game,type_,('map_albedo_opacity',),transparent=True)
    source={'type':type_,'params':{'map_albedo_opacity':{'fileName':'dash.dds'},
        'dirt_rust':{'age':0,'dirtColor':[.26,.23,.18],'dirtFactor':0,'dirtOpacity':.1,
                     'dirtScale':8,'rustColor':[.31,.18,.13],'rustFactor':0,'rustOpacity':.5,'rustScale':2.87}}}
    before=deepcopy(source);audit={}
    with pytest.raises(ValueError,match='does not declare property dirt_rust'):
        native.material(source,lambda r,k:r)
    result=native.material(source,lambda r,k:'fixture::/'+r,vehicle_mode=True,report=audit)
    assert source==before and result['type']==type_ and set(result['params'])=={'map_albedo_opacity'}
    assert audit['vehicleWarnings'][0]['sourceValue']==source['params']['dirt_rust']
    source['params']['dirt_rust']['unknownBehavior']=True
    with pytest.raises(ValueError,match='does not declare'):
        native.material(source,lambda r,k:r,vehicle_mode=True)


def test_declared_native_transparent_recoloring_is_preserved(fixture_mod):
    from test_legacy_material_params import standard_exporter_fixture
    _,game,_=fixture_mod
    native=standard_exporter_fixture(game,'PHYS_TRANSPARENT_NRML_MAP')
    source={'type':'PHYS_TRANSPARENT_NRML_MAP','params':{'color_blend':{'albedoScales':[1.46],'colors':[]}}}
    before=deepcopy(source)
    audit={}
    result=native.material(source,lambda r,k:r,vehicle_mode=True,report=audit)
    assert source==before and 'color_blend' in result['params']
    assert not audit.get('vehicleWarnings')
    assert all(row.get('policy')!='omit_inactive_tf2_material_property' for row in audit.get('materialMigrations',[]))
    values={key:value for entry in result['params']['color_blend']['fragmentProperties'] for key,value in entry.items()}
    assert values['albedoScales'][0]==1.46


@pytest.mark.parametrize('key',['map_cblend_dirt_rust','map_dirt','map_dirt_normal','map_rust','map_rust_normal','map_normal'])
def test_unused_transparent_sampler_is_archived_without_resolving_it(fixture_mod,key):
    _,game,_=fixture_mod
    native=material_inventory(game,'PHYS_TRANSPARENT',('map_albedo_opacity',),transparent=True)
    source={'type':'PHYS_TRANSPARENT','params':{'map_albedo_opacity':{'fileName':'body.dds'},
        key:{'fileName':'unused.dds','type':'TWOD'}}}
    before=deepcopy(source)
    reads=[]
    def resolve(ref,kind):reads.append(ref);return 'fixture::/'+ref
    audit={}
    result=native.material(source,resolve,vehicle_mode=True,report=audit)
    assert source==before and reads==['body.dds']
    assert set(result['params'])=={'map_albedo_opacity'}
    assert audit['vehicleWarnings'][0]['sourceValue']==source['params'][key]
    with pytest.raises(ValueError,match='does not declare'):
        native.material(source,resolve)


def test_vehicle_unknown_property_field_keeps_declared_values_and_original(fixture_mod):
    _, game, _ = fixture_mod
    native = material_inventory(game, 'PHYSICAL', ('two_sided',))
    source = {'type':'PHYSICAL','params':{'two_sided':{'alphaScale':.75,'order':2}}}
    with pytest.raises(ValueError, match='Unknown two_sided'):
        native.material(source, lambda r,k:r)
    audit = {}
    result = native.material(source, lambda r,k:r, vehicle_mode=True, report=audit)
    assert result['params']['two_sided'] == {'fragmentProperties':[{'alphaScale':.75}]}
    assert source['params']['two_sided']['order'] == 2
    assert audit['vehicleWarnings'][0]['sourceValue'] == {'order':2}


def test_vehicle_empty_texture_binding_keeps_other_authored_textures(fixture_mod):
    from trf3_mod_converter.base_resources import normalize_reference
    _, game, _ = fixture_mod
    native = material_inventory(game, 'PHYSICAL', ('map_albedo','map_normal'))
    source = {'type':'PHYSICAL','params':{'map_albedo':{'fileName':''},
        'map_normal':{'fileName':'normal.dds'}}}
    before = deepcopy(source)
    def resolve(reference, kind):
        return '::/textures/'+normalize_reference(reference)
    with pytest.raises(ValueError):
        native.material(source, resolve)
    audit = {}
    result = native.material(source, resolve, vehicle_mode=True, report=audit)
    assert 'map_albedo' not in result['params']
    assert result['params']['map_normal']['fragmentSamplers']['map_normalTex']['fileName'] == '::/textures/normal.dds'
    assert source == before and audit['vehicleWarnings'][0]['sourceValue'] == {'fileName':''}


def test_physical_default_alpha_matches_opaque_native_defaults(fixture_mod):
    _, game, _ = fixture_mod
    source = {'type': 'PHYSICAL', 'params': {
        'alpha_scale': {'alphaScale': 1}, 'alpha_test': {'alphaThreshold': 0.5, 'cutout': False}}}
    before, audit = deepcopy(source), {}
    result = opaque_alpha_fixture(game, 'PHYSICAL').material(source, lambda ref, kind: ref, report=audit)
    assert source == before and result['params'] == {}
    assert {row['property'] for row in audit['materialMigrations']} == {'alpha_scale', 'alpha_test'}


@pytest.mark.parametrize('params', [
    {'alpha_scale': {'alphaScale': True}}, {'alpha_scale': {'alphaScale': 0.75}},
    {'alpha_test': {'cutout': True}}, {'alpha_test': {'preferAlphaToCoverage': True}},
])
def test_physical_nondefault_alpha_needs_explicit_review(fixture_mod, params):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='does not declare'):
        opaque_alpha_fixture(game, 'PHYSICAL').material({'type': 'PHYSICAL', 'params': params}, lambda r, k: r)


def test_opaque_normal_map_aging_samplers_stay_inactive_and_audited(fixture_mod):
    _, game, _ = fixture_mod
    native = material_inventory(game, 'PHYSICAL_NRML_MAP', ('map_albedo', 'map_normal'))
    inactive = ['map_cblend_dirt_rust', 'map_dirt', 'map_dirt_normal', 'map_rust', 'map_rust_normal']
    source = {'type': 'PHYSICAL_NRML_MAP', 'params': {
        key: {'fileName': key+'.dds', 'type': 'TWOD', 'wrapS': 'REPEAT'} for key in inactive}}
    source['params'].update(map_albedo={'fileName': 'body.dds'}, map_normal={'fileName': 'normal.dds'})
    before, audit, resolutions = deepcopy(source), {}, []
    def resolve(ref, kind):
        resolutions.append((ref, kind))
        return 'fixture::/'+ref
    result = native.material(source, resolve, report=audit, resource='body.mtl')
    assert source == before and result['type'] == 'PHYSICAL_NRML_MAP'
    assert resolutions == [('body.dds', 'texture'), ('normal.dds', 'texture')]
    assert set(result['params']) == {'map_albedo', 'map_normal'}
    assert [row['property'] for row in audit['materialMigrations']] == inactive
    assert all(row['sourceValue'] == source['params'][row['property']] for row in audit['materialMigrations'])


@pytest.mark.parametrize('values', [
    {'fileName': 'mask.dds'}, {'fileName': 'mask.dds', 'type': 'CUBE_MAP'},
    {'fileName': 'mask.dds', 'type': 'TWOD', 'customSampler': True},
    {'fileName': 'mask.dds', 'type': 'TWOD', 'redGreen': 1},
    {'fileName': 'mask.dds', 'type': 'TWOD', 'mipmapAlphaScale': float('inf')},
])
def test_unverified_inert_sampler_shapes_are_not_dropped(fixture_mod, values):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='does not declare'):
        material_inventory(game, 'PHYSICAL_NRML_MAP').material({
            'type': 'PHYSICAL_NRML_MAP', 'params': {'map_cblend_dirt_rust': values}}, lambda r, k: r)


def test_declared_aging_sampler_is_preserved_and_resolved(fixture_mod):
    _, game, _ = fixture_mod
    native = material_inventory(game, 'PHYSICAL_NRML_MAP_CBLEND_DIRT', ('map_cblend_dirt_rust',))
    source = {'type': 'PHYSICAL_NRML_MAP_CBLEND_DIRT',
              'params': {'map_cblend_dirt_rust': {'fileName': 'aging.dds', 'type': 'TWOD'}}}
    result = native.material(source, lambda r, k: 'fixture::/'+r)
    assert result['params']['map_cblend_dirt_rust']['fragmentSamplers']['map_cblend_dirt_rustTex'] == {
        'fileName': 'fixture::/aging.dds', 'type': 'TWOD'}


def test_exact_neutral_unused_normal_and_coefficients_are_audited(fixture_mod):
    _, game, _ = fixture_mod
    for type_, params, transparent in (
        ('PHYSICAL', {'normal_scale': {'normalScale': 1}}, False),
        ('PHYS_TRANSPARENT', {'normal_scale': {'normalScale': 1}}, True),
        ('PHYS_TRANSPARENT', {'props': {'coeffs': [1, 1.0, 1, 1]}}, True),
    ):
        source, audit = {'type': type_, 'params': params}, {}
        before = deepcopy(source)
        native = material_inventory(game, type_, transparent=transparent)
        assert native.material(source, lambda r, k: r, report=audit)['params'] == {}
        assert source == before and audit['materialMigrations'][0]['sourceValue'] == next(iter(params.values()))


@pytest.mark.parametrize('type_,params,transparent,tangent', [
    ('PHYSICAL', {'normal_scale': {'normalScale': 0.5}}, False, False),
    ('PHYSICAL', {'normal_scale': {'normalScale': True}}, False, False),
    ('PHYSICAL', {'normal_scale': {'normalScale': 1}}, False, True),
    ('PHYS_TRANSPARENT', {'normal_scale': {'normalScale': 1}}, True, True),
    ('PHYS_TRANSPARENT', {'props': {'coeffs': [1, 1, 0.5, 1]}}, True, False),
    ('PHYS_TRANSPARENT', {'props': {'coeffs': [1, 1, True, 1]}}, True, False),
    ('PHYS_TRANSPARENT', {'props': {'coeffs': [1, 1, 1, 1]}}, False, False),
])
def test_nondefault_or_unverified_neutral_blocks_stay_blocked(fixture_mod, type_, params, transparent, tangent):
    _, game, _ = fixture_mod
    with pytest.raises(ValueError, match='does not declare'):
        material_inventory(game, type_, transparent=transparent, tangent=tangent).material({
            'type': type_, 'params': params}, lambda r, k: r)


def test_klm_livery_typos_are_audited_without_enabling_new_scales(fixture_mod):
    _, game, _ = fixture_mod
    source = {'type': 'PHYSICAL_NRML_MAP_CBLEND_DIRT', 'params': {
        'albedo_KLMale': {'albedoKLMale': [1, 1, 1]},
        'alpha_KLMale': {'alphaKLMale': 1}, 'normal_KLMale': {'normalKLMale': 1},
        'color_blend': {'albedoKLMales': [1.5], 'colors': [[0, 0, 0]]},
        'dirt_rust': {'dirtKLMale': 9, 'rustKLMale': 4.8, 'dirtOpacity': 0.1, 'rustOpacity': 0.2}}}
    audit, before = {}, deepcopy(source)
    result = standard_exporter_fixture(game).material(source, lambda r, k: r, report=audit)
    assert source == before and set(result['params']) == {'color_blend', 'dirt_rust'}
    assert result['params']['color_blend']['fragmentProperties'] == [{'colors': [[0, 0, 0], [-1, -1, -1]]}]
    assert result['params']['dirt_rust']['fragmentProperties'] == [{'dirtOpacity': 0.1, 'rustOpacity': 0.2}]
    assert {row['property'] for row in audit['materialMigrations'] if 'sourceValue' in row} == {
        'albedo_KLMale', 'alpha_KLMale', 'normal_KLMale', 'color_blend/albedoKLMales',
        'dirt_rust/dirtKLMale', 'dirt_rust/rustKLMale'}


def test_active_depth_write_and_transparent_alpha_are_preserved(fixture_mod):
    _, game, _ = fixture_mod
    source = {'type': 'PHYS_TRANSPARENT', 'params': {
        'polygon_offset': {'factor': -2, 'units': -2, 'forceDepthWrite': True},
        'alpha_scale': {'alphaScale': 0.3}}}
    result = material_inventory(game, 'PHYS_TRANSPARENT', ('polygon_offset', 'alpha_scale'),
                                transparent=True).material(source, lambda r, k: r)
    assert result['params']['polygon_offset']['fragmentProperties'] == [source['params']['polygon_offset']]
    assert result['params']['alpha_scale']['fragmentProperties'] == [{'alphaScale': 0.3}]


def test_player_logo_array_requests_explicit_target_adapter(fixture_mod):
    _, game, _ = fixture_mod
    type_ = 'PHYSICAL_NRML_MAP_CBLEND_DIRT_LOGO'
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        archive.writestr('rendering/'+type_.lower()+'.mat.lua', emit({
            'legacyName': type_, 'properties': [{'name': 'map_logo', 'id': 'properties/map_logo.prop'}]}))
        archive.writestr('rendering/properties/map_logo.prop.lua', emit({'fragmentSamplers': []}))
    source = {'type': type_, 'params': {'map_logo': 'player-logo-array'}}
    before = deepcopy(source)
    with pytest.raises(ValueError, match='verified TF3 player-logo adapter'):
        NativeInventory(game).material(source, lambda r, k: pytest.fail('Must not invent a logo resource'))
    assert source == before
    audit = {}
    result = NativeInventory(game).material(source, lambda r, k: pytest.fail('Must not invent a logo resource'),
                                            vehicle_mode=True, report=audit)
    assert result['params']['map_logo'] == {}
    assert audit['vehicleWarnings'] and source == before

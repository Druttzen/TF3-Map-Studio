from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from test_tf2_vehicle_port import fixture_mod, model
from test_tf2_vehicle_port import stock_dependencies
from trf3_mod_converter.batch import scan_mods, convert_queue
from trf3_mod_converter.conversion_choices import conversion_choices
from trf3_mod_converter.converter import allow_missing_vehicle_dependencies
from trf3_mod_converter.missing_data import complete_payload
from trf3_mod_converter.native_donors import NativeDonorCatalog
from trf3_mod_converter.tf2_vehicle_port import port_tf2_mod, snapshot, emit, flatten
from trf3_mod_converter.cargo_port import CargoCatalog, port_compartments
from test_cargo_port import NativeCargo
from trf3_mod_converter.vehicle_mode import class_average_emissions, vehicle_package, compatibility_model, source_gear_radii, compatible_gear_configs, prepare_vehicle_model


def donor(path, noise, pollution, family='train', engine=('ELECTRIC',), size=None):
    return SimpleNamespace(resource=path, _signature=SimpleNamespace(family=family, engines=engine, size=size),
        metadata={'emissions': {'noise': {'score': noise}, 'pollution': {'score': pollution}}})


@pytest.fixture
def class_catalog(monkeypatch):
    catalog = SimpleNamespace(donors=[donor('one.mdl', 10, 2), donor('two.mdl', 20, 4),
        donor('diesel.mdl', 100, 90, engine=('DIESEL',)), donor('car.mdl', 99, 99, family='car'),
        donor('auto.mdl', -1, -1), donor('invalid.mdl', float('nan'), True)])
    monkeypatch.setattr(NativeDonorCatalog, 'from_native', staticmethod(lambda native: catalog))
    return catalog


def test_class_average_is_arithmetic_mean_and_excludes_other_types_and_auto_values(class_catalog):
    source = model()
    original = deepcopy(source)
    result, audit = class_average_emissions(source, object(), model_path='vehicle/train/a.mdl')
    assert result == {'noise': {'score': 15}, 'pollution': {'score': 3}}
    assert audit['populations']['noise']['count'] == 2
    assert audit['populations']['pollution']['selection'] == 'same_type_and_propulsion'
    assert source == original


def test_no_average_population_does_not_invent_a_score(class_catalog):
    class_catalog.donors = [donor('auto.mdl', -1, -1)]
    with pytest.raises(ValueError, match='No explicit installed TF3 noise'):
        class_average_emissions(model(), object())


def test_vehicle_scope_includes_texture_only_repaints_without_base_model(tmp_path):
    texture = tmp_path/'res/textures/models/vehicle/train/repaint.dds'
    texture.parent.mkdir(parents=True)
    texture.write_bytes(b'appearance')
    assert vehicle_package(tmp_path)
    other = tmp_path/'map'
    other.mkdir()
    (other/'mod.lua').write_text(emit({'info': {'name': 'Map'}}))
    assert not vehicle_package(other)


def test_scan_vehicle_only_keeps_repaint_and_skips_nonvehicles(tmp_path):
    for name, resource in [('repaint', 'textures/models/vehicle/bus/skin.dds'),
                           ('terrain', 'textures/terrain/ground.dds')]:
        root = tmp_path/name
        file = root/'res'/resource
        file.parent.mkdir(parents=True)
        file.write_bytes(b'image')
        (root/'mod.lua').write_text(emit({'info': {'name': name, 'authors': [{'name':'Author'}]}}))
    result = scan_mods(tmp_path, vehicles_only=True)
    assert [item.display_name for item in result['items']] == ['repaint']
    assert any('non-vehicle' in message for message in result['warnings'])


def test_tf2_payload_is_carried_without_a_donor():
    source = model()
    report = {}
    assert complete_payload(source, object(), 40, preserve_tf2=True, report=report) == (
        0, 'preserve_tf2_constant_vehicle_mass')
    assert report['dataCompletions'][0]['rawCapacity'] == 40
    source['metadata'] = {'airVehicle': {'maxPayload': 1900}}
    assert complete_payload(source, object(), 40, preserve_tf2=True)[0] == 1900


def test_conflicting_installed_texture_is_kept_separate_from_authored_texture(fixture_mod,class_catalog):
    from trf3_mod_converter.lua_metadata import load_lua_table
    from trf3_mod_converter.source_game_resources import verify_source_game_dependencies
    from test_source_game_resources import dds
    source,game,output=fixture_mod
    tf2,files=stock_dependencies(fixture_mod)
    authored=dds()+b'authored appearance'
    own=source/'res/textures/stock.dds'
    own.write_bytes(authored)
    before=snapshot(source)
    report=port_tf2_mod(source,output,tf3_game=game,tf2_game=tf2,mod_id='fixture_test',name='Draft',vehicle_policy='tf2_complete')
    assert snapshot(source)==before
    assert (output/'content/textures/stock.dds').read_bytes()==authored
    assert (output/'content/textures/tf2_base/stock.dds').read_bytes()==files['textures/stock.dds']
    assert (output/'_port_originals/res/textures/tf2_base/stock.dds').read_bytes()==files['textures/stock.dds']
    material=load_lua_table((output/'content/models/material/light.mtl').read_text())
    assert material['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName']=='fixture_test::/textures/tf2_base/stock.dds'
    row=next(r for r in report['sourceGameDependencies'] if r['kind']=='texture')
    assert row['originalFile']=='_port_originals/res/textures/tf2_base/stock.dds'
    assert verify_source_game_dependencies(tf2,report['sourceGameDependencies'],report['sourceGameResourceFingerprints'],report['sourceGameInventoryFingerprint'])


def test_base_mesh_material_collision_preserves_each_author_context(fixture_mod,class_catalog):
    from trf3_mod_converter.lua_metadata import load_lua_table
    source,game,output=fixture_mod
    tf2,files=stock_dependencies(fixture_mod)
    mesh=load_lua_table(files['models/mesh/light.msh'].decode())
    mesh['subMeshes'][0]['materials']=['light.mtl']
    (tf2/'res/models/mesh/light.msh').write_text(emit(mesh))
    authored=emit({'type':'PHYSICAL','params':{'map_albedo':{'fileName':'body.dds'}}}).encode()
    (source/'res/models/material/light.mtl').write_bytes(authored)
    report=port_tf2_mod(source,output,tf3_game=game,tf2_game=tf2,mod_id='fixture_test',name='Draft',vehicle_policy='tf2_complete')
    own=load_lua_table((output/'content/models/material/light.mtl').read_text())
    base=load_lua_table((output/'content/models/material/tf2_base/light.mtl').read_text())
    assert own['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName']=='fixture_test::/textures/body.dds'
    assert base['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName']=='fixture_test::/textures/stock.dds'
    assert (output/'_port_originals/res/models/material/light.mtl').read_bytes()==authored
    row=next(r for r in report['sourceGameDependencies'] if r['kind']=='material')
    assert row['targetReference']=='fixture_test::/models/material/tf2_base/light.mtl'
    assert (output/row['originalFile']).read_bytes()==files['models/material/light.mtl']


def test_missing_dependency_relaxation_does_not_relax_unsafe_paths_or_geometry():
    messages = ['a.mdl: missing local resource for "base.mdl".',
                'a.mdl: invalid TF3 resource reference "../escape.mdl".',
                'wheel.msh: missing companion mesh blob wheel.msh.blob.']
    d = SimpleNamespace(blockers=messages[:], warnings=[], resource_audit={'blockers':messages[:]})
    allow_missing_vehicle_dependencies(d)
    assert d.blockers == messages[1:]
    assert d.resource_audit['status'] == 'blocked'
    assert messages[0] in d.resource_audit['unresolvedVehicleDependencies']


def test_vehicle_export_retains_original_values_and_records_average_choice(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    before = snapshot(source)
    item = scan_mods(source)['items'][0]
    item.vehicle_policy, item.emissions_policy = 'tf2_complete', 'class_average'
    result = convert_queue([item], output, tf3_game=game)
    assert result['counts']['completed'] == 1, result['items'][0]['message']
    target = output/item.mod_id
    report = json.loads((target/'conversion-report.json').read_text())
    assert report['conversionChoices'] == conversion_choices('class_average', 'tf2_complete')
    text = (target/'content/models/model/vehicle/train/test.mdl').read_text()
    assert 'power = 1220' in text and 'weightEmpty = 79500' in text
    assert 'score = 15' in text and 'score = 3' in text
    assert snapshot(source) == before
    # The mode is part of the receipt identity; retries cannot silently switch it.
    changed = scan_mods(source)['items'][0]
    changed.emissions_policy = 'class_average'
    retry = convert_queue([changed], output, tf3_game=game)
    assert retry['counts']['failed'] == 1
    assert 'not overwritten' in retry['items'][0]['message']


def test_texture_repaint_exports_with_unavailable_requirement_and_callback(tmp_path):
    source, game, output = tmp_path/'skin', tmp_path/'game', tmp_path/'output'
    texture = source/'res/textures/models/vehicle/train/skin.dds'
    texture.parent.mkdir(parents=True)
    texture.write_bytes(b'original skin')
    (game/'base/content').mkdir(parents=True)
    (source/'mod.lua').write_text('function data() return {info={name="Skin", authors={{name="Author"}}, '
        'dependencies={"missing_base_mod"}}, runFn=function() error("MUST NOT RUN") end} end')
    before = snapshot(source)
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='skin_draft', name='Skin',
                          vehicle_policy='tf2_complete', emissions_policy='class_average')
    assert result['migrationAudit']['vehicleWarnings']
    assert (output/'content/textures/models/vehicle/train/skin.dds').read_bytes() == b'original skin'
    assert snapshot(source) == before
    assert 'MUST NOT RUN' in (output/'_port_originals/mod.lua').read_text()


def test_vehicle_export_archives_legacy_selection_params(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    text = (source/'mod.lua').read_text()
    text = text.replace('name = "Fixture",', 'name = "Fixture", params = {{key="old", values={"A","B"}}},')
    (source/'mod.lua').write_text(text)
    before = snapshot(source)
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft',
                          vehicle_policy='tf2_complete')
    assert snapshot(source) == before
    assert 'params' not in json.loads((output/'mod.json').read_text())
    assert any('selection controls' in w['message'] for w in result['migrationAudit']['vehicleWarnings'])
    assert (output/'_port_originals/mod.lua').read_text() == text


def test_empty_optional_hide_target_does_not_block_vehicle_export(fixture_mod, class_catalog):
    from trf3_mod_converter.lua_metadata import load_lua_table
    source, game, output = fixture_mod
    path = source/'res/models/model/vehicle/train/test.mdl'
    data = load_lua_table(path.read_text())
    data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['toHide'] = ['']
    path.write_text(emit(data))
    before = snapshot(source)
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft', vehicle_policy='tf2_complete')
    assert snapshot(source) == before
    assert any('empty optional cargo hide' in w['message'] for w in result['migrationAudit']['vehicleWarnings'])


def test_vehicle_batch_rechecks_legacy_metadata_instead_of_using_scan_error(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    item = scan_mods(source)['items'][0]
    item.vehicle_policy = 'tf2_complete'
    item.scan_error = 'Legacy metadata needs a strict manual review'
    result = convert_queue([item], output, tf3_game=game)
    assert result['counts']['completed'] == 1, result['items'][0]['message']


def test_compatibility_model_keeps_tf2_physics_and_cargo_without_donor_geometry(class_catalog):
    calls = ('sortLods', 'toCompartmentList', 'addTransformatorConfig', 'replaceMeshIdWithNodeName',
        'squeezeConfigsToOneConfigForVehicles', 'turnRoadAndRailToLandVehicle', 'convertWeight',
        'landVehicleSoundSetToSoundConfig', 'makeCargoEntry', 'makeCargoTypeSet', 'convertCargoTypes',
        'addVehicleExtent', 'addTransportVehicleTransportModes', 'convertParticleSystem')
    class Native:
        def reference(self, path):
            return '::/'+path
        def read(self, path):
            return ('\n'.join('function model_metadata_util.'+call+'(p,d) return d end' for call in calls)).encode()
    source = model()
    before = deepcopy(source)
    report = {}
    text = compatibility_model(source, lambda ref, kind:'fixture::/'+ref, Native(),
        model_path='vehicle/train/test.mdl', report=report)
    assert 'power = 1220' in text and 'weight = 79.5' in text
    assert 'compartments =' in text and 'result.version = 2' in text
    assert 'vehicle_util.convertWeight(path, result)' in text
    assert 'score = 15' in text
    assert source == before and report['legacyVehicleData'][0]['originalPhysicsPreserved']


def test_missing_air_radius_comes_from_original_tf2_geometry():
    import struct
    source = {'metadata': {'airVehicle': {'configs': [{'wheels': ['wheel.msh']}]}}}
    descriptor = {'vertexAttr': {'position': {'offset':0, 'count':48, 'numComp':3}}}
    blob = b''.join(struct.pack('<fff', *p) for p in ((.5,0,0),(-.5,0,0),(0,0,.5),(0,0,-.5)))
    report = {}
    result = source_gear_radii(source, lambda mesh:(descriptor,blob), report=report, model_path='air.mdl')
    assert result['metadata']['airVehicle']['configs'][0]['wheelRadii'] == [.5]
    assert 'wheelRadii' not in source['metadata']['airVehicle']['configs'][0]
    assert report['sourceGeometryCompletions'][0]['method'] == 'radius_from_tf2_wheel_vertex_positions'


def test_supplied_air_radius_is_never_replaced():
    source = {'metadata': {'airVehicle': {'configs': [{'wheels':['wheel.msh'], 'wheelRadii':[.7]}]}}}
    def unexpected(mesh):
        raise AssertionError('Supplied TF2 radius must win')
    assert source_gear_radii(source, unexpected, report={}, model_path='air.mdl') == source


def test_preparsed_vehicle_model_is_reused_without_mutating_source(fixture_mod,class_catalog,monkeypatch):
    import trf3_mod_converter.tf2_vehicle_port as module
    source,game,output=fixture_mod
    path=source/'res/models/model/vehicle/train/test.mdl'
    text=path.read_text()
    before=snapshot(source)
    parse=module.load_resource_table
    calls=[]
    def tracked(value,*args,**kwargs):
        if value==text:calls.append(kwargs.get('resource'))
        return parse(value,*args,**kwargs)
    monkeypatch.setattr(module,'load_resource_table',tracked)
    result=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Draft',vehicle_policy='tf2_complete')
    assert calls==['models/model/vehicle/train/test.mdl']
    assert result['sourceUnchanged'] and snapshot(source)==before
    converted=(output/'content/models/model/vehicle/train/test.mdl').read_text()
    assert 'power = 1220' in converted and 'weightEmpty = 79500' in converted


def test_bad_tf2_geometry_does_not_supply_an_invented_radius():
    source = {'metadata': {'airVehicle': {'configs': [{'wheels':['wheel.msh']}]}}}
    report = {}
    result = source_gear_radii(source, lambda mesh:({}, b''), report=report, model_path='air.mdl')
    assert result['metadata']['airVehicle']['configs'][0]['wheelRadii'] == []
    assert report['vehicleWarnings'] and 'sourceGeometryCompletions' not in report


def test_shared_gear_meshes_are_bound_to_their_own_lods_without_losing_radii():
    metadata = {'railVehicle': {'configs': [{'axles':['wheel0.msh','wheel1.msh'], 'axleRadii':[.7,.8]}]}}
    nodes = [[{'name':'wheel0','mesh':'wheel0.msh'}], [{'name':'wheel1','mesh':'wheel1.msh'}], []]
    audit = {}
    compatible_gear_configs(metadata, nodes, model_path='shared.mdl', report=audit)
    configs = metadata['railVehicle']['configs']
    assert [c['axles'] for c in configs] == [['wheel0.msh'], ['wheel1.msh'], []]
    assert [c['axleRadii'] for c in configs] == [[.7], [.8], []]
    assert audit['vehicleWarnings']


def test_empty_legacy_gear_list_becomes_empty_config_for_native_helper():
    metadata = {'railVehicle': {'configs': []}}
    audit = {}
    compatible_gear_configs(metadata, [[]], model_path='bogie.mdl', report=audit)
    assert metadata == {'railVehicle': {'config': {}}}
    assert audit['vehicleAdaptations'][0]['sourceValue'] == []


def test_missing_component_carrier_uses_explicit_rail_folder_and_preserves_source():
    source = model()
    source['metadata']['transportVehicle'].pop('carrier')
    audit = {}
    result = prepare_vehicle_model(source, model_path='models/model/vehicle/waggon/bogie.mdl', report=audit)
    assert result['metadata']['transportVehicle']['carrier'] == 'RAIL'
    assert 'carrier' not in source['metadata']['transportVehicle']
    assert audit['vehicleWarnings'][0]['estimated']
    unknown = prepare_vehicle_model(source, model_path='models/model/unknown.mdl', report={})
    assert 'carrier' not in unknown['metadata']['transportVehicle']


def test_mixed_children_keep_numeric_nodes_without_relocating_named_transform():
    source = model()
    children = source['lods'][0]['node']['children']
    source['lods'][0]['node']['children'] = {i+1:v for i,v in enumerate(children)} | {'transf':[1]*16}
    audit = {}
    result = prepare_vehicle_model(source, model_path='vehicle/train/test.mdl', report=audit)
    assert result['lods'][0]['node']['children'] == children
    assert 'transf' not in result['lods'][0]['node']
    assert audit['vehicleWarnings'] and isinstance(source['lods'][0]['node']['children'], dict)


def test_stray_numeric_tables_in_mesh_node_preserve_graph_transforms_and_bindings():
    from trf3_mod_converter.vehicle_profiles import derive_lod_nodes
    from trf3_mod_converter.tf2_vehicle_port import flatten
    source = model()
    expected = deepcopy(source)
    mesh = next(n for n in flatten(source['lods'][0]['node']) if n.get('mesh'))
    mesh[1] = {'mesh':'ignored-wheel.msh','transf':[1]*16}
    mesh[2] = {'mesh':'ignored-frame.msh'}
    original = deepcopy(source)
    audit = {}
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/container.mdl', report=audit)
    assert result == expected and source == original
    expected_nodes, expected_worlds = derive_lod_nodes(expected['lods'], metadata=expected['metadata'])
    nodes, worlds = derive_lod_nodes(result['lods'], metadata=result['metadata'])
    assert nodes == expected_nodes and worlds == expected_worlds
    assert audit['vehicleWarnings'][0]['sourceValue'] == {1:mesh[1], 2:mesh[2]}


@pytest.mark.parametrize('extras,has_mesh', [({2:{'mesh':'a.msh'}},True), ({1:3},True), ({1:{'mesh':'a.msh'}},False)])
def test_other_invalid_node_tables_still_require_review(extras,has_mesh):
    from trf3_mod_converter.vehicle_profiles import derive_lod_nodes
    from trf3_mod_converter.tf2_vehicle_port import flatten
    source = model()
    node = next(n for n in flatten(source['lods'][0]['node']) if n.get('mesh'))
    if not has_mesh: node.pop('mesh')
    node.update(extras)
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/container.mdl', report={})
    with pytest.raises(ValueError, match='Unsupported node fields'):
        derive_lod_nodes(result['lods'],metadata=result['metadata'])


def test_constant_homogeneous_transform_is_equivalent_without_accepting_perspective():
    source = model()
    matrix = [2,0,0,0,0,2,0,0,0,0,2,0,6,0,4,2]
    source['lods'][0]['node']['transf'] = matrix
    result = prepare_vehicle_model(source, model_path='vehicle/plane/a.mdl', report={})
    assert result['lods'][0]['node']['transf'] == [1,0,0,0,0,1,0,0,0,0,1,0,3,0,2,1]
    assert source['lods'][0]['node']['transf'] == matrix
    matrix[3] = .2
    result = prepare_vehicle_model(source, model_path='vehicle/plane/a.mdl', report={})
    assert result['lods'][0]['node']['transf'] == matrix


def test_invalid_optional_cargo_display_does_not_discard_capacity():
    source = model()
    load = source['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    load['cargoEntries'] = [{'type':'COAL','capacity':68,'cargoBay':{'childId':999}}]
    audit = {}
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/menu.mdl', report=audit)
    target = result['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    assert target == {'type':'COAL','capacity':68}
    assert load['cargoEntries'][0]['cargoBay'] == {'childId':999} and audit['vehicleWarnings']


def test_invalid_volume_and_palette_do_not_replace_capacity_or_source_colors():
    source = model()
    source['metadata']['colorConfig'] = {'configs':[[[2,.5,.25]]]}
    entry = {'type':'COAL','capacity':68,'cargoBay':{'bbMin':[0,0,0],'bbMax':[0,0,0],'childId':0}}
    source['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'] = [entry]
    audit = {}
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/a.mdl', report=audit)
    assert 'colorConfig' not in result['metadata']
    assert result['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0] == {'type':'COAL','capacity':68}
    assert source['metadata']['colorConfig']['configs'] == [[[2,.5,.25]]] and entry['cargoBay']
    assert len(audit['vehicleWarnings']) == 2


def test_missing_cargo_seat_binding_preserves_capacity_and_valid_seats():
    source = model()
    entry = {'type':'PASSENGERS','capacity':68,'seats':[0,72]}
    source['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'] = [entry]
    result = prepare_vehicle_model(source, model_path='vehicle/ship/a.mdl', report={})
    target = result['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    assert target == {'type':'PASSENGERS','capacity':68,'seats':[0]}
    assert entry['seats'] == [0,72]


def test_combined_cargo_display_follows_native_custom_slot_precedence():
    source = model()
    load = source['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    entry = {'type':'LOGS','capacity':68,'cargoBay':{'childId':0},
             'customCargoModels':{'configurations':[{'slotLevels':[[],[0]]}]}}
    load['cargoEntries'] = [entry]
    audit = {}
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/a.mdl', report=audit)
    target = result['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    assert target['capacity'] == 68 and target['customCargoModels'] == entry['customCargoModels']
    assert 'cargoBay' not in target and entry['cargoBay'] == {'childId':0}
    assert audit['vehicleWarnings'][0]['policy'] == 'native_makeLoadIndicators_custom_slots_precedence'


def test_unused_empty_cargo_slots_preserve_bays_and_capacities():
    source = model()
    provider = {'slots':[{'group':1,'models':[]}]}
    source['metadata']['cargoSlotProvider'] = provider
    entry = {'type':'COAL','capacity':68,'cargoBay':{'childId':0}}
    source['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'] = [entry]
    audit = {}
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/a.mdl', report=audit)
    assert 'cargoSlotProvider' not in result['metadata'] and source['metadata']['cargoSlotProvider'] == provider
    assert result['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'] == [entry]
    assert audit['vehicleWarnings'][0]['sourceValue'] == provider
    entry['customCargoModels'] = {'configurations':[{'slotLevels':[[],[0]]}]}
    result = prepare_vehicle_model(source, model_path='vehicle/waggon/a.mdl', report={})
    assert result['metadata']['cargoSlotProvider'] == provider


def test_custom_slot_siblings_follow_native_explicit_configurations():
    data=model()
    data['metadata']['cargoSlotProvider']={'slots':[{'group':1,'models':['#BIG'],
        'transf':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}]}
    data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries']=[{'type':'COAL','capacity':68}]
    entry=data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    custom={'configurations':[{'slotLevels':[[],[0]]}],1:{'slotLevels':[[],[6]]}}
    entry['customCargoModels']=deepcopy(custom)
    entry.pop('cargoBay',None)
    original=deepcopy(data)
    audit={}
    prepared=prepare_vehicle_model(data,model_path='vehicle/train/test.mdl',report=audit)
    target=prepared['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    assert data==original and target['capacity']==entry['capacity']
    assert target['customCargoModels']=={'configurations':custom['configurations']}
    assert audit['vehicleWarnings'][0]['sourceValue']=={1:custom[1]}
    options={'catalog':CargoCatalog.from_native(NativeCargo()),'nodes':list(flatten(data['lods'][0]['node'])),
        'cargo_slot_provider':data['metadata']['cargoSlotProvider'],'expand_classes':False}
    with pytest.raises(ValueError,match='customCargoModels fields'):
        port_compartments(data['metadata']['transportVehicle'],**options)
    converted,extras,cargo_audit=port_compartments(prepared['metadata']['transportVehicle'],**options)
    cargo=converted['compartments'][0]['loadConfigs'][0]['cargoEntry']
    assert cargo['capacity']==cargo_audit['maxCapacity']==68
    assert extras['loadIndicator']['configs'][cargo['loadIndicator']]['cargoSlots']['configurations']==[[[],[0]]]


@pytest.mark.parametrize('extra',[{2:{'slotLevels':[[],[0]]}},{1:['not a config']},{1:{'unknown':1}}])
def test_unverified_custom_slot_siblings_remain_blocked(extra):
    data=model()
    data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries']=[{'type':'COAL','capacity':68}]
    entry=data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    custom={'configurations':[{'slotLevels':[[],[0]]}],**deepcopy(extra)}
    entry['customCargoModels']=custom
    prepared=prepare_vehicle_model(data,model_path='vehicle/train/test.mdl',report={})
    assert prepared['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['customCargoModels']==custom
    with pytest.raises(ValueError,match='customCargoModels fields'):
        port_compartments(prepared['metadata']['transportVehicle'],catalog=CargoCatalog.from_native(NativeCargo()),
            nodes=list(flatten(data['lods'][0]['node'])),expand_classes=False,allow_legacy_layouts=True)


def test_absent_visibility_names_keep_existing_bindings_and_capacity():
    data=model()
    load=data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    load['cargoEntries']=[{'type':'COAL','capacity':68}]
    load['toHide']=['wheel','missing_source_wheel',1]
    original=deepcopy(data)
    audit={}
    prepared=prepare_vehicle_model(data,model_path='vehicle/train/test.mdl',report=audit)
    target=prepared['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    assert data==original and target['toHide']==['wheel',1]
    assert target['cargoEntries']==load['cargoEntries']
    assert audit['vehicleWarnings'][0]['sourceValue']==load['toHide']
    options={'catalog':CargoCatalog.from_native(NativeCargo()),'nodes':list(flatten(data['lods'][0]['node'])),
        'expand_classes':False}
    with pytest.raises(ValueError,match='missing node'):
        port_compartments(data['metadata']['transportVehicle'],**options)
    converted,_,cargo_audit=port_compartments(prepared['metadata']['transportVehicle'],**options)
    load=converted['compartments'][0]['loadConfigs'][0]
    assert load['toHide']==['wheel','body'] and load['cargoEntry']['capacity']==cargo_audit['maxCapacity']==68


def test_visibility_name_present_in_another_source_lod_is_preserved():
    data=model()
    data['lods'].append(deepcopy(data['lods'][0]))
    data['lods'][1]['node']['children'].append({'name':'only_far_lod','mesh':'far.msh','materials':['body.mtl']})
    load=data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    load['toHide']=['only_far_lod']
    prepared=prepare_vehicle_model(data,model_path='vehicle/train/test.mdl',report={})
    assert prepared['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['toHide']==['only_far_lod']


@pytest.mark.parametrize('flag',[True,False])
def test_external_industry_flag_preserves_native_cargo_and_source(flag):
    data=model()
    load=data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    load['cargoEntries']=[{'type':'PLANKS','capacity':8,'rt_off':flag}]
    original=deepcopy(data);audit={}
    prepared=prepare_vehicle_model(data,model_path='vehicle/truck/test.mdl',report=audit)
    assert data==original and audit['vehicleWarnings'][0]['sourceValue'] is flag
    options={'catalog':CargoCatalog.from_native(NativeCargo()),'nodes':list(flatten(data['lods'][0]['node'])),
        'expand_classes':False}
    with pytest.raises(ValueError,match='rt_off'):
        port_compartments(data['metadata']['transportVehicle'],**options)
    converted,_,cargo_audit=port_compartments(prepared['metadata']['transportVehicle'],**options)
    cargo=converted['compartments'][0]['loadConfigs'][0]['cargoEntry']
    assert cargo['capacity']==cargo_audit['maxCapacity']==8
    assert cargo['cargoTypeSet']['cargoTypesIncluded']==['::/cargos/planks/planks.cargo']


@pytest.mark.parametrize('flag',[1,'dynamic'])
def test_nonboolean_external_industry_flag_remains_blocked(flag):
    data=model()
    load=data['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    load['cargoEntries']=[{'type':'PLANKS','capacity':8,'rt_off':flag}]
    prepared=prepare_vehicle_model(data,model_path='vehicle/truck/test.mdl',report={})
    with pytest.raises(ValueError,match='rt_off'):
        port_compartments(prepared['metadata']['transportVehicle'],catalog=CargoCatalog.from_native(NativeCargo()),
            nodes=list(flatten(data['lods'][0]['node'])),expand_classes=False)


def test_non_vehicle_dynamic_helper_does_not_block_vehicle_package(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    path = source/'res/models/model/vehicle/train/helper_example.mdl'
    text = 'local unknown = require "unknown"\nlocal n = unknown.generate()\nfunction data() return {version=1,metadata={},lods={{node=n}}} end'
    path.write_text(text)
    vehicle_path = source/'res/models/model/vehicle/train/test.mdl'
    vehicle_path.write_text(vehicle_path.read_text().replace('groupFileName = ""',
        'groupFileName = "vehicle/train/helper_example.mdl"'))
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft', vehicle_policy='tf2_complete')
    assert not (output/'content/models/model/vehicle/train/helper_example.mdl').exists()
    assert (output/'_port_originals/res/models/model/vehicle/train/helper_example.mdl').read_text() == text
    assert result['portCounts']['models'] == 1
    assert '::/models/model/vehicle/train/helper_example.mdl' in (output/'content/models/model/vehicle/train/test.mdl').read_text()
    assert any(w.get('kind') == 'model' and 'helper_example.mdl' in w.get('targetReference','')
               for w in result['migrationAudit']['vehicleWarnings'])


def test_missing_mesh_geometry_is_archived_and_external_in_vehicle_mode(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    path = source/'res/models/mesh/orphan.msh'
    path.write_text(emit({'subMeshes':[], 'vertexAttr':[]}))
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft', vehicle_policy='tf2_complete')
    assert not (output/'content/models/mesh/orphan.msh').exists()
    assert (output/'_port_originals/res/models/mesh/orphan.msh').read_bytes() == path.read_bytes()
    assert any('unused mesh' in row['message'] for row in result['migrationAudit']['vehicleWarnings'])
    (source/'res/models/mesh/wheel.msh.blob').unlink()
    with pytest.raises(ValueError, match='Missing mesh blob'):
        port_tf2_mod(source, output.parent/'strict', tf3_game=game, mod_id='other', name='Draft')
    result = port_tf2_mod(source, output.parent/'external', tf3_game=game, mod_id='other', name='Draft', vehicle_policy='tf2_complete')
    assert not (output.parent/'external/content/models/mesh/wheel.msh').exists()
    assert '::/models/mesh/wheel.msh' in (output.parent/'external/content/models/model/vehicle/train/test.mdl').read_text()
    assert any('referenced mesh descriptor' in row['message'] for row in result['migrationAudit']['vehicleWarnings'])


def test_unsupported_helper_animation_keeps_literal_vehicle_data(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    path = source/'res/models/model/vehicle/train/test.mdl'
    path.write_text('local vehicleutil = require "vehicleutil"\n'+path.read_text().replace('name = "root",',
                    'name = "root", animations = {drive = vehicleutil.makeCouplingRodAnim(1)},'))
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft', vehicle_policy='tf2_complete')
    text = (output/'content/models/model/vehicle/train/test.mdl').read_text()
    assert 'power = 1220' in text and 'weightEmpty = 79500' in text
    assert any('helper animation' in row['message'] for row in result['migrationAudit']['vehicleWarnings'])
    assert 'makeCouplingRodAnim' in (output/'_port_originals/res/models/model/vehicle/train/test.mdl').read_text()


def test_unreferenced_invalid_mesh_archives_geometry_without_counting_it_as_active(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    relative = 'models/mesh/unused.msh'
    descriptor = emit({'subMeshes':[{'materials':[' ']}], 'vertexAttr':[]})
    (source/'res'/relative).write_text(descriptor)
    (source/'res'/(relative+'.blob')).write_bytes(b'unused geometry')
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft', vehicle_policy='tf2_complete')
    assert result['portCounts']['meshes'] == 3
    assert not (output/'content'/relative).exists()
    assert not (output/'content'/(relative+'.blob')).exists()
    assert (output/'_port_originals/res'/relative).read_text() == descriptor
    assert (output/'_port_originals/res'/(relative+'.blob')).read_bytes() == b'unused geometry'
    assert any('unused mesh with unported' in w['message'] for w in result['migrationAudit']['vehicleWarnings'])


def test_unbound_optional_forward_flag_is_omitted_without_guessing_direction(fixture_mod, class_catalog):
    source, game, output = fixture_mod
    path = source/'res/models/model/vehicle/train/test.mdl'
    path.write_text(path.read_text().replace('crew = true','crew = true, forward = f'))
    result = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft', vehicle_policy='tf2_complete')
    assert any('optional forward' in w['message'] for w in result['migrationAudit']['vehicleWarnings'])
    assert 'forward = f' in (output/'_port_originals/res/models/model/vehicle/train/test.mdl').read_text()


@pytest.mark.parametrize('weight,speed,path', [(0,0,'vehicle/train/menu.mdl'),
    (79.5,25,'vehicle/train/engine_menu.mdl')])
def test_empty_menu_metadata_can_use_native_compatibility(class_catalog,weight,speed,path):
    source = model()
    source['lods'] = []
    source['metadata']['railVehicle'].update(weight=weight,topSpeed=speed,engines=[],configs=[{}],soundSet={})
    source['metadata']['transportVehicle']['multipleUnitOnly'] = True
    source['metadata']['seatProvider'] = {'seats':[]}
    calls = ('sortLods','toCompartmentList','addTransformatorConfig','replaceMeshIdWithNodeName',
        'squeezeConfigsToOneConfigForVehicles','turnRoadAndRailToLandVehicle','convertWeight',
        'landVehicleSoundSetToSoundConfig','makeCargoEntry','makeCargoTypeSet','convertCargoTypes',
        'addVehicleExtent','addTransportVehicleTransportModes','convertParticleSystem')
    class Native:
        def reference(self,path):return '::/'+path
        def read(self,path):return ('\n'.join('function model_metadata_util.'+c+'(p,d) return d end' for c in calls)).encode()
    text = compatibility_model(source,lambda p,k:p,Native(),model_path=path,report={},emissions_policy='tf3_automatic')
    assert 'result.version = 2' in text and f'weight = {weight}' in text and f'topSpeed = {speed}' in text

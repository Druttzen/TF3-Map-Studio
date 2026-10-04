"""End-to-end authored packages, including cargo, pure configs and batch dispatch."""
from copy import deepcopy
import json
import zipfile

import pytest

from trf3_mod_converter.batch import _preflight_profile, convert_queue, scan_mods
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, NativeInventory, port_tf2_mod, snapshot
from test_tf2_vehicle_port import fixture_mod, model


def native_files(game, files):
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        for path, data in files.items():
            archive.writestr(path, emit(data))


def write_model(source, data):
    (source/'res/models/model/vehicle/train/test.mdl').write_text(emit(data), encoding='utf-8')


@pytest.mark.parametrize('family', ['steam','diesel','wagon','tram','bus','truck','ship','plane','car','person','asset'])
def test_full_family_export_and_batch_preflight(fixture_mod, family):
    source, game, output = fixture_mod
    data = model(); m = data['metadata']
    config = {'axles':['wheel.msh'], 'fakeBogies':[]}
    sound = {'name':'train_electric_old', 'horn':'horn.wav'}
    if family in ('steam','diesel','wagon','tram'):
        m['railVehicle']['engines'] = [] if family == 'wagon' else [{'type':family.upper() if family != 'tram' else 'ELECTRIC','power':100,'tractiveEffort':50}]
        if family == 'tram':
            m['transportVehicle']['carrier']='TRAM'
            native_files(game, {'vehicle/tram/shared/default_tram.trf.lua':{}})
    else:
        del m['railVehicle']
        if family in ('bus','truck','car'):
            m['roadVehicle']={'engine':{'type':'DIESEL','power':100,'tractiveEffort':50},
                'weight':12, 'topSpeed':20, 'configs':[config], 'soundSet':sound}
            m['transportVehicle']['carrier']='ROAD'
            native_files(game, {'vehicle/shared/default_road.trf.lua':{}})
            if family == 'car':
                del m['transportVehicle'];m['car']={}
            else:
                m['seatProvider']['drivingLicense']=family.upper()
        elif family == 'ship':
            m['waterVehicle']={'weight':10000, 'topSpeed':10,'type':'SMALL','area':10,'availPower':100,
                'maxRpm':100,'waterLine':[[-5,0],[5,0]],'configs':[{'paddles':[], 'rudder':{'ids':[1],'maxAngle':15}}]}
            m['transportVehicle']['carrier']='WATER'
            native_files(game, {'vehicle/ship/shared/default_ship.trf.lua':{}})
        elif family == 'plane':
            m['airVehicle']={'weight':10000,'topSpeed':80,'type':'SMALL','maxThrust':1000,
                'idleThrust':100,'wingArea':30,'timeToFullThrust':5,
                'configs':[{'axles':[],'wheels':['wheel.msh'],'axleRadii':[],'wheelRadii':[0.3],
                            'rudder':{'ids':[1],'maxAngle':20}}]}
            m['transportVehicle']['carrier']='AIR'
            native_files(game, {'vehicle/shared/default_air.trf.lua':{}})
        else:
            del m['transportVehicle'];m.pop('seatProvider');m.pop('emission')
            if family == 'person':m['person']={'gender':'MALE','drivingLicenses':['RAIL']}
    write_model(source, data)
    original = snapshot(source)
    _preflight_profile(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Fixture')
    assert snapshot(source)==original
    target = load_lua_table((output/'content/models/model/vehicle/train/test.mdl').read_text())
    assert target['version']==2
    assert report['nativeTest']=='not_run'
    expected = {'steam':'train','diesel':'train','wagon':'waggon','plane':'plane'}.get(family,family)
    assert report['migrationAudit']['vehicleProfiles'][0]['family']==expected
    if family in ('ship','plane'):
        assert report['portCounts']['generatedAnimations']==1
        assert list((output/'content/models/animation/_tf3_port').glob('*.ani'))


def cargo_files():
    return {'cargos/coal/coal.cargo.lua':{'cargoClasses':['BULK','UNIVERSAL'],'weightFactor':1},
            'cargos/iron_ore/iron_ore.cargo.lua':{'cargoClasses':['BULK','UNIVERSAL'],'weightFactor':1},
            'cargos/water/water.cargo.lua':{'cargoClasses':['LIQUID','UNIVERSAL'],'weightFactor':1},
            'cargos/shared/bulk.cargoclass.lua':{'tag':'BULK'},
            'cargos/shared/liquid.cargoclass.lua':{'tag':'LIQUID'},
            'cargos/shared/universal.cargoclass.lua':{'tag':'UNIVERSAL'}}


def test_cargo_export_retains_capacity_adds_only_same_class_and_per_mod_refs(fixture_mod, tmp_path):
    source, game, output=fixture_mod
    from test_native_donors import donor
    native_model=donor(cargo='COAL',engine='ELECTRIC',payload=8000)
    native_model['metadata']['extent']=deepcopy(model()['boundingInfo'])
    native_model['metadata']['landVehicle'].update(weightEmpty=79500,topSpeed=25,
        engines=[{'type':'ELECTRIC','power':1220,'tractiveEffort':120}])
    native_files(game, {**cargo_files(),'vehicle/train/bulk/bulk.mdl':native_model})
    data=model(); data['metadata']['seatProvider']=[]
    data['metadata']['transportVehicle']['compartmentsList']=[{'loadConfigs':[{
        'cargoEntries':[{'type':'COAL','capacity':40}], 'toHide':[1]}]}]
    write_model(source, data)
    inventory=NativeInventory(game)
    for dest in (output,tmp_path/'second'):
        report=port_tf2_mod(source,dest,tf3_game=game,mod_id='fixture_test',name='Fixture',_native_inventory=inventory)
        audit=report['migrationAudit']['cargoMigrations'][0]
        assert audit['maxCapacity']==40
        assert [a['cargoType'] for a in audit['additions']]==['iron_ore']
        assert 'cargos/coal/coal.cargo' in report['baseGameResources']
        assert 'cargos/iron_ore/iron_ore.cargo' in report['baseGameResources']
        assert 'cargos/water/water.cargo' not in report['baseGameResources']
        target=load_lua_table((dest/'content/models/model/vehicle/train/test.mdl').read_text())
        assert target['metadata']['landVehicle']['weightMaxPayload']==8000
        assert audit['payloadPolicy']=='matched_native_capacity_ratio'
        assert report['migrationAudit']['dataCompletions'][0]['donorResource']=='vehicle/train/bulk/bulk.mdl'
        assert 'vehicle/train/bulk/bulk.mdl' in report['baseGameResources']
        loads=target['metadata']['transportVehicle']['compartments'][0]['loadConfigs']
        assert [l['cargoEntry']['capacity'] for l in loads]==[40,40]
        assert all(l['toHide']==['body'] for l in loads)
    assert hasattr(inventory,'_cargo_catalog')
    assert inventory.references==set()


def test_pure_config_package_exports_without_any_vehicle_model(fixture_mod):
    source,game,output=fixture_mod
    import shutil
    shutil.rmtree(source/'res')
    path=source/'res/config/multiple_unit/custom.lua';path.parent.mkdir(parents=True)
    path.write_text(emit({'name':'Fixture','vehicles':[{'name':'characters/era_a_driver_rail.mdl','forward':True}]}))
    native_files(game, {'characters/era_a_driver_rail/era_a_driver_rail.mdl':{}})
    _preflight_profile(source)
    report=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Fixture')
    assert report['portCounts']['models']==0
    assert report['portCounts']['multiple_unit']==1
    assert (output/'content/config/multiple_unit/custom.mu.lua').exists()


def test_queue_dispatches_non_electric_profiles(fixture_mod):
    source,game,output=fixture_mod
    d=model();d['metadata']['railVehicle']['engines'][0]['type']='DIESEL';write_model(source,d)
    items=scan_mods(source)['items']
    result=convert_queue(items,output,tf3_game=game)
    assert result['counts']['completed']==1
    assert result['counts']['failed']==0
    saved=json.loads((output/items[0].mod_id/'conversion-report.json').read_text())
    assert saved['migrationAudit']['vehicleProfiles'][0]['profile']=='tf2_train_diesel'


def test_common_particle_camera_label_and_inline_animation_are_retained():
    from trf3_mod_converter.tf2_vehicle_port import port_model
    from test_tf2_vehicle_port import Native
    d=model();original=deepcopy(d)
    d['metadata']['cameraConfig']={'positions':[{'group':1,'fov':80}]}
    d['metadata']['labelList']={'labels':[{'childId':1,'type':'NAME'}]}
    d['metadata']['particleSystem']={'emitters':[{'child':1,'frequency':20,'lifeTime':3,
        'size01':[0.2,2], 'color':[0.5,0.5,0.5], 'velocity':[0,0,2], 'initialAlpha':0.7}]}
    node=d['lods'][0]['node']['children'][0]
    node['animations']={'open':{'type':'KEYFRAME','params':{'origin':[0,0,0],
        'keyframes':[{'time':0,'rot':[0,0,0],'transl':[0,0,0]}]}}}
    before=deepcopy(d);report={}
    target=port_model(d,lambda ref,kind:ref,Native(),report=report)
    assert d==before and d!=original
    m=target['metadata'];e=m['particleSystem']['emitters'][0]
    assert m['cameraConfig']['positions'][0]['group']=='body'
    assert m['labelList']['labels'][0]['childId']=='body'
    assert e['child']=='body' and e['frequency']=={'value':20}
    assert e['sizeOverLifeTime']['curve'][1]['value']=={'value':2}
    assert report['particleMigrations'][0]['engineDependentTiming']=='requires_native_verification'
    assert target['lods'][0]['node']['children'][0]['animations']['open']==node['animations']['open']


def test_localized_display_does_not_translate_matching_identifiers():
    from trf3_mod_converter.resource_profiles import load_resource_table
    text='function data() return {params={{key="Localized",name=_("Localized")}}, tags={"Localized"}} end'
    data=load_resource_table(text)
    output=emit(data, {'Localized'})
    assert 'key = "Localized"' in output
    assert 'name = _("Localized")' in output
    assert 'tags = { "Localized" }' in output


def test_editor_backup_is_inert_and_does_not_collide_with_live_model(fixture_mod):
    source,game,output=fixture_mod
    live=source/'res/models/model/vehicle/train/test.mdl'
    backup=live.with_name(live.name+'~');backup.write_bytes(b'original editor backup')
    report=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Fixture')
    assert report['portCounts']['models']==1
    path=report['pathMapping']['models/model/vehicle/train/test.mdl~']
    assert path.endswith('.editor_backup')
    assert (output/'content'/path).read_bytes()==b'original editor backup'


def test_native_binary_at_sign_is_not_confused_with_callback_suffix(fixture_mod):
    _,game,_=fixture_mod
    with zipfile.ZipFile(game/'base/content/resources.zip','a') as archive:
        archive.writestr('ui/icon@2x.tga',b'authored image placeholder')
    assert NativeInventory(game).reference('ui/icon@2x.tga')=='::/ui/icon@2x.tga'


@pytest.mark.parametrize('count', [2,4])
def test_color_blend_uses_material_specific_schema_and_retains_colors(fixture_mod,count):
    _,game,_=fixture_mod
    prop='color_blend' if count==2 else 'color_blend4'
    native_files(game, {f'rendering/properties/{prop}.prop.lua':{'fragmentProperties':[
        {'name':'albedoScales','arrayCount':count,'defaultValue':0},
        {'name':'colors','arrayCount':count,'defaultValue':[-1,-1,-1]}]},
        'rendering/fixture.mat.lua':{'properties':[{'name':'color_blend','id':f'properties/{prop}.prop'}]}})
    values={'colors':[[0.3,0.5,0.7]],'albedoScales':[0.6]}
    source={'type':'FIXTURE','params':{'color_blend':values}}
    before=deepcopy(source);log={}
    result=NativeInventory(game).material(source,lambda ref,kind:ref,report=log)
    fields=result['params']['color_blend']['fragmentProperties'][0]
    assert fields['albedoScales']==[0.6]+[0]*(count-1)
    assert fields['colors']==[[0.3,0.5,0.7]]+[[-1,-1,-1]]*(count-1)
    assert log['materialMigrations'][0]['nativeSchema'].endswith(prop+'.prop.lua')
    assert 'light_receiver' not in result['params']  # This authored type does not declare it.
    assert source==before
    source['params']['color_blend']={'albedoScales':[], 'colors':[]}
    fields=NativeInventory(game).material(source,lambda ref,kind:ref)['params']['color_blend']['fragmentProperties'][0]
    assert fields['albedoScales']==[0]*count
    assert fields['colors']==[[-1,-1,-1]]*count
    if count==2:
        source['params']['color_blend']={'albedoScale':0.65,'colors':[]}
        fields=NativeInventory(game).material(source,lambda ref,kind:ref)['params']['color_blend']['fragmentProperties'][0]
        assert fields['albedoScales']==[0.65,0]
        assert fields['colors']==[[-1,-1,-1],[-1,-1,-1]]


def test_lod_mesh_variant_requires_explicit_same_name_and_world_transform():
    from trf3_mod_converter.tf2_vehicle_port import port_model
    from test_tf2_vehicle_port import Native
    d=model(); d['lods'].append(deepcopy(d['lods'][0]))
    d['metadata']['railVehicle']['configs'].append(deepcopy(d['metadata']['railVehicle']['configs'][0]))
    wheel=d['lods'][1]['node']['children'][1];wheel['mesh']='wheel_lod1.msh'
    audit={}
    result=port_model(d,lambda ref,kind:ref,Native(),report=audit)
    assert result['metadata']['railVehicle']['config']['axles']==['wheel']
    assert audit['vehicleAdaptations'][0]['nodes']==['wheel']
    wheel['transf']=[1,0,0,0,0,1,0,0,0,0,1,0,2,0,0,1]
    with pytest.raises(ValueError,match='has no node'):
        port_model(d,lambda ref,kind:ref,Native())


def test_material_property_must_be_declared_by_selected_native_type(fixture_mod):
    _,game,_=fixture_mod
    native_files(game, {'rendering/properties/color_blend.prop.lua':{'fragmentProperties':[
        {'name':'albedoScales','arrayCount':2,'defaultValue':0},
        {'name':'colors','arrayCount':2,'defaultValue':[-1,-1,-1]}]}})
    with pytest.raises(ValueError,match='PHYSICAL does not declare property color_blend'):
        NativeInventory(game).material({'type':'PHYSICAL','params':{
            'color_blend':{'albedoScales':[0.5]}}},lambda ref,kind:ref)


@pytest.mark.parametrize('url', [[], [''], ['https://example.org/mod']])
def test_single_literal_url_wrapper_is_unwrapped_without_loss(fixture_mod,url):
    source,game,output=fixture_mod
    descriptor=load_lua_table((source/'mod.lua').read_text())
    descriptor['info']['url']=url
    (source/'mod.lua').write_text(emit(descriptor),encoding='utf-8')
    before=snapshot(source)
    report=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Fixture')
    info=json.loads((output/'_metadata/modinfo.json').read_text())
    assert info['url']==(url[0] if url else '')
    assert report['migrationAudit']['metadataMigrations'][0]['sourceValue']==url
    assert snapshot(source)==before


def test_package_resolves_mesh_default_from_unanimous_explicit_model_slot(fixture_mod):
    source,game,output=fixture_mod
    mesh=source/'res/models/mesh/body.msh'
    descriptor={'subMeshes':[{'indices':{'position':{'count':0,'offset':0}},
                              'materials':['missing/old_body.mtl']}],
                'vertexAttr':{'position':{'count':0,'numComp':3,'offset':0}}}
    mesh.write_text(emit(descriptor),encoding='utf-8')
    before=snapshot(source)
    report=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Fixture')
    target=load_lua_table((output/'content/models/mesh/body.msh').read_text())
    assert target['subMeshes'][0]['materials']==['fixture_test::/models/material/body.mtl']
    assert target['subMeshes'][0]['indices']==descriptor['subMeshes'][0]['indices']
    assert target['vertexAttr']==descriptor['vertexAttr']
    assert report['migrationAudit']['meshMigrations'][0]['method']=='unanimous_explicit_model_material_slot'
    assert (output/'content/models/mesh/body.msh.blob').read_bytes()==(source/'res/models/mesh/body.msh.blob').read_bytes()
    assert snapshot(source)==before


@pytest.mark.parametrize('suffix', ['zip','dll'])
def test_opaque_resource_containers_cannot_receive_success(fixture_mod,suffix):
    source,game,output=fixture_mod
    (source/f'res/opaque.{suffix}').write_bytes(b'opaque source behavior')
    original=snapshot(source)
    with pytest.raises(ValueError, match='Opaque resource'):
        _preflight_profile(source)
    with pytest.raises(ValueError, match='Opaque resource'):
        port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Fixture')
    assert snapshot(source)==original
    assert not output.exists()

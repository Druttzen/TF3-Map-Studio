from copy import deepcopy
import json
import zipfile

import pytest

from trf3_mod_converter.lua_metadata import UnsupportedValue, load_lua_table
from trf3_mod_converter.tf2_vehicle_port import NativeInventory, checked_name, emit, literal, port_model, port_tf2_mod, snapshot


class Native:
    def reference(self, path): return '::/'+path


def model():
    return {'version':1,'boundingInfo':{'bbMin':[-6,-2,0],'bbMax':[6,2,5]},'lods':[
        {'node':{'name':'root','children':[
            {'name':'body','children':[{'name':'body','mesh':'body.msh','materials':['body.mtl']}]},
            {'name':'wheel','mesh':'wheel.msh','materials':['body.mtl']},
            {'name':'light','mesh':'light.msh','materials':['light.mtl']}]}},
    ],'metadata':{'transportVehicle':{'carrier':'RAIL','compartmentsList':[{'loadConfigs':[{'cargoEntries':[], 'toHide':[]}]}],
                                    'groupFileName':'','loadSpeed':1,'multipleUnitOnly':False,'reversible':True},
                   'railVehicle':{'engines':[{'type':'ELECTRIC','power':1220,'tractiveEffort':120}],
                       'topSpeed':25,'weight':79.5,'soundSet':{'name':'train_electric_old','horn':'horn.wav'},
                       'configs':[{'axles':['wheel.msh'],'frontForwardParts':[4],
                                   'fakeBogies':[{'group':1,'offset':3.1,'position':0}]}]},
                   'seatProvider':{'crewModels':[], 'seats':[{'group':1,'crew':True}]},
                   'emission':{'idleEmission':-1,'speedEmission':-1,'powerEmission':-1},
                   'maintenance':{'lifespan':36525}}}


@pytest.fixture
def fixture_mod(tmp_path):
    source = tmp_path/'source'; game = tmp_path/'game'
    source.mkdir(); content = game/'base/content'; content.mkdir(parents=True)
    (source/'mod.lua').write_text(emit({'info':{'name':'Fixture','description':'key','authors':[{'name':'Original Creator'}]}}))
    (source/'strings.lua').write_text(emit({'en':{'key':'Original description'}}))
    data = model(); data['metadata']['description']={'name':'key'}
    files = {'models/model/vehicle/train/test.mdl':emit(data),
             'models/material/body.mtl':emit({'type':'PHYSICAL','params':{'map_albedo':{'fileName':'body.dds'}}}),
             'models/material/light.mtl':emit({'type':'PHYSICAL','params':{'map_albedo':{'fileName':'body.dds'}}})}
    for mesh in ('body','wheel','light'):
        files[f'models/mesh/{mesh}.msh']=emit({'subMeshes':[], 'vertexAttr':[]})
        files[f'models/mesh/{mesh}.msh.blob']=b'original mesh binary\x00\xff'
    files.update({'textures/body.dds':b'fixture texture','audio/effects/horn.wav':b'fixture audio'})
    for path, value in files.items():
        target=source/'res'/path; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(value if isinstance(value,bytes) else value.encode())
    with zipfile.ZipFile(content/'resources.zip','w') as archive:
        archive.writestr('rendering/physical.mat.lua',emit({'properties':[
            {'name':'map_albedo','id':'properties/map_albedo.prop'}]}))
        archive.writestr('rendering/properties/map_albedo.prop.lua',emit({'fragmentSamplers':[{'name':'albedoTex'}]}))
        for path in ('vehicle/train/shared/sound/train_electric_old.snd.lua',
                     'vehicle/train/shared/default_train.trf.lua',
                     'vehicle/shared/ani/front_forward_parts_on.ani',
                     'vehicle/shared/ani/front_forward_parts_off.ani'):
            archive.writestr(path,'return {}')
    return source,game,tmp_path/'output'


@pytest.fixture
def fractional_revision_mod(fixture_mod):
    source, _, _ = fixture_mod
    metadata = load_lua_table((source/'mod.lua').read_text())
    metadata['info']['minorVersion'] = 1.2
    (source/'mod.lua').write_text(emit(metadata), encoding='utf-8')
    return fixture_mod


@pytest.mark.parametrize('revision', [0, 6])
def test_fractional_source_revision_accepts_explicit_integer_override(fractional_revision_mod, revision):
    source, game, output = fractional_revision_mod
    before = snapshot(source)
    original_metadata = (source/'mod.lua').read_bytes()
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft',
                          revision=revision)
    assert report['revision'] == revision
    assert json.loads((output/'mod.json').read_text())['revision'] == revision
    assert snapshot(source) == before
    assert (output/'_port_originals/mod.lua').read_bytes() == original_metadata
    assert load_lua_table((source/'mod.lua').read_text())['info']['minorVersion'] == 1.2


def test_fractional_source_revision_still_needs_an_explicit_override(fractional_revision_mod):
    source, game, output = fractional_revision_mod
    before = snapshot(source)
    with pytest.raises(ValueError, match='revision must be a non-negative integer'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft')
    assert snapshot(source) == before
    assert not output.exists()


@pytest.mark.parametrize('revision', [-1, 1.2, True])
def test_fractional_source_revision_rejects_invalid_override(fractional_revision_mod, revision):
    source, game, output = fractional_revision_mod
    before = snapshot(source)
    with pytest.raises(ValueError, match='Revision override must be a non-negative integer'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft',
                     revision=revision)
    assert snapshot(source) == before
    assert not output.exists()


def test_full_port_preserves_binaries_source_and_credits(fixture_mod):
    source,game,output=fixture_mod; before=snapshot(source)
    report=port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='New Name')
    assert snapshot(source)==before
    assert report['sourceUnchanged'] and report['nativeTest']=='not_run'
    assert json.loads((output/'conversion-report.json').read_text())==report
    assert json.loads((output/'source-sha256.json').read_text())==before
    assert report['portCounts']=={'models':1,'materials':2,'meshes':3,'animations':0}
    for path in ('models/mesh/wheel.msh','models/mesh/wheel.msh.blob','textures/body.dds','audio/effects/horn.wav'):
        assert (output/'content'/path).read_bytes()==(source/'res'/path).read_bytes()
    assert (output/'_port_originals/res/models/model/vehicle/train/test.mdl').read_bytes()==(source/'res/models/model/vehicle/train/test.mdl').read_bytes()
    assert json.loads((output/'_metadata/modinfo.json').read_text())['authors'][0]['name']=='Original Creator'
    assert not (output/'content/vehicle/train/shared/default_train.trf.lua').exists()
    material=load_lua_table((output/'content/models/material/body.mtl').read_text())
    assert material['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName']=='fixture_test::/textures/body.dds'


def stock_dependencies(fixture_mod):
    from test_source_game_resources import geometry, dds, installed
    source, game, output = fixture_mod
    mesh, blob, _ = geometry()
    files = {'models/mesh/light.msh': mesh, 'models/mesh/light.msh.blob': blob,
             'models/material/light.mtl': emit({'type':'PHYSICAL', 'params':{
                 'map_albedo':{'fileName':'stock.dds'}}}).encode(), 'textures/stock.dds':dds()}
    tf2, _ = installed(source.parent, files)
    for path in files:
        local = source/'res'/path
        if local.exists(): local.unlink()
    return tf2, files


def test_exact_installed_dependencies_run_adapters_and_archive_all_input_bytes(fixture_mod):
    from trf3_mod_converter.source_game_resources import verify_source_game_dependencies
    source, game, output = fixture_mod
    tf2, files = stock_dependencies(fixture_mod)
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=tf2, mod_id='fixture_test', name='Draft')
    assert snapshot(source) == before
    rows = report['sourceGameDependencies']
    assert len(rows) == 4
    assert report['sourceGameInstallation'] == str(tf2.resolve())
    assert verify_source_game_dependencies(tf2, rows, report['sourceGameResourceFingerprints'],
                                          report['sourceGameInventoryFingerprint'])
    for row in rows:
        assert (output/row['originalFile']).read_bytes() == files[row['sourceResource'][4:]]
    for path in ('models/mesh/light.msh', 'models/mesh/light.msh.blob', 'textures/stock.dds'):
        assert (output/'content'/path).read_bytes() == files[path]
    material = load_lua_table((output/'content/models/material/light.mtl').read_text())
    assert material['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName'] == 'fixture_test::/textures/stock.dds'


def test_installed_mesh_rejects_mismatched_authored_material_slots(fixture_mod):
    source, game, output = fixture_mod
    tf2, _ = stock_dependencies(fixture_mod)
    path = source/'res/models/model/vehicle/train/test.mdl'
    data = load_lua_table(path.read_text())
    data['lods'][0]['node']['children'][2]['materials'] = ['body.mtl', 'body.mtl']
    path.write_text(emit(data))
    with pytest.raises(ValueError, match='material slots'):
        port_tf2_mod(source, output, tf3_game=game, tf2_game=tf2, mod_id='fixture_test', name='Draft')
    assert not output.exists()


def test_installed_material_cannot_bind_to_unrelated_authored_texture(fixture_mod):
    source, game, output = fixture_mod
    tf2, _ = stock_dependencies(fixture_mod)
    (source/'res/textures/stock.dds').write_bytes(b'unrelated authored texture')
    with pytest.raises(ValueError, match='conflicts with an authored resource'):
        port_tf2_mod(source, output, tf3_game=game, tf2_game=tf2, mod_id='fixture_test', name='Draft')
    assert not output.exists()


def test_installed_dependency_change_blocks_publication(fixture_mod, monkeypatch):
    source, game, output = fixture_mod
    tf2, _ = stock_dependencies(fixture_mod)
    original = NativeInventory.material
    def change_after_adaptation(self, data, resolve, **kwargs):
        result = original(self, data, resolve, **kwargs)
        if kwargs.get('resource') == 'models/material/light.mtl':
            (tf2/'res/textures/stock.dds').write_bytes(b'changed after reading')
        return result
    monkeypatch.setattr(NativeInventory, 'material', change_after_adaptation)
    with pytest.raises(ValueError, match='installed TF2 resources changed'):
        port_tf2_mod(source, output, tf3_game=game, tf2_game=tf2, mod_id='fixture_test', name='Draft')
    assert not output.exists()


@pytest.mark.parametrize('case',['callback','script','module','repair','blob','nested','alias_source'])
def test_port_blockers_preserve_existing_output(fixture_mod,case):
    source,game,output=fixture_mod
    output.mkdir(); (output/'sentinel.txt').write_text('keep me')
    repairs=None
    if case=='callback':
        (source/'mod.lua').write_text('function data() return {info={name="Fixture"},runFn=function() error("must never execute") end} end')
    if case=='script': (source/'res/custom.lua').write_text('error("must never execute")')
    if case=='module': (source/'res/custom.module').write_text('error("must never execute")')
    if case=='repair': repairs={'unused.dds':'body.dds'}
    if case=='blob': (source/'res/models/mesh/wheel.msh.blob').unlink()
    if case=='nested': output=source/'nested'
    if case=='alias_source': output=source/'..'/'source'
    before=snapshot(source)
    with pytest.raises(ValueError): port_tf2_mod(source,output,tf3_game=game,mod_id='fixture_test',name='Fixture',repairs=repairs,overwrite=True)
    assert snapshot(source)==before
    assert (source.parent/'output/sentinel.txt').read_text()=='keep me'


def test_native_inventory_requires_real_resource(fixture_mod):
    _,game,_=fixture_mod; native=NativeInventory(game)
    assert native.reference('vehicle/train/shared/default_train.trf')=='::/vehicle/train/shared/default_train.trf'
    with pytest.raises(ValueError,match='missing'): native.reference('vehicle/missing.trf')


def test_cli_port_exports_draft_and_applies_metadata(fixture_mod,capsys):
    from trf3_mod_converter.cli import main
    source,game,output=fixture_mod
    assert main(['port-tf2',str(source),str(output),'--tf3-game',str(game),
                 '--mod-id','fixture_test','--name','Draft','--revision','6'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['revision']==6 and report['portProfile']=='tf2_electric_locomotive'
    assert report['nativeTest']=='not_run'


def test_actual_unit_and_node_migration_preserves_input():
    source=model(); original=deepcopy(source)
    target=port_model(source,lambda ref,kind:'test::/'+kind+'/'+ref,Native())
    assert source == original
    assert target['version'] == 2
    m=target['metadata']
    assert m['landVehicle']['weightEmpty'] == 79500
    assert m['landVehicle']['engines'][0]['power'] == 1220
    assert m['landVehicle']['topSpeed'] == 25
    assert m['maintenance']['lifespan'] == 73050
    assert m['seatProvider']['seats'][0]['group'] == 'body'
    assert m['railVehicle']['config']['axles'] == ['wheel']
    assert m['railVehicle']['config']['fakeBogies'][0][0]['group'] == 'body'
    assert m['soundConfig']['effects']['horn'] == ['test::/audio/horn.wav']
    assert m['transportVehicle']['compartments'][0]['loadConfigs'][0]['cargoEntry']['capacity'] == 0
    nodes=target['lods'][0]['node']['children']
    assert nodes[0]['children'][0]['name'] == 'body_mesh'
    assert nodes[2]['animations']['front_forward_parts_on']['params']['id'].endswith('front_forward_parts_on.ani')


def test_empty_blinking_lists_are_safe_but_active_blinking_is_blocked():
    d=model()
    for key in ('blinkingLights0','blinkingLights1'):
        d['metadata']['railVehicle']['configs'][0][key]=[]
    before=deepcopy(d)
    assert port_model(d,lambda ref,kind:ref,Native())['version']==2
    assert d==before
    d['metadata']['railVehicle']['configs'][0]['blinkingLights1']=[1]
    with pytest.raises(ValueError,match='Non-empty rail blinking lights'):
        port_model(d,lambda ref,kind:ref,Native())


def test_empty_old_compartment_schema_retains_load_config_structure():
    d=model();t=d['metadata']['transportVehicle']
    del t['compartmentsList'];t['compartments']=[[[],[]],[[]]]
    result=port_model(d,lambda ref,kind:ref,Native())
    compartments=result['metadata']['transportVehicle']['compartments']
    assert [len(c['loadConfigs']) for c in compartments]==[2,1]
    assert all(load['cargoEntry']['capacity']==0 for c in compartments for load in c['loadConfigs'])
    t['compartments']=[[{'capacity':10}]]
    with pytest.raises(ValueError,match='(?:must be|expected) a literal list'):
        port_model(d,lambda ref,kind:ref,Native())


@pytest.mark.parametrize('kind',['unknown_metadata','capacity','node','hidden_node','emissions'])
def test_unsupported_behavior_is_blocked(kind):
    d=model(); m=d['metadata']
    if kind == 'unknown_metadata': m['customScript'] = {}
    if kind == 'capacity': m['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'] = [{'capacity':10}]
    if kind == 'node': m['seatProvider']['seats'][0]['group'] = 99
    if kind == 'hidden_node': m['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['toHide']=[-1]
    if kind == 'emissions': m['emission']['idleEmission'] = 25
    with pytest.raises(ValueError): port_model(d,lambda ref,kind:ref,Native())


def test_diesel_rail_profile_is_supported_without_altering_power():
    d=model();d['metadata']['railVehicle']['engines'][0]['type']='DIESEL'
    target=port_model(d,lambda ref,kind:ref,Native())
    assert target['metadata']['landVehicle']['engines'][0]['type']=='DIESEL'
    assert target['metadata']['transportVehicle']['engineTransportModes']==['TRAIN','ELECTRIC_TRAIN']


def test_serializer_retains_unicode_control_characters_and_translations():
    data={'description':{'name':'translated'},'text':'å\\"\n\x00\t123'}
    emitted=emit(data,{'translated'})
    assert '_("translated")' in emitted
    assert load_lua_table(emitted) == data
    with pytest.raises(ValueError): literal({'node':[UnsupportedValue('dynamic callback')]})


def test_path_mapping_blocks_traversal_and_normalizes_consistently():
    assert checked_name('models/model/SJ_(1925).mdl') == 'models/model/sj__1925_.mdl'
    with pytest.raises(ValueError): checked_name('../escape.mdl')
    with pytest.raises(ValueError): checked_name('model\\escape.mdl')

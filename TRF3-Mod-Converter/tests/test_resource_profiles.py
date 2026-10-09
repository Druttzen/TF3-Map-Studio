from copy import deepcopy
import pytest

from trf3_mod_converter.lua_metadata import TranslatedString, load_lua_table
from trf3_mod_converter.resource_profiles import (
    BridgeFactory, ConstantCallback, capability_report, classify_resource,
    load_resource_table, port_config, port_resource, port_static_model, resource_target,
)


def resolve(reference, kind):
    return f'demo::/{kind}/{reference}'


class Native:
    def __init__(self): self.references = []
    def reference(self,path):
        self.references.append(path)
        return '::/'+path


def model(metadata=None):
    return {'version':1,'boundingInfo':{'bbMin':[-1,-1,0],'bbMax':[1,1,2]},
            'lods':[{'node':{'name':'Root','children':[{'name':'Root','mesh':'cube.msh','materials':['cube.mtl']}]} }],
            'metadata':metadata or {}}


def emit(value):
    from trf3_mod_converter.tf2_vehicle_port import emit
    return emit(value)


def test_declarative_reader_folds_locals_assignments_and_constants():
    source='''function data()
local dir = "custom/"
local t = {}
t.name = _("Rail")
t.speed = 144 / 3.6
t.height = 2
t.height = t.height + 1
t.model = dir .. "rail.mdl"
return t
end'''
    assert load_resource_table(source) == {'name':'Rail','speed':40,'height':3,'model':'custom/rail.mdl'}


def test_reader_preserves_empty_table_aliases_before_freezing_return_value():
    assert load_resource_table('function data() local t={} local alias=t alias.x=3 return t end') == {'x':3}
    assert load_resource_table('function data() local t={} t[1]="a" return {items=t} end') == {'items':['a']}


@pytest.mark.parametrize('argument', ['_', 'require', 'math', 'data', '...'])
def test_callback_parameters_cannot_shadow_builtin_translation_or_helpers(argument):
    source = f'function data() return {{updateFn=function({argument}) return {{name=_("Box")}} end}} end'
    with pytest.raises(ValueError, match='parameter'):
        load_resource_table(source)


def test_cyclic_tables_and_alias_expansion_are_rejected_before_normalization():
    with pytest.raises(ValueError, match='cyclic'):
        load_resource_table('function data() local t={} t.child=t return t end')
    with pytest.raises(ValueError, match='cyclic'):
        load_resource_table('function data() local a={} local b={a=a} a.b=b return {root=a} end')
    assignments = ['local t0={name="leaf"}'] + [f'local t{i}={{t{i-1},t{i-1}}}' for i in range(1,31)]
    source = 'function data() ' + ' '.join(assignments) + ' return {root=t30} end'
    with pytest.raises(ValueError, match='expanded literal'):
        load_resource_table(source)
    # A small shared literal remains valid and independent after normalization.
    result=load_resource_table('function data() local a={x=1} return {a=a,b=a} end')
    assert result == {'a':{'x':1},'b':{'x':1}}
    assert result['a'] is not result['b']


def test_reader_preserves_translation_provenance_and_defers_translated_concatenation():
    result=load_resource_table('function data() return {name=_("Box"),id="Box"} end')
    assert isinstance(result['name'],TranslatedString)
    assert not isinstance(result['id'],TranslatedString)
    from trf3_mod_converter.resource_profiles import TranslatedConcat
    value = load_resource_table('function data() return {name=_("Box") .. " suffix"} end')['name']
    assert isinstance(value, TranslatedConcat)
    assert value.parts == ((True, 'Box'), (False, ' suffix'))


@pytest.mark.parametrize('source',[
    'os.execute("do not execute") function data() return {} end',
    'function data() local x=api.engine.getComponent(1) return { x=x } end',
    'local helper=require "custom" function data() return {} end',
    'local require = function() return {} end function data() return {} end',
    'function data() local x={} for i=1,10 do x[i]=i end return x end',
    'function data() return { updateFn=function(params) return params end } end',
    'function data() return { x=2^10000 } end',
    'function data() return { x=2^1024 } end',
    'function data() return { x=1, x=2 } end',
    'function data() local t={x=1} local fn=function() return {x=t.x} end t.x=2 return {updateFn=fn} end',
])
def test_reader_blocks_side_effects_unknown_helpers_dynamic_callbacks_and_duplicates(source):
    with pytest.raises(ValueError): load_resource_table(source)


def test_verified_factory_and_constant_callback_are_descriptors_not_executed():
    source='''local b=require "bridgeutil"
function data() local config={pillarBase={"a.mdl"}}
return {updateFn=b.makeDefaultUpdateFn(config)} end'''
    assert load_resource_table(source)['updateFn'] == BridgeFactory({'pillarBase':['a.mdl']})
    source='function data() return {updateFn=function(params) return {models={}} end} end'
    assert isinstance(load_resource_table(source)['updateFn'],ConstantCallback)


def test_resource_suffixes_and_capabilities_are_classified_without_claiming_engine_success():
    assert resource_target('config/multiple_unit/Custom Pack.lua') == 'config/multiple_unit/custom_pack.mu.lua'
    assert resource_target('config/ground_texture/foo.gtex.lua') == 'config/ground_texture/foo.gtex.lua'
    assert resource_target('construction/asset/box.con') == 'construction/asset/box.con.lua'
    assert classify_resource('config/terrain_materials/dirt.lua') == 'terrain_material'
    assert classify_resource('vehicle/motor.trf') == 'script'
    assert classify_resource('vehicle/motor.snd') == 'script'
    report=capability_report(['scripts/custom.lua','config/track/narrow.lua','models/model/tree.mdl'])
    assert report['nativeTest'] == 'not_run'
    assert report['resourceClasses'] == {'script':1,'track':1,'model':1}
    assert 'arbitrary_scripts' in report['manualMigration']
    with pytest.raises(ValueError): resource_target('../escape.lua')


@pytest.mark.parametrize('path', ['___/model.mdl~', 'models/___/model.mdl~',
                                  '___../model.mdl~', 'models/___../model.mdl',
                                  '___./model.mdl'])
def test_normalization_cannot_create_empty_or_parent_path_segments(path):
    with pytest.raises(ValueError, match='Invalid resource path'):
        resource_target(path)


def test_static_model_preserves_geometry_and_maps_labels_cameras_and_tree_menu():
    original=model({'tree':[], 'description':{'name':'Tree','icon':'ui/tree.tga'},
                    'order':{'value':5},'category':{'categories':['tree']},
                    'categoryList':{'categories':['temperate.clima.lua','large']},
                    'cameraConfig':{'positions':[{'group':1,'fov':60,'transf':[1]*16}]},
                    'labelList':{'labels':[{'childId':0,'type':'NONE'}]}})
    before=deepcopy(original)
    result=port_static_model(original,resolve)
    assert original == before
    assert result['version'] == 2
    assert result['boundingInfo'] == original['boundingInfo']
    assert result['lods'][0]['node']['children'][0]['mesh'] == 'demo::/mesh/cube.msh'
    assert result['metadata']['cameraConfig']['positions'][0]['group'] == 'Root_mesh'
    assert result['metadata']['labelList']['labels'][0]['childId'] == 'Root'
    assert result['metadata']['menuCategory']['categories'][0]['category'] == 'landscaping_vegetation'
    assert result['metadata']['categoryList']['categories'] == ['temperate.clima','large']
    assert result['metadata']['description']['icon'] == 'demo::/texture/ui/tree.tga'


@pytest.mark.parametrize('metadata',[
    {'transportVehicle':{'carrier':'RAIL'}}, {'transportNetworkProvider':{}},
    {'particleSystem':{'emitters':[]}}, {'tree':{'forest':True}}, {'category':{'categories':['unmappedMenu']}},
    {'cameraConfig':{'positions':[{'group':500}]}},
])
def test_static_unknown_functionality_and_bad_indexes_do_not_disappear(metadata):
    with pytest.raises(ValueError): port_static_model(model(metadata),resolve)


def test_multiple_unit_and_crossing_preserve_order_direction_speed_and_models():
    unit={'name':'EMU','vehicles':[{'name':'train/front.mdl','forward':True},{'name':'train/rear.mdl','forward':False}]}
    result=port_config('config/multiple_unit/test.lua',unit,resolve)
    assert [v['forward'] for v in result['vehicles']] == [True,False]
    assert result['vehicles'][1]['name'] == 'demo::/model/train/rear.mdl'
    crossing={'name':'Crossing','yearFrom':1950,'yearTo':0,'speedLimit':25,'cost':5,
              'soundFileName':'bell.wav','config':[{'modelLeft':'left.mdl','streetWidth':8}]}
    result=port_config('config/railroad_crossing/test.lua',crossing,resolve)
    assert result['description'] == {'name':'Crossing'}
    assert result['availability'] == {'yearFrom':1950,'yearTo':0}
    assert result['soundFileName'] == 'demo::/audio/bell.wav'
    assert result['config'][0] == {'modelLeft':'demo::/model/left.mdl','streetWidth':8}
    assert result['speedLimit'] == 25


def test_ground_texture_factory_becomes_literal_sampler_and_resolves_material_indices():
    text='''local tu=require "texutil"
function data() return {texture=tu.makeMaterialIndexTexture("res/textures/ground/mask.tga","REPEAT","CLAMP_TO_EDGE"),
texSize={10,20},materialIndexMap={[1]="dirt.lua",[255]="sand.lua"},priority=12} end'''
    data=load_resource_table(text)
    result=port_config('config/ground_texture/mask.lua',data,resolve)
    assert result['texture']['fileName'] == 'demo::/texture/ground/mask.tga'
    assert result['texture']['magFilter'] == 'NEAREST'
    assert result['texture']['compressionAllowed'] is False
    assert result['materialIndexMap'][255] == 'demo::/terrain_material/sand.lua'
    assert result['texSize'] == [10,20]
    automatic=port_config('config/auto_ground_tex/tree.lua',{'groundTex':'mask.lua','category':'auto.model.tree','gridSize':18},resolve)
    assert automatic['groundTex'] == 'demo::/ground_texture/mask.lua'


def test_terrain_material_and_grass_cannot_drop_reverse_material_bindings():
    terrain={'name':'Dirt','desc':'Ground','categories':['ground'],'order':4,'priority':100,
             'detailColorTexture':'dirt.dds','grass':'custom.lua','detailSize':0.03125}
    result=port_config('config/terrain_material/dirt.lua',terrain,resolve)
    assert result['description'] == {'name':'Dirt','description':'Ground'}
    assert result['menuCategory']['categories'][0]['filterCategories'] == ['ground']
    assert result['detailSize'] == 0.03125
    assert result['grass'] == 'demo::/grass/custom.lua'
    with pytest.raises(ValueError,match='associations'):
        port_config('config/grass/foo.lua',{'materials':['dirt.lua']},resolve)


def test_track_split_preserves_gauge_grade_speed_and_catenary_pair():
    data={'name':'Narrow track','shapeWidth':3.5,'speedLimit':22,'railBase':0.3,'railHeight':0.15,
          'railTrackWidth':1,'trackDistance':4,'minCurveRadius':25,'maxSlope':0.2,'shapeSleeperStep':0.5,
          'railModel':'rail.mdl','railMaterial':'rail.mtl','ballastMaterial':'ballast.mtl',
          'catenaryBase':5,'catenaryPoleModel':'pole.mdl','catenaryMaxPoleDistanceFactor':2,
          'borderGroundTex':'border.lua','cost':80}
    docs=port_resource('config/track/narrow.lua',emit(data),resolve,resource_reference='demo::/config/track/narrow.street_template')
    assert len(docs) == 4
    template=load_lua_table(docs['config/track/narrow.street_template.lua'])
    style=load_lua_table(docs['config/track/narrow.street.lua'])
    electric=load_lua_table(docs['config/track/narrow_catenary.street_template.lua'])
    electric_style=load_lua_table(docs['config/track/narrow_catenary.street.lua'])
    assert template['laneConfigs'][0]['speed'] == 22
    assert template['laneConfigs'][0]['width'] == 3.5
    assert template['laneConfigs'][0]['height'] == pytest.approx(0.45)
    assert template['maxSlope'] == 0.2 and template['minCurveRadius'] == 25
    assert style['railTrackWidth'] == 1
    assert style['materials']['ballast'] == {'name':'demo::/material/ballast.mtl','size':[7,7]}
    assert electric_style['catenary']['catenaryMaxPoleDistance'] == 2
    assert template['catenaryAdd'] == 'demo::/config/track/narrow_catenary.street_template'
    assert electric['catenaryRemove'] == 'demo::/config/track/narrow.street_template'
    assert 'ELECTRIC_TRAIN' in electric['laneConfigs'][0]['transportModes']
    data['tunnelWallMaterial']='old.mtl'
    with pytest.raises(ValueError,match='no override was dropped'):
        port_resource('config/track/narrow.lua',emit(data),resolve,resource_reference='demo::/config/track/narrow.street_template')


def test_street_split_preserves_lane_dimensions_directions_modes_and_speed_units():
    data={'name':'Village road','numLanes':2,'streetWidth':8,'sidewalkWidth':2,'sidewalkHeight':0.15,
          'speed':36,'maxSlope':0.4,'cost':30,'materials':{'streetPaving':{'name':'road.mtl','size':[8,8]}},
          'assets':[{'name':'lamp.mdl','distance':20,'oneSideOnly':True}]}
    docs=port_resource('config/street/village.lua',emit(data),resolve,resource_reference='demo::/config/street/village.street_template')
    template=load_lua_table(docs['config/street/village.street_template.lua'])
    style=load_lua_table(docs['config/street/village.street.lua'])
    assert [v['width'] for v in template['laneConfigs']] == [2,4,4,2]
    assert [v['forward'] for v in template['laneConfigs']] == [False,False,True,True]
    assert all(v['speed'] == 10 for v in template['laneConfigs'])
    assert style['assets']['asset_1']['name'] == 'demo::/model/lamp.mdl'
    assert style['materials']['streetPaving']['size'] == [8,8]
    with pytest.raises(ValueError,match='Asymmetric'):
        port_resource('config/street/village.lua',emit({**data,'numLanes':3}),resolve,resource_reference='demo::/config/street/village.street_template')


def test_default_bridge_uses_installed_script_and_captured_verified_model_bounds():
    text='''local b=require "bridgeutil"
function data()
local config={pillarBase={"base.mdl"},pillarRepeat={"rep.mdl"},pillarTop={"top.mdl"},
railingBegin={},railingRepeat={"side.mdl","rep.mdl","side.mdl"},railingEnd={}}
return {name="Test bridge",cost=90,speedLimit=30,pillarMinDist=12,pillarTargetDist=24,
updateFn=b.makeDefaultUpdateFn(config)} end'''
    native=Native()
    bounds=lambda ref:{'bbMin':[-1,-1,0],'bbMax':[6,4,2]}
    docs=port_resource('config/bridge/test.lua',text,resolve,native,
                       resource_reference='demo::/config/bridge/test.bridge',model_bounds=bounds)
    result=load_lua_table(docs['config/bridge/test.bridge.lua'])
    assert result['pillarTargetDist'] == 24 and result['speedLimit'] == 30
    assert result['updateScript']['fileName'] == '::/infrastructure/bridge/bridge.script@cement.updateFn'
    assert result['updateScript']['params']['pillarBase'][0] == ['demo::/model/base.mdl',[[-1,-1,0],[6,4,2]]]
    assert native.references == ['infrastructure/bridge/bridge.script@cement.updateFn']
    with pytest.raises(ValueError,match='bounds'):
        port_resource('config/bridge/test.lua',text,resolve,native,resource_reference='demo::/config/bridge/test.bridge')


def test_constant_asset_construction_emits_script_and_preserves_models_ground_alignment_params():
    text='''function data() return {type="ASSET_DEFAULT",description={name="Box"},
params={{key="color",name="Color",values={"Blue","Red"},defaultIndex=1}},
updateFn=function(params) return {models={{id="box.mdl",transf={1,0,0,0,0,1,0,0,0,0,1,0,2,3,4,1}}},
groundFaces={{face={{0,0,0},{1,0,0},{0,1,0}},modes={{type="FILL",key="dirt.lua"}}}},
terrainAlignmentLists={{type="EQUAL",faces={{{0,0,0},{1,0,0},{0,1,0}}},slopeLow=0.3,slopeHigh=0.6}},cost=4} end} end'''
    docs=port_resource('construction/asset/box.con',text,resolve,resource_reference='demo::/construction/asset/box.con')
    output=load_lua_table(docs['construction/asset/box.con.lua'])
    script=load_resource_table(docs['construction/asset/box.script.lua'])
    result=script['updateFn'].result
    assert output['params'][0]['defaultIndex'] == 2
    assert output['params'][0]['numbers'] == [0,1]
    assert output['updateScript']['fileName'] == 'demo::/construction/asset/box.script@updateFn'
    assert result['subconstructions'][0]['models'][0]['id'] == 'demo::/model/box.mdl'
    assert result['subconstructions'][0]['groundFaces'][0]['modes'][0]['key'] == 'demo::/ground_texture/dirt.lua'
    assert result['subconstructions'][0]['terrainAlignmentLists'][0]['slopeHigh'] == 0.6
    assert result['cost'] == 4


def test_construction_parameter_translation_keeps_literal_key_and_translated_displays():
    source='''function data() return {type="ASSET_DEFAULT",description={name=_("Box")},
params={{key="Choice",name=_("Choice"),tooltip=_("Help"),values={_("Blue"),_("Red")}}},
updateFn=function(params) return {models={}} end} end'''
    docs=port_resource('construction/asset/box.con',source,resolve,
                       resource_reference='demo::/construction/asset/box.con',
                       translations={'Box','Choice','Help','Blue','Red'})
    text=docs['construction/asset/box.con.lua']
    assert 'key = "Choice"' in text
    assert 'name = _("Choice")' in text
    assert 'tooltip = _("Help")' in text
    assert '_("Blue")' in text and '_("Red")' in text


def test_static_model_validates_known_animation_fields_and_shared_label_schema():
    asset=model({'labelList':{'labels':[{'type':'NAME','font':'Lato','params':{'key':'name'}}]}})
    mesh=asset['lods'][0]['node']['children'][0]
    mesh['animations']={'move':{'type':'KEYFRAME','params':{'origin':[0,0,0],
                          'keyframes':[{'time':0,'rot':[0,0,0],'transl':[1,2,3]}]}}}
    result=port_static_model(asset,resolve)
    assert result['metadata']['labelList']['labels'][0]['childId'] == 'Root'
    mesh['animations']['move']['params']['keyframes'][0]['transl']=[1,2]
    with pytest.raises(ValueError,match='3 numbers'):
        port_static_model(asset,resolve)


def test_static_model_lifespan_retains_duration_and_rejects_unmapped_maintenance():
    original=model({'maintenance':{'lifespan':36525,'runningCosts':10,'runningCostScale':1}})
    result=port_static_model(original,resolve)
    assert result['metadata']['maintenance'] == {'lifespan':73050,'runningCosts':10,'runningCostScale':1}
    assert original['metadata']['maintenance']['lifespan'] == 36525
    original['metadata']['maintenance']['unknownBehavior']=True
    with pytest.raises(ValueError,match='maintenance'):
        port_static_model(original,resolve)


def test_unknown_resources_functional_constructions_and_tunnel_portals_remain_blocked():
    for path,text in [
        ('config/tunnel/old.lua','function data() return {portals={{"x.mdl"}}} end'),
        ('construction/station/station.con','function data() return {type="RAIL_STATION",updateFn=function() return {} end} end'),
        ('construction/station/track.module','function data() return {} end'),
        ('scripts/api.lua','function data() return {} end'),
    ]:
        with pytest.raises(ValueError): port_resource(path,text,resolve,resource_reference='demo::/target')

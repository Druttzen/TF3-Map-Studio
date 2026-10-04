"""Read-only world checks using distinct TF3 entity component records."""
from pathlib import Path
import unittest

from lupa import LuaRuntime


ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "mod/tf3_osm_importer_mod/content/osm"

FIXTURE = r'''
local T={BASE_NODE=1,BASE_EDGE=2,PLAYER_OWNED=3,CONSTRUCTION=4,NAME=5,TRANSPORT_NETWORK=6,ASSET_GROUP=7,MODEL_INSTANCE_LIST=8}
api={type={ComponentType=T,["enum"]={RoadType={STREET=0,TRACK=1},
  BaseEdgeType={NORMAL=0,BRIDGE=1,TUNNEL=2},TransportMode={PERSON="PERSON",CAR="CAR",BUS="BUS",TRUCK="TRUCK",
  TRAM="TRAM",ELECTRIC_TRAM="ELECTRIC_TRAM",TRAIN="TRAIN",ELECTRIC_TRAIN="ELECTRIC_TRAIN"}}},engine={},cmd={}}
world={
 [10]={[T.BASE_NODE]={position={x=0,y=0,z=10}}},
 [11]={[T.BASE_NODE]={position={x=50,y=0,z=10}}},
 [12]={[T.BASE_NODE]={position={x=100,y=0,z=10}}},
 [20]={[T.BASE_NODE]={position={x=0,y=100,z=10}}},
 [21]={[T.BASE_NODE]={position={x=50,y=100,z=10}}},
 [100]={[T.BASE_EDGE]={node0=10,node1=11,roadTemplate="::/road.street_template",roadType=0,type=0,roadDevelopmentLocked=true},[T.PLAYER_OWNED]={player=42}},
 [101]={[T.BASE_EDGE]={node0=11,node1=12,roadTemplate="::/oneway.street_template",roadType=0,type=0,roadDevelopmentLocked=true},[T.PLAYER_OWNED]={player=42}},
 [102]={[T.BASE_EDGE]={node0=20,node1=21,roadTemplate="::/rail.street_template",roadType=1,type=0,roadDevelopmentLocked=true},[T.PLAYER_OWNED]={player=42}},
 [200]={[T.CONSTRUCTION]={fileName="druttzen_osm_vanilla::/osm/scenery.con",params={items={
  {model="::/assets/vegetation/tree.mdl",pos={10,20,10}},
  {model="::/assets/fountain.mdl",pos={20,20,10}},
  {texture="::/surface.gtex",face={{0,0,10},{10,0,10},{0,10,10}}}}}},
  [T.NAME]={name="OSM scenery fixture 1"},[T.PLAYER_OWNED]={player=42}},
 [201]={[T.CONSTRUCTION]={fileName="druttzen_osm_vanilla::/osm/scenery.con",params={items={
  {model="::/assets/markers/marker_locate.mdl",pos={30,40,10}}}}},
  [T.NAME]={name="Fixture village"},[T.PLAYER_OWNED]={player=42}},
 -- Existing vanilla geometry must not affect the importer counts.
 [300]={[T.BASE_EDGE]={node0=400,node1=401,roadTemplate="::/road.street_template",roadType=0,type=0}},
 [301]={[T.CONSTRUCTION]={fileName="::/vanilla.con",params={items={{model="::/assets/vegetation/tree.mdl",pos={10,20,10}}}}}},
 [302]={[T.CONSTRUCTION]={fileName="druttzen_osm_vanilla::/osm/scenery.con",params={items={{model="::/assets/fountain.mdl",pos={900,900,10}}}}},
  [T.NAME]={name="OSM scenery other-dataset 1"}},
}
world[100][T.TRANSPORT_NETWORK]={nodes={{},{}},edges={{
 conns={{entity=100,index=0},{entity=100,index=1}},geometry={length=50},
 transportModes={CAR=true,BUS=true,TRUCK=true}}},turnaroundEdges={}}
world[101][T.TRANSPORT_NETWORK]={nodes={{},{}},edges={{
 conns={{entity=101,index=0},{entity=101,index=1}},geometry={length=50},
 transportModes={CAR=true,BUS=true,TRUCK=true}}},turnaroundEdges={}}
world[102][T.TRANSPORT_NETWORK]={nodes={{},{}},edges={{
 conns={{entity=102,index=0},{entity=102,index=1}},geometry={length=50},
 transportModes={TRAIN=true,ELECTRIC_TRAIN=true}}},turnaroundEdges={}}
queries={}; commandCalls=0
api.engine.entityExists=function(id) return world[id]~=nil end
api.engine.getComponent=function(id,kind)
 assert(world[id],"getComponent requires an existing entity")
 queries[#queries+1]={id,kind}; return world[id][kind]
end
api.engine.getEntitiesWithComponent=function(kind)
 error("Cannot loop over this component type")
end
api.engine.forEachEntityWithComponent=function(callback,kind)
 assert(kind==T.CONSTRUCTION,"Only constructions may be enumerated by this audit")
 for id,components in pairs(world) do if components[kind] then callback(id) end end
end
api.engine.forEachEntity=function(callback) for id in pairs(world) do callback(id) end end
api.engine.system={streetSystem={getNodeSegments=function(node)
 assert(world[node] and world[node][T.BASE_NODE],"An existing imported node is required")
 local result={}
 for id,components in pairs(world) do
   local edge=components[T.BASE_EDGE]
   if edge and (edge.node0==node or edge.node1==node) then result[#result+1]=id end
 end
 table.sort(result); return result
end},streetConnectorSystem={forEach=function(callback)
 for id,components in pairs(world) do if components[T.CONSTRUCTION] then callback(id) end end
end}}
api.engine.util={getPlayer=function() return 42 end}
api.engine.terrain={getBoundingBox=function() return {min={x=-500,y=-500},max={x=500,y=500}} end}
api.res={modelRep={find=function(name) return ({["::/assets/vegetation/tree.mdl"]=1,["::/assets/fountain.mdl"]=2,["::/assets/markers/marker_locate.mdl"]=3})[name] or -1 end,
 getName=function(id) return ({"::/assets/vegetation/tree.mdl","::/assets/fountain.mdl","::/assets/markers/marker_locate.mdl"})[id] end},
 bridgeTypeRep={find=function(name) assert(name=="::/infrastructure/bridge/steel.bridge"); return 7 end},
 tunnelTypeRep={find=function(name) assert(name=="::/infrastructure/tunnel/tunnel_c.tunnel"); return 8 end}}
api.cmd.sendCommand=function() commandCalls=commandCalls+1; error("Audit must not send commands") end
api.cmd.makeWorldBuildProposalCmd=function() commandCalls=commandCalls+1; error("Audit must not construct commands") end
dataset={id="fixture",nodes={a={pos={0,0}},b={pos={50,0}},c={pos={100,0}},x={pos={0,100}},y={pos={50,100}}},edges={
 {node0="a",node1="b",template="::/road.street_template",kind="STREET"},
 {node0="b",node1="c",template="::/oneway.street_template",kind="STREET"},
 {node0="x",node1="y",template="::/rail.street_template",kind="TRACK"}},scenery={
 {model="::/assets/vegetation/tree.mdl",pos={10,20}},
 {model="::/assets/fountain.mdl",pos={20,20},category="objects"},
 {texture="::/surface.gtex",face={{0,0},{10,0},{0,10}}}},labels={{name="Fixture village",pos={30,40}}}}
value={phase="finished",datasetId="fixture",nodes={a=10,b=11,c=12,x=20,y=21},builtEdges=3,builtScenery=3,labels=1,skipped=0}
value.sceneryRecords={
 {name="OSM scenery fixture 1",phase="scenery",first=1,last=3,entities={200},modelJournalSchema=1,modelPositions={[1]={10,20,10},[2]={20,20,10}}},
 {name="Fixture village",phase="labels",first=1,last=1,entities={201},modelJournalSchema=1,modelPositions={[1]={30,40,10}}}}
'''


def plain(value):
    if hasattr(value, "items"):
        return {key: plain(item) for key, item in value.items()}
    return value


class WorldAuditTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        controls = self.lua.execute((CONTENT / "controls.lua").read_text(encoding="utf-8"))
        self.lua.globals().modules = self.lua.table_from({
            "druttzen_osm_vanilla::/osm/controls.lua": controls,
            "druttzen_osm_vanilla::/osm/towns.lua": self.lua.execute((CONTENT / "towns.lua").read_text(encoding="utf-8")),
        })
        self.lua.execute("function ug_require(name) return assert(modules[name]) end")
        self.lua.execute(FIXTURE)
        self.audit = self.lua.execute((CONTENT / "world_audit.lua").read_text(encoding="utf-8"))

    def inspect(self):
        return self.audit.inspect(self.lua.globals().dataset, self.lua.globals().value)

    def test_saved_network_heights_detect_later_vertical_changes_without_commands(self):
        self.lua.execute('value.heightPolicy="base-v1"; value.nodeHeights={a=10,b=10,c=10,x=10,y=10}')
        self.assertTrue(self.inspect().ok)
        self.lua.execute('world[11][api.type.ComponentType.BASE_NODE].position.z=9.5')
        report=self.inspect()
        self.assertFalse(report.ok)
        self.assertEqual(report.problemCounts.wrongNodeHeights,1)
        self.assertEqual(self.lua.globals().commandCalls,0)

    def test_missing_accepted_network_height_is_not_reported_as_verified(self):
        self.lua.execute('value.heightPolicy="base-v1"; value.nodeHeights={a=10,c=10,x=10,y=10}')
        report=self.inspect()
        self.assertFalse(report.ok)
        self.assertEqual(report.problemCounts.wrongNodeHeights,1)

    def test_complete_world_counts_ownership_connectivity_and_no_mutation(self):
        before = plain(self.lua.globals().world), plain(self.lua.globals().dataset), plain(self.lua.globals().value)
        report = self.inspect()
        self.assertTrue(report.ok, plain(report.problems))
        self.assertEqual(report.expected.edges, 3)
        self.assertEqual(report.current.edges, 3)
        self.assertEqual(report.expected.usableEdges, 3)
        self.assertEqual(report.current.usableEdges, 3)
        self.assertEqual(report.current.streets, 2)
        self.assertEqual(report.current.tracks, 1)
        self.assertEqual(report.current.nodes, 5)
        self.assertEqual(report.current.components, 2)
        self.assertEqual(report.expected.components, 2)
        self.assertEqual(report.degrees.b.current, 2)

        self.assertEqual(report.degrees.b.streets, 2)
        self.assertEqual(report.current.models, 2)
        self.assertEqual(report.current.surfaces, 1)
        self.assertEqual(report.current.labels, 1)
        self.assertEqual(report.current.constructions, 2)
        self.assertIn("Saved built objects verified", self.audit.format(report))
        self.assertIn("Ground paint appearance", self.audit.format(report))
        self.assertIn("actual vehicle routes", self.audit.format(report))
        self.assertEqual(self.lua.globals().commandCalls, 0)
        def check_plain(item):
            if isinstance(item, dict):
                for key, child in item.items():
                    self.assertIsInstance(key, (str, int, float, bool))
                    check_plain(child)
            else:
                self.assertIsInstance(item, (str, int, float, bool, type(None)))
        check_plain(plain(report))
        after = plain(self.lua.globals().world), plain(self.lua.globals().dataset), plain(self.lua.globals().value)
        self.assertEqual(before, after)

    def test_shallow_water_saved_depth_and_heights_are_verified_read_only(self):
        self.lua.execute('''
          dataset.scenery[3].category="waterways";dataset.scenery[3].depth=.5
          value.options={waterways=true}
          local item=world[200][api.type.ComponentType.CONSTRUCTION].params.items[3]
          item.depth=.5; for _,p in ipairs(item.face) do p[3]=9.5 end
          value.shallowHeightReference={["0.000000,0.000000"]=10,["10.000000,0.000000"]=10,["0.000000,10.000000"]=10}
        ''')
        self.assertTrue(self.inspect().ok)
        self.lua.execute('world[200][api.type.ComponentType.CONSTRUCTION].params.items[3].face[1][3]=8')
        self.assertFalse(self.inspect().ok)
        self.assertEqual(self.lua.globals().commandCalls,0)

    def test_missing_node_and_component_are_detected_without_invalid_query(self):
        for mutation in ["world[11]=nil", "world[11][1]=nil", "value.nodes.b=nil", 'value.nodes.b="11"']:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertGreater(report.problemCounts.missingNodes, 0)
                self.assertGreater(report.problemCounts.missingEdges, 0)

    def test_missing_edge_cannot_pass_using_an_unrelated_edge(self):
        self.lua.execute("world[101]=nil")
        report = self.inspect()
        self.assertFalse(report.ok)
        self.assertEqual(report.current.edges, 2)
        self.assertEqual(report.problemCounts.missingEdges, 1)

    def test_wrong_templates_types_orientation_and_lock_are_detected(self):
        for mutation in [
            'world[101][2].roadTemplate="::/wrong.street_template"',
            "world[101][2].roadType=1",
            "world[101][2].type=2",
            "world[101][2].node0=12; world[101][2].node1=11",
            "world[101][2].roadDevelopmentLocked=false",
        ]:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertGreater(report.problemCounts.wrongEdges, 0)

    def test_missing_or_wrong_edge_and_construction_ownership_are_detected(self):
        for mutation in ["world[101][3]=nil", "world[101][3].player=7", "world[200][3]=nil", "world[201][3].player=7"]:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertEqual(report.problemCounts.ownership, 1)

    def test_missing_empty_or_wrong_vehicle_lanes_are_detected(self):
        for mutation in [
            "world[100][6]=nil",
            "world[100][6].edges={}",
            "world[100][6].edges[1].transportModes={PERSON=true}",
            "world[102][6].edges[1].transportModes={CAR=true}",
        ]:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertEqual(report.problemCounts.vehicleLanes, 1)
                self.assertEqual(report.current.usableEdges, 2)

    def test_vehicle_lane_edges_are_counted_once_and_allow_matching_modes(self):
        self.lua.execute('''
          world[100][6].edges={
            {transportModes={PERSON=true}},
            {transportModes={BUS=true}},
            {transportModes={CAR=true}},
          }
          world[101][6].edges[1].transportModes={ELECTRIC_TRAM=true}
          world[102][6].edges[1].transportModes={ELECTRIC_TRAIN=true}
        ''')
        report = self.inspect()
        self.assertTrue(report.ok, plain(report.problems))
        self.assertEqual(report.current.usableEdges, 3)

    def test_bridge_and_tunnel_resource_indices_are_verified(self):
        for kind, native_type, correct_index in [("bridge", 1, 7), ("tunnel", 2, 8)]:
            with self.subTest(kind=kind):
                self.setUp()
                self.lua.execute(f"dataset.edges[1].{kind}=true; world[100][2].type={native_type}; world[100][2].typeIndex={correct_index}")
                self.assertTrue(self.inspect().ok)
                self.lua.execute("world[100][2].typeIndex=999")
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertGreater(report.problemCounts.wrongEdges, 0)

    def test_missing_wrong_duplicate_scenery_and_marker_items_are_detected(self):
        for mutation in [
            "table.remove(world[200][4].params.items,1)",
            'world[200][4].params.items[1].model="::/wrong.mdl"',
            'world[200][4].params.items[3].texture="::/wrong.gtex"',
            "world[200][4].params.items[1].rotation=2.1",
            "world[201][4].params.items[1].pos={31,40,10}",
            'world[201][4].params.items[1].model="::/wrong-marker.mdl"',
            "world[200][4].params.items[4]=world[200][4].params.items[1]",
            "world[200][4].params.items=nil",
        ]:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertTrue(report.problemCounts.missingScenery or report.problemCounts.wrongScenery)

    def test_unrelated_marker_with_same_name_does_not_change_counts(self):
        self.lua.execute('''
          world[303]={[4]={fileName="druttzen_osm_vanilla::/osm/scenery.con",params={items={
            {model="::/assets/markers/marker_locate.mdl",pos={900,900,10}}}}},
            [5]={name="Fixture village"},[3]={player=7}}
        ''')
        report = self.inspect()
        self.assertTrue(report.ok, plain(report.problems))
        self.assertEqual(report.current.labels, 1)
        self.assertEqual(report.current.constructions, 2)

    def test_existing_geometry_attached_to_an_imported_node_is_excluded(self):
        self.lua.execute('''
          world[304]={[2]={node0=11,node1=500,roadTemplate="::/road.street_template",roadType=0,type=0}}
        ''')
        report = self.inspect()
        self.assertTrue(report.ok, plain(report.problems))
        self.assertEqual(report.current.edges, 3)
        self.assertEqual(report.degrees.b.current, 2)

    def test_native_parameter_table_fallback_preserves_custom_items(self):
        self.lua.execute('''
          local original=world[200][4].params
          world[200][4].params={seed=0}
          world[200][4].params_native={asTable=function() return original end}
        ''')
        self.assertTrue(self.inspect().ok)

    def flatten_models(self):
        self.lua.execute('''
          table.remove(world[200][4].params.items,1)
          world[201]=nil
          world[210]={[7]={},[8]={thinInstances={{modelId=1,pos={x=10.000001,y=19.999999,z=10},rot=2*math.pi,scale=1}}},
            [5]={name="OSM scenery fixture 1"},[3]={player=42}}
          world[211]={[7]={},[8]={fatInstances={{modelId=3,transf={
            cols=function(_,index) assert(index>=0 and index<=2,"Native columns are zero-based"); return {x=index==0 and 1 or 0,y=index==1 and 1 or 0,z=index==2 and 1 or 0} end,
            getTransl=function() return {x=30,y=40,z=10} end}}}},
            [5]={name="Fixture village"},[3]={player=42}}
          value.sceneryRecords[1].entities={200,210}; value.sceneryRecords[2].entities={211}
        ''')

    def test_flattened_models_and_marker_are_checked_by_live_transforms(self):
        self.flatten_models()
        report=self.inspect()
        self.assertTrue(report.ok,plain(report.problems))
        self.assertEqual(report.current.models,2)
        self.assertEqual(report.current.labels,1)
        self.assertEqual(report.current.assetGroups,2)
        self.assertEqual(self.lua.globals().commandCalls,0)

    def test_live_vertical_displacement_is_rejected(self):
        for mutation in ['world[210][8].thinInstances[1].pos.z=510',
                         'world[211][8].fatInstances[1].transf.getTransl=function() return {x=30,y=40,z=-1000} end']:
            with self.subTest(mutation=mutation):
                self.setUp();self.flatten_models();self.lua.execute(mutation)
                self.assertFalse(self.inspect().ok)

    def test_sheared_or_tilted_full_transform_is_rejected(self):
        self.flatten_models()
        self.lua.execute('world[211][8].fatInstances[1].transf.cols=function(_,i) return {x=i==0 and 1 or 0,y=i==1 and 1 or 0,z=i==2 and 1 or .5} end')
        self.assertFalse(self.inspect().ok)

    def test_older_save_without_xyz_is_explicitly_partial(self):
        self.lua.execute('value.sceneryRecords=nil')
        report=self.inspect()
        self.assertFalse(report.ok);self.assertTrue(report.partial)
        self.assertEqual(report.missingModelHeights,3)
        self.assertIn('partially verified',self.audit.format(report))

    def test_missing_or_changed_journalled_assets_cannot_pass(self):
        for mutation in ['world[210]=nil','value.sceneryRecords[2].name="Wrong village"','world[210][3].player=7',
                         'world[210][8].thinInstances[1].pos.x=12','world[210][8].thinInstances[1].rot=1',
                         'world[210][8].thinInstances[1].scale=2','world[210][8].thinInstances[1].modelId=2']:
            with self.subTest(mutation=mutation):
                self.setUp(); self.flatten_models(); self.lua.execute(mutation)
                self.assertFalse(self.inspect().ok)

    def test_journalled_unnamed_vegetation_uses_live_models(self):
        self.flatten_models()
        self.lua.execute('world[210][5]=nil')
        report=self.inspect()
        self.assertTrue(report.ok,plain(report.problems))
        self.assertEqual(report.current.models,2)

    def test_unnamed_marker_retains_its_journal_name_and_live_position(self):
        self.flatten_models()
        self.lua.execute('world[211][5]=nil')
        report=self.inspect()
        self.assertTrue(report.ok,plain(report.problems))
        self.assertEqual(report.current.labels,1)
        self.lua.execute('world[211][8].fatInstances[1].transf.getTransl=function() return {x=31,y=40,z=10} end')
        self.assertFalse(self.inspect().ok)

    def test_progress_skips_and_dataset_changes_cannot_pass_a_complete_world(self):
        for mutation in ['value.phase="scenery"', "value.skipped=1", 'value.datasetId="changed"', "value.builtEdges=2"]:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertGreater(report.problemCounts.progress, 0)

    def test_selected_categories_do_not_expect_excluded_nodes_or_items(self):
        self.lua.execute('''
          value.options={roads=false,vegetation=false,objects=false,surfaces=false,places=false}
          value.builtEdges=1; value.builtScenery=0; value.labels=0
          value.sceneryRecords={}
          world[200]=nil; world[201]=nil
        ''')
        report = self.inspect()
        self.assertTrue(report.ok, plain(report.problems))
        self.assertEqual(report.expected.nodes, 2)
        self.assertEqual(report.current.nodes, 2)
        self.assertEqual(report.current.edges, 1)
        self.assertEqual(report.current.components, 1)
        self.assertEqual(report.expected.models, 0)

    def test_reused_node_and_duplicate_edge_are_detected(self):
        for mutation in ["value.nodes.c=11", "world[103]=world[101]"]:
            with self.subTest(mutation=mutation):
                self.setUp(); self.lua.execute(mutation)
                report = self.inspect()
                self.assertFalse(report.ok)
                self.assertTrue(report.problemCounts.wrongNodes or report.problemCounts.wrongEdges)

    def test_positive_boundary_expected_positions_match_without_mutating_source(self):
        self.lua.execute('''
          local T=api.type.ComponentType
          dataset.nodes.c.pos={500,0}; world[12][T.BASE_NODE].position.x=499.99
          dataset.scenery[1].pos={500,20}; world[200][T.CONSTRUCTION].params.items[1].pos={499.99,20,10}
          dataset.labels[1].pos={30,500}; world[201][T.CONSTRUCTION].params.items[1].pos={30,499.99,10}
          value.sceneryRecords[1].modelPositions[1]={499.99,20,10}; value.sceneryRecords[2].modelPositions[1]={30,499.99,10}
          dataset.scenery[3].face[2]={500,0}; world[200][T.CONSTRUCTION].params.items[3].face[2]={499.99,0,10}
        ''')
        before=plain(self.lua.globals().dataset),plain(self.lua.globals().world)
        report=self.inspect()
        self.assertTrue(report.ok,plain(report.problems))
        self.assertEqual(before,(plain(self.lua.globals().dataset),plain(self.lua.globals().world)))
        self.assertEqual(self.lua.globals().commandCalls,0)

    def test_fictional_sample_expectations_and_unstarted_state(self):
        self.lua.globals().dataset = self.lua.execute((CONTENT / "dataset.lua").read_text(encoding="utf-8"))
        self.lua.globals().value = self.lua.table_from({"phase": "ready"})
        report = self.inspect()
        self.assertFalse(report.ok)
        self.assertEqual(report.expected.nodes, 12)
        self.assertEqual(report.expected.streets, 8)
        self.assertEqual(report.expected.tracks, 2)
        self.assertEqual(report.expected.components, 2)
        self.assertEqual(report.expected.scenery, 117)
        self.assertEqual(report.expected.models, 115)
        self.assertEqual(report.expected.surfaces, 2)
        self.assertEqual(report.expected.labels, 1)


if __name__ == "__main__":
    unittest.main()

"""Game-script logic checks using Lua, with a simulated TF3 command boundary.

These verify persistence and failure handling; they do not replace testing in TF3.
Development-only dependency: lupa.
"""
from pathlib import Path
import unittest

from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT/'mod/druttzen_osm_vanilla/content/osm'

def load_script(lua,path):
    """Mirror TF3 resource loading in a fresh environment, then call data()."""
    return lua.eval('''function(source,name)
      local env=setmetatable({data=false},{__index=_G})
      local chunk=assert(load(source,name,"t",env))
      assert(chunk()==nil,"Script resources must expose data(), not return a module")
      assert(type(env.data)=="function","function data() not defined: "..name)
      local result=env.data()
      assert(type(result)=="table","Script data() must return callbacks")
      return result
    end''')(path.read_text(encoding='utf-8'),str(path))

MOCK = r'''
logs={}; commands={}; ownershipCommands={}; owners={}; names={}; missing=nil; failNext=false; failOwnershipNext=false; failNameNext=false; flattenModelOnly=false; outside=false; nextId=100
components={}
function print(s) logs[#logs+1]=s end
function ug_require(name) assert(modules[name],"Unknown module: "..name); return modules[name] end
local rep={find=function(name) if name==missing then return -1 end return 1 end,
  get=function(_) return {laneConfigs={},streetStyle="::/vanilla-style"} end}
api={type={ComponentType={BASE_NODE=1,PLAYER_OWNED=2,BASE_EDGE=3,CONSTRUCTION=4,ASSET_GROUP=5,NAME=6},["enum"]={BaseEdgeType={NORMAL=0,BRIDGE=1,TUNNEL=2},RoadType={TRACK=1,STREET=0}}},
 res={streetTemplateRep=rep,bridgeTypeRep=rep,tunnelTypeRep=rep,modelRep=rep,
  groundTextureRep={find=function(name) if name==missing then return -1 end return name end},constructionRep=rep},
 engine={util={getPlayer=function() return 42 end},terrain={
  isValidCoordinate=function(_) return not outside end,
  getHeightAt=function(_) return 10 end},
  entityExists=function(id) return components[id]~=nil end,
  getComponent=function(id,kind)
    if kind==2 then return owners[id] end
    if kind==6 then return names[id] end
    local c=components[id]
    if c and ((kind==1 and c.position) or (kind==3 and c.node0) or (kind==4 and c.fileName) or (kind==5 and c.assetGroup)) then return c end
  end},cmd={}}
api.type.Vec2f={new=function(x,y) return {x=x,y=y} end}
api.type.Vec3f={new=function(x,y,z) return {x=x,y=y,z=z} end}
api.type.Mat4f={new=function() return {} end}
api.type.NodeAndEntity={new=function() return {comp={}} end}
api.type.SegmentAndEntity={new=function()
  local fields={comp={}}
  return setmetatable({}, {__index=fields,__newindex=function(_,key,value)
    if key=="playerOwned" then error("Do not assign a Lua table to a native component field") end
    fields[key]=value
  end})
end}
api.type.SimpleProposal={new=function() return {streetProposal={}} end,
 ConstructionEntity={new=function() return {} end}}
api.cmd.makeWorldBuildProposalCmd=function(p,_,ignore,_) assert(ignore==false); return p end
api.cmd.makeEntitySetPlayerCmd=function(entity,player) return {ownership=true,entity=entity,player=player} end
api.cmd.makeEntitySetNameCmd=function(entity,name,forceSameEntity)
 assert(forceSameEntity==true); return {naming=true,entity=entity,name=name}
end
api.cmd.sendCommand=function(p,callback)
 if p.naming then
   if failNameNext then failNameNext=false; return end
   names[p.entity]={name=p.name}; return
 end
 if p.ownership then
   ownershipCommands[#ownershipCommands+1]=p
   if failOwnershipNext then failOwnershipNext=false; return end
   owners[p.entity]={player=p.player}; return
 end
 commands[#commands+1]=p
 if failNext then failNext=false; callback({resultProposalData={errorState={messages={"Collision"}}}},false); return end
 local nodes={}
 for _,n in ipairs(p.streetProposal.nodesToAdd or {}) do
  nextId=nextId+1; nodes[n.entity]=nextId; components[nextId]={position=n.comp.position}
 end
 local segments={}
 for _,e in ipairs(p.streetProposal.edgesToAdd or {}) do
  nextId=nextId+1
  local comp={node0=nodes[e.comp.node0] or e.comp.node0,node1=nodes[e.comp.node1] or e.comp.node1,objects={}}
  components[nextId]=comp
  segments[#segments+1]={entity=nextId,comp=comp}
 end
 local resultEntities={}
 for _,con in ipairs(p.constructionsToAdd or {}) do
   nextId=nextId+1
   local hasGround=false
   for _,item in ipairs(con.params.items) do if item.texture then hasGround=true end end
   -- TF3 flattens model-only proposals into asset groups and loses their name.
   local flattened=flattenModelOnly and not hasGround
   components[nextId]=not flattened and {fileName=con.fileName,params=con.params} or {assetGroup=true,items=con.params.items}
   if not flattened then names[nextId]={name=""} end
   resultEntities[#resultEntities+1]={nextId,1}
 end
 callback({proposal={proposal={addedSegments=segments}},resultEntities=resultEntities},true,resultEntities)
end
state={value=nil,subscriptions={}}
function state:get() return self.value end
function state:set(value) self.value=value end
function state:hasEventSubscriptions() return #self.subscriptions>0 end
function state:subscribeToEvent(name) self.subscriptions[#self.subscriptions+1]=name end
'''


class GameScriptTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().dataset=self.lua.execute((CONTENT/'dataset.lua').read_text(encoding='utf-8'))
        self.lua.globals().modules=self.lua.table_from({
            'druttzen_osm_vanilla::/osm/dataset.lua':self.lua.globals().dataset,
            'druttzen_osm_vanilla::/osm/controls.lua':self.lua.execute((CONTENT/'controls.lua').read_text(encoding='utf-8')),
        })
        self.lua.execute(MOCK)
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']=self.lua.execute(
            (CONTENT/'ui_snapshot.lua').read_text(encoding='utf-8'))
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/world_audit.lua']=self.lua.execute(
            (CONTENT/'world_audit.lua').read_text(encoding='utf-8'))
        self.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.state=self.lua.globals().state
        self.script.update(None,self.state,1)

    def event(self,name,param=None):
        if isinstance(param,dict): param=self.lua.table_from(param)
        self.script.handleEvent(None,self.state,'test','druttzen_osm_vanilla','osm.'+name,param)

    def step(self):
        result=self.script.update(None,self.state,1)
        if result is not None:
            self.script.postUpdate(None,self.state,1,result)

    def finish(self):
        for _ in range(200):
            self.step()
            if self.state.value.phase in ('finished','error'): break
        self.assertEqual(self.state.value.phase,'finished',self.state.value.error)

    def test_complete_counts_positive_node_reuse_and_no_duplicate_start(self):
        self.event('start'); self.finish()
        d=self.lua.globals().dataset; value=self.state.value
        self.assertEqual(value.builtEdges,len(d.edges))
        self.assertEqual(value.builtScenery,len(d.scenery))
        self.assertEqual(value.labels,len(d.labels))
        self.assertTrue(all(id>0 for id in value.nodes.values()))
        proposals=[p for p in self.lua.globals().commands.values() if p.streetProposal.edgesToAdd]
        self.assertTrue(any(p.streetProposal.edgesToAdd[1].comp.node0>0 for p in proposals))
        self.assertTrue(all(p.streetProposal.edgesToRemove is None and p.constructionsToRemove is None for p in proposals))
        count=len(self.lua.globals().commands)
        self.event('start'); self.step()
        self.assertEqual(len(self.lua.globals().commands),count)

    def test_pause_resume_keeps_cursor(self):
        self.event('start'); self.step(); self.event('pause')
        cursor=self.state.value.cursor; count=len(self.lua.globals().commands)
        self.step()
        self.assertEqual(self.state.value.phase,'paused')
        self.assertEqual(len(self.lua.globals().commands),count)
        self.event('resume'); self.finish()
        self.assertGreater(self.state.value.builtScenery,0)

    def test_update_schedules_builds_only_while_active(self):
        self.assertIsNone(self.script.update(None,self.state,1))
        self.event('start')
        self.assertIsNotNone(self.script.update(None,self.state,1))
        self.event('pause')
        self.assertIsNone(self.script.update(None,self.state,1))
        self.event('resume'); self.finish()
        self.assertIsNone(self.script.update(None,self.state,1))

    def test_failed_job_retry(self):
        self.event('start'); self.lua.globals().failNext=True; self.step()
        self.assertEqual(self.state.value.phase,'error')
        self.assertEqual(self.state.value.cursor,1)
        self.assertEqual(self.state.value.builtScenery,0)
        self.assertIn('Collision',self.state.value.error)
        self.event('retry'); self.finish()
        self.assertEqual(self.state.value.skipped,0)

    def test_ownership_retry_does_not_duplicate_accepted_geometry(self):
        self.event('configure',{'vegetation':False,'surfaces':False,'objects':False,'places':False})
        self.event('start')
        self.lua.globals().failOwnershipNext=True
        self.step(); self.step()
        value=self.state.value
        self.assertEqual(value.phase,'error')
        self.assertEqual(value.builtEdges,1)
        self.assertIsNotNone(value.pendingOwnership)
        cursor=value.cursor
        self.event('skip')
        self.assertEqual(value.cursor,cursor)
        self.assertEqual(value.skipped,0)
        self.event('retry'); self.finish()
        self.assertEqual(value.builtEdges,len(self.lua.globals().dataset.edges))
        proposals=[p for p in self.lua.globals().commands.values() if p.streetProposal.edgesToAdd]
        self.assertEqual(len(proposals),len(self.lua.globals().dataset.edges))
        self.assertIsNone(value.pendingOwnership)
        self.assertEqual(len(list(self.lua.globals().owners.values())),len(self.lua.globals().dataset.edges))

    def test_last_edge_ownership_must_finish_before_import_completion(self):
        self.event('configure',{'vegetation':False,'surfaces':False,'objects':False,'places':False})
        self.event('start')
        while self.state.value.builtEdges<len(self.lua.globals().dataset.edges)-1:
            self.step()
        self.lua.globals().failOwnershipNext=True
        self.step()
        self.assertEqual(self.state.value.phase,'error')
        self.assertIsNotNone(self.state.value.pendingOwnership)
        count=len(self.lua.globals().commands)
        self.event('retry'); self.finish()
        self.assertEqual(len(self.lua.globals().commands),count)
        self.assertIsNone(self.state.value.pendingOwnership)

    def test_scenery_is_recorded_owned_and_named(self):
        self.event('start'); self.finish()
        records=list(self.state.value.sceneryRecords.values())
        self.assertEqual(len(records),3)
        self.assertEqual(records[-1].name,'OSM test village')
        for record in records:
            for entity in record.entities.values():
                self.assertEqual(self.lua.globals().names[entity].name,record.name)
                self.assertEqual(self.lua.globals().owners[entity].player,42)

    def test_unnamed_optimized_assets_finish_without_unsafe_name_command(self):
        self.lua.globals().flattenModelOnly=True
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.builtScenery,117)
        self.assertEqual(self.state.value.labels,1)
        records=list(self.state.value.sceneryRecords.values())
        first=records[0].entities[1]
        self.assertIsNone(self.lua.globals().names[first])
        self.assertEqual(self.lua.globals().owners[first].player,42)
        marker=records[-1].entities[1]
        self.assertIsNone(self.lua.globals().names[marker])
        self.assertEqual(records[-1].name,'OSM test village')
        self.assertEqual(len(self.lua.globals().commands),13)
        proposal=self.lua.globals().commands[13].constructionsToAdd[1]
        self.assertEqual(len(proposal.params['items']),1)
        self.event('placeNames')
        self.assertIn('OSM test village (x -150 m, y -50 m)',self.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),13)

    def test_scenery_naming_failure_retries_without_duplicate_batch(self):
        self.event('start'); self.lua.globals().failNameNext=True; self.step()
        self.assertEqual(self.state.value.phase,'error')
        self.assertEqual(self.state.value.builtScenery,100)
        self.assertIsNotNone(self.state.value.pendingScenery)
        self.event('skip')
        self.assertEqual(self.state.value.skipped,0)
        self.event('retry'); self.finish()
        scenery=[p for p in self.lua.globals().commands.values() if p.constructionsToAdd]
        self.assertEqual(len(scenery),3)
        self.assertIsNone(self.state.value.pendingScenery)

    def test_place_names_paginate_without_building_and_reject_changed_dataset(self):
        self.lua.execute('''
          dataset.labels={}; state.value.sceneryRecords={}; state.value.datasetId=dataset.id
          for index=1,21 do
            dataset.labels[index]={name="Place "..index,pos={index,-index}}
            state.value.sceneryRecords[index]={phase="labels",first=index,name="Place "..index,entities={index}}
          end
          state.value.labels=21
        ''')
        self.event('placeNames')
        self.assertIn('page 1/2',self.state.value.notice)
        self.assertIn('Place 20 (x 20 m, y -20 m)',self.state.value.notice)
        self.assertNotIn('Place 21',self.state.value.notice)
        self.event('placeNames')
        self.assertIn('page 2/2',self.state.value.notice)
        self.assertIn('Place 21 (x 21 m, y -21 m)',self.state.value.notice)
        self.event('placeNames')
        self.assertIn('page 1/2',self.state.value.notice)
        self.lua.globals().dataset.id='changed'
        self.event('placeNames')
        self.assertIn('Dataset changed',self.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_failed_job_skip_counts_missing_chunk(self):
        self.event('start'); self.lua.globals().failNext=True; self.step()
        self.event('skip'); self.finish()
        self.assertEqual(self.state.value.skipped,1)
        self.assertEqual(self.state.value.builtScenery,len(self.lua.globals().dataset.scenery)-100)

    def test_changed_dataset_stops_without_more_commands(self):
        self.event('start'); self.step()
        self.lua.globals().dataset.id='changed'
        count=len(self.lua.globals().commands); self.step()
        self.assertEqual(self.state.value.phase,'error')
        self.assertEqual(len(self.lua.globals().commands),count)

    def test_missing_resource_prevents_import(self):
        self.lua.globals().missing=self.lua.globals().dataset.edges[1].template
        self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_off_map_prevents_partial_import(self):
        self.lua.globals().outside=True; self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_named_ground_resources_are_validated_without_numeric_comparison(self):
        self.event('validate')
        self.assertIn('passed',self.state.value.notice)
        surface=next(s for s in self.lua.globals().dataset.scenery.values() if s.texture)
        self.lua.globals().missing=surface.texture
        self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertIn('Missing vanilla resource',self.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_gui_request_subscription_is_added_once_and_migrates_existing_state(self):
        self.assertIn('osm.ui.snapshot',self.state.subscriptions.values())
        count=len(self.state.subscriptions)
        self.script.update(None,self.state,1)
        self.assertEqual(len(self.state.subscriptions),count)
        self.state.value.uiSnapshotSubscribed=None
        self.lua.execute('state.subscriptions={"osm.start","osm.pause"}')
        self.script.update(None,self.state,1)
        self.assertIn('osm.ui.snapshot',self.state.subscriptions.values())

    def test_world_verification_subscription_is_added_once_and_migrates_existing_state(self):
        self.assertEqual(list(self.state.subscriptions.values()).count('osm.verify'),1)
        count=len(self.state.subscriptions)
        self.script.update(None,self.state,1)
        self.assertEqual(len(self.state.subscriptions),count)
        self.lua.execute('''
          state.value.worldAuditSubscribed=nil
          state.subscriptions={"osm.start","osm.pause","osm.ui.snapshot"}
        ''')
        self.script.update(None,self.state,1)
        self.assertEqual(list(self.state.subscriptions.values()).count('osm.verify'),1)
        self.assertEqual(list(self.state.subscriptions.values()).count('osm.ui.snapshot'),1)
        self.assertTrue(self.state.value.worldAuditSubscribed)
        migrated_count=len(self.state.subscriptions)
        self.script.update(None,self.state,1)
        self.assertEqual(len(self.state.subscriptions),migrated_count)

    def test_verify_requires_finished_import_and_does_not_build(self):
        # The small command mock has no live world component inventory. Stub the
        # audit boundary here; its actual component reads are tested separately.
        self.lua.execute('''
          auditCalls={}
          local audit=modules["druttzen_osm_vanilla::/osm/world_audit.lua"]
          audit.inspect=function(receivedDataset,value)
            assert(receivedDataset==dataset)
            auditCalls[#auditCalls+1]={phase=value.phase,cursor=value.cursor,
              builtEdges=value.builtEdges,builtScenery=value.builtScenery,labels=value.labels}
            return {ok=value.phase=="finished",phase=value.phase}
          end
          audit.format=function(report)
            return report.ok and "Mock world objects verified" or "Verification requires a finished import"
          end
        ''')
        controls=self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua']
        for phase in ('ready','scenery','edges','labels','paused','error'):
            with self.subTest(phase=phase):
                self.state.value.phase=phase
                self.assertFalse(controls.enabled('verify',self.state.value))
                self.event('verify')
                self.assertFalse(self.state.value.audit.ok)
                self.assertIn('requires a finished import',self.state.value.notice)
                self.assertEqual(len(self.lua.globals().commands),0)
        self.state.value.phase='ready'
        self.event('start'); self.finish()
        self.assertTrue(controls.enabled('verify',self.state.value))
        before=(len(self.lua.globals().commands),self.state.value.cursor,self.state.value.builtEdges,
                self.state.value.builtScenery,self.state.value.labels,dict(self.state.value.nodes.items()))
        self.event('verify')
        self.assertTrue(self.state.value.audit.ok)
        self.assertEqual(self.state.value.notice,'Mock world objects verified')
        self.assertEqual(self.state.value.phase,'finished')
        after=(len(self.lua.globals().commands),self.state.value.cursor,self.state.value.builtEdges,
               self.state.value.builtScenery,self.state.value.labels,dict(self.state.value.nodes.items()))
        self.assertEqual(before,after)
        self.assertEqual(self.lua.globals().auditCalls[len(self.lua.globals().auditCalls)].phase,'finished')

    def test_verify_native_read_error_clears_stale_success_without_building(self):
        self.lua.execute('''
          state.value.phase="finished"
          state.value.audit={ok=true}
          modules["druttzen_osm_vanilla::/osm/world_audit.lua"].inspect=function()
            error("Native component inventory unavailable")
          end
        ''')
        self.event('verify')
        self.assertIsNone(self.state.value.audit)
        self.assertIn('World check failed',self.state.value.notice)
        self.assertIn('Native component inventory unavailable',self.state.value.notice)
        self.assertEqual(self.state.value.phase,'finished')
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_missing_unselected_ground_resource_does_not_block_rail_only_import(self):
        surface=next(s for s in self.lua.globals().dataset.scenery.values() if s.texture)
        self.lua.globals().missing=surface.texture
        self.event('configure',dict(roads=False,vegetation=False,surfaces=False,objects=False,places=False))
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.builtEdges,2)
        self.assertEqual(self.state.value.builtScenery,0)

    def test_unselected_scenery_and_unused_nodes_outside_map_do_not_block_rails(self):
        self.lua.execute('''
          api.engine.terrain.isValidCoordinate=function(p) return math.abs(p.x)<=500 and math.abs(p.y)<=500 end
          dataset.nodes.unused={pos={10000,0}}
          dataset.scenery[#dataset.scenery+1]={model="::/assets/vegetation/tree.mdl",pos={10000,0}}
        ''')
        self.event('configure',dict(roads=False,vegetation=False,surfaces=False,objects=False,places=False))
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.builtEdges,2)

    def test_unselected_road_resources_and_markers_do_not_block_rails(self):
        self.lua.globals().missing=self.lua.globals().dataset.edges[1].template
        self.lua.execute('dataset.labels[1].pos={10000,0}; api.engine.terrain.isValidCoordinate=function(p) return math.abs(p.x)<=500 and math.abs(p.y)<=500 end')
        self.event('configure',dict(roads=False,vegetation=False,surfaces=False,objects=False,places=False))
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.builtEdges,2)

    def test_selected_categories_build_only_railways_and_markers(self):
        self.event('configure',dict(roads=False,vegetation=False,surfaces=False,objects=False))
        self.event('start'); self.finish()
        dataset=self.lua.globals().dataset
        tracks=sum(e.kind=='TRACK' for e in dataset.edges.values())
        self.assertEqual(self.state.value.builtEdges,tracks)
        self.assertEqual(self.state.value.builtScenery,0)
        self.assertEqual(self.state.value.labels,1)
        proposals=[p for p in self.lua.globals().commands.values() if p.streetProposal.edgesToAdd]
        self.assertTrue(all(p.streetProposal.edgesToAdd[1].type==1 for p in proposals))

    def test_zero_selection_prevents_start(self):
        controls=self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua']
        self.event('configure',{c.key:False for c in controls.categories.values()})
        self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertIn('No dataset items',self.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_settings_saved_and_batch_size_changed_while_paused(self):
        self.event('configure',dict(batchSize=10))
        self.event('start'); self.step()
        self.assertEqual(self.state.value.builtScenery,10)
        self.event('pause'); self.event('configure',dict(batchSize=25))
        self.assertEqual(self.state.value.options.batchSize,25)
        self.event('resume'); self.step()
        self.assertEqual(self.state.value.builtScenery,35)
        self.finish()
        self.assertEqual(self.state.value.builtScenery,len(self.lua.globals().dataset.scenery))

    def test_selections_locked_after_start(self):
        self.event('start'); self.event('configure',dict(roads=False,batchSize=25))
        self.assertTrue(self.state.value.options.roads)
        self.assertEqual(self.state.value.options.batchSize,100)
        self.assertIn('locked',self.state.value.notice)

    def test_invalid_settings_are_atomic(self):
        for patch in [dict(batchSize=0),dict(batchSize=101),dict(batchSize=2.5),dict(interval=float('nan')),
                      dict(interval=-1),dict(interval=3),dict(roads='false'),dict(unknown=True)]:
            self.event('configure',patch)
            self.assertEqual(self.state.value.options.batchSize,100)
            self.assertEqual(self.state.value.options.interval,0)
            self.assertTrue(self.state.value.options.roads)

    def test_import_delay_throttles_proposals(self):
        self.event('configure',dict(interval=1)); self.event('start'); self.step()
        count=len(self.lua.globals().commands)
        self.script.postUpdate(None,self.state,.4,None)
        self.assertEqual(len(self.lua.globals().commands),count)
        self.script.postUpdate(None,self.state,.6,None)
        self.assertEqual(len(self.lua.globals().commands),count+1)

    def test_validation_reports_errors_without_building(self):
        self.event('validate')
        self.assertIn('passed',self.state.value.notice)
        self.assertEqual(self.state.value.phase,'ready')
        self.assertEqual(len(self.lua.globals().commands),0)
        self.lua.globals().outside=True; self.event('validate')
        self.assertIn('outside',self.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_gui_snapshot_is_read_only_and_returns_selected_totals(self):
        self.lua.execute('api.engine.terrain.getBoundingBox=function() return {min={x=-500,y=-500},max={x=500,y=500}} end')
        bridge=load_script(self.lua,CONTENT/'ui_bridge.script.lua')
        readonly=self.lua.eval('{get=function(_) return state.value end}')
        self.event('configure',dict(roads=False))
        snapshot=bridge.guiHandleEvent(None,readonly,None,'test','druttzen_osm_vanilla','osm.ui.snapshot',None)
        self.assertEqual(snapshot.mapWidth,1000)
        self.assertFalse(snapshot.options.roads)
        self.assertFalse(snapshot.started)
        self.assertGreater(snapshot.totals.edges,0)
        self.assertLess(snapshot.totals.edges,len(self.lua.globals().dataset.edges))
        self.assertIsNone(bridge.guiHandleEvent(None,readonly,None,'test','another-mod','osm.ui.snapshot',None))

    def test_scenery_preserves_rotation_and_ground_faces(self):
        script=load_script(self.lua,CONTENT/'scenery.script.lua')
        params=self.lua.eval('{items={{model="::/test.mdl",pos={1,2,3},rotation=0},{texture="::/test.gtex",face={{0,0,0},{1,0,0},{0,1,0}}}}}')
        result=script.updateFn(None,params)
        self.assertEqual(result.metadata.druttzenOsmImporter.schema,1)
        sub=result.subconstructions[1]
        self.assertEqual(sub.models[1].transf[13],1)
        self.assertEqual(sub.models[1].transf[15],3)
        self.assertEqual(len(sub.groundFaces[1].face),3)
        self.assertEqual(len(sub.terrainAlignmentLists[1].faces),0)

    def test_all_lua_syntax_and_definitions(self):
        loader=self.lua.eval('function(text,name) local fn,err=load(text,name); return fn~=nil,err end')
        for file in CONTENT.glob('*.lua'):
            ok,err=loader(file.read_text(encoding='utf-8'),file.name)
            self.assertTrue(ok,err)

    def test_dataset_import_defaults_used_by_engine_and_gui(self):
        self.lua.globals().dataset.importOptions=self.lua.table_from({'batchSize':17,'interval':.5})
        self.state.value=None
        self.script.update(None,self.state,1)
        self.assertEqual(self.state.value.options.batchSize,17)
        self.assertEqual(self.state.value.options.interval,.5)
        bridge=load_script(self.lua,CONTENT/'ui_bridge.script.lua')
        self.lua.execute('api.engine.terrain.getBoundingBox=function() return {min={x=-500,y=-500},max={x=500,y=500}} end')
        snapshot=bridge.guiHandleEvent(None,self.state,None,'test','druttzen_osm_vanilla','osm.ui.snapshot',None)
        self.assertEqual(snapshot.options.batchSize,17)
        self.event('configure',{'batchSize':25})
        self.script.update(None,self.state,1)
        self.assertEqual(self.state.value.options.batchSize,25)

    def test_decorative_tree_replacement_keeps_object_selection(self):
        controls=self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua']
        item=self.lua.table_from({'model':'::/assets/vegetation/tree.mdl','category':'objects'})
        self.assertEqual(controls.sceneryCategory(item),'objects')


if __name__=='__main__': unittest.main()


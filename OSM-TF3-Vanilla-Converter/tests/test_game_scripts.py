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
logs={}; commands={}; missing=nil; failNext=false; outside=false; nextId=100
components={}
function print(s) logs[#logs+1]=s end
function ug_require(name) assert(modules[name],"Unknown module: "..name); return modules[name] end
local rep={find=function(name) if name==missing then return -1 end return 1 end,
  get=function(_) return {laneConfigs={},streetStyle="::/vanilla-style"} end}
api={type={ComponentType={BASE_NODE=1},["enum"]={BaseEdgeType={NORMAL=0,BRIDGE=1,TUNNEL=2},RoadType={TRACK=1,STREET=0}}},
 res={streetTemplateRep=rep,bridgeTypeRep=rep,tunnelTypeRep=rep,modelRep=rep,groundTextureRep=rep,constructionRep=rep},
 engine={util={getPlayer=function() return 42 end},terrain={
  isValidCoordinate=function(_) return not outside end,
  getHeightAt=function(_) return 10 end},
  entityExists=function(id) return components[id]~=nil end,
  getComponent=function(id,_) return components[id] end},cmd={}}
api.type.Vec2f={new=function(x,y) return {x=x,y=y} end}
api.type.Vec3f={new=function(x,y,z) return {x=x,y=y,z=z} end}
api.type.Mat4f={new=function() return {} end}
api.type.NodeAndEntity={new=function() return {comp={}} end}
api.type.SegmentAndEntity={new=function() return {comp={}} end}
api.type.SimpleProposal={new=function() return {streetProposal={}} end,
 ConstructionEntity={new=function() return {} end}}
api.cmd.makeWorldBuildProposalCmd=function(p,_,ignore,_) assert(ignore==false); return p end
api.cmd.sendCommand=function(p,callback)
 commands[#commands+1]=p
 if failNext then failNext=false; callback({resultProposalData={errorState={messages={"Collision"}}}},false); return end
 local nodes={}
 for _,n in ipairs(p.streetProposal.nodesToAdd or {}) do
  nextId=nextId+1; nodes[n.entity]=nextId; components[nextId]={position=n.comp.position}
 end
 local segments={}
 for _,e in ipairs(p.streetProposal.edgesToAdd or {}) do
  segments[#segments+1]={comp={node0=nodes[e.comp.node0] or e.comp.node0,node1=nodes[e.comp.node1] or e.comp.node1}}
 end
 callback({proposal={proposal={addedSegments=segments}}},true,{})
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
        self.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.state=self.lua.globals().state
        self.script.update(None,self.state,1)

    def event(self,name,param=None):
        if isinstance(param,dict): param=self.lua.table_from(param)
        self.script.handleEvent(None,self.state,'test','druttzen_osm_vanilla','osm.'+name,param)

    def step(self):
        self.script.postUpdate(None,self.state,1,None)

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

    def test_failed_job_retry(self):
        self.event('start'); self.lua.globals().failNext=True; self.step()
        self.assertEqual(self.state.value.phase,'error')
        self.assertEqual(self.state.value.cursor,1)
        self.assertEqual(self.state.value.builtScenery,0)
        self.assertIn('Collision',self.state.value.error)
        self.event('retry'); self.finish()
        self.assertEqual(self.state.value.skipped,0)

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


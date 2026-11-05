"""Native state commits must be selective, immutable and immediately durable."""
import unittest

import test_game_scripts as game


NATIVE = r'''
nativeFinds=0; nativeInserts=0; nativeMaterializations=0
local Native={}; Native.__index=Native
function nativePlain(value)
  if getmetatable(value)==Native then value=value.values end
  if type(value)~="table" then return value end
  local result={}; for k,v in pairs(value) do result[k]=nativePlain(v) end
  return result
end
function nativeFrom(value)
  if type(value)~="table" then return value end
  local result=setmetatable({values={}},Native)
  for k,v in pairs(value) do result.values[k]=nativeFrom(v) end
  return result
end
function Native:find(k) nativeFinds=nativeFinds+1; return self.values[k] end
function Native:clone()
  local result=setmetatable({values={}},Native)
  -- Shallow sharing catches accidental writes through a retained child.
  for k,v in pairs(self.values) do result.values[k]=v end
  return result
end
function Native:insert(k,v) nativeInserts=nativeInserts+1; self.values[k]=nativeFrom(v) end
function Native:insert_native(k,v) nativeInserts=nativeInserts+1; self.values[k]=v end
function Native:remove(k) self.values[k]=nil end
function Native:next(k) local following=next(self.values,k); return following end
function Native:size() local n=0; for _ in pairs(self.values) do n=n+1 end; return n end
function Native:asTable() nativeMaterializations=nativeMaterializations+1; return nativePlain(self) end
function installNativeState()
  state.saved=nativeFrom(state.value or {}); state.commits={}; state.fullReads=0
  function state:get() self.fullReads=self.fullReads+1; return nativePlain(self.saved) end
  function state:set(v) self.saved=nativeFrom(v); self.value=nativePlain(self.saved) end
  function state:get_native() return self.saved end
  function state:set_native(v)
    self.saved=v; self.commits[#self.commits+1]=v
    self.value=nativePlain(v)
  end
end
'''


class NativeStateTests(unittest.TestCase):
    def setUp(self):
        self.h=game.GameScriptTests(); self.h.setUp()
        self.lua,self.state=self.h.lua,self.h.state
        self.lua.execute(NATIVE)
        self.lua.execute('installNativeState()')
        self.bridge=self.lua.execute((game.CONTENT/'native_state.lua').read_text())
        self.lua.globals().bridgeModule=self.bridge

    def test_read_only_fields_do_not_materialize_or_commit_large_journals(self):
        self.lua.execute('''
          local large={}; for i=1,20000 do large[i]={model="unchanged",pos={i,i,10}} end
          state:set({phase="paused",matches=large}); nativeFinds=0
          local view=bridgeModule.open(state):get()
          assert(view.phase=="paused")
        ''')
        self.assertEqual(self.state.fullReads,0)
        self.assertEqual(len(self.state.commits),0)
        self.assertEqual(self.lua.globals().nativeMaterializations,0)
        self.assertLess(self.lua.globals().nativeFinds,5)

    def test_nested_updates_append_remove_and_iteration_keep_previous_commits_immutable(self):
        self.lua.execute('''
          state:set({nodes={a=1,b=2},records={{entity=10}},phase="ready"})
          original=state.saved
          local s=bridgeModule.open(state); local v=s:get()
          v.nodes.a=3; v.nodes.b=nil; v.nodes.c=4
          table.insert(v.records,{entity=11}); s:set(v)
          v.records[1].entity=12; s:set(v)
          local seen={}; for k,item in pairs(v.nodes) do seen[k]=item end
          assert(seen.a==3 and seen.b==nil and seen.c==4)
          assert(#v.records==2)
          old=nativePlain(original); first=nativePlain(state.commits[1]); last=nativePlain(state.saved)
        ''')
        g=self.lua.globals()
        self.assertEqual(g.old.nodes.a,1)
        self.assertEqual(g.old.records[1].entity,10)
        self.assertEqual(g.first.records[1].entity,10)
        self.assertEqual(g.last.records[1].entity,12)
        self.assertEqual(g.last.records[2].entity,11)

    def test_plain_record_finalization_after_checkpoint_is_included_in_next_commit(self):
        self.lua.execute('''
          state:set({records={}})
          local s=bridgeModule.open(state); local v=s:get()
          local record={entities={42},complete=false}
          v.records[1]=record; v.pending=record; s:set(v)
          record.complete=true; v.pending=nil; s:set(v)
          first=nativePlain(state.commits[1]); last=nativePlain(state.saved)
        ''')
        g=self.lua.globals()
        self.assertFalse(g.first.records[1].complete)
        self.assertTrue(g.last.records[1].complete)
        self.assertIsNone(g.last.pending)

    def test_replacing_initial_state_preserves_queued_native_requests_and_later_edits(self):
        self.lua.execute('''
          state:set({nativeRequests={{name="osm.start"}},obsolete=true})
          local s=bridgeModule.open(state); local old=s:get()
          local v={phase="ready",nativeRequests=old.nativeRequests}
          s:set(v); v.notice="saved"; s:set(v)
          initialized=nativePlain(state.saved)
          s:set({phase="finished"}); replaced=nativePlain(state.saved)
        ''')
        g=self.lua.globals()
        self.assertEqual(g.initialized.nativeRequests[1].name,'osm.start')
        self.assertEqual(g.initialized.notice,'saved')
        self.assertIsNone(g.initialized.obsolete)
        self.assertEqual(g.replaced.phase,'finished')
        self.assertIsNone(g.replaced.nativeRequests)

    def test_native_owner_restores_accepted_journal_after_ownership_failure(self):
        wake=game.load_script(self.lua,game.CONTENT/'importer.script.lua')
        events=game.load_script(self.lua,game.CONTENT/'importer.script.lua')
        owner=game.load_script(self.lua,game.CONTENT/'importer.script.lua')
        def event(name):
            events.queueEvent(None,self.state,None,'druttzen_osm_vanilla','osm.'+name,self.lua.table())
        def tick():
            result=wake.wakeUpdate(None,self.state,1)
            if result is not None: owner.engineTick(None,self.state,1,result)
        self.lua.execute('''
          local send=api.cmd.sendCommand
          function api.cmd.sendCommand(command,callback)
            if command.ownership then
              assert(state.value.pendingScenery or state.value.pendingOwnership)
              assert(state.value.acceptedUnjournalled==nil)
              assert(state.value.cursor>1)
            end
            return send(command,callback)
          end
          failOwnershipNext=true
        ''')
        event('start'); tick()
        self.assertEqual(self.state.value.phase,'error')
        self.assertEqual(self.state.value.errorKind,'finalization')
        self.assertEqual(len(self.lua.globals().commands),1)
        # A new owner models full script recreation after a saved-game reload.
        owner=game.load_script(self.lua,game.CONTENT/'importer.script.lua')
        event('retry')
        for _ in range(200):
            tick()
            if self.state.value.phase in ('finished','error'): break
        self.assertEqual(self.state.value.phase,'finished',self.state.value.error)
        self.assertEqual(self.state.fullReads,0)
        self.assertEqual(self.state.value.builtEdges,len(self.lua.globals().dataset.edges))

    def test_scalar_commit_never_rewrites_unmodified_match_catalog(self):
        self.lua.execute('''
          state:set({phase="ready",matches={[1]={model="kept",pos={10,20,30}}}})
          oldMatches=state.saved:find("matches"); nativeInserts=0
          local s=bridgeModule.open(state); local v=s:get()
          assert(v.matches[1].model=="kept")
          v.phase="paused"; s:set(v)
          assert(state.saved:find("matches")==oldMatches)
        ''')
        self.assertEqual(self.lua.globals().nativeInserts,1)

    def test_panel_reads_native_metadata_without_materializing_saved_model_positions(self):
        import test_panel as panel
        h=panel.PanelTests(); h.setUp()
        h.lua.execute(NATIVE)
        h.lua.execute('''
          installNativeState()
          local large={}; for i=1,20000 do large[i]={model="kept",pos={i,i,10}} end
          state.saved:insert("matches",large)
          api.engine.getComponent=function(id,kind)
            assert(id==900 and kind==api.type.ComponentType.GAME_SCRIPT)
            return setmetatable({state_native=state.saved},{__index=function(_,key)
              if key=="state" then error("The panel must not materialize the entire saved state") end
            end})
          end
          nativeFinds=0
        ''')
        tree=h.tree()
        start=h.lua.globals().findNode(tree,'druttzen-osm-command-start')
        self.assertTrue(start.params.meta.enabled)
        self.assertEqual(h.lua.globals().state.fullReads,0)
        self.assertEqual(h.lua.globals().nativeMaterializations,0)
        self.assertEqual(len(h.lua.globals().state.commits),0)
        self.assertLess(h.lua.globals().nativeFinds,1000)


if __name__=='__main__': unittest.main()

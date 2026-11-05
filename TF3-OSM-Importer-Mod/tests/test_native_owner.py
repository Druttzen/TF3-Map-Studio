"""Exercise TF3's distinct callback instances without duplicating map geometry."""
import unittest

import test_game_scripts as game
from test_game_scripts import CONTENT, load_script


class NativeOwnerTests(unittest.TestCase):
    def setUp(self):
        self.h = game.GameScriptTests(); self.h.setUp()
        self.lua, self.state = self.h.lua, self.h.state
        self.lua.execute('''
          mapLoads={}
          local original=ug_require
          function ug_require(name)
            if name:find("/dataset.lua",1,true) or name:find("/maps/",1,true) then
              mapLoads[name]=(mapLoads[name] or 0)+1
            end
            return original(name)
          end
        ''')
        self.wake = load_script(self.lua, CONTENT/'importer.script.lua')
        self.events = load_script(self.lua, CONTENT/'importer.script.lua')
        self.owner = load_script(self.lua, CONTENT/'importer.script.lua')

    def queue(self, name, param=None):
        if isinstance(param, dict): param = self.lua.table_from(param)
        self.events.queueEvent(None, self.state, 'native-test', 'druttzen_osm_vanilla', 'osm.'+name, param)

    def tick(self):
        result = self.wake.wakeUpdate(None, self.state, 1)
        if result is not None: self.owner.engineTick(None, self.state, 1, result)

    def test_native_bindings_use_the_single_geometry_owner(self):
        desc = load_script(self.lua, CONTENT/'importer.gs.lua')
        self.assertTrue(desc.updateScript.fileName.endswith('@wakeUpdate'))
        self.assertTrue(desc.handleEventScript.fileName.endswith('@queueEvent'))
        self.assertTrue(desc.postUpdateScript.fileName.endswith('@engineTick'))
        self.queue('configure', {'batchSize': 25})
        self.assertEqual(len(self.lua.globals().mapLoads), 0)
        self.tick()
        self.assertEqual(self.state.value.options.batchSize, 25)
        self.assertEqual(dict(self.lua.globals().mapLoads), {'druttzen_osm_vanilla::/osm/dataset.lua': 1})
        self.assertIsNone(self.state.value.nativeRequests)

    def test_map_selection_and_reload_never_require_default_in_other_callbacks(self):
        resource = 'druttzen_osm_vanilla::/osm/maps/owner-test.lua'
        self.lua.execute('chosen={schema=1,id="owner-test",size={800,800},nodes={},edges={},scenery={},labels={}}')
        self.lua.globals().modules[resource] = self.lua.globals().chosen
        self.queue('mapSelect', {'resource': 'osm/maps/owner-test.lua'})
        self.tick()
        self.assertEqual(self.state.value.mapExpectedId, 'owner-test')
        self.lua.execute('mapLoads={}')
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/dataset.lua'] = None
        self.wake = load_script(self.lua, CONTENT/'importer.script.lua')
        self.owner = load_script(self.lua, CONTENT/'importer.script.lua')
        self.tick()
        self.assertTrue(self.state.value.mapReady)
        self.assertEqual(dict(self.lua.globals().mapLoads), {resource: 1})

    def test_start_then_pause_is_ordered_and_does_not_build_between_requests(self):
        self.queue('start'); self.queue('pause'); self.tick()
        self.assertIn(self.state.value.phase, ('ready', 'paused'))
        self.assertEqual(len(self.lua.globals().commands), 0)
        self.assertEqual(self.state.value.builtEdges, 0)
        self.assertEqual(self.state.value.builtScenery, 0)

    def test_request_before_initial_owner_update_survives_state_initialization(self):
        self.state.value = self.lua.table()
        self.queue('configure', {'batchSize': 25})
        self.tick()
        self.assertEqual(self.state.value.options.batchSize, 25)
        self.assertIsNone(self.state.value.nativeRequests)

    def test_native_request_queue_is_bounded(self):
        for _ in range(65): self.queue('status')
        self.assertEqual(len(self.state.value.nativeRequests), 64)
        self.assertIn('pending', self.state.value.notice)
        self.tick()
        self.assertIsNone(self.state.value.nativeRequests)
        self.assertEqual(len(self.lua.globals().commands), 0)

    def test_idle_wake_does_not_load_maps_or_write_state(self):
        self.tick()
        self.lua.execute('writes=0; local original=state.set; state.set=function(self,v) writes=writes+1; original(self,v) end; mapLoads={}')
        for _ in range(600): self.tick()
        self.assertEqual(self.lua.globals().writes, 0)
        self.assertEqual(len(self.lua.globals().mapLoads), 0)

    def test_previously_started_import_finishes_through_native_owner(self):
        self.h.event('start'); self.h.step()
        before = self.state.value.builtScenery
        self.assertGreater(before, 0)
        for _ in range(200):
            self.tick()
            if self.state.value.phase in ('finished', 'error'): break
        self.assertEqual(self.state.value.phase, 'finished', self.state.value.error)
        self.assertEqual(self.state.value.builtEdges, len(self.lua.globals().dataset.edges))
        self.assertEqual(self.state.value.builtScenery, len(self.lua.globals().dataset.scenery))

    def test_native_copies_are_read_once_and_accepted_build_is_durable_before_ownership(self):
        self.tick()
        self.lua.execute('''
          local function copy(v)
            if type(v)~="table" then return v end
            local result={}; for k,item in pairs(v) do result[k]=copy(item) end
            return result
          end
          nativeReads=0
          function state:get() nativeReads=nativeReads+1; return copy(self.value) end
          function state:set(v) self.value=copy(v) end
          local send=api.cmd.sendCommand
          function api.cmd.sendCommand(command,callback)
            if command.ownership then
              assert(state.value.acceptedUnjournalled==nil)
              assert(state.value.pendingScenery or state.value.pendingOwnership)
              assert(state.value.cursor>1,"Accepted cursor must already be persisted")
            end
            return send(command,callback)
          end
        ''')
        self.queue('start')
        self.lua.execute('nativeReads=0; failOwnershipNext=true')
        self.owner.engineTick(None, self.state, 1, self.lua.table())
        self.assertEqual(self.lua.globals().nativeReads, 1)
        self.assertEqual(self.state.value.phase, 'error')
        self.assertEqual(self.state.value.errorKind, 'finalization')
        self.assertIsNotNone(self.state.value.pendingScenery)
        accepted = len(self.lua.globals().commands)
        self.queue('retry'); self.queue('pause'); self.tick()
        self.assertEqual(len(self.lua.globals().commands), accepted)
        self.queue('resume'); self.tick()
        for _ in range(200):
            if self.state.value.phase in ('finished', 'error'): break
            self.tick()
        self.assertEqual(self.state.value.phase, 'finished', self.state.value.error)
        self.assertEqual(self.state.value.builtEdges, len(self.lua.globals().dataset.edges))


if __name__ == '__main__': unittest.main()

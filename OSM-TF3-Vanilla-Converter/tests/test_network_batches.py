"""Atomic network batches preserve node identity and accepted-command recovery."""
import unittest
import test_game_scripts as game


class NetworkBatchTests(unittest.TestCase):
    def setUp(self):
        self.h = game.GameScriptTests(); self.h.setUp()
        self.lua, self.state = self.h.lua, self.h.state
        self.lua.execute('''
          dataset.scenery={}; dataset.labels={}; dataset.nodes={}; dataset.edges={}
          for i=1,251 do dataset.nodes[tostring(i)]={pos={i,0}} end
          for i=1,250 do dataset.edges[i]={kind="STREET",node0=tostring(i),node1=tostring(i+1),
            template="::/infrastructure/street/town/town_new_xsmall.street_template"} end
        ''')
        self.h.event('configure', {'networkBatchSize': 100})

    def test_chain_uses_unique_negative_ids_and_one_shared_node_per_source(self):
        self.h.event('start'); self.h.finish()
        self.assertEqual(self.state.value.builtEdges, 250)
        self.assertEqual(len(self.lua.globals().commands), 3)
        self.assertEqual(len(self.lua.globals().commands[1].streetProposal.nodesToAdd), 101)
        self.assertEqual(len(self.lua.globals().commands[2].streetProposal.nodesToAdd), 100)
        self.assertEqual(len(list(self.state.value.nodes.values())), 251)
        self.assertEqual(len(set(self.state.value.nodes.values())), 251)
        for command in self.lua.globals().commands.values():
            ids = [n.entity for n in command.streetProposal.nodesToAdd.values()]
            ids += [e.entity for e in command.streetProposal.edgesToAdd.values()]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertTrue(all(i < 0 for i in ids))

    def test_invalid_batch_sizes_leave_settings_unchanged(self):
        for size in (0,101,1.5,True,float('nan'),'10'):
            self.h.event('configure', {'networkBatchSize': size})
            self.assertEqual(self.state.value.options.networkBatchSize, 100)

    def test_rejected_batch_keeps_exact_range_and_no_provisional_nodes(self):
        self.h.event('start'); self.lua.globals().failNext = True; self.h.step()
        self.assertEqual(self.state.value.phase, 'error')
        self.assertEqual((self.state.value.failedFirst, self.state.value.failedLast), (1, 100))
        self.assertEqual(len(self.state.value.nodes), 0)
        self.assertEqual(self.state.value.builtEdges, 0)
        self.h.event('configure', {'networkBatchSize': 10})
        self.h.event('skip'); self.h.finish()
        self.assertEqual(self.state.value.builtEdges, 150)
        self.assertEqual(self.state.value.skipped, 1)

    def test_finalization_failure_survives_reload_without_replaying_batch(self):
        self.h.event('start'); self.lua.globals().failOwnershipNext = True; self.h.step()
        self.assertEqual(self.state.value.errorKind, 'finalization')
        self.assertEqual(self.state.value.builtEdges, 100)
        self.assertEqual(len(self.state.value.pendingOwnership), 100)
        self.assertEqual(self.state.value.cursor, 101)
        self.h.script = game.load_script(self.lua, game.CONTENT/'importer.script.lua')
        self.h.event('retry'); self.h.finish()
        self.assertEqual(len(self.lua.globals().commands), 3)
        self.assertEqual(self.state.value.builtEdges, 250)
        self.assertIsNone(self.state.value.pendingOwnership)

    def test_pause_limit_counts_successful_batches_and_resume_keeps_exact_cursor(self):
        self.h.event('configure', {'stepLimit': 1})
        self.h.event('start'); self.h.step(); self.h.step()
        self.assertEqual(self.state.value.phase, 'paused')
        self.assertEqual(self.state.value.cursor, 101)
        self.h.event('configure', {'networkBatchSize': 25})
        self.h.event('resume'); self.h.step(); self.h.step()
        self.assertEqual(self.state.value.phase, 'paused')
        self.assertEqual(self.state.value.cursor, 126)
        self.assertEqual(self.state.value.builtEdges, 125)

    def test_excluded_category_stops_batch_without_building_excluded_source(self):
        self.lua.execute('dataset.edges[51].kind="TRACK"')
        self.h.event('configure', {'railways': False})
        self.h.event('start'); self.h.finish()
        self.assertEqual(self.state.value.builtEdges, 249)
        self.assertEqual(len(self.lua.globals().commands[1].streetProposal.edgesToAdd), 50)
        self.assertEqual(len(self.lua.globals().commands[2].streetProposal.edgesToAdd), 100)

    def test_bad_accepted_result_stays_stopped_and_cannot_be_replayed(self):
        self.lua.execute('''
          local send=api.cmd.sendCommand
          api.cmd.sendCommand=function(command,callback)
            if command.ownership or command.naming then return send(command,callback) end
            send(command,function(result,success,entities)
              local s=result.proposal.proposal.addedSegments
              s[1],s[2]=s[2],s[1]
              callback(result,success,entities)
            end)
          end
        ''')
        self.h.event('start'); self.h.step()
        self.assertTrue(self.state.value.acceptedUnjournalled)
        self.assertEqual(self.state.value.errorKind, 'accepted_state')
        self.h.event('retry'); self.h.step()
        self.assertEqual(len(self.lua.globals().commands), 1)

    def test_curved_rails_share_provisional_tangents_without_native_lookup(self):
        self.lua.execute('''
          dataset.edges={dataset.edges[1],dataset.edges[2]}
          dataset.edges[1].kind="TRACK"; dataset.edges[2].kind="TRACK"
          dataset.nodes["1"].pos={0,0}; dataset.nodes["2"].pos={27,9}; dataset.nodes["3"].pos={36.25,11.88}
          api.engine.system.streetSystem.getNodeTrackSegments=function() error("No accepted native rail node yet") end
        ''')
        self.h.event('start'); self.h.finish()
        edges = self.lua.globals().commands[1].streetProposal.edgesToAdd
        self.assertEqual(edges[1].comp.node1, edges[2].comp.node0)
        self.assertAlmostEqual(edges[2].comp.tangent0.y / edges[2].comp.tangent0.x, 9/27)


if __name__ == '__main__': unittest.main()

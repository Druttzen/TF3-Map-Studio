"""Keep retryable command preparation separate from unknown build outcomes."""
import unittest

import test_game_scripts as game
from test_game_scripts import CONTENT, load_script


class CommandFailureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.h = game.GameScriptTests()
        self.h.setUp()
        self.lua = self.h.lua
        self.lua.execute('''
          dataset.edges={}; dataset.labels={}; dataset.scenery={}
          for i=1,3 do
            dataset.scenery[i]={category="vegetation",
              model="::/assets/vegetation/tree.mdl",pos={i*10,i*5},rotation=0}
          end
          savedMake=api.cmd.makeWorldBuildProposalCmd
          savedSend=api.cmd.sendCommand
        ''')
        self.h.event('configure', dict(batchSize=1))

    def reload(self):
        self.h.script = load_script(self.lua, CONTENT/'importer.script.lua')

    def test_constructor_failure_retries_only_unbuilt_range_after_reload(self):
        self.h.event('start')
        self.h.step()
        self.assertEqual(self.h.state.value.builtScenery, 1)
        first_entity = self.h.state.value.sceneryRecords[1].entities[1]
        self.lua.execute('''
          api.cmd.makeWorldBuildProposalCmd=function()
            error("ground_tex_util::Fill: empty triangles")
          end
        ''')
        self.h.step()
        value = self.h.state.value
        self.assertEqual(value.phase, 'error')
        self.assertEqual(value.errorKind, 'preparation')
        self.assertEqual(value.cursor, 2)
        self.assertEqual((value.failedFirst, value.failedLast), (2, 2))
        self.assertEqual(value.builtScenery, 1)
        self.assertEqual(len(self.lua.globals().commands), 1)
        self.assertIsNone(value.acceptedUnjournalled)
        self.assertIsNone(value.pendingScenery)

        self.lua.execute('api.cmd.makeWorldBuildProposalCmd=savedMake')
        self.reload()
        self.h.event('retry')
        self.h.finish()
        self.assertEqual(value.builtScenery, 3)
        self.assertEqual(value.skipped, 0)
        self.assertEqual(len(self.lua.globals().commands), 3)
        self.assertEqual(len(value.sceneryRecords), 3)
        self.assertEqual(value.sceneryRecords[1].entities[1], first_entity)
        self.assertEqual([r.first for r in value.sceneryRecords.values()], [1, 2, 3])

    def test_send_exception_after_world_mutation_still_blocks_replay(self):
        self.lua.execute('''
          sendAttempts=0
          api.cmd.sendCommand=function(p,callback)
            sendAttempts=sendAttempts+1
            -- The world accepted this command, but its result never reached us.
            savedSend(p,function() end)
            error("native result delivery failed")
          end
        ''')
        self.h.event('start')
        self.h.step()
        value = self.h.state.value
        self.assertEqual(value.phase, 'error')
        self.assertEqual(value.errorKind, 'command_state')
        self.assertEqual(value.cursor, 1)
        self.assertEqual(value.builtScenery, 0)
        self.assertEqual(len(self.lua.globals().commands), 1)
        self.reload()
        self.h.event('retry')
        self.h.step()
        self.assertEqual(value.phase, 'error')
        self.assertIn('cannot be safely replayed', value.notice)
        self.assertEqual(self.lua.globals().sendAttempts, 1)
        self.h.event('skip')
        self.assertEqual(value.cursor, 1)
        self.assertEqual(value.skipped, 0)

    def test_send_without_callback_still_has_unknown_outcome(self):
        self.lua.execute('api.cmd.sendCommand=function() end')
        self.h.event('start')
        self.h.step()
        value = self.h.state.value
        self.assertEqual(value.errorKind, 'command_state')
        self.assertIn('Builder must execute', value.error)
        self.h.event('retry')
        self.assertEqual(value.phase, 'error')
        self.assertEqual(value.cursor, 1)

    def test_accepted_result_decoding_failure_cannot_replay(self):
        self.lua.execute('''
          api.cmd.sendCommand=function(p,callback)
            savedSend(p,function(res,success)
              callback(res,success,{false}) -- invalid native entity entry
            end)
          end
        ''')
        self.h.event('start')
        self.h.step()
        value = self.h.state.value
        self.assertEqual(value.errorKind, 'accepted_state')
        self.assertTrue(value.acceptedUnjournalled)
        self.assertEqual(value.cursor, 1)
        self.assertEqual(len(self.lua.globals().commands), 1)
        self.reload()
        self.h.event('retry')
        self.h.step()
        self.assertEqual(value.phase, 'error')
        self.assertEqual(len(self.lua.globals().commands), 1)
        self.h.event('skip')
        self.assertEqual(value.cursor, 1)
        self.assertEqual(value.skipped, 0)

    def test_accepted_batch_finalization_retries_without_rebuilding(self):
        self.h.event('start')
        self.lua.globals().failNameNext = True
        self.h.step()
        value = self.h.state.value
        self.assertEqual(value.errorKind, 'finalization')
        self.assertEqual(value.builtScenery, 1)
        self.assertEqual(value.cursor, 2)
        self.assertIsNotNone(value.pendingScenery)
        self.h.event('skip')
        self.assertEqual(value.cursor, 2)
        self.reload()
        self.h.event('retry')
        self.h.finish()
        self.assertEqual(value.builtScenery, 3)
        self.assertEqual(len(self.lua.globals().commands), 3)
        self.assertIsNone(value.pendingScenery)

    def test_rejected_submission_remains_retryable(self):
        self.h.event('start')
        self.lua.globals().failNext = True
        self.h.step()
        value = self.h.state.value
        self.assertEqual(value.errorKind, 'proposal_rejected')
        self.assertEqual(value.cursor, 1)
        self.reload()
        self.h.event('retry')
        self.h.finish()
        self.assertEqual(value.builtScenery, 3)
        self.assertEqual(len(self.lua.globals().commands), 4)


if __name__ == '__main__':
    unittest.main()

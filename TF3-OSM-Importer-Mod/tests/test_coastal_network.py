"""Partille E20 crosses a coarse DSM pixel below the native water level."""
import unittest
import test_game_scripts as game


class CoastalNetworkTests(unittest.TestCase):
    def setUp(self):
        self.h = game.GameScriptTests(); self.h.setUp()
        self.lua = self.h.lua
        self.lua.execute('''
          dataset.scenery={}; dataset.labels={}
          dataset.nodes={a={pos={0,0}},b={pos={0,60}}}
          dataset.edges={{kind="STREET",node0="a",node1="b",
            template="::/infrastructure/street/town/town_new_one_way_xsmall.street_template"}}
          globalWaterLevel=0
          api.engine.terrain.getBaseHeightAt=function(p) return p.y==0 and 0.45 or -1.47 end
        ''')

    def test_empty_native_error_messages_never_produce_blank_panel_error(self):
        self.lua.execute('''
          local send=api.cmd.sendCommand
          function api.cmd.sendCommand(command,callback)
            if command.ownership or command.naming then return send(command,callback) end
            callback({resultProposalData={errorState={messages={},warnings={"Place on Land"}}}},false)
          end
        ''')
        self.h.event('start'); self.h.step()
        self.assertEqual(self.h.state.value.error, 'Place on Land')

    def test_completely_empty_native_error_has_actionable_fallback(self):
        self.lua.execute('''
          api.cmd.sendCommand=function(command,callback)
            callback({resultProposalData={errorState={messages={}}}},false)
          end
        ''')
        self.h.event('start'); self.h.step()
        self.assertIn('inspect the game log', self.h.state.value.error)


if __name__ == '__main__': unittest.main()

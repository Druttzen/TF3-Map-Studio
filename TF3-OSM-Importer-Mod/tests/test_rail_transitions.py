"""Short curved Partille rail must meet the accepted tangent in three dimensions."""
import unittest
import test_game_scripts as game


class RailTransitionTests(unittest.TestCase):
    def setUp(self):
        self.h = game.GameScriptTests(); self.h.setUp()
        self.lua, self.state = self.h.lua, self.h.state
        self.lua.execute('''
          dataset.scenery={}; dataset.labels={}
          dataset.nodes={a={pos={0,0}},b={pos={27,9}},c={pos={36.25,11.88}}}
          dataset.edges={
            {kind="TRACK",node0="a",node1="b",template="::/infrastructure/track/standard/standard_catenary.street_template"},
            {kind="TRACK",node0="b",node1="c",template="::/infrastructure/track/standard/standard_catenary.street_template"}}
          api.engine.terrain.getBaseHeightAt=function(p) return p.x<28 and 2.2 or 2.7 end
        ''')
        self.h.event('start'); self.h.step()
        self.assertEqual(self.state.value.builtEdges, 1)
        self.lua.execute('''
          local node=state.value.nodes.b
          components[900]={node0=state.value.nodes.a,node1=node,
            tangent0={x=27,y=9,z=0.25},tangent1={x=27,y=9,z=0.25}}
          api.engine.system.streetSystem.getNodeTrackSegments=function(n)
            assert(n==node); return {900}
          end
        ''')

    def assert_parallel(self, vector, direction):
        scale = vector.x / direction[0]
        self.assertGreater(scale, 0)
        self.assertAlmostEqual(vector.y, direction[1] * scale)
        self.assertAlmostEqual(vector.z, direction[2] * scale)

    def test_short_continuation_uses_accepted_3d_tangent(self):
        self.h.step()
        edge = self.lua.globals().commands[2].streetProposal.edgesToAdd[1]
        self.assert_parallel(edge.comp.tangent0, (27, 9, .25))
        self.assertAlmostEqual(edge.comp.tangent1.x, 9.25)
        self.assertAlmostEqual(edge.comp.position1.z, 2.7)
        self.assertEqual(self.state.value.builtEdges, 2)

    def test_reversed_existing_edge_keeps_forward_build_direction(self):
        self.lua.execute('''
          local e=components[900]
          e.node0,e.node1=e.node1,e.node0
          e.tangent0={x=-27,y=-9,z=-0.25}
        ''')
        self.h.step()
        self.assert_parallel(self.lua.globals().commands[2].streetProposal.edgesToAdd[1].comp.tangent0, (27, 9, .25))

    def test_unrelated_branch_does_not_force_a_right_angle(self):
        self.lua.execute('components[900].tangent1={x=-9,y=27,z=0}')
        self.h.step()
        tangent = self.lua.globals().commands[2].streetProposal.edgesToAdd[1].comp.tangent0
        self.assertAlmostEqual(tangent.x, 9.25)
        self.assertAlmostEqual(tangent.y, 2.88)

    def test_existing_end_node_aligns_without_moving_it(self):
        self.lua.execute('''
          state.value.nodes.c=901
          components[901]={position={x=36.25,y=11.88,z=2.7}}
          components[902]={node0=901,node1=903,tangent0={x=30,y=8,z=0.2}}
          api.engine.system.streetSystem.getNodeTrackSegments=function(n)
            return n==901 and {902} or {900}
          end
        ''')
        self.h.step()
        edge = self.lua.globals().commands[2].streetProposal.edgesToAdd[1]
        self.assert_parallel(edge.comp.tangent1, (30, 8, .2))
        self.assertEqual(edge.comp.node1, 901)


if __name__ == '__main__': unittest.main()

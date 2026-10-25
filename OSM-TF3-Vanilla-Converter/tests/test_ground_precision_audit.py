"""Audit and failed-command persistence for native ground-coordinate cleanup."""
import unittest

import test_game_scripts as game
import test_world_audit as world


class GroundPrecisionAuditTests(unittest.TestCase):
    def setUp(self):
        self.h = world.WorldAuditTests()
        self.h.setUp()
        self.lua = self.h.lua

    def test_cleaned_real_huge_polygon_matches_source_without_mutation(self):
        # A later polygon in the real failed dataset has two native-equal
        # corners but retains a valid triangle after cleanup.
        self.lua.execute("""
          api.engine.terrain.getBoundingBox=function()
            return {min={x=-10240,y=-10240},max={x=10240,y=10240}}
          end
          dataset.scenery[3].face={
            {-10240,-6345.658521868215},
            {-10240,-6345.658667418904},
            {-9910.946133241478,-6345.658667418904},
            {-9905.071491072375,-6338.634332405993}}
          world[200][api.type.ComponentType.CONSTRUCTION].params.items[3].face={
            {-10240,-6345.658521868215,10},
            {-9910.946133241478,-6345.658667418904,10},
            {-9905.071491072375,-6338.634332405993,10}}
        """)
        before = tuple(world.plain(self.lua.globals()[name])
                       for name in ("dataset", "value", "world"))
        report = self.h.inspect()
        self.assertTrue(report.ok, world.plain(report.problems))
        self.assertEqual(report.expected.surfaces, 1)
        self.assertEqual(report.current.surfaces, 1)
        self.assertEqual(before, tuple(world.plain(self.lua.globals()[name])
                                      for name in ("dataset", "value", "world")))
        self.assertEqual(self.lua.globals().commandCalls, 0)

    def test_clockwise_source_matches_normalized_accepted_face(self):
        self.lua.execute("dataset.scenery[3].face={{0,0},{0,10},{10,0}}")
        report = self.h.inspect()
        self.assertTrue(report.ok, world.plain(report.problems))
        self.assertEqual(self.lua.globals().commandCalls, 0)

    def test_recorded_omission_is_explicit_without_missing_or_counter_noise(self):
        self.lua.execute("""
          dataset.scenery[4]={texture="::/surface.gtex",category="surfaces",face={
            {-10240,8821.498023327178},
            {-10239.531158446041,8821.498332458224},
            {-10240,8821.498332458224}}}
          value.omittedScenery=1
          value.sceneryOmissions={[4]="Ground face collapses at TF3 coordinate precision"}
        """)
        report = self.h.inspect()
        self.assertFalse(report.ok)
        self.assertEqual(report.omittedScenery, 1)
        self.assertEqual(report.problemCounts.omittedGround, 1)
        self.assertIsNone(report.problemCounts.progress)
        self.assertIsNone(report.problemCounts.missingScenery)
        self.assertIsNone(report.problemCounts.wrongScenery)
        self.assertEqual(report.expected.scenery, 3)
        self.assertEqual(report.current.scenery, 3)
        self.assertEqual(self.lua.globals().commandCalls, 0)

    def test_collapsed_live_face_is_reported_as_wrong_and_missing_ground(self):
        self.lua.execute("""
          world[200][api.type.ComponentType.CONSTRUCTION].params.items[3].face={
            {-10240,8821.498023327178,10},
            {-10239.531158446041,8821.498332458224,10},
            {-10240,8821.498332458224,10}}
        """)
        report = self.h.inspect()
        self.assertFalse(report.ok)
        self.assertEqual(report.problemCounts.wrongScenery, 1)
        self.assertEqual(report.problemCounts.missingScenery, 1)
        self.assertEqual(self.lua.globals().commandCalls, 0)


class GroundPrecisionPreparationTests(unittest.TestCase):
    def test_command_preparation_failure_keeps_retry_safe_and_omission_unique(self):
        h = game.GameScriptTests()
        h.setUp()
        h.lua.execute("""
          api.engine.terrain.getBoundingBox=function()
            return {min={x=-10240,y=-10240},max={x=10240,y=10240}}
          end
          dataset.size={20480,20480}; dataset.edges={}; dataset.labels={}
          dataset.scenery={
            {category="surfaces",texture="::/terrain/ground/dirt.gtex",face={
              {-10240,8821.498023327178},
              {-10239.531158446041,8821.498332458224},
              {-10240,8821.498332458224}}},
            {category="vegetation",model="::/tree.mdl",pos={-10235,8820}}}
          local make=api.cmd.makeWorldBuildProposalCmd
          local fail=true
          api.cmd.makeWorldBuildProposalCmd=function(...)
            if fail then fail=false; error("native ground preparation failed") end
            return make(...)
          end
        """)
        h.event("start")
        h.step()
        self.assertEqual(h.state.value.phase, "error")
        self.assertEqual(h.state.value.errorKind, "preparation")
        self.assertEqual(h.state.value.cursor, 1)
        self.assertEqual(h.state.value.failedLast, 2)
        self.assertEqual(h.state.value.omittedScenery, 1)
        self.assertEqual(len(h.lua.globals().commands), 0)
        h.script = game.load_script(h.lua, game.CONTENT / "importer.script.lua")
        h.event("retry")
        h.finish()
        self.assertEqual(h.state.value.omittedScenery, 1)
        self.assertEqual(h.state.value.builtScenery, 1)
        self.assertEqual(len(h.lua.globals().commands), 1)
        self.assertEqual(h.state.value.sceneryRecords[1].modelPositions[2][1], -10235)


if __name__ == "__main__":
    unittest.main()

"""Native ground-fill precision regression from a 20,480 m import."""
import unittest
import test_game_scripts as game
from test_game_scripts import CONTENT, load_script


class GroundPrecisionTests(unittest.TestCase):
    def setUp(self):
        self.h = game.GameScriptTests(); self.h.setUp(); self.lua = self.h.lua
        self.controls = self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua']
        self.lua.execute('''
          api.engine.terrain.getBoundingBox=function() return {min={x=-10240,y=-10240},max={x=10240,y=10240}} end
          dataset.size={20480,20480};dataset.edges={};dataset.labels={}
          collapsed={category="surfaces",texture="::/terrain/ground/dirt.gtex",face={
            {-10240,8821.498023327178},{-10239.531158446041,8821.498332458224},{-10240,8821.498332458224}}}
          valid={category="surfaces",texture=collapsed.texture,face={{-10240,8820},{-10239,8820},{-10240,8821}}}
          tree={category="vegetation",model="::/tree.mdl",pos={-10235,8820}}
          dataset.scenery={valid,collapsed,tree}
        ''')

    def test_exact_huge_face_is_rejected_at_native_precision(self):
        face, reason = self.controls.groundFace(self.lua.globals().collapsed.face)
        self.assertIsNone(face); self.assertIn('precision', reason)

    def test_valid_thin_face_is_not_removed_by_a_blanket_area_cutoff(self):
        face = self.lua.eval('{{-10240,8821.498023327178},{-10239.5,8821.499332458224},{-10240,8821.499332458224}}')
        self.assertEqual(len(self.controls.groundFace(face)), 3)

    def test_duplicate_native_points_are_cleaned_without_mutating_source(self):
        face = self.lua.eval('{{-10240,8820},{-10239,8820},{-10239,8820.00001},{-10240,8821},{-10240,8820}}')
        self.assertEqual(len(self.controls.groundFace(face)), 3)
        self.assertEqual(len(face), 5)

    def test_only_unbuildable_face_omitted_model_journal_keeps_source_index(self):
        self.h.event('start'); self.h.finish()
        value = self.h.state.value
        self.assertEqual(value.builtScenery, 2); self.assertEqual(value.omittedScenery, 1)
        self.assertIsNotNone(value.sceneryOmissions[2]); self.assertEqual(value.skipped, 0)
        items = self.lua.globals().commands[1].constructionsToAdd[1].params['items']
        self.assertEqual(len(items), 2); self.assertEqual(items[2].sourceIndex, 3)
        self.assertEqual(value.sceneryRecords[1].modelPositions[3][1], -10235)
        self.assertEqual(len(self.lua.globals().dataset.scenery[2].face), 3)

    def test_rejected_batch_retry_does_not_count_omission_twice(self):
        self.lua.globals().failNext = True
        self.h.event('start'); self.h.step()
        self.assertEqual(self.h.state.value.omittedScenery, 1)
        self.h.script = load_script(self.lua, CONTENT/'importer.script.lua')
        self.h.event('retry'); self.h.finish()
        self.assertEqual(self.h.state.value.omittedScenery, 1)
        self.assertEqual(self.h.state.value.builtScenery, 2)

    def test_all_omitted_batch_advances_without_an_empty_native_command(self):
        self.lua.execute('dataset.scenery={collapsed};dataset.importOptions={stepLimit=1}')
        self.h.event('start'); self.h.finish()
        self.assertEqual(len(self.lua.globals().commands), 0)
        self.assertEqual(self.h.state.value.builtScenery, 0)
        self.assertEqual(self.h.state.value.omittedScenery, 1)

    def test_construction_has_a_final_precision_guard(self):
        script = load_script(self.lua, CONTENT/'scenery.script.lua')
        with self.assertRaisesRegex(Exception, 'collapses'):
            script.updateFn(None, self.lua.eval('{items={collapsed}}'))

    def test_snapshot_exposes_omission_separately_from_built_and_skipped(self):
        self.h.event('start'); self.h.finish()
        snapshot = self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']
        result = snapshot.fromState(self.h.state.value, self.lua.eval('api.engine.terrain.getBoundingBox()'))
        self.assertEqual(result.omittedScenery, 1); self.assertEqual(result.builtScenery, 2)
        self.assertEqual(result.skipped, 0)

    def test_legacy_save_recovery_keeps_prior_build_and_unlocks_retry_only_after_inventory(self):
        self.lua.execute('''dataset.scenery={valid,collapsed}
          api.engine.forEachEntityWithComponent=function(callback,kind)
            for id,comp in pairs(components) do if kind==4 and comp.fileName then callback(id) end end
          end''')
        self.h.event('configure', {'batchSize': 1}); self.h.event('start'); self.h.step()
        self.assertEqual(self.h.state.value.builtScenery, 1)
        self.lua.execute('''
          state.value.phase="error";state.value.resumePhase="scenery";state.value.cursor=2
          state.value.failedFirst=2;state.value.failedLast=2;state.value.errorKind="command_state"
          state.value.error='[string "content/osm/importer.script.lua"]:811: Unknown exception'
        ''')
        self.h.script=load_script(self.lua, CONTENT/'importer.script.lua')
        self.h.script.update(None,self.h.state,1)
        self.assertEqual(self.h.state.value.errorKind, 'preparation')
        self.assertEqual(len(self.lua.globals().commands), 1)
        self.assertEqual(self.h.state.value.cursor, 2)
        self.h.event('retry'); self.h.finish()
        self.assertEqual(len(self.lua.globals().commands), 1)
        self.assertEqual(self.h.state.value.builtScenery, 1)
        self.assertEqual(self.h.state.value.omittedScenery, 1)

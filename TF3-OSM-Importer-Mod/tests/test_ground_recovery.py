"""Revision 10 recovery requires proof that no failed ground batch exists."""
from pathlib import Path
from types import SimpleNamespace
import unittest

from lupa import LuaRuntime


CONTENT = Path(__file__).resolve().parents[1] / 'mod/tf3_osm_importer_mod/content/osm'


class GroundRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().controls = self.lua.execute((CONTENT/'controls.lua').read_text(encoding='utf-8'))
        self.lua.execute('''
          function ug_require(name)
            assert(name=="druttzen_osm_vanilla::/osm/controls.lua")
            return controls
          end
          local T={CONSTRUCTION=4}
          world={
            [200]={[T.CONSTRUCTION]={fileName="druttzen_osm_vanilla::/osm/scenery.con"}},
            [301]={[T.CONSTRUCTION]={fileName="::/vanilla.con"}},
            [400]={assetGroup=true}
          }
          reads=0; enumerations=0; commands=0
          api={type={ComponentType=T},engine={terrain={}},cmd={}}
          api.engine.terrain.getBoundingBox=function()
            return {min={x=-10240,y=-10240},max={x=10240,y=10240}}
          end
          api.engine.getComponent=function(entity,kind)
            reads=reads+1
            return assert(world[entity],"Unknown entity")[kind]
          end
          api.engine.forEachEntityWithComponent=function(callback,kind)
            assert(kind==T.CONSTRUCTION)
            enumerations=enumerations+1
            for entity,components in pairs(world) do
              if components[kind] then callback(entity) end
            end
          end
          api.cmd.makeWorldBuildProposalCmd=function() commands=commands+1; error("read only") end
          api.cmd.sendCommand=function() commands=commands+1; error("read only") end
          local clean={{0,0},{1,0},{0,1}}
          local collapsed={{10000,10000},{10000.0001,10000},{10000,10000.0001}}
          dataset={id="legacy-map",scenery={
            {texture="::/ground.gtex",face=clean},
            {texture="::/ground.gtex",face=clean},
            {texture="::/ground.gtex",face=collapsed},
            {texture="::/ground.gtex",face=clean}}}
          value={phase="error",resumePhase="scenery",errorKind="command_state",
            error='[string "F:/game/mod/content/osm/importer.script.lua"]:811: Unknown exception',
            datasetId=dataset.id,cursor=3,failedFirst=3,failedLast=4,
            builtScenery=2,options=controls.options(),sceneryRecords={
              {first=1,last=2,phase="scenery",entities={200}}}}
        ''')
        self.recovery = self.lua.execute((CONTENT/'ground_recovery.lua').read_text(encoding='utf-8'))

    def check(self):
        result = self.recovery.check(self.lua.globals().dataset, self.lua.globals().value)
        self.assertEqual(self.lua.globals().commands, 0)
        return result

    def assert_blocked(self, reason=None):
        allowed, message = self.check()
        self.assertFalse(allowed, message)
        if reason:
            self.assertIn(reason, message)

    def test_old_texture_failure_is_safe_with_known_prior_construction(self):
        allowed, message = self.check()
        self.assertTrue(allowed, message)
        self.assertEqual(self.lua.globals().enumerations, 1)
        self.assertEqual(self.lua.globals().value.phase, 'error')
        self.assertEqual(self.lua.globals().value.errorKind, 'command_state')
        self.assertEqual(self.lua.globals().value.cursor, 3)
        self.assertEqual(self.lua.globals().value.builtScenery, 2)

    def test_native_filename_prefix_may_vary_but_suffix_must_be_exact(self):
        for prefix in ('C:/Steam/content/osm/', '@mod/', ''):
            with self.subTest(prefix=prefix):
                self.lua.globals().value.error = '[string "'+prefix+'importer.script.lua"]:811: Unknown exception'
                self.assertTrue(self.check()[0])

    def test_saved_native_constructor_traceback_is_accepted(self):
        # Exact formatting from the failed save's 2026-10-25 stdout, including
        # the C++ frame and pcall frames stored after the error's first line.
        path = 'C:/Program Files (x86)/Steam/userdata/8131795/3493540/local/mods/tf3_osm_importer_mod/content/osm/importer.script.lua'
        error = ('[string "'+path+'"]:811: Unknown exception\n'
                 'stack traceback:\n'
                 '    =[C](-1): makeWorldBuildProposalCmd\n'
                 '    '+path+'(811): ?\n'
                 '    =[C](-1): pcall\n'
                 '    '+path+'(790): ?\n')
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                self.lua.globals().value.error = error.replace('\n', newline)
                self.assertTrue(self.check()[0])

    def test_traceback_first_frame_must_be_native_constructor(self):
        first = '[string "importer.script.lua"]:811: Unknown exception'
        for suffix in ('\nextra text', '\nstack traceback:\n    =[C](-1): sendCommand\n',
                       '\nstack traceback:\n    =[C](-1): pcall\n    =[C](-1): makeWorldBuildProposalCmd\n',
                       '\nstack traceback:\n    =[C](-1): makeWorldBuildProposalCmdOther\n'):
            with self.subTest(suffix=suffix):
                self.lua.globals().value.error = first+suffix
                self.assert_blocked('not the revision 10')

    def test_any_unknown_importer_construction_blocks_even_if_renamed(self):
        self.lua.execute('''
          world[500]={[api.type.ComponentType.CONSTRUCTION]={
            fileName="druttzen_osm_vanilla::/osm/scenery.con",name="Other dataset or renamed batch"}}
        ''')
        self.assert_blocked('outside the accepted-object journal')

    def test_prior_accepted_range_cannot_overlap_failed_cursor(self):
        self.lua.execute('value.sceneryRecords[1].last=value.cursor')
        self.assert_blocked('overlaps')

    def test_unrelated_or_new_errors_are_not_reclassified(self):
        for error in ('[string "importer.script.lua"]:812: Unknown exception',
                      '[string "importer.script.lua"]:811: sendCommand failed',
                      '[string "other.script.lua"]:811: Unknown exception',
                      '[string "importer.script.lua"]:811: Unknown exception extra'):
            with self.subTest(error=error):
                self.lua.globals().value.error = error
                self.assert_blocked('not the revision 10')

    def test_model_candidate_blocks_even_with_a_collapsed_texture(self):
        self.lua.execute('dataset.scenery[4]={category="vegetation",model="::/tree.mdl",pos={4,4}}')
        self.assert_blocked('only ground textures')

    def test_unselected_model_does_not_count_as_candidate(self):
        self.lua.execute('''
          dataset.scenery[4]={category="vegetation",model="::/tree.mdl",pos={4,4}}
          value.options.vegetation=false
        ''')
        self.assertTrue(self.check()[0])

    def test_no_collapsed_face_cannot_prove_this_failure(self):
        self.lua.execute('dataset.scenery[3].face={{2,2},{3,2},{2,3}}')
        self.assert_blocked('No collapsed ground face')

    def test_missing_or_throwing_enumeration_is_blocked(self):
        self.lua.execute('api.engine.forEachEntityWithComponent=nil')
        self.assert_blocked('cannot be checked')
        self.lua.execute('api.engine.forEachEntityWithComponent=function() error("unavailable") end')
        self.assert_blocked('check failed')

    def test_userdata_api_namespace_can_enumerate_constructions(self):
        api = self.lua.globals().api
        self.lua.globals().api = SimpleNamespace(engine=api.engine, type=api.type, cmd=api.cmd)
        self.assertEqual(self.lua.eval('type(api)'), 'userdata')
        self.assertTrue(self.check()[0])

    def test_userdata_namespaces_and_callables_are_invoked(self):
        api = self.lua.globals().api
        bounds = api.engine.terrain.getBoundingBox
        component = api.engine.getComponent
        enumerate_entities = api.engine.forEachEntityWithComponent
        engine = SimpleNamespace(
            terrain=SimpleNamespace(getBoundingBox=lambda: bounds()),
            getComponent=lambda entity, kind: component(entity, kind),
            forEachEntityWithComponent=lambda callback, kind: enumerate_entities(callback, kind),
        )
        self.lua.globals().api = SimpleNamespace(engine=engine, type=api.type, cmd=api.cmd)
        self.assertEqual(self.lua.eval('type(api.engine)'), 'userdata')
        self.assertEqual(self.lua.eval('type(api.engine.forEachEntityWithComponent)'), 'userdata')
        self.assertTrue(self.check()[0])

    def test_incomplete_or_throwing_component_reads_are_blocked(self):
        self.lua.execute('api.engine.getComponent=function() return nil end')
        self.assert_blocked('inventory is incomplete')
        self.lua.execute('api.engine.getComponent=function() error("unavailable") end')
        self.assert_blocked('check failed')

    def test_pending_or_unjournalled_acceptance_blocks(self):
        keys = ('pendingOwnership', 'pendingScenery', 'pendingTown', 'pendingHeightNodes',
                'pendingAccepted', 'acceptedUnjournalled')
        for key in keys:
            with self.subTest(key=key):
                self.lua.globals().value[key] = True
                self.assert_blocked('accepted object')
                self.lua.globals().value[key] = None

    def test_original_dataset_and_exact_failed_range_are_required(self):
        self.lua.execute('value.datasetId="different-map"')
        self.assert_blocked('original dataset')
        self.lua.execute('value.datasetId=dataset.id; value.failedFirst=2')
        self.assert_blocked('source range')
        self.lua.execute('value.failedFirst=value.cursor; value.failedLast=5')
        self.assert_blocked('source range')

    def test_malformed_journal_fails_closed(self):
        self.lua.execute('value.sceneryRecords[1].entities={200,200}')
        self.assert_blocked('journal is invalid')


if __name__ == '__main__':
    unittest.main()

"""Loaded resource matching, fitted geometry and importer persistence boundaries."""
import unittest
from lupa import LuaRuntime
import test_game_scripts as _game
import test_panel as _panel
CONTENT=_game.CONTENT


MODELS=r'''
modelNames={[0]="::/assets/bench.mdl",[1]="custom::/assets/bench.mdl",
 [2]="custom::/assets/water_tower.mdl",[3]="::/buildings/c/r1/1x1/a.mdl",
 [4]="::/buildings/c/r1/2x2/b.mdl",[5]="::/vehicle/water_tower.mdl"}
modelData={}
for id,name in pairs(modelNames) do
 modelData[id]={metadata={},boundingInfo={bbMin={-1,-2,0},bbMax={1,2,4}}}
end
modelData[3].boundingInfo={bbMin={-3,0,0},bbMax={3,8,9}}
modelData[4].boundingInfo={bbMin={-10,-10,0},bbMax={10,10,12}}
modelData[5].metadata.transportVehicle={}
api.res.modelRep={getAll=function(includeInvisible) assert(includeInvisible); return modelNames end,
 get=function(id) return assert(modelData[id]) end,
 find=function(name) for id,n in pairs(modelNames) do if n==name then return id end end return -1 end}
'''


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('api={res={}}')
        self.lua.execute(MODELS)
        self.matcher=self.lua.execute((CONTENT/'object_matcher.lua').read_text(encoding='utf8'))

    def match(self,source,mods=True):
        return self.matcher.resolve(self.lua.eval(source),self.lua.table_from({'useActiveMods':mods}))

    def test_vanilla_first_including_zero_repository_id(self):
        result=self.match('{match={kind="bench"},pos={0,0}}')
        self.assertEqual(result.model,'::/assets/bench.mdl')
        self.assertEqual(result.origin,'vanilla')

    def test_native_callable_userdata_can_enumerate_models(self):
        self.lua.globals().nativeEnumeration = lambda invisible: self.lua.globals().modelNames
        self.lua.execute('api.res.modelRep.getAll=nativeEnumeration; assert(type(api.res.modelRep.getAll)=="userdata")')
        result=self.match('{match={kind="bench"},pos={0,0}}')
        self.assertEqual(result.model,'::/assets/bench.mdl')
        self.assertEqual(result.origin,'vanilla')

    def test_missing_enumeration_uses_only_verified_curated_vanilla_models(self):
        self.lua.execute('''
          api.res.modelRep.getAll=nil
          modelNames[9]="::/assets/stations/street/bench_era_c_rep_1.mdl"
          modelData[9]=modelData[0]
        ''')
        result=self.match('{match={kind="bench"},pos={0,0}}')
        self.assertEqual(result.model,'::/assets/stations/street/bench_era_c_rep_1.mdl')
        self.assertEqual(result.origin,'vanilla')
        unknown=self.match('{match={kind="water_tower"},pos={0,0}}')
        self.assertTrue(unknown.unmatched)
        self.assertIn('enumeration is unavailable',unknown.reason)
        self.assertEqual(self.match('{match={kind="water_tower"},pos={0,0}}').reason,unknown.reason)

    def test_unusable_enumeration_does_not_poison_the_catalog_or_select_vehicles(self):
        for expression in ('function() error("API unavailable") end','function() return false end'):
            with self.subTest(expression=expression):
                self.lua.execute('api.res.modelRep.getAll='+expression)
                self.matcher=self.lua.execute((CONTENT/'object_matcher.lua').read_text(encoding='utf8'))
                first=self.match('{match={kind="water_tower"},pos={0,0}}')
                second=self.match('{match={kind="water_tower"},pos={0,0}}')
                self.assertTrue(first.unmatched)
                self.assertEqual(first.reason,second.reason)
                self.assertIn('only known vanilla',first.reason)

    def test_active_mod_fallback_can_be_disabled_and_vehicle_is_excluded(self):
        result=self.match('{match={kind="water_tower"},pos={0,0}}')
        self.assertEqual(result.model,'custom::/assets/water_tower.mdl')
        self.assertEqual(result.origin,'active mod')
        self.assertTrue(self.match('{match={kind="water_tower"},pos={0,0}}',False).unmatched)

    def test_inactive_mod_is_not_discovered_from_a_folder_or_dataset_hint(self):
        result=self.match('{match={kind="bicycle_parking"},pos={0,0},model="inactive::/bike_rack.mdl"}')
        self.assertTrue(result.unmatched)

    def test_building_fits_footprint_without_scaling_and_centres_native_origin(self):
        result=self.match('{match={kind="residential"},pos={0,0},rotation=0,dimensions={8,10},footprint={{-4,-5},{4,-5},{4,5},{-4,5}}}')
        self.assertEqual(result.model, '::/buildings/c/r1/1x1/a.mdl')
        self.assertEqual(result.pos[2],-4)
        self.assertIsNone(result.scale)

    def test_no_fitting_building_is_left_unbuilt(self):
        self.assertTrue(self.match('{match={kind="residential"},pos={0,0},dimensions={1,1},footprint={{-0.5,-0.5},{0.5,-0.5},{0.5,0.5},{-0.5,0.5}}}').unmatched)

    def test_corners_inside_cannot_bridge_a_concave_notch(self):
        self.assertTrue(self.match('{match={kind="residential"},pos={0,0},dimensions={8,10},footprint={{-4,-5},{4,-5},{4,5},{1,5},{1,0},{-1,0},{-1,5},{-4,5}}}').unmatched)

    def test_explicit_configured_vanilla_object_has_priority_over_filename_matching(self):
        result=self.match('{match={kind="water_tower"},model="::/assets/bench.mdl",pos={12,13},rotation=0.2}')
        self.assertEqual(result.model,'::/assets/bench.mdl')
        self.assertEqual((result.pos[1],result.pos[2]),(12,13))
        self.assertEqual(result.rotation,0.2)

    def test_semantic_matching_requires_complete_token(self):
        self.lua.execute('modelNames={[1]="custom::/assets/benchpress.mdl"}; modelData[1].metadata={} ')
        self.assertTrue(self.match('{match={kind="bench"},pos={0,0}}').unmatched)

    def test_compaction_keeps_fitted_changed_and_unmatched_decisions(self):
        self.lua.globals().matcher = self.matcher
        self.lua.execute('''
          source={match={kind="bench"},model="::/assets/bench.mdl",pos={12,13},rotation=0.2}
          scenery={source,source,source,source}
          matches={}
          for i=1,3 do matches[i]=matcher.resolve(source,{useActiveMods=true}) end
          matches[2].pos[1]=12.5
          matches[3].rotation=0.4
          matches[4]={unmatched=true,kind="bicycle_parking",reason="No safe model"}
          count,examples,catalog=matcher.compact(matches,scenery)
        ''')
        g = self.lua.globals()
        self.assertEqual(g.count, 1)
        self.assertIsNone(g.matches[1])
        self.assertEqual(self.matcher.unpack(g.matches[2], g.catalog).pos[1], 12.5)
        self.assertEqual(self.matcher.unpack(g.matches[3], g.catalog).rotation, 0.4)
        self.assertTrue(self.matcher.unpack(g.matches[4], g.catalog).unmatched)
        summary = self.matcher.summary(g.matches, g.count, g.examples, g.catalog)
        self.assertEqual(summary.vanilla, 3)
        self.assertEqual(summary.unmatched, 1)
        self.assertEqual(len(summary.examples), 2)

    def test_pooled_origins_are_lossless_and_repeated_unmatched_reasons_are_shared(self):
        self.lua.globals().matcher=self.matcher
        self.lua.execute('''
          catalog={}; matches={}
          for i=1,10000 do matches[i]=matcher.pack({unmatched=true,kind="bicycle_parking",reason="No safe model"},catalog) end
          fitted={model="::/assets/bench.mdl",kind="bench",origin="vanilla",method="class and footprint fit (no scaling)",
            pos={8123.456789012345,-7890.123456789012},rotation=1.234567890123456}
          matches[10001]=matcher.pack(fitted,catalog)
          fitted2={model=fitted.model,kind=fitted.kind,origin=fitted.origin,method=fitted.method,
            pos={-8123.456789012345,7890.123456789012},rotation=-1.234567890123456}
          matches[10002]=matcher.pack(fitted2,catalog)
        ''')
        g=self.lua.globals()
        self.assertEqual(len(g.catalog), 2)
        self.assertEqual(g.matches[1], g.matches[10000])
        for index,source in ((10001,g.fitted),(10002,g.fitted2)):
            result=self.matcher.unpack(g.matches[index],g.catalog)
            self.assertEqual((result.pos[1],result.pos[2],result.rotation),
                             (source.pos[1],source.pos[2],source.rotation))
        summary=self.matcher.summary(g.matches,0,None,g.catalog)
        self.assertEqual((summary.vanilla,summary.unmatched),(2,10000))

    def test_missing_catalog_never_falls_back_to_a_source_model(self):
        controls=self.lua.execute((CONTENT/'controls.lua').read_text())
        item=self.lua.eval('{model="::/assets/bench.mdl",match={kind="bench"},pos={0,0}}')
        value=self.lua.eval('{matches={[1]=1},matchCatalog={{unmatched=true,kind="bench",reason="Not approved"}}}')
        self.assertIsNone(controls.resolvedItem(item,1,value))
        value.matchCatalog=None
        with self.assertRaisesRegex(Exception,'Missing saved match catalog'):
            controls.resolvedItem(item,1,value)

    def test_legacy_compact_arrays_upgrade_to_lossless_strings_in_both_readers(self):
        controls=self.lua.execute((CONTENT/'controls.lua').read_text())
        catalog=self.lua.eval('{{model="::/assets/bench.mdl",kind="bench",origin="vanilla",method="semantic class"}}')
        legacy=self.lua.eval('{1,8123.456789012345,-7890.123456789012,-0.0,10.000000000000002}')
        packed=self.matcher.pack(legacy,catalog)
        self.assertIsInstance(packed,str)
        decoded=self.matcher.unpack(packed,catalog)
        value=self.lua.table_from({'matches':self.lua.table_from({1:packed}),'matchCatalog':catalog})
        item=self.lua.eval('{match={kind="bench"},pos={0,0}}')
        resolved=controls.resolvedItem(item,1,value)
        for actual in (decoded,resolved):
            self.assertEqual((actual.pos[1],actual.pos[2],actual.pos[3]),(legacy[2],legacy[3],legacy[5]))
            self.assertEqual(actual.rotation,legacy[4])
            self.assertEqual(self.lua.eval('function(v) return 1/v end')(actual.rotation),float('-inf'))

    def test_invalid_string_match_never_becomes_a_buildable_source_fallback(self):
        controls=self.lua.execute((CONTENT/'controls.lua').read_text())
        item=self.lua.eval('{match={kind="bench"},model="::/assets/bench.mdl",pos={0,0}}')
        catalog=self.lua.eval('{{model="::/assets/bench.mdl",kind="bench",origin="vanilla"}}')
        for packed in ('1|nan|0|0','1|0|inf|0','1|0|0','100|0|0|0','1|0|0|0|invalid'):
            with self.subTest(packed=packed):
                value=self.lua.table_from({'matches':self.lua.table_from({1:packed}),'matchCatalog':catalog})
                with self.assertRaises(Exception): self.matcher.unpack(packed,catalog)
                with self.assertRaises(Exception): controls.resolvedItem(item,1,value)


class MatchedImportTests(unittest.TestCase):
    event=_game.GameScriptTests.event
    step=_game.GameScriptTests.step
    finish=_game.GameScriptTests.finish
    # Do not duplicate inherited tests: these fixtures use a small mapped dataset.
    def setUp(self):
        _game.GameScriptTests.setUp(self)
        self.lua.execute(MODELS)
        self.lua.execute('dataset.edges={}; dataset.labels={}; dataset.scenery={{category="mappedObjects",match={kind="bench"},pos={20,30},rotation=0}}')

    def test_unchanged_configured_objects_do_not_duplicate_source_in_saved_matches(self):
        self.lua.execute('''
          dataset.scenery={}
          for i=1,2000 do dataset.scenery[i]={category="mappedObjects",match={kind="bench"},
            model="::/assets/bench.mdl",pos={i/10,30},rotation=0.2} end
        ''')
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.phase, 'finished', self.state.value.error)
        self.assertEqual(self.state.value.builtScenery, 2000)
        self.assertEqual(self.state.value.matchSummary.vanilla, 2000)
        self.assertEqual(len(self.state.value.matches), 0)
        self.assertEqual(len(self.state.value.matchSummary.examples), 1)
        item = self.lua.globals().commands[1].constructionsToAdd[1].params['items'][1]
        self.assertEqual(item.model, '::/assets/bench.mdl')
        self.assertEqual((item.pos[1],item.pos[2],item.rotation), (0.1,30,0.2))

    def test_existing_save_compaction_preserves_summary_progress_and_live_transforms(self):
        self.lua.execute('dataset.scenery[1].model="::/assets/bench.mdl"')
        self.event('start'); self.event('pause')
        # Simulate the equivalent full match stored by revision 11/early 12.
        self.lua.execute('''
          state.value.matches[1]={model="::/assets/bench.mdl",pos={20,30},rotation=0,
            origin="vanilla",kind="bench",method="configured vanilla substitution"}
          state.value.matchStorageRevision=nil
        ''')
        saved_cursor = self.state.value.cursor
        self.script = _game.load_script(self.lua, CONTENT/'importer.script.lua')
        self.script.update(None, self.state, 1)
        self.assertIsNone(self.state.value.matches[1])
        self.assertEqual(self.state.value.matchSummary.vanilla, 1)
        self.assertEqual(self.state.value.cursor, saved_cursor)
        self.assertEqual(self.state.value.phase, 'paused')
        self.event('resume'); self.finish()
        self.assertEqual(self.state.value.builtScenery, 1)
        self.assertEqual(_game.model_positions(self.lua,self.state.value.sceneryRecords[1])[1][1], 20)

    def test_legacy_partial_check_keeps_catalog_and_summary_after_reload(self):
        self.lua.execute('''
          dataset.scenery={}
          for i=1,2001 do dataset.scenery[i]={category="mappedObjects",match={kind="bench"},pos={i/10,30},rotation=0.2} end
        ''')
        self.event('start'); self.step()
        self.assertEqual(self.state.value.phase, 'checking')
        self.assertGreater(self.state.value.check.checked, 0)
        # Older saves stored full fitted matches, including during a check.
        self.lua.execute('''
          local matcher=modules["druttzen_osm_vanilla::/osm/object_matcher.lua"]
          local job=state.value.check
          for index,entry in pairs(job.matches) do job.matches[index]=matcher.unpack(entry,job.matchCatalog) end
          job.matchCatalog=nil; state.value.matchStorageRevision=nil
        ''')
        self.script=_game.load_script(self.lua,CONTENT/'importer.script.lua')
        self.script.update(None,self.state,1)
        self.finish()
        self.assertEqual(self.state.value.phase, 'finished', self.state.value.error)
        self.assertEqual(self.state.value.matchSummary.vanilla, 2001)
        self.assertEqual(self.state.value.builtScenery, 2001)
        self.assertEqual(len(self.state.value.matchCatalog), 1)
        self.assertEqual(_game.model_positions(self.lua,self.state.value.sceneryRecords[1])[1][1], 0.1)

    def test_matched_model_is_journalled_with_actual_xyz_and_reused_after_reload(self):
        self.event('validate')
        self.assertEqual(len(self.lua.globals().commands),0)
        self.assertEqual(self.state.value.matchSummary.vanilla,1)
        self.event('start'); self.lua.globals().failOwnershipNext=True; self.step()
        self.assertEqual(self.state.value.phase,'error')
        record=self.state.value.sceneryRecords[1]
        self.assertEqual(_game.model_positions(self.lua,record)[1][3],10)
        from test_game_scripts import load_script
        self.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.event('retry'); self.finish()
        self.assertEqual(len(self.lua.globals().commands),1)
        self.assertEqual(self.state.value.builtScenery,1)

    def test_foreign_dataset_check_cannot_replace_saved_matches_after_restore(self):
        original_id=self.lua.globals().dataset.id
        self.event('start'); self.event('pause')
        original=self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua'].resolvedItem(self.lua.globals().dataset.scenery[1],1,self.state.value).model
        self.lua.execute('dataset.id="foreign"; dataset.scenery[1].match.kind="water_tower"')
        self.event('validate')
        self.assertIn('restore the original dataset',self.state.value.notice)
        self.assertEqual(self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua'].resolvedItem(self.lua.globals().dataset.scenery[1],1,self.state.value).model,original)
        self.assertEqual(self.state.value.phase,'paused')
        self.lua.globals().dataset.id=original_id
        self.lua.execute('dataset.scenery[1].match.kind="bench"')
        self.event('resume'); self.finish()
        built=self.lua.globals().commands[1].constructionsToAdd[1].params['items'][1]
        self.assertEqual(built.model,original)
        self.assertEqual(self.state.value.builtScenery,1)

    def test_no_match_is_counted_and_never_submitted(self):
        self.lua.execute('dataset.scenery[1].match.kind="bicycle_parking"')
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.matchSummary.unmatched,1)
        self.assertEqual(self.state.value.builtScenery,0)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_object_subtype_can_be_excluded_before_matching_without_changing_other_types(self):
        self.lua.execute('dataset.scenery[2]={category="mappedObjects",match={kind="water_tower"},pos={100,100}}')
        self.event('configure',{'object_bench':False})
        self.event('start'); self.finish()
        self.assertEqual(self.state.value.matchSummary.vanilla,0)
        self.assertEqual(self.state.value.matchSummary.mods,1)
        self.assertEqual(self.state.value.builtScenery,1)


class SelectionPanelTests(unittest.TestCase):
    setUp=_panel.PanelTests.setUp
    node=_panel.PanelTests.node
    tree=_panel.PanelTests.tree
    def test_new_checkboxes_send_boolean_settings_and_lock_after_start(self):
        from test_towns import TOWN_MOCK
        self.lua.execute(TOWN_MOCK)
        for key in ('mappedObjects','buildings','towns','useActiveMods','townRoadGrowth'):
            checkbox=self.node('option-'+key)
            checkbox.params.onValueChange(1)
            self.assertTrue(self.lua.globals().state.value.options[key])
        self.node('command-start').params.onClick()
        for key in ('mappedObjects','buildings','towns','useActiveMods','townRoadGrowth'):
            self.assertFalse(self.node('option-'+key).params.meta.enabled)

    def test_counts_and_matching_preview_precede_start_and_show_town_growth_limit(self):
        self.assertIn('(',self.node('option-roads').params.label)
        self.lua.execute('state.value.builtTowns=1')
        self.assertTrue(self.node('command-placeNames').params.meta.enabled)

    def test_only_present_object_subtypes_get_checkboxes_and_values_are_saved(self):
        checkbox=self.node('option-object_fountain')
        self.assertIn('(1)',checkbox.params.label)
        checkbox.params.onValueChange(0)
        self.assertFalse(self.lua.globals().state.value.options.object_fountain)
        self.assertIsNone(self.lua.globals().findNode(self.tree(),'druttzen-osm-option-object_water_tower'))


if __name__=='__main__': unittest.main()

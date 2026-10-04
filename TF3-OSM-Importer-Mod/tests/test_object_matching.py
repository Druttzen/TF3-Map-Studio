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


class MatchedImportTests(unittest.TestCase):
    event=_game.GameScriptTests.event
    step=_game.GameScriptTests.step
    finish=_game.GameScriptTests.finish
    # Do not duplicate inherited tests: these fixtures use a small mapped dataset.
    def setUp(self):
        _game.GameScriptTests.setUp(self)
        self.lua.execute(MODELS)
        self.lua.execute('dataset.edges={}; dataset.labels={}; dataset.scenery={{category="mappedObjects",match={kind="bench"},pos={20,30},rotation=0}}')

    def test_matched_model_is_journalled_with_actual_xyz_and_reused_after_reload(self):
        self.event('validate')
        self.assertEqual(len(self.lua.globals().commands),0)
        self.assertEqual(self.state.value.matchSummary.vanilla,1)
        self.event('start'); self.lua.globals().failOwnershipNext=True; self.step()
        self.assertEqual(self.state.value.phase,'error')
        record=self.state.value.sceneryRecords[1]
        self.assertEqual(record.modelPositions[1][3],10)
        from test_game_scripts import load_script
        self.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.event('retry'); self.finish()
        self.assertEqual(len(self.lua.globals().commands),1)
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

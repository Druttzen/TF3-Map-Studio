"""Native resource-based map choice, original-file restoration and compact UI state."""
import unittest
from lupa import LuaError
import test_game_scripts as game
import test_panel as panel
from test_game_scripts import CONTENT, load_script

SOURCE='osm/maps/fictional.lua'
RESOURCE='druttzen_osm_vanilla::/'+SOURCE

class MapSelectionTests(unittest.TestCase):
    def setUp(self):
        self.h=game.GameScriptTests(); self.h.setUp()
        self.lua=self.h.lua
        self.maps=self.lua.globals().modules['druttzen_osm_vanilla::/osm/map_data.lua']
        self.lua.execute('''
          chosen={schema=1,id="second-fictional-map",size={800,800},nodes={},edges={},scenery={},labels={}}
          for i=1,700 do chosen.scenery[i]={category="objects",model="::/assets/test.mdl",pos={i%100,0}} end
        ''')
        self.lua.globals().modules[RESOURCE]=self.lua.globals().chosen

    def choose(self): self.h.event('mapSelect',{'resource':SOURCE})

    def test_choice_updates_engine_and_compact_snapshot_before_start(self):
        self.choose()
        value=self.h.state.value
        self.assertEqual(value.mapExpectedId,'second-fictional-map')
        self.assertEqual(value.datasetInfo.inventory.counts.objects,700)
        self.assertIsNone(value.datasetInfo.nodes)
        self.assertIsNone(value.datasetInfo.scenery)
        self.assertIsNone(value.datasetId)
        self.assertEqual(len(self.lua.globals().commands),0)
        helper=self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']
        snap=helper.fromState(value,self.lua.globals().api.engine.terrain.getBoundingBox())
        self.assertEqual(snap.datasetId,'second-fictional-map')
        self.assertEqual(snap.totals.scenery,700)
        self.h.event('start')
        self.assertEqual(value.datasetId,'second-fictional-map')

    def test_missing_or_invalid_file_never_replaces_previous_selection(self):
        before=self.h.state.value.datasetInfo.id
        self.h.event('mapSelect',{'resource':'osm/maps/missing.lua'})
        self.assertIn('restart TF3',self.h.state.value.notice)
        self.lua.globals().modules[RESOURCE]=self.lua.table()
        self.choose()
        self.assertIn('not a converted OSM',self.h.state.value.notice)
        self.assertEqual(self.h.state.value.datasetInfo.id,before)
        self.assertIsNone(self.h.state.value.mapSource)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_started_import_rejects_other_maps_and_default_without_losing_progress(self):
        self.h.event('start'); self.h.step(); self.h.event('pause')
        cursor=self.h.state.value.cursor
        self.choose()
        self.assertIn('another Lua map',self.h.state.value.notice)
        self.h.event('mapDefault')
        self.assertEqual(self.h.state.value.cursor,cursor)
        self.assertEqual(self.h.state.value.phase,'paused')
        self.assertEqual(self.h.state.value.datasetId,self.lua.globals().dataset.id)

    def test_reload_automatically_restores_original_map_without_gui_file_io(self):
        self.choose(); self.h.event('start'); self.h.step(); self.h.event('pause')
        cursor=self.h.state.value.cursor
        count=len(self.lua.globals().commands)
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        self.assertTrue(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.cursor,cursor)
        self.assertEqual(len(self.lua.globals().commands),count)
        self.h.event('resume'); self.h.step()
        self.assertGreater(len(self.lua.globals().commands),count)

    def test_separate_native_callback_instances_resolve_the_same_selected_resource(self):
        event_script=self.h.script
        update_script=load_script(self.lua,CONTENT/'importer.script.lua')
        build_script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.choose()
        update_script.update(None,self.h.state,1)
        self.assertTrue(self.h.state.value.mapReady)
        self.h.event('start')
        result=update_script.update(None,self.h.state,1)
        build_script.postUpdate(None,self.h.state,1,result)
        self.assertEqual(self.h.state.value.datasetId,'second-fictional-map')
        self.assertGreater(self.h.state.value.builtScenery,0)
        self.assertTrue(self.h.state.value.mapReady)

    def test_missing_source_blocks_builds_and_can_restore_same_resource(self):
        self.choose(); self.h.event('start'); self.h.step(); self.h.event('pause')
        cursor=self.h.state.value.cursor
        count=len(self.lua.globals().commands)
        original=self.lua.globals().chosen
        self.lua.globals().modules[RESOURCE]=None
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        self.assertFalse(self.h.state.value.mapReady)
        self.h.event('resume'); self.h.step()
        self.assertEqual(len(self.lua.globals().commands),count)
        self.lua.globals().modules[RESOURCE]=original
        self.choose()
        self.assertTrue(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.cursor,cursor)

    def test_changed_original_file_identity_is_rejected_on_reload(self):
        self.choose(); self.h.event('start'); self.h.event('pause')
        self.lua.globals().chosen.id='changed'
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        self.assertFalse(self.h.state.value.mapReady)
        self.assertIn('original selected Lua map has changed',self.h.state.value.notice)
        self.choose()
        self.assertFalse(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.datasetId,'second-fictional-map')

    def test_external_source_does_not_load_the_installed_default_on_reload(self):
        self.choose()
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/dataset.lua']=None
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        self.assertTrue(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.datasetInfo.id,'second-fictional-map')

    def test_legacy_installed_dataset_can_restore_original_file(self):
        original=self.lua.globals().dataset
        self.h.event('start'); self.h.event('pause')
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/dataset.lua']=self.lua.globals().chosen
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        helper=self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']
        self.assertFalse(helper.fromState(self.h.state.value,self.lua.globals().api.engine.terrain.getBoundingBox()).mapReady)
        self.lua.globals().modules[RESOURCE]=original
        self.choose()
        self.assertTrue(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.datasetId,original.id)

    def test_check_and_water_job_lock_map_selection(self):
        before=self.h.state.value.datasetInfo.id
        for field in ('check','waterJob'):
            self.h.state.value[field]=self.lua.table()
            self.choose()
            self.assertEqual(self.h.state.value.datasetInfo.id,before)
            self.h.state.value[field]=None

    def test_idle_updates_do_not_write_save_state(self):
        self.lua.execute('writes=0; local old=state.set; state.set=function(self,v) writes=writes+1; return old(self,v) end')
        for _ in range(600): self.h.step()
        self.assertEqual(self.lua.globals().writes,0)

    def test_path_normalization_and_library_only_restrictions(self):
        root='C:/fictional/local'
        valid='c:\\fictional\\local\\mods\\tf3_osm_importer_mod\\content\\osm\\maps\\å karta.lua'
        self.assertEqual(self.maps.resourcePath(valid,root),'osm/maps/å karta.lua')
        for path in ('C:/Elsewhere/map.lua',root+'/save_maps/map.lua',root+'/mods/tf3_osm_importer_mod/content/osm/maps/../map.lua'):
            with self.subTest(path=path),self.assertRaises(LuaError): self.maps.resourcePath(path,root)
        for resource in ('osm/controls.lua','osm/maps/../../controls.lua','osm/maps/map.sav','foreign::/osm/maps/a.lua'):
            with self.subTest(resource=resource),self.assertRaises(LuaError): self.maps.checkResource(resource)

class MapPanelTests(unittest.TestCase):
    def test_picker_sends_only_resource_name_and_locks_after_start(self):
        h=panel.PanelTests(); h.setUp()
        h.lua.globals().modules[RESOURCE]=h.lua.globals().dataset
        picker=h.node('map-choose')
        self.assertEqual(picker.kind,'NativeFileDialogButton')
        self.assertEqual(picker.params.filters[1][2],'lua')
        self.assertTrue(picker.params.meta.enabled)
        picker.params.onOpen(h.lua.table_from(['C:/fictional/local/mods/tf3_osm_importer_mod/content/'+SOURCE]))
        event=h.lua.globals().emitted[1]
        self.assertEqual(event.name,'osm.mapSelect')
        self.assertEqual(list(event.param.keys()),['resource'])
        self.assertEqual(event.param.resource,SOURCE)
        self.assertEqual(h.lua.globals().state.value.mapSource,SOURCE)
        h.node('command-start').params.onClick()
        self.assertFalse(h.node('map-choose').params.meta.enabled)

    def test_gui_snapshot_never_requires_full_dataset(self):
        h=panel.PanelTests(); h.setUp()
        h.lua.globals().modules['druttzen_osm_vanilla::/osm/dataset.lua']=None
        h.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']=h.lua.execute((CONTENT/'ui_snapshot.lua').read_text(encoding='utf-8'))
        helper=h.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']
        snap=helper.fromState(h.lua.globals().state.value,h.lua.globals().api.engine.terrain.getBoundingBox())
        self.assertEqual(snap.totals.edges,10)
        self.assertEqual(snap.totals.scenery,117)

if __name__=='__main__': unittest.main()

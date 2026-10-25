"""Real transfer/state contracts with separate simulated GUI and engine callbacks."""
import unittest
from lupa import LuaError
import test_game_scripts as game
import test_panel as panel
from test_game_scripts import CONTENT, load_script


class MapSelectionTests(unittest.TestCase):
    def setUp(self):
        self.h=game.GameScriptTests(); self.h.setUp()
        self.lua=self.h.lua
        self.maps=self.lua.globals().modules['druttzen_osm_vanilla::/osm/map_data.lua']
        self.lua.execute('''
          chosen={schema=1,id="second-fictional-map",size={800,800},nodes={},edges={},scenery={},labels={}}
          for i=1,700 do chosen.scenery[i]={category="objects",model="::/assets/test.mdl",pos={i%100,0}} end
        ''')

    def transfer(self, data=None, source='osm_maps/fictional.lua'):
        data=data or self.lua.globals().chosen
        header,counts=self.maps.header(data)
        token='test-transfer'
        self.h.event('mapBegin',{'source':source,'token':token,'header':header,'counts':counts})
        if self.h.state.value.mapTransfer is None:
            return
        seq=0
        for section in self.maps.sections.values():
            source_data=data[section]
            entries=list(source_data.items()) if source_data is not None else []
            for offset in range(0,len(entries),256):
                seq+=1
                items=self.lua.table_from([self.lua.table_from({'key':k,'value':v}) for k,v in entries[offset:offset+256]])
                self.h.event('mapChunk',{'token':token,'seq':seq,'section':section,'items':items})
        self.h.event('mapCommit',{'token':token,'seq':seq})

    def test_map_choice_updates_engine_and_compact_snapshot_before_start(self):
        self.transfer()
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

    def test_wrong_or_incomplete_file_never_replaces_previous_selection(self):
        before=self.h.state.value.datasetInfo.id
        header,counts=self.maps.header(self.lua.globals().chosen)
        self.h.event('mapBegin',{'source':'osm_maps/new.lua','token':'partial','header':header,'counts':counts})
        self.h.event('start')
        self.assertIsNone(self.h.state.value.datasetId)
        self.h.event('mapCommit',{'token':'partial','seq':0})
        self.assertEqual(self.h.state.value.datasetInfo.id,before)
        self.assertIsNone(self.h.state.value.mapSource)
        self.assertIn('Incomplete',self.h.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_started_import_rejects_other_maps_and_default_without_losing_progress(self):
        self.h.event('start'); self.h.step(); self.h.event('pause')
        cursor=self.h.state.value.cursor
        self.transfer()
        self.assertIn('another Lua map',self.h.state.value.notice)
        self.h.event('mapDefault')
        self.assertEqual(self.h.state.value.cursor,cursor)
        self.assertEqual(self.h.state.value.phase,'paused')
        self.assertEqual(self.h.state.value.datasetId,self.lua.globals().dataset.id)

    def test_script_reload_blocks_builds_until_original_map_is_restored(self):
        self.transfer(); self.h.event('start'); self.h.step(); self.h.event('pause')
        cursor=self.h.state.value.cursor
        count=len(self.lua.globals().commands)
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        self.assertFalse(self.h.state.value.mapReady)
        self.h.event('resume'); self.h.step()
        self.assertEqual(len(self.lua.globals().commands),count)
        self.transfer()
        self.assertTrue(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.cursor,cursor)
        self.h.event('resume'); self.h.step()
        self.assertGreater(len(self.lua.globals().commands),count)

    def test_missing_source_on_reload_does_not_load_default_dataset(self):
        self.transfer()
        self.lua.execute('modules["druttzen_osm_vanilla::/osm/dataset.lua"]=nil')
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.step()
        self.assertFalse(self.h.state.value.mapReady)
        self.assertEqual(self.h.state.value.datasetInfo.id,'second-fictional-map')

    def test_idle_updates_do_not_write_save_state(self):
        self.lua.execute('writes=0; local old=state.set; state.set=function(self,v) writes=writes+1; return old(self,v) end')
        for _ in range(600): self.h.step()
        self.assertEqual(self.lua.globals().writes,0)

    def test_path_normalization_and_external_or_traversal_rejection(self):
        self.assertEqual(self.maps.relativePath('c:\\Games\\Local\\osm_maps\\å karta.lua','C:/Games/Local'),'osm_maps/å karta.lua')
        for path in ('C:/Elsewhere/map.lua','C:/Games/Local-other/map.lua','C:/Games/Local/../map.lua','C:/Games/Local/osm/map.sav'):
            with self.subTest(path=path),self.assertRaises(LuaError):
                self.maps.relativePath(path,'C:/Games/Local')

    def test_duplicate_and_out_of_order_chunks_are_rejected(self):
        header,counts=self.maps.header(self.lua.globals().chosen)
        self.h.event('mapBegin',{'source':'osm_maps/map.lua','token':'job','header':header,'counts':counts})
        self.h.event('mapChunk',{'token':'job','seq':2,'section':'scenery','items':self.lua.table()})
        self.assertIsNone(self.h.state.value.mapTransfer)
        self.assertIsNone(self.h.state.value.mapSource)


class MapPanelTests(unittest.TestCase):
    def test_native_picker_is_first_and_locked_after_start(self):
        h=panel.PanelTests(); h.setUp()
        picker=h.node('map-choose')
        self.assertEqual(picker.kind,'NativeFileDialogButton')
        self.assertEqual(picker.params.filters[1][2],'lua')
        self.assertTrue(picker.params.meta.enabled)
        h.node('command-start').params.onClick()
        self.assertFalse(h.node('map-choose').params.meta.enabled)

    def test_gui_file_transfer_and_automatic_reload_use_acknowledged_chunks(self):
        h=panel.PanelTests(); h.setUp()
        h.lua.execute('''
          app.loadUserdata=function(directory,name)
            assert(directory=="osm_maps" and name=="test")
            return {schema=1,id="gui-fixture",size={500,500},nodes={},edges={},labels={},scenery={{model="::/a.mdl",pos={0,0}}}}
          end
        ''')
        h.node('map-choose').params.onOpen(h.lua.table_from(['C:/fictional/local/osm_maps/test.lua']))
        for _ in range(8): h.lua.globals().bridge.guiUpdate(None,h.lua.globals().state,None)
        self.assertEqual(h.lua.globals().state.value.mapExpectedId,'gui-fixture')
        self.assertTrue(h.lua.globals().state.value.mapReply.done)
        # A new engine module loses its private dataset, while GUI state needs no large payload.
        h.lua.globals().engineScript=load_script(h.lua,CONTENT/'importer.script.lua')
        h.lua.globals().engineScript.update(None,h.lua.globals().state,1)
        self.assertFalse(h.lua.globals().state.value.mapReady)
        for _ in range(8): h.lua.globals().bridge.guiUpdate(None,h.lua.globals().state,None)
        self.assertTrue(h.lua.globals().state.value.mapReady)
        self.assertEqual(h.lua.globals().state.value.datasetInfo.id,'gui-fixture')

if __name__=='__main__': unittest.main()

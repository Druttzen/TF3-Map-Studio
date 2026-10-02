"""Exercise the native panel's callbacks with TF3 recipe/API substitutes.

This verifies wiring and state rules, not native rendering.
"""
from pathlib import Path
import unittest
from lupa import LuaRuntime
from test_game_scripts import MOCK,load_script

CONTENT=Path(__file__).resolve().parents[1]/'mod/druttzen_osm_vanilla/content/osm'

UI_MOCK=r'''
recipes={}; emitted={}; added=0; removed=0; visible=false
local react={RegisterRecipe=function(name,fn) recipes[name]=fn; return fn end,
 RegisterPluginRecipe=function(extension,name,fn) assert(extension.id=="::MainModButtonAreaExtension"); recipes[name]=fn; return fn end}
local builtin={type={Orientation={Vertical=0,Horizontal=1},ScrollBarPolicy={AlwaysOff=0,AsNeeded=1}}}
for _,name in ipairs({"TextView","RichTextView","Window","Component","BoxLayout","ScrollArea","Button","CheckBox","ComboBox","ComboBoxItem"}) do
 local kind=name
 builtin[kind]=function(params) return {kind=kind,params=params} end
end
local windowApi={addSingletonWindow=function(_,_) added=added+1; visible=true end,
 removeAllWindows=function(_) removed=removed+1; visible=false end}
modules["::/gui/main/react.lua"]=react
modules["::/gui/main/builtin.lua"]=builtin
modules["::/gui/main/main_mod_button_area.tl"]={MainModButtonAreaExtension={id="::MainModButtonAreaExtension"}}
modules["::/gui/main/game_react_globals.tl"]={getDefaultWindowApi=function() return windowApi end}
modules["::/gui/main/engine_react_util.tl"]={useStepStateTimer=function(read,delay)
 assert(delay==0.25); local value=read(); return {old=function(_) return value end} end}
api.engine.terrain.getBoundingBox=function() return {min={x=-500,y=-500},max={x=500,y=500}} end
api.gui={byId={isVisible=function(id) assert(id=="druttzen-osm-import-panel"); return visible end},
 fireGuiScriptEvent=function(id,name,param)
  return bridge.guiHandleEvent(nil,state,nil,"panel",id,name,param)
 end}
api.cmd.makeScriptingSendEventCmd=function(src,id,name,param) return {src=src,id=id,name=name,param=param} end
local buildCommand=api.cmd.sendCommand
api.cmd.sendCommand=function(command,callback)
 if command.name then
  emitted[#emitted+1]=command
  engineScript.handleEvent(nil,state,command.src,command.id,command.name,command.param)
 else buildCommand(command,callback) end
end
function findNode(node,id)
 if type(node)~="table" then return end
 if node.params and node.params.meta and node.params.meta.id==id then return node end
 for _,value in pairs(node.params or {}) do
  if type(value)=="table" then
   if value.kind then local result=findNode(value,id); if result then return result end
   else for _,child in ipairs(value) do local result=findNode(child,id); if result then return result end end end
  end
 end
end
'''


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().dataset=self.lua.execute((CONTENT/'dataset.lua').read_text(encoding='utf-8'))
        self.lua.globals().modules=self.lua.table_from({
            'druttzen_osm_vanilla::/osm/dataset.lua':self.lua.globals().dataset,
            'druttzen_osm_vanilla::/osm/controls.lua':self.lua.execute((CONTENT/'controls.lua').read_text(encoding='utf-8')),
        })
        self.lua.execute(MOCK)
        self.lua.globals().engineScript=load_script(self.lua,CONTENT/'importer.script.lua')
        self.lua.globals().engineScript.update(None,self.lua.globals().state,1)
        self.lua.globals().bridge=load_script(self.lua,CONTENT/'ui_bridge.script.lua')
        self.lua.execute(UI_MOCK)
        self.panel=load_script(self.lua,CONTENT/'panel.script.lua')

    def tree(self): return self.panel.OsmImportPanel()

    def node(self,id,tree=None):
        result=self.lua.globals().findNode(tree if tree is not None else self.tree(),'druttzen-osm-'+id)
        self.assertIsNotNone(result,id)
        return result

    def test_mod_button_toggles_singleton_panel(self):
        button=self.panel.OsmImportButton()
        self.assertEqual(button.params.meta.id,'druttzen-osm-open')
        button.params.onClick()
        self.assertEqual(self.lua.globals().added,1)
        button.params.onClick()
        self.assertEqual(self.lua.globals().removed,1)
        button.params.onClick()
        self.assertEqual(self.lua.globals().added,2)

    def test_scroll_list_contains_all_commands_and_settings(self):
        tree=self.tree()
        self.assertEqual(tree.kind,'Window')
        self.assertEqual(self.node('scroll',tree).kind,'ScrollArea')
        for key in ['validate','start','pause','resume','retry','skip','status','mapSize']:
            self.assertEqual(self.node('command-'+key,tree).kind,'Button')
        for key in ['roads','railways','vegetation','surfaces','objects','places']:
            self.assertEqual(self.node('option-'+key,tree).kind,'CheckBox')
        self.assertEqual(self.node('batch',tree).kind,'ComboBox')
        self.assertEqual(self.node('delay',tree).kind,'ComboBox')

    def test_buttons_follow_import_state_and_send_correct_events(self):
        tree=self.tree()
        self.assertTrue(self.node('command-start',tree).params.meta.enabled)
        self.assertFalse(self.node('command-pause',tree).params.meta.enabled)
        self.assertFalse(self.node('command-resume',tree).params.meta.enabled)
        self.node('command-start',tree).params.onClick()
        event=self.lua.globals().emitted[1]
        self.assertEqual(event.id,'druttzen_osm_vanilla')
        self.assertEqual(event.name,'osm.start')
        tree=self.tree()
        self.assertFalse(self.node('command-start',tree).params.meta.enabled)
        self.assertTrue(self.node('command-pause',tree).params.meta.enabled)
        self.node('command-pause',tree).params.onClick()
        self.assertTrue(self.node('command-resume').params.meta.enabled)

    def test_checkboxes_and_choices_adjust_persisted_options(self):
        self.node('option-roads').params.onValueChange(0)
        self.assertFalse(self.lua.globals().state.value.options.roads)
        self.node('batch').params.onValueChange(25)
        self.node('delay').params.onValueChange(.5)
        options=self.lua.globals().state.value.options
        self.assertEqual(options.batchSize,25)
        self.assertEqual(options.interval,.5)
        self.node('command-start').params.onClick()
        self.assertFalse(self.node('option-roads').params.meta.enabled)
        self.assertEqual(self.node('batch').params.value,25)

    def test_nonpreset_settings_are_displayed(self):
        self.lua.globals().state.value.options.batchSize=17
        self.lua.globals().state.value.options.interval=.7
        batches=self.node('batch').params
        delays=self.node('delay').params
        self.assertTrue(any(item.params.value==17 for item in batches['items'].values()))
        self.assertTrue(any(item.params.value==.7 for item in delays['items'].values()))

    def test_error_controls_and_skip(self):
        self.node('command-start').params.onClick()
        self.lua.globals().failNext=True
        self.lua.globals().engineScript.postUpdate(None,self.lua.globals().state,1,None)
        tree=self.tree()
        self.assertTrue(self.node('command-retry',tree).params.meta.enabled)
        self.assertTrue(self.node('command-skip',tree).params.meta.enabled)
        self.node('command-skip',tree).params.onClick()
        self.assertEqual(self.lua.globals().state.value.skipped,1)

    def test_resource_manifest_and_game_script_bridge(self):
        resource=load_script(self.lua,CONTENT/'panel.res.lua')
        self.assertEqual(resource.type,'react-plugin ::MainModButtonAreaExtension')
        self.assertEqual(resource.data.filePath,'druttzen_osm_vanilla::/osm/panel.script@OsmImportButton')
        desc=load_script(self.lua,CONTENT/'importer.gs.lua')
        self.assertEqual(desc.guiHandleEventScript.fileName,'druttzen_osm_vanilla::/osm/ui_bridge.script@guiHandleEvent')

    def test_every_referenced_script_callback_uses_resource_entrypoint(self):
        desc=load_script(self.lua,CONTENT/'importer.gs.lua')
        scenery=load_script(self.lua,CONTENT/'scenery.con.lua')
        panel=load_script(self.lua,CONTENT/'panel.res.lua')
        paths=[item.fileName for item in desc.values()]+[scenery.updateScript.fileName,panel.data.filePath]
        for reference in paths:
            with self.subTest(reference=reference):
                filename,callback=reference.split('::/osm/',1)[1].split('@')
                script=load_script(self.lua,CONTENT/(filename+'.lua'))
                self.assertTrue(callable(script[callback]),reference)

    def test_resource_loader_does_not_accept_stale_global_data(self):
        from tempfile import TemporaryDirectory
        from lupa import LuaError
        self.lua.execute('data=function() return {} end')
        with TemporaryDirectory() as folder:
            path=Path(folder)/'broken.script.lua'
            path.write_text('local script={} -- no resource entry point\n',encoding='utf-8')
            with self.assertRaisesRegex(LuaError,'function data\\(\\) not defined'):
                load_script(self.lua,path)


if __name__=='__main__': unittest.main()

"""Exercise the native panel's callbacks with TF3 recipe/API substitutes.

This verifies recipe shape, wiring and state rules, not native rendering.
"""
from pathlib import Path
import unittest
from lupa import LuaRuntime
from test_game_scripts import MOCK,load_script

CONTENT=Path(__file__).resolve().parents[1]/'mod/druttzen_osm_vanilla/content/osm'

UI_MOCK=r'''
recipes={}; recipeContracts={}; emitted={}; added=0; removed=0; visible=false
renderDepth=0; scriptLookups=0; scriptReads=0
gameScriptAvailable=true; gameScriptComponentAvailable=true; gameScriptStateAvailable=true
local builtin={type={Orientation={Vertical=0,Horizontal=1},ScrollBarPolicy={AlwaysOff=0,AsNeeded=1}}}
local builtinKinds={}
for _,name in ipairs({"TextView","RichTextView","Window","Component","BoxLayout","ScrollArea","Button","CheckBox","ComboBox","ComboBoxItem"}) do
 local kind=name
 builtin[kind]=function(params) return {kind=kind,params=params} end
 builtinKinds[builtin[kind]]=kind
end
-- Native ordinary recipes must return a layout. A Window must instead be
-- registered as a wrapper so TF3 can identify it as a WindowContainer child.
local layouts={BoxLayout=true,FlowLayout=true,FloatingLayout=true,AbsoluteLayout=true}
local function register(name,fn,wrappedKind)
 local checked=function(...)
  renderDepth=renderDepth+1
  local ok,node=pcall(fn,...)
  renderDepth=renderDepth-1
  if not ok then error(node,0) end
  if wrappedKind then
   assert(node and node.kind==wrappedKind,"Wrapper recipe child must be "..wrappedKind..": "..name)
  else
   assert(node and layouts[node.kind],"Recipe child must be a layout: "..name)
  end
  return node
 end
 recipes[name]=checked
 recipeContracts[name]={wrappedKind=wrappedKind}
 return checked
end
local react={RegisterRecipe=function(name,fn) return register(name,fn) end,
 RegisterPluginRecipe=function(extension,name,fn)
  assert(extension.id=="::MainModButtonAreaExtension")
  return register(name,fn)
 end,
 RegisterWrapperRecipe=function(name,wrapped,fn)
  assert(builtinKinds[wrapped],"Unknown wrapped builtin")
  return register(name,fn,builtinKinds[wrapped])
 end}
local windowApi={addSingletonWindow=function(_,_) added=added+1; visible=true end,
 removeAllWindows=function(_) removed=removed+1; visible=false end}
modules["::/gui/main/react.lua"]=react
modules["::/gui/main/builtin.lua"]=builtin
modules["::/gui/main/main_mod_button_area.tl"]={MainModButtonAreaExtension={id="::MainModButtonAreaExtension"}}
modules["::/gui/main/game_react_globals.tl"]={getDefaultWindowApi=function() return windowApi end}
modules["::/gui/main/engine_react_util.tl"]={useStepStateTimer=function(read,delay)
 assert(delay==0.25); local value=read(); return {old=function(_) return value end} end}
api.engine.terrain.getBoundingBox=function() return {min={x=-500,y=-500},max={x=500,y=500}} end
api.type.ComponentType.GAME_SCRIPT=2
api.engine.system={gameScriptSystem={getEntityForGameScript=function(name)
 assert(name=="druttzen_osm_vanilla::/osm/importer.gs","Incorrect GameScript resource name")
 scriptLookups=scriptLookups+1
 if gameScriptAvailable then return 900 end
end}}
local engineGetComponent=api.engine.getComponent
api.engine.getComponent=function(id,kind)
 if id==900 then
  assert(kind==api.type.ComponentType.GAME_SCRIPT,"Incorrect GameScript component type")
  scriptReads=scriptReads+1
  if not gameScriptComponentAvailable then return nil end
  return {state=gameScriptStateAvailable and state.value or nil}
 end
 return engineGetComponent(id,kind)
end
api.gui={byId={isVisible=function(id) assert(id=="druttzen-osm-import-panel"); return visible end},
 fireGuiScriptEvent=function(id,name,param)
  assert(renderDepth==0,"API is currently restricted: fireGuiScriptEvent during recipe rendering")
  return bridge.guiHandleEvent(nil,state,nil,"panel",id,name,param)
 end}
api.cmd.makeScriptingSendEventCmd=function(src,id,name,param)
 assert(renderDepth==0,"API is currently restricted: command during recipe rendering")
 return {src=src,id=id,name=name,param=param}
end
local buildCommand=api.cmd.sendCommand
api.cmd.sendCommand=function(command,callback)
 assert(renderDepth==0,"API is currently restricted: command during recipe rendering")
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
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/world_audit.lua']=self.lua.execute(
            (CONTENT/'world_audit.lua').read_text(encoding='utf-8'))
        self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']=self.lua.execute(
            (CONTENT/'ui_snapshot.lua').read_text(encoding='utf-8'))
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
        tree=self.panel.OsmImportButton()
        self.assertEqual(tree.kind,'BoxLayout')
        button=self.node('open',tree)
        self.assertEqual(button.params.meta.id,'druttzen-osm-open')
        button.params.onClick()
        self.assertEqual(self.lua.globals().added,1)
        button.params.onClick()
        self.assertEqual(self.lua.globals().removed,1)
        button.params.onClick()
        self.assertEqual(self.lua.globals().added,2)

    def test_recipe_contract_rejects_component_roots(self):
        from lupa import LuaError
        for kind in ['Button','Component','Window']:
            with self.subTest(kind=kind), self.assertRaisesRegex(LuaError,'Recipe child must be a layout'):
                self.lua.execute('''
                    local kind=...
                    local react=modules["::/gui/main/react.lua"]
                    local builtin=modules["::/gui/main/builtin.lua"]
                    local extension=modules["::/gui/main/main_mod_button_area.tl"].MainModButtonAreaExtension
                    return react.RegisterPluginRecipe(extension,"InvalidRoot",function()
                        return builtin[kind]{ }
                    end)()
                ''',kind)

    def test_panel_is_registered_as_a_native_window_wrapper(self):
        contract=self.lua.globals().recipeContracts.OsmImportPanel
        self.assertEqual(contract.wrappedKind,'Window')
        tree=self.tree()
        self.assertEqual(tree.kind,'Window')
        self.assertEqual(tree.params.id,'druttzen-osm-import-panel')
        tree.params.onClose()
        self.assertEqual(self.lua.globals().removed,1)

    def test_waiting_panel_keeps_native_window_contract(self):
        for missing in ['gameScriptAvailable','gameScriptComponentAvailable','gameScriptStateAvailable']:
            with self.subTest(missing=missing):
                self.lua.globals()[missing]=False
                tree=self.tree()
                self.assertEqual(tree.kind,'Window')
                self.assertEqual(tree.params.id,'druttzen-osm-import-panel')
                self.assertTrue(tree.params.closable)
                self.assertIn('Waiting for the importer',tree.params.content.params.text)
                self.lua.globals()[missing]=True

    def test_panel_reads_persisted_component_with_restricted_render_api(self):
        self.tree()
        self.assertEqual(self.lua.globals().scriptLookups,1)
        self.assertEqual(self.lua.globals().scriptReads,1)
        self.assertEqual(len(self.lua.globals().emitted),0)
        self.assertEqual(len(self.lua.globals().commands),0)
        self.node('command-start').params.onClick()
        self.assertTrue(self.node('command-pause').params.meta.enabled)

    def test_render_contract_rejects_gui_script_events(self):
        from lupa import LuaError
        with self.assertRaisesRegex(LuaError,'API is currently restricted'):
            self.lua.execute('''
                local react=modules["::/gui/main/react.lua"]
                return react.RegisterRecipe("InvalidEventRead",function()
                    return api.gui.fireGuiScriptEvent("druttzen_osm_vanilla","osm.ui.snapshot",{})
                end)()
            ''')

    def test_snapshot_preserves_progress_and_does_not_modify_options(self):
        self.lua.execute('''
            state.value.phase="paused"; state.value.datasetId=dataset.id
            state.value.builtEdges=3; state.value.builtScenery=7; state.value.labels=2
            state.value.skipped=1; state.value.error="Rejected proposal"
            state.value.notice="Import paused"; state.value.options.roads=false
        ''')
        helper=self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']
        box=self.lua.globals().api.engine.terrain.getBoundingBox()
        snapshot=helper.fromState(self.lua.globals().state.value,box)
        self.assertEqual(snapshot.phase,'paused')
        self.assertTrue(snapshot.started)
        self.assertEqual((snapshot.builtEdges,snapshot.builtScenery,snapshot.labels,snapshot.skipped),(3,7,2,1))
        self.assertEqual(snapshot.error,'Rejected proposal')
        self.assertEqual(snapshot.notice,'Import paused')
        self.assertEqual((snapshot.mapWidth,snapshot.mapHeight),(1000,1000))
        snapshot.options.roads=True
        self.assertFalse(self.lua.globals().state.value.options.roads)

    def test_scroll_list_contains_all_commands_and_settings(self):
        tree=self.tree()
        self.assertEqual(tree.kind,'Window')
        self.assertEqual(self.node('scroll',tree).kind,'ScrollArea')
        for key in ['validate','start','pause','resume','retry','skip','status','verify','placeNames','mapSize']:
            self.assertEqual(self.node('command-'+key,tree).kind,'Button')
        for key in ['roads','railways','vegetation','surfaces','objects','places']:
            self.assertEqual(self.node('option-'+key,tree).kind,'CheckBox')
        self.assertEqual(self.node('batch',tree).kind,'ComboBox')
        self.assertEqual(self.node('delay',tree).kind,'ComboBox')

    def test_place_names_button_follows_imported_marker_count(self):
        self.assertFalse(self.node('command-placeNames').params.meta.enabled)
        self.lua.globals().state.value.labels=1
        self.assertTrue(self.node('command-placeNames').params.meta.enabled)

    def test_legacy_marker_warning_is_presented_without_changing_dataset(self):
        original=list(self.lua.globals().dataset.warnings.values())
        helper=self.lua.globals().modules['druttzen_osm_vanilla::/osm/ui_snapshot.lua']
        box=self.lua.globals().api.engine.terrain.getBoundingBox()
        snapshot=helper.fromState(self.lua.globals().state.value,box)
        self.assertTrue(any('Show place names' in warning for warning in snapshot.warnings.values()))
        self.assertFalse(any('Select a marker to read its name' in warning for warning in snapshot.warnings.values()))
        self.assertEqual(list(self.lua.globals().dataset.warnings.values()),original)

    def test_long_status_notes_remain_in_a_separate_scroll_area(self):
        notice='Built objects need attention | '+('Missing saved scenery items. '*80)
        self.lua.globals().state.value.notice=notice
        self.lua.globals().state.value.error='Rejected world build proposal'
        tree=self.tree()
        status=self.node('status-scroll',tree)
        body=self.node('scroll',tree)
        self.assertEqual(status.kind,'ScrollArea')
        self.assertEqual(status.params.verticalPolicy,1)
        self.assertEqual(status.params.horizontalPolicy,0)
        header=status.params.content.params.layout
        notes=[node.params.text for node in header.params.children.values() if node.kind=='RichTextView']
        self.assertIn(notice,notes)
        self.assertIn('Rejected world build proposal',notes)
        self.assertIsNone(self.lua.globals().findNode(body,'druttzen-osm-status-scroll'))

    def test_styles_keep_notes_visible_and_leave_room_for_commands(self):
        self.lua.execute('''
            package.preload["::/gui/main/stylesheetutil.lua"]=function()
                return {makeAdder=function(styles)
                    return function(selector,style) styles[selector]=style end
                end}
            end
        ''')
        styles=load_script(self.lua,CONTENT/'panel.css.lua')
        note=styles['RichTextView!osm-import-note']
        self.assertEqual(note.size[2],-1)
        self.assertGreater(note.minSize[2],0)
        self.assertTrue(styles['RichTextView!osm-import-note RichTextView::Text'].textAutoWrap)
        status=styles['ScrollArea!osm-import-status-scroll'].size
        body=styles['ScrollArea!osm-import-scroll'].size
        window=styles['Window!osm-import-panel'].size
        self.assertLessEqual(status[2],200)
        self.assertGreaterEqual(body[2],350)
        self.assertLessEqual(status[2]+body[2]+50,window[2])
        self.assertGreaterEqual(styles['!osm-import-status TextView'].fontSize,16)

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

local ssu=require "::/gui/main/stylesheetutil.lua"
function data()
  local styles={}
  local a=ssu.makeAdder(styles)
  a("Button!osm-import-open",{size={112,38},padding={8,4,8,4}})
  a("Window!osm-import-panel",{size={660,620}})
  a("Window!osm-import-panel TextView!font-scale-headline",{fontSize=20,fontWeight="Medium"})
  a("ScrollArea!osm-import-status-scroll",{size={640,180}})
  a("!osm-import-status",{padding={12,8,12,8}})
  a("!osm-import-status BoxLayout",{innerSpacing={0,5}})
  a("!osm-import-status TextView",{size={600,-1},textAutoWrap=true,fontSize=16})
  a("!osm-import-status TextView!font-scale-headline",{fontSize=20})
  a("ScrollArea!osm-import-scroll",{size={640,380}})
  a("!osm-import-list",{padding={12,8,20,16}})
  a("!osm-import-list > BoxLayout",{innerSpacing={0,10}})
  a("Button!osm-import-command",{size={580,36},padding={10,4,10,4}})
  a("ComboBox!osm-import-choice",{size={280,34}})
  -- Native CSS uses -1 for content height; zero makes notices invisible.
  a("RichTextView!osm-import-note",{size={580,-1},minSize={-1,24},padding={0,0,0,0}})
  a("!osm-import-status RichTextView!osm-import-note",{size={600,-1}})
  a("RichTextView!osm-import-note RichTextView::Text",{textAutoWrap=true,fontSize=16})
  return styles
end

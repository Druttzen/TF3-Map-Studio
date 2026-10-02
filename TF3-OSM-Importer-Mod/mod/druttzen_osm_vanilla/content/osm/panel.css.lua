local ssu=require "::/gui/main/stylesheetutil.lua"
function data()
  local styles={}
  local a=ssu.makeAdder(styles)
  a("Button!osm-import-open",{size={112,38},padding={8,4,8,4}})
  a("Window!osm-import-panel",{size={660,620}})
  a("!osm-import-status",{padding={12,8,12,8}})
  a("!osm-import-status BoxLayout",{innerSpacing={0,5}})
  a("ScrollArea!osm-import-scroll",{size={640,440}})
  a("!osm-import-list",{padding={12,8,20,16}})
  a("!osm-import-list > BoxLayout",{innerSpacing={0,10}})
  a("Button!osm-import-command",{size={580,36},padding={10,4,10,4}})
  a("ComboBox!osm-import-choice",{size={280,34}})
  a("RichTextView!osm-import-note",{size={580,0}})
  return styles
end

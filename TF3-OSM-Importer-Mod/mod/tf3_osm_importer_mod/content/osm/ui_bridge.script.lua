-- The GUI reads a small snapshot. World changes still run in the engine script.
local uiSnapshot=ug_require "druttzen_osm_vanilla::/osm/ui_snapshot.lua"
local loader=ug_require "druttzen_osm_vanilla::/osm/map_loader.lua"
local script={}
function script.guiUpdate(_userParams,state,_guiState)
  loader.update(state:get())
end
function script.guiHandleEvent(_userParams,state,_guiState,_src,id,name,_param)
  if id~="druttzen_osm_vanilla" or name~="osm.ui.snapshot" then return end
  return uiSnapshot.fromState(state:get() or {},api.engine.terrain.getBoundingBox())
end
-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return script
end

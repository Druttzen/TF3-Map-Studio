-- The GUI reads a small snapshot. World changes still run in the engine script.
local dataset=ug_require "druttzen_osm_vanilla::/osm/dataset.lua"
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local script={}
function script.guiHandleEvent(_userParams,state,_guiState,_src,id,name,_param)
  if id~="druttzen_osm_vanilla" or name~="osm.ui.snapshot" then return end
  local value=state:get() or {}
  local box=api.engine.terrain.getBoundingBox()
  local options=controls.options(value.options or dataset.importOptions)
  return {
    datasetId=dataset.id,phase=value.phase or "ready",started=value.datasetId~=nil,
    builtEdges=value.builtEdges or 0,builtScenery=value.builtScenery or 0,labels=value.labels or 0,
    skipped=value.skipped or 0,error=value.error,notice=value.notice,options=options,
    totals=controls.totals(dataset,options),warnings=dataset.warnings or {},
    mapWidth=box.max.x-box.min.x,mapHeight=box.max.y-box.min.y,
    datasetWidth=dataset.size[1],datasetHeight=dataset.size[2],
  }
end
-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return script
end

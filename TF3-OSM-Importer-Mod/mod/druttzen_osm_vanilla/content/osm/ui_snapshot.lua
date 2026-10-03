-- GPL-3.0. Shared read-only presentation of persisted importer state.
local dataset=ug_require "druttzen_osm_vanilla::/osm/dataset.lua"
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local snapshot={}

function snapshot.fromState(value,box)
  if type(value)~="table" then return nil end
  local options=controls.options(value.options or dataset.importOptions)
  return {
    datasetId=dataset.id,phase=value.phase or "ready",started=value.datasetId~=nil,
    builtEdges=value.builtEdges or 0,builtScenery=value.builtScenery or 0,labels=value.labels or 0,
    skipped=value.skipped or 0,error=value.error,notice=value.notice,options=options,
    totals=controls.totals(dataset,options),warnings=controls.warnings(dataset),
    mapWidth=box.max.x-box.min.x,mapHeight=box.max.y-box.min.y,
    datasetWidth=dataset.size[1],datasetHeight=dataset.size[2],
  }
end

return snapshot

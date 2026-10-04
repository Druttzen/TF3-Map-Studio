-- GPL-3.0. Shared read-only presentation of persisted importer state.
local dataset=ug_require "druttzen_osm_vanilla::/osm/dataset.lua"
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local water=ug_require "druttzen_osm_vanilla::/osm/water.lua"
local snapshot={}
local mappedCount=#(dataset.waterFeatures or {})
local lakeCount=0
for _,feature in ipairs(dataset.waterFeatures or {}) do if feature.kind=="lake" then lakeCount=lakeCount+1 end end

function snapshot.fromState(value,box)
  if type(value)~="table" then return nil end
  local options=controls.options(value.options or dataset.importOptions)
  local available,objectKinds=controls.available(dataset)
  return {
    datasetId=dataset.id,phase=value.phase or "ready",started=value.datasetId~=nil,
    builtEdges=value.builtEdges or 0,builtScenery=value.builtScenery or 0,labels=value.labels or 0,
    skipped=value.skipped or 0,error=value.error,notice=value.notice,options=options,
    errorKind=value.errorKind,datasetMatches=value.datasetId==nil or value.datasetId==dataset.id,
    pendingAccepted=value.pendingOwnership~=nil or value.pendingScenery~=nil or value.pendingTown~=nil,
    acceptedUnjournalled=value.acceptedUnjournalled and true or false,
    checking=value.check~=nil,runSteps=value.runSteps or 0,
    waterSettings=water.settings(value.waterSettings),waterBusy=value.waterJob~=nil,
    waterBuilt=value.waterRecord and value.waterRecord.complete or false,
    waterCount=#(value.waterRecords or {})+(value.waterRecord and 1 or 0),
    mappedWaterCount=mappedCount,mappedLakeCount=lakeCount,
    totals=controls.totals(dataset,options),warnings=controls.warnings(dataset),
    available=available,objectKinds=objectKinds,matchSummary=value.matchSummary,
    unavailableObjects=dataset.unavailableObjects or {},builtTowns=value.builtTowns or 0,
    hasMappedObjectMetadata=dataset.objectMetadata~=nil,
    mapWidth=box.max.x-box.min.x,mapHeight=box.max.y-box.min.y,
    datasetWidth=dataset.size[1],datasetHeight=dataset.size[2],
  }
end

return snapshot

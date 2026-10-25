-- GPL-3.0. Shared read-only presentation of persisted importer state.
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local water=ug_require "druttzen_osm_vanilla::/osm/water.lua"
local snapshot={}

function snapshot.fromState(value,box)
  if type(value)~="table" or not value.datasetInfo then return nil end
  local info=value.datasetInfo
  local options=controls.options(value.options)
  local available,objectKinds=info.inventory.counts,info.inventory.kinds
  return {
    datasetId=info.id,phase=value.phase or "ready",started=value.datasetId~=nil,
    mapSource=value.mapSource,mapReady=value.mapReady~=false and (not value.datasetId or value.datasetId==info.id),
    mapSelectionLocked=value.check~=nil or value.waterJob~=nil,
    builtEdges=value.builtEdges or 0,builtScenery=value.builtScenery or 0,labels=value.labels or 0,
    skipped=value.skipped or 0,error=value.error,notice=value.notice,options=options,
    errorKind=value.errorKind,datasetMatches=value.mapReady~=false and (value.datasetId==nil or value.datasetId==info.id),
    pendingAccepted=value.pendingOwnership~=nil or value.pendingScenery~=nil or value.pendingTown~=nil,
    acceptedUnjournalled=value.acceptedUnjournalled and true or false,
    checking=value.check~=nil,runSteps=value.runSteps or 0,
    waterSettings=water.settings(value.waterSettings),waterBusy=value.waterJob~=nil,
    waterBuilt=value.waterRecord and value.waterRecord.complete or false,
    waterCount=#(value.waterRecords or {})+(value.waterRecord and 1 or 0),
    mappedWaterCount=info.mappedWaterCount,mappedLakeCount=info.mappedLakeCount,
    totals=controls.totalsFromInventory(info.inventory,options),warnings=controls.warnings(info),
    available=available,objectKinds=objectKinds,matchSummary=value.matchSummary,
    unavailableObjects=info.unavailableObjects or {},builtTowns=value.builtTowns or 0,
    hasMappedObjectMetadata=info.hasMappedObjectMetadata,
    mapWidth=box.max.x-box.min.x,mapHeight=box.max.y-box.min.y,
    datasetWidth=info.size[1],datasetHeight=info.size[2],
  }
end

return snapshot

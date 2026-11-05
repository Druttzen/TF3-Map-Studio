-- GPL-3.0. Shared read-only presentation of persisted importer state.
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local water=ug_require "druttzen_osm_vanilla::/osm/water.lua"
local snapshot={}

local detailLimit=30
local function firstEntries(values)
  values=values or {}
  local shown={}
  local total=#values
  for index=1,math.min(total,detailLimit) do shown[index]=values[index] end
  return shown,total-#shown
end

function snapshot.fromState(value,box)
  if type(value)~="table" or not value.datasetInfo then return nil end
  local info=value.datasetInfo
  local options=controls.options(value.options)
  local available,objectKinds=info.inventory.counts,info.inventory.kinds
  -- Keep full conversion details in persisted datasetInfo. Only the short
  -- display copy is transformed each quarter-second panel refresh.
  local warnings,warningsOmitted=firstEntries(info.warnings)
  local unavailableObjects,unavailableObjectsOmitted=firstEntries(info.unavailableObjects)
  return {
    datasetId=info.id,phase=value.phase or "ready",started=value.datasetId~=nil,
    mapSource=value.mapSource,mapReady=value.mapReady~=false and (not value.datasetId or value.datasetId==info.id),
    mapSelectionLocked=value.check~=nil or value.waterJob~=nil,
    builtEdges=value.builtEdges or 0,builtScenery=value.builtScenery or 0,labels=value.labels or 0,
    skipped=value.skipped or 0,omittedScenery=value.omittedScenery or 0,error=value.error,notice=value.notice,options=options,
    errorKind=value.errorKind,datasetMatches=value.mapReady~=false and (value.datasetId==nil or value.datasetId==info.id),
    pendingAccepted=value.pendingOwnership~=nil or value.pendingScenery~=nil or value.pendingTown~=nil,
    acceptedUnjournalled=value.acceptedUnjournalled and true or false,
    checking=value.check~=nil,runSteps=value.runSteps or 0,
    waterSettings=water.settings(value.waterSettings),waterBusy=value.waterJob~=nil,
    waterBuilt=value.waterRecord and value.waterRecord.complete or false,
    waterCount=#(value.waterRecords or {})+(value.waterRecord and 1 or 0),
    mappedWaterCount=info.mappedWaterCount,mappedLakeCount=info.mappedLakeCount,
    totals=controls.totalsFromInventory(info.inventory,options),warnings=controls.warnings({warnings=warnings}),warningsOmitted=warningsOmitted,
    available=available,objectKinds=objectKinds,matchSummary=value.matchSummary,
    unavailableObjects=unavailableObjects,unavailableObjectsOmitted=unavailableObjectsOmitted,builtTowns=value.builtTowns or 0,
    hasMappedObjectMetadata=info.hasMappedObjectMetadata,
    mapWidth=box.max.x-box.min.x,mapHeight=box.max.y-box.min.y,
    datasetWidth=info.size[1],datasetHeight=info.size[2],
  }
end

-- Component.state_native is implemented in TF3 40425. The similarly named
-- GameScriptState.get_native/set_native methods are fatal stubs in that build;
-- use only the read-only component API here and retain ordinary engine saves.
function snapshot.fromNative(native,box)
  local infoNative=native:find("datasetInfo")
  if not infoNative then return nil end
  local function materialize(value)
    if type(value)=="userdata" or type(value)=="table" and value.asTable then return value:asTable() end
    return value
  end
  local function prefix(value)
    if not value then return {} end
    return setmetatable({},{__len=function() return value:size() end,
      __index=function(_,index) return materialize(value:find(index)) end})
  end
  local info={}
  for _,key in ipairs({"id","size","inventory","hasMappedObjectMetadata","mappedWaterCount","mappedLakeCount"}) do
    info[key]=materialize(infoNative:find(key))
  end
  info.warnings=prefix(infoNative:find("warnings"))
  info.unavailableObjects=prefix(infoNative:find("unavailableObjects"))
  local value={datasetInfo=info}
  for _,key in ipairs({"datasetId","phase","mapSource","mapReady","builtEdges","builtScenery","labels","skipped",
    "omittedScenery","error","notice","errorKind","acceptedUnjournalled","runSteps","builtTowns"}) do
    value[key]=native:find(key)
  end
  for _,key in ipairs({"check","waterJob","pendingOwnership","pendingScenery","pendingTown"}) do
    if native:find(key)~=nil then value[key]=true end
  end
  for _,key in ipairs({"options","waterSettings","matchSummary"}) do value[key]=materialize(native:find(key)) end
  local record=native:find("waterRecord")
  if record then value.waterRecord={complete=record:find("complete")} end
  value.waterRecords=prefix(native:find("waterRecords"))
  return snapshot.fromState(value,box)
end

return snapshot

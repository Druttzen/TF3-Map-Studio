-- Read-only proof for revision 10's constructor/send error classification bug.
local controls = ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local recovery = {}
local sceneryName = "druttzen_osm_vanilla::/osm/scenery.con"

local function integer(value)
  return type(value)=="number" and value==value and value>=1
    and value<math.huge and value==math.floor(value)
end

local function legacyGroundError(error)
  if type(error)~="string" then return false end
  local normalized=error:gsub("\r\n","\n")
  local firstLine,suffix=normalized:match("^([^\n]*)(.*)$")
  if not firstLine or not firstLine:match('importer%.script%.lua"%]:811: Unknown exception$') then return false end
  if suffix=="" then return true end
  -- TF3 persists the native traceback as part of the error string. Its first
  -- frame must identify command preparation, never sendCommand or a callback.
  local frame=suffix:match("^\nstack traceback:\n[ \t]*([^\n]+)")
  return frame~=nil and frame:match("^=%[C%]%(%-1%):[ \t]*makeWorldBuildProposalCmd[ \t]*$")~=nil
end

local function inspect(dataset,value)
  if type(dataset)~="table" or type(value)~="table" or value.datasetId~=dataset.id then
    return false,"The original dataset is required."
  end
  if value.phase~="error" or value.resumePhase~="scenery" or value.errorKind~="command_state"
    or not legacyGroundError(value.error) then
    return false,"This is not the revision 10 ground-command failure."
  end
  for _,key in ipairs({"pendingOwnership","pendingScenery","pendingTown","pendingHeightNodes","pendingAccepted","acceptedUnjournalled"}) do
    if value[key]~=nil then return false,"An accepted object still needs finalization." end
  end
  if not integer(value.cursor) or value.failedFirst~=value.cursor or not integer(value.failedLast)
    or value.failedLast<value.cursor or type(dataset.scenery)~="table" or value.failedLast>#dataset.scenery
    or type(value.options)~="table" then
    return false,"The failed source range is not safely identified."
  end
  -- Native API namespaces and callable bindings can be userdata. Check their
  -- availability here and let check()'s pcall verify that invocation succeeds.
  if type(controls.groundFace)~="function" or not api or not api.engine
    or not api.engine.terrain or not api.engine.terrain.getBoundingBox
    or not api.engine.forEachEntityWithComponent or not api.engine.getComponent
    or not api.type or not api.type.ComponentType or api.type.ComponentType.CONSTRUCTION==nil then
    return false,"The live construction inventory cannot be checked."
  end

  local known={}
  if value.sceneryRecords~=nil and type(value.sceneryRecords)~="table" then
    return false,"The accepted-object journal is invalid."
  end
  for _,record in pairs(value.sceneryRecords or {}) do
    if type(record)~="table" or not integer(record.first) or not integer(record.last)
      or record.last<record.first or record.last>=value.cursor or type(record.entities)~="table" then
      return false,"An accepted-object journal range overlaps the failed source range."
    end
    for _,entity in pairs(record.entities) do
      if not integer(entity) or known[entity] then return false,"The accepted-object journal is invalid." end
      known[entity]=true
    end
  end

  local box=api.engine.terrain.getBoundingBox()
  local selected,collapsed=0,false
  for index=value.cursor,value.failedLast do
    local item=dataset.scenery[index]
    if type(item)~="table" then return false,"The failed source range is incomplete." end
    local source=controls.resolvedItem(item,index,value)
    if not source and controls.selectedScenery(item,value.options) then
      return false,"A selected source item cannot be resolved."
    end
    if source and controls.selectedScenery(source,value.options) then
      -- A model-only command may flatten into an asset group. Only surfaces
      -- guarantee that an accepted candidate remains a live construction.
      if source.model or type(source.texture)~="string" or source.texture=="" then
        return false,"The failed batch must contain only ground textures."
      end
      selected=selected+1
      if not controls.groundFace(source.face,box) then collapsed=true end
    end
  end
  if selected==0 or not collapsed then return false,"No collapsed ground face was found in the failed batch." end

  -- Names can be lost or changed. Enumerate every construction and compare its
  -- resource and entity ID instead; even an unknown batch from another dataset
  -- blocks recovery. No native command is prepared or sent by this check.
  local unknown=false
  local complete=true
  local T=api.type.ComponentType
  api.engine.forEachEntityWithComponent(function(entity)
    local construction=api.engine.getComponent(entity,T.CONSTRUCTION)
    if not construction then complete=false
    elseif construction.fileName==sceneryName and not known[entity] then unknown=true end
  end,T.CONSTRUCTION)
  if not complete then return false,"The live construction inventory is incomplete." end
  if unknown then return false,"An importer construction exists outside the accepted-object journal." end
  return true,"The failed ground batch was not accepted; its collapsed face can be safely repaired."
end

function recovery.check(dataset,value)
  local ok,allowed,reason=pcall(inspect,dataset,value)
  if not ok then return false,"The live ground-recovery check failed: "..tostring(allowed) end
  return allowed,reason
end

return recovery

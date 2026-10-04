-- GPL-3.0. Native town creation with a persisted accepted-command journal.
local towns={}
local function entities()
  return api.engine.getEntitiesWithComponent(api.type.ComponentType.TOWN)
end

function towns.check(label)
  assert(type(label.name)=="string" and label.name~="","A functioning town requires a name")
  assert(type(api.cmd.makeTownCreateCmd)=="function" and type(api.cmd.makeTownSetDevelopmentActiveCmd)=="function",
    "This TF3 build does not expose the required native town commands")
  assert(api.type.Map and api.type.Map.Town and type(api.type.Map.Town.new)=="function"
    and type(api.engine.mapgen.createTowns)=="function","This TF3 build cannot prepare native mapped towns")
  local T=api.type.ComponentType
  for _,entity in ipairs(entities()) do
    local name=api.engine.getComponent(entity,T.NAME)
    assert(not name or name.name~=label.name,"A town named "..label.name.." already exists; do not create a duplicate")
  end
end

function towns.checkLimit(requested)
  local getLimit=api.engine.mapgen.getMinMaxValidNumTowns
  if type(getLimit)~="function" then return end
  local limits=getLimit()
  assert(limits and type(limits[2])=="number" and #entities()+requested<=limits[2],
    "Selected settlements plus existing towns exceed this TF3 map's supported town count")
end

function towns.prepare(label,seed)
  -- Installed gui/map_editor/map_editor.tl uses api.type.Map.Town; the SDK
  -- documents the record under the name GameMap.Town.
  local requested=api.type.Map.Town.new()
  requested.name=label.name; requested.pos=api.type.Vec2f.new(label.pos[1],label.pos[2])
  requested.sizeFactors={1,1,1}
  requested.landUse2CargoNeeds={}
  -- Use TF3's own generator for capacities, angles and cargo demand categories.
  -- This is a read-only proposal. Never execute its toRemove list.
  local result=api.engine.mapgen.createTowns(seed,{requested})
  assert(result and #result.toAdd==1,"TF3 did not prepare exactly one town at this mapped place")
  local proposed=result.toAdd[1]
  assert(proposed.name==label.name and proposed.position
    and math.abs(proposed.position.x-label.pos[1])<0.01 and math.abs(proposed.position.y-label.pos[2])<0.01,
    "TF3's town generator changed the mapped position; nothing was built")
  return proposed
end

function towns.finalize(value)
  local record=value.pendingTown
  if not record then return end
  local T=api.type.ComponentType
  assert(#record.entities==1,"Accepted town has no unique recorded entity; inspect this save without rebuilding")
  local entity=record.entities[1]
  assert(api.engine.entityExists(entity) and api.engine.getComponent(entity,T.TOWN),"The accepted town entity is missing")
  local name=api.engine.getComponent(entity,T.NAME)
  assert(name and name.name==record.name,"The accepted town name has changed; inspect this save")
  local called,success=false,false
  api.cmd.sendCommand(api.cmd.makeTownSetDevelopmentActiveCmd(entity,record.allowGrowth),function(_,ok)
    called=true; success=ok
  end)
  assert(called and success,"Town growth policy is incomplete; Retry finishes it without creating another town")
  assert(api.engine.getComponent(entity,T.TOWN).developmentActive==record.allowGrowth,"TF3 did not apply the town growth policy")
  record.complete=true; value.pendingTown=nil
end

function towns.build(value,state,label)
  towns.check(label)
  local proposed=towns.prepare(label,value.datasetId..":"..tostring(value.cursor))
  local before={}
  for _,entity in ipairs(entities()) do before[entity]=true end
  local called,accepted=false,false
  local callbackError
  local ok,err=pcall(function()
    -- Set the uncertainty marker before crossing the native command boundary.
    value.acceptedUnjournalled=true; state:set(value)
    api.cmd.sendCommand(api.cmd.makeTownCreateCmd({proposed}),function(_,success,_resultEntities)
      called=true
      local callbackOk,err=pcall(function()
      if not success then
        value.acceptedUnjournalled=nil
        error("TF3 rejected creation of town "..label.name)
      end
      accepted=true
      local record={entities={},name=label.name,pos={label.pos[1],label.pos[2]},first=value.cursor,
        allowGrowth=value.options.townRoadGrowth,initialRoads=true}
      -- Command result lists also contain generated streets/buildings. Only a
      -- newly created TOWN bearing this exact requested name is journalled.
      local T=api.type.ComponentType
      for _,entity in ipairs(entities()) do
        if not before[entity] then
          local name=api.engine.getComponent(entity,T.NAME)
          if name and name.name==label.name then record.entities[#record.entities+1]=entity end
        end
      end
      value.townRecords=value.townRecords or {}; value.townRecords[#value.townRecords+1]=record
      value.pendingTown=record; value.builtTowns=(value.builtTowns or 0)+1
      value.cursor=value.cursor+1; value.runSteps=(value.runSteps or 0)+1
      value.failedFirst=nil; value.failedLast=nil; value.acceptedUnjournalled=nil
      state:set(value)
      towns.finalize(value); value.cooldown=value.options.interval
      end)
      if not callbackOk then callbackError=tostring(err) end
    end)
    assert(called,"Town creation must execute in engine postUpdate state")
    assert(not callbackError,callbackError)
  end)
  if not ok then
    value.resumePhase=value.phase; value.phase="error"; value.error=tostring(err)
    value.errorKind=value.pendingTown and "finalization" or accepted and "accepted_state" or called and "proposal_rejected" or "command_state"
    state:set(value)
  end
end

function towns.inspect(dataset,value)
  local report={expected=0,current=0,problems={}}
  local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
  local options=controls.options(value.options or dataset.importOptions)
  for _,label in ipairs(dataset.labels or {}) do
    if controls.placeMode(label,options)=="town" then report.expected=report.expected+1 end
  end
  local system=api.engine.system and api.engine.system.townBuildingSystem
  local buildingMap=report.expected>0 and system and type(system.getTown2BuildingMap)=="function" and system.getTown2BuildingMap() or nil
  local seen={}
  for _,record in ipairs(value.townRecords or {}) do
    local source=dataset.labels[record.first]
    local entity=record.entities and record.entities[1]
    local T=api.type.ComponentType
    local town=entity and api.engine.entityExists(entity) and api.engine.getComponent(entity,T.TOWN)
    local name=town and api.engine.getComponent(entity,T.NAME)
    if not source or controls.placeMode(source,options)~="town" or #record.entities~=1 or seen[entity]
      or not name or name.name~=source.name or not record.complete
      or town.developmentActive~=record.allowGrowth then
      report.problems[#report.problems+1]="Recorded town or its growth policy does not match the completed import"
    else
      report.current=report.current+1; seen[entity]=true
      if not buildingMap then
        report.problems[#report.problems+1]="Town entity verified; native simulated-building checks are unavailable"
      elseif not buildingMap[entity] or #buildingMap[entity]==0 then
        report.problems[#report.problems+1]="Town exists but has no simulated buildings; inspect its placement and functionality"
      end
    end
  end
  if report.current~=report.expected or (value.builtTowns or 0)~=report.expected then
    report.problems[#report.problems+1]="Functioning town count does not match the selected place tags"
  end
  return report
end
return towns

-- GPL-3.0. TF3 builder using its installed API definitions and vanilla resources.
local dataset = ug_require "druttzen_osm_vanilla::/osm/dataset.lua"
local controls = ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local worldAudit = ug_require "druttzen_osm_vanilla::/osm/world_audit.lua"
local script = {}
local eventId = "druttzen_osm_vanilla"
local sceneryName = "druttzen_osm_vanilla::/osm/scenery.con"
local bridgeName = "::/infrastructure/bridge/steel.bridge"
local tunnelName = "::/infrastructure/tunnel/tunnel_c.tunnel"
local markerName = "::/assets/markers/marker_locate.mdl"
local compType = api.type.ComponentType
local enums = api.type["enum"]

local function message(text)
  print("[OSM Vanilla] "..text)
end

local function initialState(state)
  local value = state:get() or {}
  if not value.phase then
    value = { phase="ready", cursor=1, builtEdges=0, builtScenery=0, skipped=0, nodes={}, labels=0 }
  end
  value.options=controls.options(value.options or dataset.importOptions)
  return value
end

local function status(value)
  message(string.format("%s | roads/rails %d/%d | scenery %d/%d | markers %d/%d | skipped jobs %d%s",
    value.phase, value.builtEdges or 0, #dataset.edges, value.builtScenery or 0, #dataset.scenery,
    value.labels or 0, #dataset.labels,
    value.skipped or 0, value.error and " | "..value.error or ""))
end

local function requireResource(rep, name)
  local id = rep.find(name)
  -- TF3 has both indexed repositories and named ones (ground textures).
  local found = (type(id)=="number" and id>=0)
    or (type(id)=="string" and id~="" and id~="-1")
  assert(found, "Missing vanilla resource: "..name)
  return id
end

local function preflight(value)
  assert(dataset.schema==1 and type(dataset.id)=="string" and dataset.id~="", "Prepare an OSM dataset with the converter first.")
  assert(#dataset.edges+#dataset.scenery+#dataset.labels>0, "Dataset has no supported roads, tracks or scenery.")
  local totals=controls.totals(dataset,value.options)
  assert(totals.edges+totals.scenery+totals.labels>0,"No dataset items match your import selections.")
  local function checkPosition(p)
    assert(type(p)=="table" and type(p[1])=="number" and type(p[2])=="number"
      and p[1]==p[1] and p[2]==p[2] and math.abs(p[1])<math.huge and math.abs(p[2])<math.huge,
      "Invalid dataset coordinate")
    assert(api.engine.terrain.isValidCoordinate(api.type.Vec2f.new(p[1],p[2])),
      "Dataset extends outside this map; check converter map width and height.")
  end
  local checked = {}
  for _, edge in ipairs(dataset.edges) do
    if value.options[edge.kind=="TRACK" and "railways" or "roads"] then
      assert(dataset.nodes[edge.node0] and dataset.nodes[edge.node1], "Invalid dataset node reference")
      checkPosition(dataset.nodes[edge.node0].pos)
      checkPosition(dataset.nodes[edge.node1].pos)
      if not checked[edge.template] then
        requireResource(api.res.streetTemplateRep, edge.template)
        checked[edge.template] = true
      end
      if edge.bridge then requireResource(api.res.bridgeTypeRep, bridgeName) end
      if edge.tunnel then requireResource(api.res.tunnelTypeRep, tunnelName) end
      if edge.heightGuide then checkPosition(edge.heightGuide.start); checkPosition(edge.heightGuide.finish) end
    end
  end
  for _, item in ipairs(dataset.scenery) do
    if value.options[controls.sceneryCategory(item)] then
      if item.model and not checked[item.model] then
        requireResource(api.res.modelRep, item.model)
        checked[item.model] = true
      end
      if item.model then checkPosition(item.pos) end
      if item.texture then
        if not checked[item.texture] then
          requireResource(api.res.groundTextureRep,item.texture); checked[item.texture]=true
        end
        assert(#item.face>=3,"Invalid ground polygon")
        for _,p in ipairs(item.face) do checkPosition(p) end
      end
    end
  end
  if value.options.places then
    for _,label in ipairs(dataset.labels) do checkPosition(label.pos) end
    if #dataset.labels>0 then requireResource(api.res.modelRep,markerName) end
  end
  if totals.scenery+totals.labels>0 then requireResource(api.res.constructionRep, sceneryName) end
  -- Never accept a referenced visual resource from another mod namespace.
  for name, _ in pairs(checked) do assert(name:sub(1,3)=="::/", "Non-vanilla reference rejected: "..name) end
  for _,warning in ipairs(controls.warnings(dataset)) do message(warning) end
end

local function terrainZ(pos)
  local xy = api.type.Vec2f.new(pos[1],pos[2])
  assert(api.engine.terrain.isValidCoordinate(xy), "Coordinate outside this map; check converter map size.")
  return api.engine.terrain.getHeightAt(xy)
end

local function nodePosition(edge, nodeId, ending)
  local p = dataset.nodes[nodeId].pos
  local z = terrainZ(p)
  if edge.heightGuide then
    local guide = edge.heightGuide
    local t = ending and guide.t1 or guide.t0
    z = terrainZ(guide.start)*(1-t)+terrainZ(guide.finish)*t
    if edge.tunnel then z=z-(guide.depth or 8)*math.sin(math.pi*t) end
  end
  return api.type.Vec3f.new(p[1],p[2],z)
end

local function existingNode(value, id, position)
  local entity = value.nodes[id]
  if entity and api.engine.entityExists(entity) then return entity end
  -- Only re-use nodes created by this import. Existing map nodes remain independent.
  return nil
end

local function edgeProposal(edge, value)
  local proposal = api.type.SimpleProposal.new()
  local p0, p1 = nodePosition(edge,edge.node0,false), nodePosition(edge,edge.node1,true)
  local id0, id1 = existingNode(value,edge.node0,p0), existingNode(value,edge.node1,p1)
  if id0 then p0=api.engine.getComponent(id0,compType.BASE_NODE).position end
  if id1 then p1=api.engine.getComponent(id1,compType.BASE_NODE).position end
  assert(not id0 or id0~=id1, "Both endpoints resolve to the same node")
  local newNodes={}
  local function newNode(entity, position)
    local n=api.type.NodeAndEntity.new()
    n.entity=entity; n.comp.position=position
    newNodes[#newNodes+1]=n
  end
  if not id0 then newNode(-3,p0) end
  if not id1 then newNode(-4,p1) end
  local e=api.type.SegmentAndEntity.new()
  e.entity=-1
  e.comp.node0=id0 or -3; e.comp.node1=id1 or -4
  e.comp.position0=p0; e.comp.position1=p1
  local tangent=api.type.Vec3f.new(p1.x-p0.x,p1.y-p0.y,p1.z-p0.z)
  e.comp.tangent0=tangent; e.comp.tangent1=tangent
  e.comp.type=enums.BaseEdgeType.NORMAL
  if edge.bridge then
    e.comp.type=enums.BaseEdgeType.BRIDGE
    e.comp.typeIndex=requireResource(api.res.bridgeTypeRep,bridgeName)
  elseif edge.tunnel then
    e.comp.type=enums.BaseEdgeType.TUNNEL
    e.comp.typeIndex=requireResource(api.res.tunnelTypeRep,tunnelName)
  end
  e.type=edge.kind=="TRACK" and 1 or 0
  local template=api.res.streetTemplateRep.get(requireResource(api.res.streetTemplateRep,edge.template))
  e.comp.laneConfigs=template.laneConfigs
  e.comp.roadTemplate=edge.template; e.comp.roadStyle=template.streetStyle
  e.comp.roadType=edge.kind=="TRACK" and enums.RoadType.TRACK or enums.RoadType.STREET
  e.comp.roadDevelopmentLocked=true
  -- Assign ownership with TF3's native entity command after the build.
  proposal.streetProposal.nodesToAdd=newNodes
  proposal.streetProposal.edgesToAdd={e}
  return proposal
end

local function finishOwnership(value)
  local entity=value.pendingOwnership
  if not entity then return end
  local edge=api.engine.getComponent(entity,compType.BASE_EDGE)
  assert(edge,"The built edge is missing; ownership cannot be completed.")
  local player=api.engine.util.getPlayer()
  local function assign(id)
    api.cmd.sendCommand(api.cmd.makeEntitySetPlayerCmd(id,player))
    local owner=api.engine.getComponent(id,compType.PLAYER_OWNED)
    assert(owner and owner.player==player,"The built edge awaits ownership. Retry this step.")
  end
  for _,object in ipairs(edge.objects or {}) do assign(object[1]) end
  assign(entity)
  value.pendingOwnership=nil
end

local function finishScenery(value)
  local record=value.pendingScenery
  if not record then return end
  assert(#record.entities>0,"The game returned no scenery entity. Keep this save for inspection; do not rebuild this accepted step.")
  for _,entity in ipairs(record.entities) do
    assert(api.engine.entityExists(entity),"An accepted scenery object is missing. Keep this save for inspection.")
    api.cmd.sendCommand(api.cmd.makeEntitySetPlayerCmd(entity,api.engine.util.getPlayer()))
    local owner=api.engine.getComponent(entity,compType.PLAYER_OWNED)
    assert(owner and owner.player==api.engine.util.getPlayer(),"Scenery ownership is incomplete. Retry this step.")
    local named=api.engine.getComponent(entity,compType.NAME)
    -- Asset groups have no NAME component and the name command cannot add it.
    -- Their live model transforms are verified by the saved entity journal.
    if named then
      if named.name~=record.name then api.cmd.sendCommand(api.cmd.makeEntitySetNameCmd(entity,record.name,true)) end
      named=api.engine.getComponent(entity,compType.NAME)
      assert(named and named.name==record.name,"Scenery naming is incomplete. Retry this step.")
    else
      assert(api.engine.getComponent(entity,compType.ASSET_GROUP),"The scenery object cannot be identified as a construction or asset group.")
    end
  end
  value.pendingScenery=nil
end

local function labelProposal(value)
  local source=dataset.labels[value.cursor]
  local proposal=api.type.SimpleProposal.new()
  local construction=api.type.SimpleProposal.ConstructionEntity.new()
  construction.fileName=sceneryName
  construction.params={items={{model=markerName,rotation=0,
    pos={source.pos[1],source.pos[2],terrainZ(source.pos)}}},seed=0}
  construction.transf=api.type.Mat4f.new()
  construction.name=source.name
  construction.playerEntity=api.engine.util.getPlayer()
  proposal.constructionsToAdd={construction}
  return proposal,value.cursor
end

local function sceneryProposal(value)
  local items={}
  local last=value.cursor-1
  local included=0
  -- Scan by original dataset index, so progress remains resumable when the
  -- batch size changes. A batch counts selected items, not excluded ones.
  while last<#dataset.scenery and included<value.options.batchSize do
    last=last+1
    if value.options[controls.sceneryCategory(dataset.scenery[last])] then included=included+1 end
  end
  for i=value.cursor,last do
    local source=dataset.scenery[i]
    if value.options[controls.sceneryCategory(source)] and source.model then
      items[#items+1]={model=source.model,rotation=source.rotation,
        pos={source.pos[1],source.pos[2],terrainZ(source.pos)}}
    elseif value.options[controls.sceneryCategory(source)] and source.texture then
      local face={}
      for _,p in ipairs(source.face) do face[#face+1]={p[1],p[2],terrainZ(p)} end
      items[#items+1]={texture=source.texture,face=face}
    end
  end
  if included==0 then return nil,last,0 end
  local proposal=api.type.SimpleProposal.new()
  local construction=api.type.SimpleProposal.ConstructionEntity.new()
  construction.fileName=sceneryName
  construction.params={items=items,seed=0}
  construction.transf=api.type.Mat4f.new()
  construction.name="OSM scenery "..dataset.id.." "..tostring(value.cursor)
  construction.playerEntity=api.engine.util.getPlayer()
  proposal.constructionsToAdd={construction}
  return proposal,last,included
end

function script.update(_userParams, state, _dt)
  local value=initialState(state)
  if not state:hasEventSubscriptions() then
    for _,name in ipairs({"osm.start","osm.pause","osm.resume","osm.retry","osm.skip","osm.status","osm.validate","osm.configure","osm.mapSize"}) do
      state:subscribeToEvent(name)
    end
  end
  -- GUI requests use the same native subscription mechanism as engine events.
  -- Keep this separate so saves started with revision 3 gain the new request.
  if not value.uiSnapshotSubscribed then
    state:subscribeToEvent("osm.ui.snapshot")
    value.uiSnapshotSubscribed=true
  end
  if not value.worldAuditSubscribed then
    state:subscribeToEvent("osm.verify")
    value.worldAuditSubscribed=true
  end
  if not value.placeNamesSubscribed then
    state:subscribeToEvent("osm.placeNames")
    value.placeNamesSubscribed=true
  end
  state:set(value)
  -- TF3 schedules postUpdate for scripts that return an update result.
  -- Return a serializable result only while there are build steps to run.
  if value.phase=="edges" or value.phase=="scenery" or value.phase=="labels" then return {} end
end

function script.handleEvent(_userParams, state, _src, id, name, param)
  if id~=eventId then return end
  local value=initialState(state)
  if name=="osm.placeNames" then
    value.notice,value.placeNamesPage=controls.placeNames(dataset,value)
    state:set(value); message(value.notice); return
  end
  if name=="osm.verify" then
    local ok,report=pcall(worldAudit.inspect,dataset,value)
    value.audit=ok and report or nil
    value.notice=ok and worldAudit.format(report) or ("World check failed: "..tostring(report))
    state:set(value); message(value.notice); return
  end
  if name=="osm.status" then
    value.notice="Progress refreshed."; state:set(value); status(value); return
  end
  if name=="osm.configure" then
    local ok,options=pcall(controls.configure,value.options,param,value.datasetId~=nil)
    if ok then value.options=options; value.notice="Import settings saved."
    else value.notice=tostring(options) end
    state:set(value); return
  end
  if name=="osm.validate" then
    local ok,err=pcall(preflight,value)
    value.notice=ok and "Map and vanilla resource checks passed." or tostring(err)
    state:set(value); message(value.notice); return
  end
  if name=="osm.mapSize" then
    local box=api.engine.terrain.getBoundingBox()
    value.notice=string.format("Map size: %.0f Ã— %.0f metres",box.max.x-box.min.x,box.max.y-box.min.y)
    state:set(value); message(value.notice); return
  end
  if name=="osm.start" then
    if value.datasetId then
      value.notice="Import already started in this save. Use resume/retry; use a new map for another dataset."
      state:set(value); message(value.notice)
      return
    end
    local ok,err=pcall(preflight,value)
    if not ok then value.notice=tostring(err); state:set(value); message(value.notice); return end
    value.datasetId=dataset.id; value.phase="scenery"; value.cursor=1; value.nodes={}
    value.notice="Import started."; value.error=nil
    message("Starting vanilla import. No existing roads, trees or towns will be deleted.")
  elseif name=="osm.pause" and (value.phase=="edges" or value.phase=="scenery" or value.phase=="labels") then
    value.resumePhase=value.phase; value.phase="paused"
    value.notice="Import paused. Progress is kept in this save."
  elseif name=="osm.resume" and value.phase=="paused" then
    if value.datasetId~=dataset.id then
      value.notice="Dataset changed; restore the original dataset before resuming."
      state:set(value); message(value.notice); return
    end
    value.phase=value.resumePhase
    value.notice="Import resumed."
  elseif name=="osm.retry" and value.phase=="error" then
    value.phase=value.resumePhase; value.error=nil
    value.notice="Retrying the failed step."
  elseif name=="osm.skip" and value.phase=="error" then
    if value.pendingOwnership or value.pendingScenery then
      value.notice="This accepted object already exists. Retry to complete ownership and naming; it cannot be skipped."
      state:set(value); message(value.notice); return
    end
    value.cursor=value.failedLast and value.failedLast+1 or value.cursor+1
    value.skipped=value.skipped+1
    value.phase=value.resumePhase; value.error=nil; value.failedLast=nil
    value.notice="Failed step skipped. Items in that step were not built."
  end
  state:set(value); status(value)
end

function script.postUpdate(_userParams, state, _dt, _result)
  local value=initialState(state)
  if value.phase~="edges" and value.phase~="scenery" and value.phase~="labels" then return end
  if value.datasetId~=dataset.id then
    value.resumePhase=value.phase; value.phase="error"; value.error="Dataset changed; restore it before continuing."
    state:set(value); status(value); return
  end
  if value.pendingOwnership then
    local ok,err=pcall(finishOwnership,value)
    if not ok then
      value.resumePhase=value.phase; value.phase="error"; value.error=tostring(err)
      state:set(value); status(value); return
    end
  end
  if value.pendingScenery then
    local ok,err=pcall(finishScenery,value)
    if not ok then
      value.resumePhase=value.phase; value.phase="error"; value.error=tostring(err)
      state:set(value); status(value); return
    end
  end
  value.cooldown=math.max(0,(value.cooldown or 0)-math.max(0,_dt or 0))
  if value.cooldown>0 then state:set(value); return end
  if value.phase=="scenery" and value.cursor>#dataset.scenery then
    value.phase="edges"; value.cursor=1; state:set(value)
  end
  if value.phase=="edges" then
    while value.cursor<=#dataset.edges and not value.options[dataset.edges[value.cursor].kind=="TRACK" and "railways" or "roads"] do
      value.cursor=value.cursor+1
    end
  end
  if value.phase=="edges" and value.cursor>#dataset.edges then
    value.phase="labels"; value.cursor=1; state:set(value)
  end
  if value.phase=="labels" and (not value.options.places or value.cursor>#dataset.labels) then
    value.phase="finished"; value.notice="Import finished. Check the map before continuing."; state:set(value); status(value); return
  end
  local phase=value.phase
  local ok,err=pcall(function()
    local proposal,last,included
    local edge
    if phase=="edges" then
      edge=dataset.edges[value.cursor]; proposal=edgeProposal(edge,value); last=value.cursor
    elseif phase=="labels" then proposal,last=labelProposal(value)
    else proposal,last,included=sceneryProposal(value) end
    if not proposal then value.cursor=last+1; state:set(value); return end
    value.failedLast=last
    local called=false
    api.cmd.sendCommand(api.cmd.makeWorldBuildProposalCmd(proposal,nil,false,false),function(res,success,resultEntities)
      called=true
      local callbackOk,callbackError=pcall(function()
      if success then
        if phase=="edges" then
          local built=res.proposal.proposal.addedSegments[1]
          value.nodes[edge.node0]=built.comp.node0; value.nodes[edge.node1]=built.comp.node1
          value.builtEdges=value.builtEdges+1
          -- Commit the accepted geometry before assigning ownership. If that
          -- separate command fails, Retry completes it without building twice.
          value.cursor=last+1; value.failedLast=nil
          value.pendingOwnership=built.entity
          state:set(value)
          finishOwnership(value)
        else
          local record={entities={},name=proposal.constructionsToAdd[1].name,phase=phase,first=value.cursor,last=last}
          for _,entry in ipairs(resultEntities or res.resultEntities or {}) do
            local entity=entry[1]
            if api.engine.entityExists(entity) and
              (api.engine.getComponent(entity,compType.CONSTRUCTION) or api.engine.getComponent(entity,compType.ASSET_GROUP)) then
              record.entities[#record.entities+1]=entity
            end
          end
          value.sceneryRecords=value.sceneryRecords or {}
          value.sceneryRecords[#value.sceneryRecords+1]=record
          if phase=="labels" then value.labels=(value.labels or 0)+1
          else value.builtScenery=value.builtScenery+included end
          value.cursor=last+1; value.failedLast=nil; value.pendingScenery=record
          state:set(value)
          finishScenery(value)
        end
        value.cursor=last+1; value.failedLast=nil
        value.cooldown=value.options.interval
      else
        value.resumePhase=phase; value.phase="error"
        local errors=res and res.resultProposalData and res.resultProposalData.errorState
        value.error=errors and table.concat(errors.messages or {},"; ") or "Game rejected the build proposal"
        status(value)
      end
      state:set(value)
      end)
      if not callbackOk then
        value.resumePhase=phase; value.phase="error"; value.error=tostring(callbackError)
        state:set(value); status(value)
      end
    end)
    assert(called,"Builder must execute in engine postUpdate state")
  end)
  if not ok then
    value.resumePhase=phase; value.phase="error"; value.error=tostring(err)
    state:set(value); status(value)
  elseif value.cursor%100==0 then status(value) end
end

-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return script
end

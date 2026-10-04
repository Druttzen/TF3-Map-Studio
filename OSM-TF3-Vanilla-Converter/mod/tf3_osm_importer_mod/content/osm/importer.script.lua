-- GPL-3.0. TF3 builder using its installed API definitions and vanilla resources.
local dataset = ug_require "druttzen_osm_vanilla::/osm/dataset.lua"
local controls = ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local worldAudit = ug_require "druttzen_osm_vanilla::/osm/world_audit.lua"
local water = ug_require "druttzen_osm_vanilla::/osm/water.lua"
local matcher = ug_require "druttzen_osm_vanilla::/osm/object_matcher.lua"
local towns = ug_require "druttzen_osm_vanilla::/osm/towns.lua"
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
    if #dataset.edges+#dataset.scenery+#dataset.labels>1000 and not (dataset.importOptions and dataset.importOptions.stepLimit~=nil) then
      value.options=controls.options(dataset.importOptions); value.options.stepLimit=100
      value.notice="Large dataset: automatic pause is set to 100 successful build steps per run. Inspect and save each run before resuming."
    end
  end
  value.options=controls.options(value.options or dataset.importOptions)
  value.waterSettings=water.settings(value.waterSettings)
  value.waterRecords=value.waterRecords or {}
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

local checkBudget=1000

local function newCheck(value,starting)
  assert(dataset.schema==1 and type(dataset.id)=="string" and dataset.id~="", "Prepare an OSM dataset with the converter first.")
  assert(#dataset.edges+#dataset.scenery+#dataset.labels>0, "Dataset has no supported roads, tracks or scenery.")
  local totals=controls.totals(dataset,value.options)
  assert(totals.edges+totals.scenery+totals.labels+totals.towns>0,"No dataset items match your import selections.")
  if totals.towns>0 then towns.checkLimit(totals.towns) end
  local box=api.engine.terrain.getBoundingBox()
  local width,height=box.max.x-box.min.x,box.max.y-box.min.y
  assert(type(dataset.size)=="table" and type(dataset.size[1])=="number" and type(dataset.size[2])=="number"
    and dataset.size[1]>0 and dataset.size[2]>0,"Invalid prepared map dimensions")
  assert(dataset.size[1]<=width+0.01 and dataset.size[2]<=height+0.01,
    string.format("Prepared area %.0f x %.0f m is larger than this map (%.0f x %.0f m). Reconvert OSM and heightmap with matching dimensions; do not scale only one file.",
      dataset.size[1],dataset.size[2],width,height))
  return {datasetId=dataset.id,starting=starting,returnPhase=value.phase,section=1,cursor=1,checked=0,
    total=#dataset.edges+#dataset.scenery+#dataset.labels,resources={},matches={},townNames={}}
end

local function advanceCheck(value,job,budget)
  assert(job.datasetId==dataset.id,"Dataset changed during checking; restore the original dataset.")
  local box=api.engine.terrain.getBoundingBox()
  local function checkPosition(p)
    assert(type(p)=="table" and type(p[1])=="number" and type(p[2])=="number"
      and p[1]==p[1] and p[2]==p[2] and math.abs(p[1])<math.huge and math.abs(p[2])<math.huge,
      "Invalid dataset coordinate")
    p=controls.position(p,box)
    assert(api.engine.terrain.isValidCoordinate(api.type.Vec2f.new(p[1],p[2])),
      string.format("Dataset coordinate x %.3f, y %.3f is outside this map; check converter map width and height.",p[1],p[2]))
  end
  local checked=job.resources
  local function resource(rep,name,matched)
    assert(type(name)=="string" and (name:sub(1,3)=="::/" or name=="druttzen_osm_vanilla::/osm/dirty_water.gtex"
      or matched and value.options.useActiveMods and name:match("^[^:]+::/")),"Unapproved resource reference: "..tostring(name))
    if not checked[name] then requireResource(rep,name); checked[name]=true end
  end
  local function checkEdge(edge)
    if value.options[edge.kind=="TRACK" and "railways" or "roads"] then
      assert(dataset.nodes[edge.node0] and dataset.nodes[edge.node1], "Invalid dataset node reference")
      checkPosition(dataset.nodes[edge.node0].pos)
      checkPosition(dataset.nodes[edge.node1].pos)
      for _,id in ipairs({edge.node0,edge.node1}) do
        local z=controls.elevation(dataset.nodes[id])
        if z~=nil then
          local limits=api.engine.mapgen.getMinMaxValidTerrainHeight()
          assert(z>=limits[1] and z<=limits[2],"Road/rail elevation is outside TF3's terrain height limits")
        end
      end
      resource(api.res.streetTemplateRep,edge.template)
      if edge.bridge then resource(api.res.bridgeTypeRep,bridgeName) end
      if edge.tunnel then resource(api.res.tunnelTypeRep,tunnelName) end
      if edge.heightGuide then checkPosition(edge.heightGuide.start); checkPosition(edge.heightGuide.finish) end
    end
  end
  local function checkScenery(item)
    if controls.selectedScenery(item,value.options) then
      if item.match then
        checkPosition(item.pos)
        local match=matcher.resolve(item,value.options); job.matches[job.cursor]=match
        if match.unmatched then return end
        item=controls.resolvedItem(item,job.cursor,{matches=job.matches})
      end
      if item.model then resource(api.res.modelRep,item.model,item.match~=nil) end
      if item.model then checkPosition(item.pos) end
      if item.texture then
        if item.category=="waterways" then
          assert(item.depth==0.5 and item.texture=="druttzen_osm_vanilla::/osm/dirty_water.gtex","Invalid shallow-water treatment")
          assert(#item.face==3,"Shallow water requires a prepared triangle")
        end
        resource(api.res.groundTextureRep,item.texture)
        assert(#item.face>=3,"Invalid ground polygon")
        for _,p in ipairs(item.face) do checkPosition(p) end
      end
    end
  end
  local lists={dataset.edges,dataset.scenery,dataset.labels}
  local used=0
  while job.section<=3 and used<budget do
    local list=lists[job.section]
    if job.cursor>#list then job.section=job.section+1; job.cursor=1
    else
      local item=list[job.cursor]
      if job.section==1 then checkEdge(item)
      elseif job.section==2 then checkScenery(item)
      else
        local mode=controls.placeMode(item,value.options)
        if mode then checkPosition(item.pos) end
        if mode=="town" then
          assert(not job.townNames[item.name],"Duplicate selected town name: "..item.name)
          job.townNames[item.name]=true; towns.check(item)
          towns.prepare({name=item.name,pos=controls.position(item.pos,box)},job.datasetId..":"..tostring(job.cursor))
        elseif mode=="marker" then resource(api.res.modelRep,markerName) end
      end
      job.cursor=job.cursor+1; job.checked=job.checked+1; used=used+1
    end
  end
  while job.section<=3 and job.cursor>#lists[job.section] do job.section=job.section+1; job.cursor=1 end
  if job.section<=3 then return false end
  local totals=controls.totals(dataset,value.options)
  if totals.scenery+totals.labels>0 then requireResource(api.res.constructionRep,sceneryName) end
  for _,warning in ipairs(controls.warnings(dataset)) do message(warning) end
  return true
end

local function beginImport(value)
  value.datasetId=dataset.id; value.phase="scenery"; value.cursor=1; value.nodes={}; value.runSteps=0
  -- Preserve older saves' height rules. New imports exclude construction
  -- alignments from their height reference, including future water basins.
  value.heightPolicy="base-v1"; value.heightReference={}; value.nodeHeights={}
  value.notice="Import started."; value.error=nil
  message("Starting selected OSM import with saved progress.")
end

local function finishCheck(value,job)
  value.check=nil; value.phase=job.returnPhase
  value.matches=job.matches; value.matchSummary=matcher.summary(job.matches)
  if job.starting then beginImport(value)
  else value.notice=string.format("Map/resource checks passed. Object matches: %d vanilla, %d active mod, %d without a safe match (left unbuilt).",
    value.matchSummary.vanilla,value.matchSummary.mods,value.matchSummary.unmatched) end
end

local function requestCheck(value,starting)
  local job=newCheck(value,starting)
  if job.total<=checkBudget then
    assert(advanceCheck(value,job,checkBudget)); finishCheck(value,job)
  else
    value.check=job; value.phase="checking"
    value.notice="Checking map and resources in small steps. Pause cancels the check without building."
  end
end

local function terrainZ(pos)
  pos=controls.position(pos,api.engine.terrain.getBoundingBox())
  local xy = api.type.Vec2f.new(pos[1],pos[2])
  assert(api.engine.terrain.isValidCoordinate(xy), "Coordinate outside this map; check converter map size.")
  return api.engine.terrain.getHeightAt(xy)
end

local function referenceHeight(value,pos)
  if value.heightPolicy~="base-v1" then return terrainZ(pos) end
  pos=controls.position(pos,api.engine.terrain.getBoundingBox())
  local key=string.format("%.6f,%.6f",pos[1],pos[2])
  value.heightReference=value.heightReference or {}
  local z=value.heightReference[key]
  if z==nil then
    local xy=api.type.Vec2f.new(pos[1],pos[2])
    assert(api.engine.terrain.isValidCoordinate(xy),"Coordinate outside this map")
    z=api.engine.terrain.getBaseHeightAt(xy)
    assert(controls.finiteHeight(z),"TF3 returned an invalid base terrain height")
    value.heightReference[key]=z
  end
  return z
end

local function nodePosition(edge, nodeId, ending,value)
  local p = controls.position(dataset.nodes[nodeId].pos,api.engine.terrain.getBoundingBox())
  local explicit=value.heightPolicy=="base-v1" and controls.elevation(dataset.nodes[nodeId]) or nil
  local z = explicit or referenceHeight(value,p)
  if edge.heightGuide and explicit==nil then
    local guide = edge.heightGuide
    local t = ending and guide.t1 or guide.t0
    z = referenceHeight(value,guide.start)*(1-t)+referenceHeight(value,guide.finish)*t
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
  local p0, p1 = nodePosition(edge,edge.node0,false,value), nodePosition(edge,edge.node1,true,value)
  local id0, id1 = existingNode(value,edge.node0,p0), existingNode(value,edge.node1,p1)
  if id0 then p0=api.engine.getComponent(id0,compType.BASE_NODE).position end
  if id1 then p1=api.engine.getComponent(id1,compType.BASE_NODE).position end
  assert(controls.finiteHeight(p0.z) and controls.finiteHeight(p1.z),"Invalid road/rail height")
  assert(math.abs(p1.x-p0.x)+math.abs(p1.y-p0.y)>0.000001,"Road/rail segment has coincident endpoints")
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
  if value.pendingHeightNodes then
    value.nodeHeights=value.nodeHeights or {}
    for _,id in ipairs(value.pendingHeightNodes) do
      local node=api.engine.getComponent(value.nodes[id],compType.BASE_NODE)
      assert(node and controls.finiteHeight(node.position.z),"Accepted road/rail node has no valid height")
      value.nodeHeights[id]=node.position.z
    end
    value.pendingHeightNodes=nil
  end
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
  local pos=controls.position(source.pos,api.engine.terrain.getBoundingBox())
  local proposal=api.type.SimpleProposal.new()
  local construction=api.type.SimpleProposal.ConstructionEntity.new()
  construction.fileName=sceneryName
  construction.params={items={{model=markerName,rotation=0,
    pos={pos[1],pos[2],terrainZ(pos)}}},seed=0}
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
  local scanned=0
  -- Scan by original dataset index, so progress remains resumable when the
  -- batch size changes. A batch counts selected items, not excluded ones.
  while last<#dataset.scenery and included<value.options.batchSize and scanned<checkBudget do
    last=last+1
    scanned=scanned+1
    if controls.selectedScenery(dataset.scenery[last],value.options) and controls.resolvedItem(dataset.scenery[last],last,value) then included=included+1 end
  end
  -- A preparation failure belongs to this explicit candidate batch, even if
  -- terrain/resource checks stop before a native proposal can be submitted.
  value.failedLast=last
  for i=value.cursor,last do
    local source=controls.resolvedItem(dataset.scenery[i],i,value)
    if source and controls.selectedScenery(source,value.options) and source.model then
      requireResource(api.res.modelRep,source.model)
      local pos=controls.position(source.pos,api.engine.terrain.getBoundingBox())
      items[#items+1]={model=source.model,rotation=source.rotation,
        pos={pos[1],pos[2],terrainZ(pos)}}
    elseif source and controls.selectedScenery(source,value.options) and source.texture then
      local face={}
      local shallow=source.category=="waterways"
      if shallow then water.checkEmpty(source.face,20) end
      for _,sourcePos in ipairs(source.face) do
        local p=controls.position(sourcePos,api.engine.terrain.getBoundingBox())
        local z=terrainZ(p)
        if shallow then
          value.shallowHeightReference=value.shallowHeightReference or {}
          local key=string.format("%.6f,%.6f",p[1],p[2])
          local height=value.shallowHeightReference[key]
          if height==nil then height=api.engine.terrain.getBaseHeightAt(api.type.Vec2f.new(p[1],p[2])); value.shallowHeightReference[key]=height end
          local limits=api.engine.mapgen.getMinMaxValidTerrainHeight()
          assert(controls.finiteHeight(height) and height-0.5>=limits[1] and height<=limits[2],"Invalid shallow-water terrain height")
          z=height-0.5
        end
        face[#face+1]={p[1],p[2],z}
      end
      items[#items+1]={texture=source.texture,face=face,depth=shallow and 0.5 or nil}
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

local function proposedModelPositions(value,phase,last,proposal)
  if phase=="edges" then return nil end
  local items=proposal.constructionsToAdd[1].params.items
  local positions={}
  local function save(index,item)
    assert(item and item.model and type(item.pos)=="table" and controls.finiteHeight(item.pos[3]),
      "A scenery model has no finite prepared world height")
    positions[index]={item.pos[1],item.pos[2],item.pos[3]}
  end
  if phase=="labels" then save(value.cursor,items[1])
  else
    local itemIndex=0
    for index=value.cursor,last do
      local source=controls.resolvedItem(dataset.scenery[index],index,value)
      if source and controls.selectedScenery(source,value.options) and (source.model or source.texture) then
        itemIndex=itemIndex+1
        if source.model then save(index,items[itemIndex]) end
      end
    end
  end
  return positions
end

local function waterOwnership(value)
  local record=value.waterRecord
  assert(record and #record.entities>0,"TF3 returned no water entity; inspect this test save before any further build")
  for _,entity in ipairs(record.entities) do
    assert(api.engine.entityExists(entity),"Accepted test water entity is missing; inspect this test save")
    api.cmd.sendCommand(api.cmd.makeEntitySetPlayerCmd(entity,api.engine.util.getPlayer()))
    local owner=api.engine.getComponent(entity,compType.PLAYER_OWNED)
    assert(owner and owner.player==api.engine.util.getPlayer(),"Test water ownership is incomplete; Build retries ownership without building again")
  end
end

local function buildWater(value,state)
  local p=value.waterJob
  if value.waterRecord then waterOwnership(value); value.waterJob=nil; value.notice="Test water ownership completed. No duplicate built."; state:set(value); return end
  local proposal=water.proposal(p)
  local called,callbackError=false,nil
  api.cmd.sendCommand(api.cmd.makeWorldBuildProposalCmd(proposal,nil,false,false),function(res,success,entities)
    called=true
    local ok,err=pcall(function()
    if not success then
      local errors=res and res.resultProposalData and res.resultProposalData.errorState
      error(errors and table.concat(errors.messages or {},"; ") or "TF3 rejected test water")
    end
    local record={entities={},settings=p,navigable=false}
    for _,entry in ipairs(entities or res.resultEntities or {}) do
      local entity=entry[1]
      if api.engine.entityExists(entity) and (api.engine.getComponent(entity,compType.CONSTRUCTION) or api.engine.getComponent(entity,compType.ASSET_GROUP)) then record.entities[#record.entities+1]=entity end
    end
    -- Commit every accepted result before fallible ownership work. Never
    -- replay an accepted construction after a save/reload or callback failure.
    value.waterRecord=record; state:set(value)
    waterOwnership(value); value.waterJob=nil
    value.notice="Experimental test water built. Inspect its surface, basin and save/reload in TF3. Decorative water is not navigable."
    state:set(value)
    end)
    if not ok then callbackError=tostring(err) end
  end)
  assert(called,"Test water builder must execute in engine postUpdate state")
  assert(not callbackError,callbackError)
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
  if not value.waterSupportSubscribed then
    state:subscribeToEvent("osm.waterSupport"); value.waterSupportSubscribed=true
  end
  if not value.waterTestSubscribed then
    for _,name in ipairs({"osm.waterConfigure","osm.waterCheck","osm.waterBuild"}) do state:subscribeToEvent(name) end
    value.waterTestSubscribed=true
  end
  state:set(value)
  -- TF3 schedules postUpdate for scripts that return an update result.
  if not value.waterNextSubscribed then
    state:subscribeToEvent("osm.waterNext"); value.waterNextSubscribed=true; state:set(value)
  end
  -- Return a serializable result only while there are build steps to run.
  if value.waterJob or value.phase=="checking" or value.phase=="edges" or value.phase=="scenery" or value.phase=="labels" then return {} end
end

function script.handleEvent(_userParams, state, _src, id, name, param)
  if id~=eventId then return end
  local value=initialState(state)
  if value.waterJob and name~="osm.status" and name~="osm.waterSupport" then
    value.notice="Test water build is pending; wait for completion before another command."; state:set(value); return
  end
  if value.check and name~="osm.pause" and name~="osm.status" and name~="osm.mapSize" and name~="osm.placeNames" then
    value.notice="Map checks are running. Pause to cancel before changing selections or starting another check."
    state:set(value); return
  end
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
      if not value.datasetId then value.matches=nil; value.matchSummary=nil end
    else value.notice=tostring(options) end
    state:set(value); return
  end
  if name=="osm.validate" then
    local ok,err=pcall(requestCheck,value,false)
    if not ok then value.notice=tostring(err) end
    state:set(value); message(value.notice); return
  end
  if name=="osm.mapSize" then
    local box=api.engine.terrain.getBoundingBox()
    value.notice=string.format("Map size: %.0f x %.0f metres",box.max.x-box.min.x,box.max.y-box.min.y)
    state:set(value); message(value.notice); return
  end
  if name=="osm.waterSupport" then
    local ok,terrain=pcall(function()
      return api.engine.getComponent(api.engine.util.getWorld(),compType.TERRAIN)
    end)
    value.notice=controls.waterSupport(ok and terrain or nil)
    state:set(value); message(value.notice); return
  end
  if name=="osm.waterNext" then
    local ok,err=pcall(function()
      assert(controls.enabled("waterBuild",value) and value.waterRecord and value.waterRecord.complete,"Complete the current water patch before preparing another")
      assert(#value.waterRecords<99,"Experimental water test limit reached: use another test save")
      value.waterRecords[#value.waterRecords+1]=value.waterRecord
      value.waterRecord=nil
    end)
    value.notice=ok and "Accepted water retained. Choose another position and height before building the next patch." or tostring(err)
    state:set(value); message(value.notice); return
  end
  if name=="osm.waterConfigure" or name=="osm.waterCheck" or name=="osm.waterBuild" then
    if not controls.enabled("waterBuild",value) then value.notice="Pause or finish the import before testing local water."; state:set(value); return end
    local ok,result=pcall(function()
      if name=="osm.waterConfigure" then
        assert(not value.waterRecord,"Water settings are locked for the accepted patch; complete ownership, then prepare another patch")
        value.waterSettings=water.configure(value.waterSettings,param)
        return "Test water settings saved. Nothing built."
      end
      if name=="osm.waterCheck" then water.checkRecorded(value.waterSettings,value.waterRecords); water.check(value.waterSettings); return "Test water area checked. No water or terrain changed." end
      if value.waterRecord then
        assert(not value.waterRecord.complete,"Water is already recorded. Prepare another patch before building at another position.")
      end
      water.checkRecorded(value.waterSettings,value.waterRecords)
      value.waterJob=water.configure(nil,value.waterSettings)
      return "Test water queued for the next engine build step."
    end)
    value.notice=tostring(result); state:set(value); message(value.notice); return
  end
  if name=="osm.start" then
    if value.datasetId then
      value.notice="Import already started in this save. Use resume/retry; use a new map for another dataset."
      state:set(value); message(value.notice)
      return
    end
    local ok,err=pcall(requestCheck,value,true)
    if not ok then value.notice=tostring(err); state:set(value); message(value.notice); return end
  elseif name=="osm.pause" and value.check then
    value.phase=value.check.returnPhase; value.check=nil
    value.notice="Map check cancelled. No objects were built by this check."
  elseif name=="osm.pause" and (value.phase=="edges" or value.phase=="scenery" or value.phase=="labels") then
    value.resumePhase=value.phase; value.phase="paused"
    value.notice="Import paused. Progress is kept in this save."
  elseif name=="osm.resume" and value.phase=="paused" then
    if value.datasetId~=dataset.id then
      value.notice="Dataset changed; restore the original dataset before resuming."
      state:set(value); message(value.notice); return
    end
    value.phase=value.resumePhase
    value.runSteps=0
    value.notice="Import resumed."
  elseif name=="osm.retry" and value.phase=="error" then
    if value.datasetId~=dataset.id then
      value.notice="Dataset changed; restore the original dataset before retrying."
      state:set(value); message(value.notice); return
    end
    if value.acceptedUnjournalled or value.errorKind=="command_state" then
      value.notice="The previous build outcome cannot be safely replayed. Keep this save for inspection."
      state:set(value); message(value.notice); return
    end
    value.phase=value.resumePhase; value.error=nil; value.errorKind=nil
    value.notice="Retrying the failed step."
  elseif name=="osm.skip" and value.phase=="error" then
    if value.datasetId~=dataset.id or value.errorKind=="dataset_identity" then
      value.notice="A dataset identity failure cannot skip source items. Restore the original dataset, then Retry."
      state:set(value); message(value.notice); return
    end
    if value.pendingOwnership or value.pendingScenery or value.pendingTown then
      value.notice="This accepted object already exists. Retry to complete ownership and naming; it cannot be skipped."
      state:set(value); message(value.notice); return
    end
    if not controls.skippable(value) or value.failedFirst~=value.cursor
      or type(value.failedLast)~="number" or value.failedLast<value.cursor then
      value.notice="This state error has no safely identified rejected job to skip. Retry or inspect this save."
      state:set(value); message(value.notice); return
    end
    value.cursor=value.failedLast+1
    value.skipped=value.skipped+1
    value.phase=value.resumePhase; value.error=nil; value.errorKind=nil; value.failedFirst=nil; value.failedLast=nil
    value.notice="Failed step skipped. Items in that step were not built."
  end
  state:set(value); status(value)
end

function script.postUpdate(_userParams, state, _dt, _result)
  local value=initialState(state)
  if value.waterJob then
    local ok,err=pcall(buildWater,value,state)
    if not ok then
      value.waterJob=nil; value.notice="Test water stopped: "..tostring(err)
    elseif value.waterRecord then value.waterRecord.complete=true end
    state:set(value); return
  end
  if value.phase=="checking" then
    local job=value.check
    if not job then value.phase="ready"; value.notice="Missing map check; start the check again."; state:set(value); return end
    local ok,done=pcall(advanceCheck,value,job,checkBudget)
    if not ok then
      value.phase=job.returnPhase; value.check=nil
      value.notice=string.format("Map check stopped after %d/%d items: %s",job.checked,job.total,tostring(done))
      message(value.notice)
    elseif done then finishCheck(value,job); message(value.notice)
    else value.notice=string.format("Checking map and resources: %d/%d items (%.1f%%). No objects built.",job.checked,job.total,100*job.checked/job.total) end
    state:set(value); return
  end
  if value.phase~="edges" and value.phase~="scenery" and value.phase~="labels" then return end
  if value.datasetId~=dataset.id then
    value.resumePhase=value.phase; value.phase="error"; value.error="Dataset changed; restore it before continuing."
    value.errorKind="dataset_identity"; value.failedFirst=nil; value.failedLast=nil
    state:set(value); status(value); return
  end
  if value.pendingOwnership then
    local ok,err=pcall(finishOwnership,value)
    if not ok then
      value.resumePhase=value.phase; value.phase="error"; value.error=tostring(err)
      value.errorKind="finalization"
      state:set(value); status(value); return
    end
  end
  if value.pendingScenery then
    local ok,err=pcall(finishScenery,value)
    if not ok then
      value.resumePhase=value.phase; value.phase="error"; value.error=tostring(err)
      value.errorKind="finalization"
      state:set(value); status(value); return
    end
  end
  if value.pendingTown then
    local ok,err=pcall(towns.finalize,value)
    if not ok then
      value.resumePhase=value.phase; value.phase="error"; value.error=tostring(err); value.errorKind="finalization"
      state:set(value); status(value); return
    end
  end
  value.cooldown=math.max(0,(value.cooldown or 0)-math.max(0,_dt or 0))
  if value.cooldown>0 then state:set(value); return end
  if value.phase=="scenery" and value.cursor>#dataset.scenery then
    value.phase="edges"; value.cursor=1; state:set(value)
  end
  if value.phase=="edges" then
    local scanned=0
    while value.cursor<=#dataset.edges and not value.options[dataset.edges[value.cursor].kind=="TRACK" and "railways" or "roads"] and scanned<checkBudget do
      value.cursor=value.cursor+1
      scanned=scanned+1
    end
    if value.cursor<=#dataset.edges and not value.options[dataset.edges[value.cursor].kind=="TRACK" and "railways" or "roads"] then state:set(value); return end
  end
  if value.phase=="edges" and value.cursor>#dataset.edges then
    value.phase="labels"; value.cursor=1; state:set(value)
  end
  if value.phase=="labels" then
    local scanned=0
    while value.cursor<=#dataset.labels and not controls.placeMode(dataset.labels[value.cursor],value.options) and scanned<checkBudget do
      value.cursor=value.cursor+1; scanned=scanned+1
    end
    if value.cursor<=#dataset.labels and not controls.placeMode(dataset.labels[value.cursor],value.options) then state:set(value); return end
  end
  if value.phase=="labels" and value.cursor>#dataset.labels then
    value.phase="finished"; value.notice="Import finished. Check the map before continuing."; state:set(value); status(value); return
  end
  if value.options.stepLimit>0 and (value.runSteps or 0)>=value.options.stepLimit then
    value.resumePhase=value.phase; value.phase="paused"
    value.notice=string.format("Automatically paused after %d successful build steps. Save and inspect the map; Resume starts another run.",value.runSteps)
    state:set(value); status(value); return
  end
  local phase=value.phase
  local submitted,accepted=false,false
  value.failedFirst=value.cursor; value.failedLast=value.cursor
  local ok,err=pcall(function()
    if phase=="labels" and controls.placeMode(dataset.labels[value.cursor],value.options)=="town" then
      local source=dataset.labels[value.cursor]
      local pos=controls.position(source.pos,api.engine.terrain.getBoundingBox())
      towns.build(value,state,{name=source.name,pos=pos})
      return
    end
    local proposal,last,included
    local edge
    if phase=="edges" then
      edge=dataset.edges[value.cursor]; proposal=edgeProposal(edge,value); last=value.cursor
    elseif phase=="labels" then proposal,last=labelProposal(value)
    else proposal,last,included=sceneryProposal(value) end
    if not proposal then value.cursor=last+1; value.failedFirst=nil; value.failedLast=nil; state:set(value); return end
    -- Preserve the exact world XYZ supplied to our identity-transformed native
    -- construction. Publish this evidence only after acceptance, before any
    -- separate ownership/name commands can fail. Older journals stay unchanged.
    local modelPositions=proposedModelPositions(value,phase,last,proposal)
    value.failedLast=last
    local called=false
    submitted=true
    api.cmd.sendCommand(api.cmd.makeWorldBuildProposalCmd(proposal,nil,false,false),function(res,success,resultEntities)
      called=true
      local callbackOk,callbackError=pcall(function()
      if success then
        accepted=true
        -- An accepted command must never be replayed if result decoding fails
        -- before its native entities can be journalled.
        value.acceptedUnjournalled=true; state:set(value)
        value.runSteps=(value.runSteps or 0)+1
        if phase=="edges" then
          local built=res.proposal.proposal.addedSegments[1]
          value.nodes[edge.node0]=built.comp.node0; value.nodes[edge.node1]=built.comp.node1
          if value.heightPolicy=="base-v1" then
            value.pendingHeightNodes={edge.node0,edge.node1}
          end
          value.builtEdges=value.builtEdges+1
          -- Commit the accepted geometry before assigning ownership. If that
          -- separate command fails, Retry completes it without building twice.
          value.cursor=last+1; value.failedFirst=nil; value.failedLast=nil
          value.pendingOwnership=built.entity
          value.acceptedUnjournalled=nil
          state:set(value)
          finishOwnership(value)
        else
          local record={entities={},name=proposal.constructionsToAdd[1].name,phase=phase,first=value.cursor,last=last,
            modelJournalSchema=1,modelPositions=modelPositions}
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
          value.cursor=last+1; value.failedFirst=nil; value.failedLast=nil; value.pendingScenery=record
          value.acceptedUnjournalled=nil
          state:set(value)
          finishScenery(value)
        end
        value.cursor=last+1; value.failedFirst=nil; value.failedLast=nil; value.errorKind=nil
        value.cooldown=value.options.interval
      else
        value.resumePhase=phase; value.phase="error"
        value.errorKind="proposal_rejected"
        local errors=res and res.resultProposalData and res.resultProposalData.errorState
        value.error=errors and table.concat(errors.messages or {},"; ") or "Game rejected the build proposal"
        status(value)
      end
      state:set(value)
      end)
      if not callbackOk then
        value.resumePhase=phase; value.phase="error"; value.error=tostring(callbackError)
        value.errorKind=(value.pendingOwnership or value.pendingScenery) and "finalization" or "accepted_state"
        state:set(value); status(value)
      end
    end)
    assert(called,"Builder must execute in engine postUpdate state")
  end)
  if not ok then
    value.resumePhase=phase; value.phase="error"; value.error=tostring(err)
    value.errorKind=accepted and "accepted_state" or submitted and "command_state" or "preparation"
    state:set(value); status(value)
  elseif value.cursor%100==0 then status(value) end
end

-- TF3 .script resources expose callbacks through data(), not a module return.
function data()
  return script
end

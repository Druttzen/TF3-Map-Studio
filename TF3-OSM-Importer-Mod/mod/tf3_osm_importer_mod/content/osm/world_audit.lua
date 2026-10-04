-- GPL-3.0. Read-only checks against the installed TF3 entity/component API.
local controls = ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local audit = {}
local sceneryName = "druttzen_osm_vanilla::/osm/scenery.con"
local markerName = "::/assets/markers/marker_locate.mdl"
local bridgeName = "::/infrastructure/bridge/steel.bridge"
local tunnelName = "::/infrastructure/tunnel/tunnel_c.tunnel"

local function coordinate(p,box)
  if not p or type(p[1])~="number" or type(p[2])~="number" then return nil end
  p=controls.position(p,box)
  return string.format("%.6f,%.6f",p[1],p[2])
end

local function itemKey(item,box)
  if item.model then
    local pos=coordinate(item.pos,box)
    local rotation=item.rotation or 0
    if type(rotation)~="number" then return nil end
    return pos and "model|"..item.model.."|"..pos.."|"..string.format("%.6f",rotation) or nil
  end
  if item.texture and item.face then
    local points={}
    for _,p in ipairs(item.face) do
      local pos=coordinate(p,box)
      if not pos then return nil end
      points[#points+1]=pos
    end
    local suffix=""
    if item.depth~=nil then
      if not controls.finiteHeight(item.depth) then return nil end
      suffix="|depth:"..string.format("%.6f",item.depth)
    end
    return "surface|"..item.texture.."|"..table.concat(points,";")..suffix
  end
  return nil
end

local function pairKey(a,b)
  if a>b then a,b=b,a end
  return tostring(a)..":"..tostring(b)
end

local function addLink(graph,a,b)
  graph[a]=graph[a] or {}; graph[b]=graph[b] or {}
  graph[a][b]=true; graph[b][a]=true
end

local function components(graph)
  local seen,count={},0
  for start in pairs(graph) do
    if not seen[start] then
      count=count+1
      local queue={start}; seen[start]=true
      local cursor=1
      while queue[cursor] do
        for neighbour in pairs(graph[queue[cursor]]) do
          if not seen[neighbour] then
            seen[neighbour]=true; queue[#queue+1]=neighbour
          end
        end
        cursor=cursor+1
      end
    end
  end
  return count
end

function audit.inspect(dataset,value)
  value=value or {}
  local box=api.engine.terrain.getBoundingBox()
  local rawCoordinate,rawItemKey=coordinate,itemKey
  local function coordinate(p) return rawCoordinate(p,box) end
  local function itemKey(item) return rawItemKey(item,box) end
  local T=api.type.ComponentType
  local enums=api.type["enum"]
  local modes=enums.TransportMode
  local player=api.engine.util.getPlayer()
  local options=controls.options(value.options or dataset.importOptions)
  local report={
    ok=false,partial=false,missingModelHeights=0,phase=value.phase or "ready",datasetId=value.datasetId,
    skipped=value.skipped or 0,problems={},problemCounts={},degrees={},
    expected={nodes=0,edges=0,usableEdges=0,streets=0,tracks=0,scenery=0,models=0,surfaces=0,labels=0,components=0},
    current={nodes=0,edges=0,usableEdges=0,streets=0,tracks=0,scenery=0,models=0,surfaces=0,labels=0,components=0,constructions=0,assetGroups=0},
    counters={edges=value.builtEdges or 0,scenery=value.builtScenery or 0,labels=value.labels or 0},
    limitations={
      "Ground surfaces are checked as saved construction items; inspect their appearance on the map.",
      "Vehicle lanes and imported road/rail graph connectivity are checked; actual vehicle routes remain untested.",
      "Place names are stored in the importer journal; use Show place names. Native asset windows may not display them.",
    },
  }
  local function problem(kind,text)
    report.problems[#report.problems+1]=text
    report.problemCounts[kind]=(report.problemCounts[kind] or 0)+1
  end
  local function owned(entity,label)
    local owner=api.engine.getComponent(entity,T.PLAYER_OWNED)
    if not owner or owner.player~=player then
      problem("ownership",label.." is not owned by the current player.")
    end
  end

  if report.phase~="finished" then problem("progress","Import is "..report.phase.."; verification requires a finished import.") end
  if value.datasetId~=dataset.id then problem("progress","Saved import does not match the current dataset.") end
  if report.skipped>0 then problem("progress",tostring(report.skipped).." import jobs were skipped.") end

  local expectedNodes,expectedEdges,expectedGraph={},{},{}
  for index,edge in ipairs(dataset.edges or {}) do
    if options[edge.kind=="TRACK" and "railways" or "roads"] then
      expectedEdges[#expectedEdges+1]={source=edge,index=index}
      expectedNodes[edge.node0]=true; expectedNodes[edge.node1]=true
      addLink(expectedGraph,edge.node0,edge.node1)
      report.expected.edges=report.expected.edges+1
      local kind=edge.kind=="TRACK" and "tracks" or "streets"
      report.expected[kind]=report.expected[kind]+1
      for _,id in ipairs({edge.node0,edge.node1}) do
        report.degrees[id]=report.degrees[id] or {expected=0,current=0,streets=0,tracks=0}
        report.degrees[id].expected=report.degrees[id].expected+1
      end
    end
  end
  report.expected.components=components(expectedGraph)
  report.expected.usableEdges=report.expected.edges
  local liveNodes,nodeIds={},value.nodes or {}
  for id in pairs(expectedNodes) do
    report.expected.nodes=report.expected.nodes+1
    local entity=nodeIds[id]
    local node
    if type(entity)=="number" and entity>=0 and api.engine.entityExists(entity) then
      node=api.engine.getComponent(entity,T.BASE_NODE)
    end
    if not node then
      problem("missingNodes","Imported node "..tostring(id).." is missing.")
    else
      report.current.nodes=report.current.nodes+1
      if liveNodes[entity] then problem("wrongNodes","Imported nodes share the same world entity: "..tostring(id)..".") end
      liveNodes[entity]=id
      if value.heightPolicy=="base-v1" then
        local z=value.nodeHeights and value.nodeHeights[id]
        if not controls.finiteHeight(z) then
          problem("wrongNodeHeights","Imported node "..tostring(id).." has no saved accepted height.")
        elseif not node.position or not controls.finiteHeight(node.position.z) or math.abs(node.position.z-z)>0.01 then
          problem("wrongNodeHeights","Imported node "..tostring(id).." has moved from its accepted road/rail height.")
        end
      end
      local source=dataset.nodes and dataset.nodes[id]
      local expectedPos=source and source.pos and controls.position(source.pos,box)
      if expectedPos and node.position and
        (math.abs(node.position.x-expectedPos[1])>0.01 or math.abs(node.position.y-expectedPos[2])>0.01) then
        problem("wrongNodes","Imported node "..tostring(id).." has moved from its dataset position.")
      end
    end
  end

  -- Only edges between this import's selected, recorded nodes enter the audit.
  local pairsToCheck={}
  for _,entry in ipairs(expectedEdges) do
    local a,b=nodeIds[entry.source.node0],nodeIds[entry.source.node1]
    if a and b and liveNodes[a] and liveNodes[b] then pairsToCheck[pairKey(a,b)]=true end
  end
  local candidates,actualGraph={},{},{}
  -- BASE_EDGE cannot be enumerated with getEntitiesWithComponent in TF3.
  -- Query only segments incident to this import's recorded live nodes.
  local edgeEntities,seenEdges={},{}
  for nodeEntity in pairs(liveNodes) do
    for _,entity in ipairs(api.engine.system.streetSystem.getNodeSegments(nodeEntity)) do
      if not seenEdges[entity] then
        seenEdges[entity]=true; edgeEntities[#edgeEntities+1]=entity
      end
    end
  end
  for _,entity in ipairs(edgeEntities) do
    if api.engine.entityExists(entity) then
      local edge=api.engine.getComponent(entity,T.BASE_EDGE)
      if edge and liveNodes[edge.node0] and liveNodes[edge.node1] and pairsToCheck[pairKey(edge.node0,edge.node1)] then
        local key=pairKey(edge.node0,edge.node1)
        candidates[key]=candidates[key] or {}
        candidates[key][#candidates[key]+1]={entity=entity,comp=edge}
        report.current.edges=report.current.edges+1
        local kind=edge.roadType==enums.RoadType.TRACK and "tracks" or "streets"
        report.current[kind]=report.current[kind]+1
        local network=api.engine.getComponent(entity,T.TRANSPORT_NETWORK)
        local usable=false
        for _,lane in ipairs(network and network.edges or {}) do
          local allowed=lane.transportModes or {}
          if kind=="tracks" then
            usable=allowed[modes.TRAIN] or allowed[modes.ELECTRIC_TRAIN] or false
          else
            usable=allowed[modes.CAR] or allowed[modes.BUS] or allowed[modes.TRUCK]
              or allowed[modes.TRAM] or allowed[modes.ELECTRIC_TRAM] or false
          end
          if usable then break end
        end
        if usable then report.current.usableEdges=report.current.usableEdges+1
        else problem("vehicleLanes","Imported "..(kind=="tracks" and "rail" or "road").." edge "..tostring(entity).." has no vehicle-compatible transport lane.") end
        addLink(actualGraph,edge.node0,edge.node1)
        for _,id in ipairs({liveNodes[edge.node0],liveNodes[edge.node1]}) do
          report.degrees[id].current=report.degrees[id].current+1
          report.degrees[id][kind]=report.degrees[id][kind]+1
        end
        owned(entity,"Imported edge "..tostring(entity))
      end
    end
  end
  report.current.components=components(actualGraph)
  local used={}
  for _,entry in ipairs(expectedEdges) do
    local source=entry.source
    local a,b=nodeIds[source.node0],nodeIds[source.node1]
    local expectedType=source.bridge and enums.BaseEdgeType.BRIDGE
      or source.tunnel and enums.BaseEdgeType.TUNNEL or enums.BaseEdgeType.NORMAL
    local roadType=source.kind=="TRACK" and enums.RoadType.TRACK or enums.RoadType.STREET
    local available=a and b and liveNodes[a] and liveNodes[b] and candidates[pairKey(a,b)] or {}
    local match,fallback
    for _,candidate in ipairs(available or {}) do
      if not used[candidate.entity] then
        fallback=fallback or candidate
        local edge=candidate.comp
        if edge.node0==a and edge.node1==b and edge.roadTemplate==source.template
          and edge.roadType==roadType and edge.type==expectedType then match=candidate; break end
      end
    end
    match=match or fallback
    if not match then
      problem("missingEdges","Dataset edge "..tostring(entry.index).." is missing between its recorded nodes.")
    else
      used[match.entity]=true
      local edge=match.comp
      if edge.node0~=a or edge.node1~=b then problem("wrongEdges","Dataset edge "..tostring(entry.index).." has reversed endpoints.") end
      if edge.roadTemplate~=source.template then problem("wrongEdges","Dataset edge "..tostring(entry.index).." uses the wrong road or rail template.") end
      if edge.roadType~=roadType or edge.type~=expectedType then problem("wrongEdges","Dataset edge "..tostring(entry.index).." has the wrong road, rail, bridge or tunnel type.") end
      if source.bridge or source.tunnel then
        local rep=source.bridge and api.res.bridgeTypeRep or api.res.tunnelTypeRep
        local name=source.bridge and bridgeName or tunnelName
        local index=rep.find(name)
        if type(index)~="number" or index<0 or edge.typeIndex~=index then
          problem("wrongEdges","Dataset edge "..tostring(entry.index).." uses the wrong bridge or tunnel resource.")
        end
      end
      if edge.roadDevelopmentLocked~=true then problem("wrongEdges","Dataset edge "..tostring(entry.index).." is not protected from town road changes.") end
    end
  end
  for _,entries in pairs(candidates) do
    for _,entry in ipairs(entries) do
      if not used[entry.entity] then problem("wrongEdges","Extra edge "..tostring(entry.entity).." shares an imported endpoint pair.") end
    end
  end

  local expectedItems,foundItems,labelNames={},{},{}
  local savedPositions={scenery={},labels={}}
  local schemas={scenery={},labels={}}
  for _,record in ipairs(value.sceneryRecords or {}) do
    if savedPositions[record.phase] then
      for index=record.first or 1,record.last or record.first or 0 do
        schemas[record.phase][index]=record.modelJournalSchema
        local saved=record.modelPositions and record.modelPositions[index]
        if saved then
          if savedPositions[record.phase][index] then problem("wrongScenery","Duplicate saved model position in importer journal.") end
          savedPositions[record.phase][index]=saved
        end
      end
    end
  end
  local positionsByKey={}
  local function expectPosition(item,key,index,phase)
    local p=savedPositions[phase][index]
    if type(p)=="table" and controls.finiteHeight(p[1]) and controls.finiteHeight(p[2]) and controls.finiteHeight(p[3]) then
      local xy=controls.position(item.pos,box)
      if math.abs(p[1]-xy[1])>0.01 or math.abs(p[2]-xy[2])>0.01 then
        problem("wrongScenery","Saved accepted model position differs from its source item.")
      end
      positionsByKey[key]=positionsByKey[key] or {}
      positionsByKey[key][#positionsByKey[key]+1]=p
    else
      savedPositions[phase][index]=nil
      report.partial=true; report.missingModelHeights=report.missingModelHeights+1
      if schemas[phase][index]==1 then problem("wrongScenery","New importer journal is missing a finite accepted model position.") end
    end
  end
  local function savedPositionMatches(key,pos)
    local candidates=positionsByKey[key]
    if not candidates then return true end -- explicitly partial for old saves
    if not pos or not controls.finiteHeight(pos[1]) or not controls.finiteHeight(pos[2]) or not controls.finiteHeight(pos[3]) then return false end
    for _,p in ipairs(candidates) do
      if math.abs(pos[1]-p[1])<=0.01 and math.abs(pos[2]-p[2])<=0.01 and math.abs(pos[3]-p[3])<=0.01 then return true end
    end
    return false
  end
  for index,item in ipairs(dataset.scenery or {}) do
    if options[controls.sceneryCategory(item)] then
      local key=itemKey(item)
      if key then expectedItems[key]=(expectedItems[key] or 0)+1
      else problem("wrongScenery","A selected dataset scenery item has invalid saved parameters.") end
      report.expected.scenery=report.expected.scenery+1
      if item.model then
        report.expected.models=report.expected.models+1
        if key then expectPosition(item,key,index,"scenery") end
      elseif item.texture then report.expected.surfaces=report.expected.surfaces+1 end
    end
  end
  if options.places then
    for index,label in ipairs(dataset.labels or {}) do
      local pos=coordinate(label.pos)
      local key=pos and "label|"..label.name.."|"..pos
      if key then expectedItems[key]=(expectedItems[key] or 0)+1
      else problem("wrongScenery","A selected dataset marker has invalid saved parameters.") end
      labelNames[label.name]=true
      report.expected.labels=report.expected.labels+1
      if key then expectPosition(label,key,index,"labels") end
    end
  end
  local prefix="OSM scenery "..tostring(dataset.id).." "
  local assetEntities,seenAssets,assetRecords={},{},{}
  if value.sceneryRecords then
    for _,record in ipairs(value.sceneryRecords) do
      for _,entity in ipairs(record.entities or {}) do
        if not api.engine.entityExists(entity) then
          problem("missingScenery","Recorded scenery entity "..tostring(entity).." is missing.")
        else
          local named=api.engine.getComponent(entity,T.NAME)
          if named and named.name~=record.name then
            problem("wrongScenery","Recorded scenery entity "..tostring(entity).." has lost its import name.")
          end
          if api.engine.getComponent(entity,T.ASSET_GROUP) and not seenAssets[entity] then
            seenAssets[entity]=true; assetEntities[#assetEntities+1]=entity
            assetRecords[entity]=record
          end
        end
      end
    end
  else
    -- Older saves have no entity journal. Only explicitly named groups qualify.
    api.engine.forEachEntity(function(entity)
      local named=api.engine.getComponent(entity,T.NAME)
      local name=named and named.name or ""
      if (name:sub(1,#prefix)==prefix or labelNames[name]) and api.engine.getComponent(entity,T.ASSET_GROUP) then
        assetEntities[#assetEntities+1]=entity
      end
    end)
  end
  -- Model-only builds become ASSET_GROUP entities, not CONSTRUCTION records.
  -- The mission savegame helper enumerates CONSTRUCTION components directly.
  local constructionEntities={}
  api.engine.forEachEntityWithComponent(function(entity)
    constructionEntities[#constructionEntities+1]=entity
  end,T.CONSTRUCTION)
  for _,entity in ipairs(constructionEntities) do
    if api.engine.entityExists(entity) then
      local construction=api.engine.getComponent(entity,T.CONSTRUCTION)
      if construction and construction.fileName==sceneryName then
        local named=api.engine.getComponent(entity,T.NAME)
        local name=named and named.name or ""
        local batch=name:sub(1,#prefix)==prefix
        local items=construction.params and construction.params.items
        if type(items)~="table" and construction.params_native then
          local params=construction.params_native:asTable()
          items=params and params.items
        end
        local label=false
        if not batch and labelNames[name] and type(items)=="table" then
          for _,item in ipairs(items) do
            local pos=coordinate(item.pos)
            if item.model==markerName and pos and expectedItems["label|"..name.."|"..pos] then label=true; break end
          end
        end
        if batch or label then
          report.current.constructions=report.current.constructions+1
          owned(entity,"Imported construction "..tostring(entity))
          if type(items)~="table" then
            problem("wrongScenery","Imported construction "..tostring(entity).." has no saved item list.")
          else
            for _,item in ipairs(items) do
              local key
              if label then
                report.current.labels=report.current.labels+1
                local pos=coordinate(item.pos)
                if item.model==markerName and pos then key="label|"..name.."|"..pos end
              else
                report.current.scenery=report.current.scenery+1
                if item.model then report.current.models=report.current.models+1
                elseif item.texture then report.current.surfaces=report.current.surfaces+1 end
                key=itemKey(item)
                if item.depth~=nil then
                  for _,p in ipairs(item.face or {}) do
                    local reference=value.shallowHeightReference and value.shallowHeightReference[coordinate(p)]
                    if item.depth~=0.5 or not controls.finiteHeight(reference) or not controls.finiteHeight(p[3]) or math.abs(p[3]-(reference-0.5))>0.01 then
                      problem("wrongScenery","Saved shallow-water bed differs from its 0.5 m reference; native terrain cells still need visual measurement.")
                    end
                  end
                end
              end
              if key and expectedItems[key] then foundItems[key]=(foundItems[key] or 0)+1
              else problem("wrongScenery","Imported construction "..tostring(entity).." contains an unexpected model, surface or marker position.") end
              if item.model and key and not savedPositionMatches(key,item.pos) then
                problem("wrongScenery","Imported construction model differs from its saved accepted XYZ position.")
              end
            end
          end
        end
      end
    end
  end
  -- Match native float transforms within one centimetre. Spatial buckets keep
  -- this linear in the number of models rather than scanning the dataset per tree.
  local buckets={}
  local function bucket(model,x,y) return model.."|"..tostring(x).."|"..tostring(y) end
  local function expectAsset(item,key,name,index,phase)
    item={model=item.model,pos=controls.position(item.pos,box),rotation=item.rotation,scale=item.scale}
    item.acceptedPos=savedPositions[phase][index]
    local x,y=math.floor(item.pos[1]/0.01),math.floor(item.pos[2]/0.01)
    local model=api.res.modelRep.find(item.model)
    local id=bucket(model,x,y)
    buckets[id]=buckets[id] or {}
    buckets[id][#buckets[id]+1]={item=item,key=key,name=name}
  end
  if #assetEntities>0 then
    for index,item in ipairs(dataset.scenery or {}) do
      if item.model and options[controls.sceneryCategory(item)] then expectAsset(item,itemKey(item),nil,index,"scenery") end
    end
    if options.places then
      for index,label in ipairs(dataset.labels or {}) do
        expectAsset({model=markerName,pos=label.pos,rotation=0},"label|"..label.name.."|"..coordinate(label.pos),label.name,index,"labels")
      end
    end
  end
  for _,entity in ipairs(assetEntities) do
    local named=api.engine.getComponent(entity,T.NAME)
    local record=assetRecords[entity]
    local name=record and record.name or (named and named.name or "")
    local isLabel=record and record.phase=="labels" or (not record and labelNames[name] and true or false)
    report.current.assetGroups=report.current.assetGroups+1
    owned(entity,"Imported asset group "..tostring(entity))
    local models=api.engine.getComponent(entity,T.MODEL_INSTANCE_LIST)
    local function checkModel(modelId,pos,rotation,scale,basis)
      if isLabel then report.current.labels=report.current.labels+1
      else report.current.scenery=report.current.scenery+1; report.current.models=report.current.models+1 end
      local model=modelId
      local x,y=math.floor(pos.x/0.01),math.floor(pos.y/0.01)
      local key
      for dx=-1,1 do for dy=-1,1 do
        for _,expected in ipairs(buckets[bucket(model,x+dx,y+dy)] or {}) do
          local item=expected.item
          local angle=math.abs(((rotation-(item.rotation or 0)+math.pi)%(2*math.pi))-math.pi)
          local heightMatches=not item.acceptedPos or (controls.finiteHeight(pos.z) and math.abs(pos.z-item.acceptedPos[3])<=0.01)
          local basisMatches=true
          if basis then
            local c,s=math.cos(item.rotation or 0),math.sin(item.rotation or 0)
            local expectedBasis={c,s,0,-s,c,0,0,0,1}
            for index=1,9 do
              if not controls.finiteHeight(basis[index]) or math.abs(basis[index]-expectedBasis[index])>0.0001 then basisMatches=false; break end
            end
          end
          if expected.name==(isLabel and name or nil) and math.abs(pos.x-item.pos[1])<=0.01 and math.abs(pos.y-item.pos[2])<=0.01
            and heightMatches and basisMatches and angle<=0.0001 and math.abs(scale-1)<=0.0001 then
            if not key or (foundItems[expected.key] or 0)<expectedItems[expected.key] then key=expected.key end
          end
        end
      end end
      if key then foundItems[key]=(foundItems[key] or 0)+1
      else problem("wrongScenery","Imported asset group "..tostring(entity).." contains an unexpected model, position, rotation or scale.") end
    end
    if not models then problem("missingScenery","Imported asset group "..tostring(entity).." has no model instances.")
    else
      for _,model in ipairs(models.thinInstances or {}) do checkModel(model.modelId,model.pos,model.rot,model.scale) end
      for _,model in ipairs(models.fatInstances or {}) do
        -- Installed custom_entity_util uses zero-based columns; the API's
        -- "1-4" comment does not match the native matrix accessor.
        local col=model.transf:cols(0)
        local y,z=model.transf:cols(1),model.transf:cols(2)
        checkModel(model.modelId,model.transf:getTransl(),(math.atan2 or math.atan)(col.y,col.x),math.sqrt(col.x*col.x+col.y*col.y),
          {col.x,col.y,col.z,y.x,y.y,y.z,z.x,z.y,z.z})
      end
    end
  end
  if report.expected.edges+report.expected.scenery+report.expected.labels==0 then
    problem("progress","No dataset items are selected for verification.")
  end
  for key,count in pairs(expectedItems) do
    local actual=foundItems[key] or 0
    if actual<count then problem("missingScenery",tostring(count-actual).." saved scenery or marker items are missing: "..key)
    elseif actual>count then problem("wrongScenery",tostring(actual-count).." duplicate scenery or marker items were found: "..key) end
  end
  for _,kind in ipairs({"edges","scenery","labels"}) do
    if report.counters[kind]~=report.expected[kind] then
      problem("progress","Saved "..kind.." progress is "..tostring(report.counters[kind]).." of "..tostring(report.expected[kind]).." selected items.")
    end
  end
  if report.partial then
    report.limitations[#report.limitations+1]=string.format("Accepted XYZ positions are missing for %d models/markers from older or incomplete journals; their vertical position is not verified.",report.missingModelHeights)
  end
  report.ok=#report.problems==0 and not report.partial
  return report
end

function audit.format(report)
  local e,c=report.expected,report.current
  local text=string.format("%s | nodes %d/%d | roads %d/%d | rails %d/%d | vehicle lane edges %d/%d | models %d/%d | ground items %d/%d | markers %d/%d | connected groups %d/%d",
    report.ok and "Saved built objects verified" or (#report.problems==0 and report.partial and "Built objects partially verified" or "Built objects need attention"),
    c.nodes,e.nodes,c.streets,e.streets,c.tracks,e.tracks,c.usableEdges,e.usableEdges,c.models,e.models,
    c.surfaces,e.surfaces,c.labels,e.labels,c.components,e.components)
  if #report.problems>0 then
    local shown={}
    for i=1,math.min(3,#report.problems) do shown[#shown+1]=report.problems[i] end
    text=text.." | "..table.concat(shown," ")
    if #report.problems>3 then text=text.." ("..tostring(#report.problems-3).." more issues)" end
  end
  if report.partial then text=text..string.format(" | Accepted XYZ evidence missing for %d models/markers. Vertical position is not verified.",report.missingModelHeights) end
  return text.." Ground paint appearance and actual vehicle routes still need a map check. Place names: use Show place names."
end

return audit

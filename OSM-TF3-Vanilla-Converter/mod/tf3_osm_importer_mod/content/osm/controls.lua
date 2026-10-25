-- GPL-3.0. Shared options and command rules for the engine and native TF3 UI.
local controls={}
controls.categories={
  {key="roads",label="Roads and tram streets"},
  {key="railways",label="Railways"},
  {key="vegetation",label="Trees and shrubs"},
  {key="surfaces",label="Ground surfaces"},
  {key="waterways",label="Mapped small waters: 0.5 m bed + Water Dirty"},
  {key="objects",label="Fountains, bollards and advertising columns"},
  {key="mappedObjects",label="Other mapped objects: match loaded game models"},
  {key="buildings",label="Building footprints: decorative model substitutes"},
  {key="places",label="Named place markers"},
  {key="towns",label="Functioning towns from city, town, village and hamlet tags"},
}
controls.policies={
  {key="useActiveMods",label="Search active mods when vanilla has no suitable object"},
  {key="townRoadGrowth",label="Allow new town roads and automatic town growth"},
}
controls.objectKinds={
  {key="tree",label="Individually mapped trees"},{key="fountain",label="Fountains"},
  {key="bollard",label="Bollards"},{key="advertising_column",label="Advertising columns"},
  {key="bench",label="Benches"},{key="waste_basket",label="Waste baskets"},
  {key="drinking_water",label="Drinking water points"},{key="post_box",label="Post boxes"},
  {key="bicycle_parking",label="Bicycle parking"},{key="street_lamp",label="Street lamps"},
  {key="rock",label="Mapped rocks"},{key="memorial",label="Memorials"},{key="monument",label="Monuments"},
  {key="water_tower",label="Water towers"},{key="lighthouse",label="Lighthouses"},
  {key="storage_tank",label="Storage tanks"},{key="power_tower",label="Power towers"},
  {key="residential",label="Residential building outlines"},{key="commercial",label="Commercial building outlines"},
  {key="industrial",label="Industrial building outlines"},{key="building",label="Buildings with unspecified use"},
}
controls.commands={
  {key="validate",label="Check map and match objects",help="Check coordinates and loaded resources, then preview vanilla-first object matches before starting."},
  {key="start",label="Start import",help="Build the selected parts of the prepared dataset. Use a new test map first."},
  {key="pause",label="Pause import / cancel check",help="Stop building and keep progress, or cancel a running map check without building."},
  {key="resume",label="Resume import",help="Continue a paused import from its saved position."},
  {key="retry",label="Retry failed step",help="Try the rejected build proposal again."},
  {key="skip",label="Skip failed step",help="Omit the failed proposal. A scenery step can contain an entire batch."},
  {key="status",label="Show progress",help="Refresh the progress message and write it to the game log."},
  {key="verify",label="Verify built objects",help="Compare completed import records with live map nodes, roads, tracks and scenery. Ground appearance needs a visual check."},
  {key="placeNames",label="Show place names",help="Show recorded place names and map coordinates, twenty at a time. Click again for the next page."},
  {key="mapSize",label="Read map size",help="Show the map width and height to enter in the desktop converter."},
  {key="waterSupport",label="Read water support",help="Read the current global water level and explain the limits of water at other heights. Does not change the map."},
  {key="waterCheck",label="Check test water area",help="Read-only check of the configured experimental water patch. Existing networks and constructions have priority."},
  {key="waterBuild",label="Build experimental test water",help="Build one small decorative water patch. Not ship-navigable water. Use a separate test save."},
  {key="waterNext",label="Prepare another water patch",help="Keep the accepted patch and unlock settings for a separate patch at another position or height."},
}

function controls.options(source)
  local result={batchSize=100,interval=0,stepLimit=0}
  for _,category in ipairs(controls.categories) do result[category.key]=true end
  -- Native depth/paint validation is pending; select this experiment explicitly.
  result.waterways=false; result.buildings=false; result.towns=false
  for _,policy in ipairs(controls.policies) do result[policy.key]=true end
  for _,kind in ipairs(controls.objectKinds) do result["object_"..kind.key]=true end
  for key,_ in pairs(result) do
    if source and source[key]~=nil then result[key]=source[key] end
  end
  return result
end

function controls.configure(source,patch,locked)
  assert(type(patch)=="table","Settings must be a table")
  local result=controls.options(source)
  for key,value in pairs(patch) do
    if key=="batchSize" then
      assert(type(value)=="number" and value==value and value%1==0 and value>=1 and value<=100,
        "Scenery batch size must be a whole number from 1 to 100")
    elseif key=="stepLimit" then
      assert(type(value)=="number" and value==value and value%1==0 and value>=0 and value<=10000,
        "Automatic pause must be a whole number from 0 to 10000 build steps")
    elseif key=="interval" then
      assert(type(value)=="number" and value==value and value>=0 and value<=2,
        "Import delay must be between 0 and 2 simulation seconds")
    else
      local known=false
      for _,category in ipairs(controls.categories) do if key==category.key then known=true; break end end
      for _,policy in ipairs(controls.policies) do if key==policy.key then known=true; break end end
      for _,kind in ipairs(controls.objectKinds) do if key=="object_"..kind.key then known=true; break end end
      assert(known,"Unknown import setting: "..tostring(key))
      assert(type(value)=="boolean","Import selections must be true or false")
      assert(not locked or value==result[key],"Import selections are locked after starting; use a new map to change them")
    end
    result[key]=value
  end
  return result
end

function controls.sceneryCategory(item)
  if item.category=="buildings" or item.category=="mappedObjects" then return item.category end
  if item.category=="waterways" then return "waterways" end
  if item.category=="surfaces" or item.category=="vegetation" or item.category=="objects" then return item.category end
  if item.texture then return "surfaces" end
  if item.model and item.model:find("::/assets/vegetation/",1,true)==1 then return "vegetation" end
  return "objects"
end

function controls.placeMode(label,options)
  local place=label.place or (label.osm and label.osm.tags and label.osm.tags.place)
  if options.towns and (place=="city" or place=="town" or place=="village" or place=="hamlet") then return "town" end
  if options.places then return "marker" end
end

function controls.resolvedItem(item,index,value)
  if not item.match then return item end
  local match=value.matches and value.matches[index]
  if not match then return item.model and item or nil end
  if match.unmatched then return nil end
  local result={}
  for key,v in pairs(item) do result[key]=v end
  result.model=match.model; result.pos=match.pos; result.rotation=match.rotation
  return result
end

function controls.selectedScenery(item,options)
  return options[controls.sceneryCategory(item)] and not item.unmatched
    and (not item.match or options["object_"..item.match.kind]~=false)
end

-- Dataset tables are immutable while selected. Retain only small aggregates;
-- changing a category must not rescan every source item on the GUI thread.
-- Weak keys also release aggregates when a different map replaces the source.
local countsCache=setmetatable({},{__mode="k"})
function controls.invalidateCounts(dataset)
  if dataset then countsCache[dataset]=nil
  else countsCache=setmetatable({},{__mode="k"}) end
end

local function sourceCounts(dataset)
  local cached=countsCache[dataset]
  if cached and cached.id==dataset.id and cached.edges==dataset.edges
    and cached.scenery==dataset.scenery and cached.labels==dataset.labels
    and cached.edgeCount==#dataset.edges and cached.sceneryCount==#dataset.scenery
    and cached.labelCount==#dataset.labels then return cached end
  local counts={}
  local kinds={}
  local buckets={}
  for _,category in ipairs(controls.categories) do counts[category.key]=0 end
  for _,edge in ipairs(dataset.edges or {}) do
    local key=edge.kind=="TRACK" and "railways" or "roads"; counts[key]=counts[key]+1
  end
  for _,item in ipairs(dataset.scenery or {}) do
    local key=controls.sceneryCategory(item); counts[key]=counts[key]+1
    if item.match then local kind=item.match.kind; kinds[kind]=(kinds[kind] or 0)+1 end
    if not item.unmatched then
      local byKind=buckets[key]
      if not byKind then byKind={}; buckets[key]=byKind end
      -- false distinguishes an unconditional item from any named match kind.
      local kind=item.match and item.match.kind or false
      byKind[kind]=(byKind[kind] or 0)+1
    end
  end
  counts.places=#(dataset.labels or {})
  for _,label in ipairs(dataset.labels or {}) do
    if controls.placeMode(label,{towns=true})=="town" then counts.towns=counts.towns+1 end
  end
  cached={id=dataset.id,edges=dataset.edges,scenery=dataset.scenery,labels=dataset.labels,
    edgeCount=#dataset.edges,sceneryCount=#dataset.scenery,labelCount=#dataset.labels,
    counts=counts,kinds=kinds,buckets=buckets}
  countsCache[dataset]=cached
  return cached
end

function controls.available(dataset)
  local cached=sourceCounts(dataset)
  return cached.counts,cached.kinds
end

function controls.inventory(dataset)
  local cached=sourceCounts(dataset)
  if not cached.inventory then
    local buckets={}
    for category,byKind in pairs(cached.buckets) do
      for kind,count in pairs(byKind) do buckets[#buckets+1]={category=category,kind=kind or nil,count=count} end
    end
    cached.inventory={counts=cached.counts,kinds=cached.kinds,buckets=buckets}
  end
  return cached.inventory
end

function controls.position(p,box)
  if not box or type(p)~="table" or type(p[1])~="number" or type(p[2])~="number" then return p end
  -- TF3 excludes its positive boundary. A centimetre also prevents native
  -- float rounding onto that boundary. Never change the source dataset.
  local x,y=p[1],p[2]
  if x>box.max.x-0.01 and x<=box.max.x+0.000001 then x=box.max.x-0.01 end
  if y>box.max.y-0.01 and y<=box.max.y+0.000001 then y=box.max.y-0.01 end
  return {x,y,p[3]}
end

function controls.finiteHeight(z)
  return type(z)=="number" and z==z and math.abs(z)<math.huge
end

-- Ground fill uses native float coordinates. Thin clipped polygons can have
-- positive double-precision area but collapse at Huge-map world coordinates.
-- Retain source coordinates/heights, removing only native duplicate vertices.
function controls.float32(value)
  if value==0 or not controls.finiteHeight(value) then return value end
  local negative=value<0
  local magnitude=math.abs(value)
  local exponent=math.floor(math.log(magnitude)/math.log(2))
  local power=2^exponent
  -- Correct logarithm rounding at exact powers of two.
  if magnitude<power then exponent=exponent-1
  elseif magnitude>=power*2 then exponent=exponent+1 end
  if exponent>127 then return negative and -math.huge or math.huge end
  local step=2^math.max(exponent-23,-149)
  local scaled=magnitude/step
  local rounded=math.floor(scaled)
  local fraction=scaled-rounded
  if fraction>0.5 or fraction==0.5 and rounded%2==1 then rounded=rounded+1 end
  local result=rounded*step
  if result>(2-2^-23)*2^127 then result=math.huge end
  return negative and -result or result
end

function controls.groundFace(source,box)
  assert(type(source)=="table","Invalid ground polygon")
  local face,xy={},{}
  for _,point in ipairs(source) do
    assert(type(point)=="table" and controls.finiteHeight(point[1]) and controls.finiteHeight(point[2]),"Invalid ground coordinate")
    local p=box and controls.position(point,box) or point
    -- TF3's Lua runtime does not provide string.pack/unpack.
    local x,y=controls.float32(p[1]),controls.float32(p[2])
    assert(controls.finiteHeight(x) and controls.finiteHeight(y),"Unrepresentable ground coordinate")
    local previous=xy[#xy]
    if not previous or x~=previous[1] or y~=previous[2] then
      face[#face+1]={p[1],p[2],p[3]}; xy[#xy+1]={x,y}
    end
  end
  if #xy>1 and xy[1][1]==xy[#xy][1] and xy[1][2]==xy[#xy][2] then
    face[#face]=nil; xy[#xy]=nil
  end
  local area=0
  if #xy>=3 then
    local origin=xy[1]
    for i=2,#xy-1 do
      area=area+(xy[i][1]-origin[1])*(xy[i+1][2]-origin[2])-(xy[i][2]-origin[2])*(xy[i+1][1]-origin[1])
    end
  end
  if #xy<3 or area==0 then return nil,"Ground face collapses at TF3 coordinate precision" end
  -- Converter faces are already counterclockwise. Normalize older inputs too.
  if area<0 then
    local reversed={face[1]}
    for i=#face,2,-1 do reversed[#reversed+1]=face[i] end
    face=reversed
  end
  return face
end

function controls.elevation(node)
  if node.elevation==nil then return nil end
  local e=node.elevation
  assert(type(e)=="table" and controls.finiteHeight(e.metres),"Invalid road/rail elevation")
  assert(e.datum=="game" and type(e.source)=="string" and e.source~="",
    "Road/rail elevation must have datum=game and a named source; raw OSM ele is not a game height")
  return e.metres
end

function controls.waterSupport(terrain)
  local level=terrain and terrain.waterLevel
  local prefix=controls.finiteHeight(level) and string.format("Current global water level: %.2f m. ",level) or "Global water level could not be read. "
  return prefix.."The installed TF3 API exposes one navigable water level. No supported command for separate navigable lake/river levels was found. "..
    "Mapped small waters use Landscaping Water Dirty on a 0.5 m shallow bed. Water Dirty is ground paint, not navigable water. Elevated model surfaces are a separate experiment. Lakes retain their metadata without changing the global sea level. No water or terrain was changed."
end

function controls.skippable(value)
  return value.phase=="error" and value.datasetMatches~=false
    and not value.pendingOwnership and not value.pendingScenery and not value.pendingTown and not value.pendingAccepted
    and not value.acceptedUnjournalled
    and (value.errorKind=="proposal_rejected" or value.errorKind=="preparation")
end

function controls.enabled(command,value)
  local phase=value.phase or "ready"
  if phase=="checking" then return command=="pause" or command=="status" or command=="mapSize" end
  if command=="waterNext" then return not value.waterBusy and value.waterBuilt==true and (phase=="ready" or phase=="paused" or phase=="finished") end
  if command=="waterCheck" or command=="waterBuild" then return not value.waterBusy and (phase=="ready" or phase=="paused" or phase=="finished") end
  if command=="start" then return not value.datasetId end
  if command=="pause" then return phase=="scenery" or phase=="edges" or phase=="labels" end
  if command=="resume" then return phase=="paused" end
  if command=="skip" then return controls.skippable(value) end
  if command=="retry" then return phase=="error" and value.datasetMatches~=false
    and not value.acceptedUnjournalled and value.errorKind~="command_state" end
  if command=="verify" then return phase=="finished" end
  if command=="placeNames" then return (value.labels or 0)+(value.builtTowns or 0)>0 end
  return command=="validate" or command=="status" or command=="mapSize" or command=="waterSupport"
end

function controls.placeNames(dataset,value)
  if value.datasetId~=dataset.id then return "Dataset changed; restore the original dataset to read place coordinates.",0 end
  local entries={}
  for _,record in ipairs(value.sceneryRecords or {}) do
    local source=record.phase=="labels" and dataset.labels[record.first]
    if source then
      entries[#entries+1]=string.format("%s (x %.0f m, y %.0f m)",record.name,source.pos[1],source.pos[2])
    end
  end
  for _,record in ipairs(value.townRecords or {}) do
    entries[#entries+1]=string.format("%s (functioning town, x %.0f m, y %.0f m)",record.name,record.pos[1],record.pos[2])
  end
  if #entries==0 then return "No recorded place markers or towns. Older saves may need their original dataset for names.",0 end
  local pages=math.ceil(#entries/20)
  local page=(value.placeNamesPage or 0)%pages
  local shown={}
  for index=page*20+1,math.min(#entries,(page+1)*20) do shown[#shown+1]=entries[index] end
  return string.format("Recorded place names, page %d/%d: %s. Coordinates are metres from the map centre.",page+1,pages,table.concat(shown,"; ")),(page+1)%pages
end

function controls.warnings(dataset)
  local result={}
  for _,warning in ipairs(dataset.warnings or {}) do
    if warning:find("Place names become named vanilla marker constructions",1,true) then
      warning="Place markers are decorative models, not simulated towns. Read their recorded names and coordinates with Show place names."
    end
    result[#result+1]=warning
  end
  return result
end

function controls.totals(dataset,options)
  return controls.totalsFromInventory(controls.inventory(dataset),options)
end

function controls.totalsFromInventory(cached,options)
  local counts=cached.counts
  local totals={edges=0,scenery=0,labels=0,towns=0}
  if options.roads then totals.edges=totals.edges+counts.roads end
  if options.railways then totals.edges=totals.edges+counts.railways end
  if options.towns then totals.towns=counts.towns end
  if options.places then totals.labels=counts.places-totals.towns end
  for _,bucket in ipairs(cached.buckets) do
    if options[bucket.category] and (not bucket.kind or options["object_"..bucket.kind]~=false) then
      totals.scenery=totals.scenery+bucket.count
    end
  end
  return totals
end
return controls

-- GPL-3.0. Shared options and command rules for the engine and native TF3 UI.
local controls={}
controls.categories={
  {key="roads",label="Roads and tram streets"},
  {key="railways",label="Railways"},
  {key="vegetation",label="Trees and shrubs"},
  {key="surfaces",label="Ground surfaces"},
  {key="waterways",label="Mapped small waters: 0.5 m bed + Water Dirty"},
  {key="objects",label="Fountains, bollards and advertising columns"},
  {key="places",label="Named place markers"},
}
controls.commands={
  {key="validate",label="Check map and resources",help="Check coordinates and vanilla resources before starting."},
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
  result.waterways=false
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
      assert(known,"Unknown import setting: "..tostring(key))
      assert(type(value)=="boolean","Import selections must be true or false")
      assert(not locked or value==result[key],"Import selections are locked after starting; use a new map to change them")
    end
    result[key]=value
  end
  return result
end

function controls.sceneryCategory(item)
  if item.category=="waterways" then return "waterways" end
  if item.category=="surfaces" or item.category=="vegetation" or item.category=="objects" then return item.category end
  if item.texture then return "surfaces" end
  if item.model and item.model:find("::/assets/vegetation/",1,true)==1 then return "vegetation" end
  return "objects"
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

function controls.enabled(command,value)
  local phase=value.phase or "ready"
  if phase=="checking" then return command=="pause" or command=="status" or command=="mapSize" end
  if command=="waterNext" then return not value.waterBusy and value.waterBuilt==true and (phase=="ready" or phase=="paused" or phase=="finished") end
  if command=="waterCheck" or command=="waterBuild" then return not value.waterBusy and (phase=="ready" or phase=="paused" or phase=="finished") end
  if command=="start" then return not value.datasetId end
  if command=="pause" then return phase=="scenery" or phase=="edges" or phase=="labels" end
  if command=="resume" then return phase=="paused" end
  if command=="retry" or command=="skip" then return phase=="error" end
  if command=="verify" then return phase=="finished" end
  if command=="placeNames" then return (value.labels or 0)>0 end
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
  if #entries==0 then return "No recorded place markers. Older saves may need their original dataset for names.",0 end
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

local totalsCache={}
function controls.totals(dataset,options)
  local key=""
  for _,category in ipairs(controls.categories) do key=key..(options[category.key] and "1" or "0") end
  totalsCache[dataset]=totalsCache[dataset] or {}
  if totalsCache[dataset][key] then return totalsCache[dataset][key] end
  local totals={edges=0,scenery=0,labels=options.places and #dataset.labels or 0}
  for _,edge in ipairs(dataset.edges) do
    if options[edge.kind=="TRACK" and "railways" or "roads"] then totals.edges=totals.edges+1 end
  end
  for _,item in ipairs(dataset.scenery) do
    if options[controls.sceneryCategory(item)] then totals.scenery=totals.scenery+1 end
  end
  totalsCache[dataset][key]=totals
  return totals
end
return controls

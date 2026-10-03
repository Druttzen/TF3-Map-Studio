-- GPL-3.0. Shared options and command rules for the engine and native TF3 UI.
local controls={}
controls.categories={
  {key="roads",label="Roads and tram streets"},
  {key="railways",label="Railways"},
  {key="vegetation",label="Trees and shrubs"},
  {key="surfaces",label="Ground surfaces"},
  {key="objects",label="Fountains, bollards and advertising columns"},
  {key="places",label="Named place markers"},
}
controls.commands={
  {key="validate",label="Check map and resources",help="Check coordinates and vanilla resources before starting."},
  {key="start",label="Start import",help="Build the selected parts of the prepared dataset. Use a new test map first."},
  {key="pause",label="Pause import",help="Keep the current position and stop building."},
  {key="resume",label="Resume import",help="Continue a paused import from its saved position."},
  {key="retry",label="Retry failed step",help="Try the rejected build proposal again."},
  {key="skip",label="Skip failed step",help="Omit the failed proposal. A scenery step can contain an entire batch."},
  {key="status",label="Show progress",help="Refresh the progress message and write it to the game log."},
  {key="verify",label="Verify built objects",help="Compare completed import records with live map nodes, roads, tracks and scenery. Ground appearance needs a visual check."},
  {key="placeNames",label="Show place names",help="Show recorded place names and map coordinates, twenty at a time. Click again for the next page."},
  {key="mapSize",label="Read map size",help="Show the map width and height to enter in the desktop converter."},
}

function controls.options(source)
  local result={batchSize=100,interval=0}
  for _,category in ipairs(controls.categories) do result[category.key]=true end
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
  if item.category=="surfaces" or item.category=="vegetation" or item.category=="objects" then return item.category end
  if item.texture then return "surfaces" end
  if item.model and item.model:find("::/assets/vegetation/",1,true)==1 then return "vegetation" end
  return "objects"
end

function controls.enabled(command,value)
  local phase=value.phase or "ready"
  if command=="start" then return not value.datasetId end
  if command=="pause" then return phase=="scenery" or phase=="edges" or phase=="labels" end
  if command=="resume" then return phase=="paused" end
  if command=="retry" or command=="skip" then return phase=="error" end
  if command=="verify" then return phase=="finished" end
  if command=="placeNames" then return (value.labels or 0)>0 end
  return command=="validate" or command=="status" or command=="mapSize"
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

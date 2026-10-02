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
  return command=="validate" or command=="status" or command=="mapSize"
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

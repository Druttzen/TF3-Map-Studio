-- GPL-3.0. Engine-only Lua map resources with compact presentation metadata.
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local maps={}
function maps.checkResource(resource)
  assert(type(resource)=="string" and #resource<=4096 and resource:sub(1,9)=="osm/maps/"
    and resource:sub(-4):lower()==".lua" and not resource:find("[\\:%z\r\n]")
    and not resource:find("//",1,true),"Choose a Lua map from the importer's content/osm/maps folder")
  for part in resource:gmatch("[^/]+") do assert(part~="." and part~="..","Invalid map path") end
  return resource
end
function maps.resourcePath(path,root)
  assert(type(path)=="string","Choose a converted Lua map")
  path=path:gsub("\\","/")
  root=root:gsub("\\","/"):gsub("/+$","")
  for _,folder in ipairs({"tf3_osm_importer_mod","druttzen_osm_vanilla"}) do
    local prefix=root.."/mods/"..folder.."/content/"
    local actual,expected=path,prefix
    if root:match("^%a:") then actual=path:lower(); expected=prefix:lower() end
    if actual:sub(1,#expected)==expected then return maps.checkResource(path:sub(#prefix+1)) end
  end
  error("Copy the converted Lua map into mods/tf3_osm_importer_mod/content/osm/maps inside TF3 userdata, restart TF3, then select it again.")
end
function maps.validate(data)
  assert(type(data)=="table" and data.schema==1 and type(data.id)=="string" and #data.id>0 and #data.id<=256,
    "This is not a converted OSM Lua map. Export a Lua map with OSM-TF3-Vanilla-Converter.")
  assert(type(data.size)=="table" and controls.finiteHeight(data.size[1]) and controls.finiteHeight(data.size[2])
    and data.size[1]>0 and data.size[2]>0,"Invalid Lua map dimensions")
  for _,section in ipairs({"nodes","edges","scenery","labels"}) do
    assert(type(data[section])=="table","Missing Lua map section: "..section)
  end
  for _,key in ipairs({"waterFeatures","warnings","unavailableObjects","importOptions","objectMetadata"}) do
    assert(data[key]==nil or type(data[key])=="table","Invalid Lua map field: "..key)
  end
  for _,warning in ipairs(data.warnings or {}) do assert(type(warning)=="string","Invalid map warning") end
  for _,entry in ipairs(data.unavailableObjects or {}) do
    assert(type(entry)=="table" and type(entry.tag)=="string" and controls.finiteHeight(entry.count) and entry.count>=0,"Invalid map object summary")
  end
  controls.configure(nil,data.importOptions or {},false)
  return data
end
function maps.load(resource)
  maps.checkResource(resource)
  local ok,data=pcall(ug_require,"druttzen_osm_vanilla::/"..resource)
  assert(ok,"Could not read the selected Lua map. Keep it in content/osm/maps and restart TF3 after adding or replacing files. "..tostring(ok and "" or data))
  return maps.validate(data)
end
function maps.describe(data)
  local lakes=0
  for _,feature in ipairs(data.waterFeatures or {}) do if feature.kind=="lake" then lakes=lakes+1 end end
  return {id=data.id,size=data.size,inventory=controls.inventory(data),warnings=data.warnings or {},
    unavailableObjects=data.unavailableObjects or {},hasMappedObjectMetadata=data.objectMetadata~=nil,
    mappedWaterCount=#(data.waterFeatures or {}),mappedLakeCount=lakes}
end
return maps

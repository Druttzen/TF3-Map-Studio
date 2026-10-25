-- GPL-3.0. Compact map descriptions and bounded GUI-to-engine data transfers.
local controls=ug_require "druttzen_osm_vanilla::/osm/controls.lua"
local maps={sections={"nodes","edges","scenery","labels","waterFeatures"},chunkSize=256}
local fields={"schema","id","size","bounds","importOptions","warnings","unavailableObjects","objectMetadata"}

function maps.relativePath(path,root)
  assert(type(path)=="string" and #path<=4096,"Choose a converted Lua map file")
  path=path:gsub("\\","/")
  root=root:gsub("\\","/"):gsub("/+$","")
  local comparePath,compareRoot=path,root
  if root:match("^%a:") then comparePath=path:lower(); compareRoot=root:lower() end
  assert(comparePath:sub(1,#compareRoot+1)==compareRoot.."/",
    "Copy the Lua map into TF3's userdata folder (for example local/osm_maps), then select it again. The game only supports reading userdata files.")
  local relative=path:sub(#root+2)
  maps.location(relative)
  return relative
end

function maps.location(relative)
  assert(type(relative)=="string" and #relative>4 and #relative<=4096
    and not relative:find("[\\:%z\r\n]") and relative:sub(1,1)~="/","Invalid map path")
  for part in relative:gmatch("[^/]+") do assert(part~="." and part~="..","Invalid map path") end
  assert(not relative:find("//",1,true),"Invalid map path")
  local directory,name=relative:match("^(.*)/([^/]+)%.[lL][uU][aA]$")
  assert(directory and directory~="" and name~="","Choose a .lua file inside a userdata subfolder")
  return directory,name
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

function maps.describe(data)
  local lakes=0
  for _,feature in ipairs(data.waterFeatures or {}) do if feature.kind=="lake" then lakes=lakes+1 end end
  return {id=data.id,size=data.size,inventory=controls.inventory(data),warnings=data.warnings or {},
    unavailableObjects=data.unavailableObjects or {},hasMappedObjectMetadata=data.objectMetadata~=nil,
    mappedWaterCount=#(data.waterFeatures or {}),mappedLakeCount=lakes}
end

function maps.header(data)
  maps.validate(data)
  local header,counts={},{}
  for _,key in ipairs(fields) do header[key]=data[key] end
  for _,section in ipairs(maps.sections) do
    local count=0
    for _ in pairs(data[section] or {}) do count=count+1 end
    counts[section]=count
  end
  return header,counts
end

function maps.begin(param)
  assert(type(param)=="table" and type(param.token)=="string" and #param.token<=128,"Invalid map transfer")
  maps.location(param.source)
  local data={}
  for _,key in ipairs(fields) do data[key]=param.header and param.header[key] end
  local total=0
  for _,section in ipairs(maps.sections) do
    local count=param.counts and param.counts[section]
    assert(type(count)=="number" and count>=0 and count%1==0 and count<=20000000,"Invalid map item count")
    total=total+count; data[section]={}
  end
  assert(total<=20000000,"Lua map exceeds the transfer item limit")
  maps.validate(data)
  return {token=param.token,source=param.source,data=data,counts=param.counts,received={},total=total,count=0,seq=0}
end

function maps.accept(job,param)
  assert(job and param.token==job.token and param.seq==job.seq+1,"Map transfer interrupted; select the file again")
  local target=job.data[param.section]
  assert(job.counts[param.section] and type(target)=="table" and type(param.items)=="table"
    and #param.items>0 and #param.items<=maps.chunkSize,"Invalid map transfer chunk")
  local received=job.received[param.section] or 0
  assert(received+#param.items<=job.counts[param.section],"Too many map items")
  for _,entry in ipairs(param.items) do
    local key=entry.key
    assert((type(key)=="string" and #key<=256 or type(key)=="number" and key%1==0 and key>=1)
      and target[key]==nil and type(entry.value)=="table","Invalid or duplicate map item")
    if param.section~="nodes" then assert(type(key)=="number" and key<=job.counts[param.section],"Invalid map array index") end
    target[key]=entry.value
  end
  job.received[param.section]=received+#param.items; job.count=job.count+#param.items; job.seq=param.seq
end

function maps.finish(job,param)
  assert(job and param.token==job.token and param.seq==job.seq and job.count==job.total,"Incomplete map transfer")
  for _,section in ipairs(maps.sections) do
    assert((job.received[section] or 0)==job.counts[section],"Incomplete map section")
    if section~="nodes" then assert(#job.data[section]==job.counts[section],"Map array has gaps") end
  end
  return maps.validate(job.data)
end
return maps

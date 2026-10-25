-- GPL-3.0. GUI-only file loading. Engine callbacks receive small acknowledged chunks.
local maps=ug_require "druttzen_osm_vanilla::/osm/map_data.lua"
local loader={}
local pending,attempted
local function send(name,param)
  api.cmd.sendCommand(api.cmd.makeScriptingSendEventCmd("OSM map selector","druttzen_osm_vanilla","osm."..name,param or {}))
end
function loader.choose(path)
  if type(path)~="string" or path=="" then return end
  local ok,relative=pcall(maps.relativePath,path,app.getUserDataFolder())
  if not ok then send("mapNotice",{message=tostring(relative)}); return end
  pending={source=relative,token=tostring({}),section=1,seq=0}
end
function loader.cancel()
  pending=nil; send("mapCancel")
end
function loader.update(value)
  if type(value)~="table" then return end
  if value.mapReady then attempted=nil end
  if not pending and value.mapSource and value.mapReady==false then
    local key=value.mapSource..":"..tostring(value.mapExpectedId)
    if attempted~=key then
      attempted=key; pending={source=value.mapSource,token=tostring({}),section=1,seq=0}
    end
  end
  if not pending then return end
  local job=pending
  local ok,err=pcall(function()
    local reply=value.mapReply
    if reply and reply.token==job.token and reply.error then pending=nil; return end
    if reply and reply.token==job.token and reply.done then pending=nil; return end
    if not job.data then
      local directory,name=maps.location(job.source)
      job.data=maps.validate(app.loadUserdata(directory,name))
      local header,counts=maps.header(job.data)
      send("mapBegin",{source=job.source,token=job.token,header=header,counts=counts})
      return
    end
    local transfer=value.mapTransfer
    if not transfer or transfer.token~=job.token or transfer.seq~=job.seq then return end
    while job.section<=#maps.sections do
      local section=maps.sections[job.section]
      local source=job.data[section] or {}
      local items={}
      for _=1,maps.chunkSize do
        local key,item=next(source,job.cursor)
        job.cursor=key
        if key==nil then break end
        items[#items+1]={key=key,value=item}
      end
      if job.cursor==nil then job.section=job.section+1 end
      if #items>0 then
        job.seq=job.seq+1
        send("mapChunk",{token=job.token,seq=job.seq,section=section,items=items})
        return
      end
    end
    if not job.committed then
      job.committed=true; send("mapCommit",{token=job.token,seq=job.seq})
    end
  end)
  if not ok then
    pending=nil
    send("mapNotice",{token=job.token,message="Could not load Lua map: "..tostring(err)})
  end
end
return loader

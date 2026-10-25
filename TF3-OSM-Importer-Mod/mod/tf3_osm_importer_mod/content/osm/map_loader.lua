-- GPL-3.0. The native dialog sends only a virtual resource name to the engine.
local maps=ug_require "druttzen_osm_vanilla::/osm/map_data.lua"
local loader={}
local function send(name,param)
  api.cmd.sendCommand(api.cmd.makeScriptingSendEventCmd("OSM map selector","druttzen_osm_vanilla","osm."..name,param))
end
function loader.choose(path)
  if type(path)~="string" or path=="" then return end
  local ok,resource=pcall(maps.resourcePath,path,app.getUserDataFolder())
  if ok then send("mapSelect",{resource=resource})
  else send("mapNotice",{message=tostring(resource)}) end
end
return loader

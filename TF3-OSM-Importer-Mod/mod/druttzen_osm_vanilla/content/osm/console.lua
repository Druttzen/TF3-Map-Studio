local helper = {}
local eventId = "druttzen_osm_vanilla"
local function send(name, params)
  api.cmd.sendCommand(api.cmd.makeScriptingSendEventCmd("OSM Importer", eventId, name, params or {}))
end
function helper.start() send("osm.start") end
function helper.pause() send("osm.pause") end
function helper.resume() send("osm.resume") end
function helper.retry() send("osm.retry") end
function helper.skip() send("osm.skip") end
function helper.status() send("osm.status") end
function helper.verify() send("osm.verify") end
function helper.placeNames() send("osm.placeNames") end
function helper.validate() send("osm.validate") end
function helper.configure(options) send("osm.configure",options) end
function helper.mapSize()
  local box=api.engine.terrain.getBoundingBox()
  local width,height=box.max.x-box.min.x,box.max.y-box.min.y
  print(string.format("[OSM Vanilla] map width %.0f m, height %.0f m",width,height))
  return width,height
end
return helper

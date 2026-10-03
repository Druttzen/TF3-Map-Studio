function data()
  return {
    description = { name = "OSM scenery", description = "Vanilla OSM vegetation and ground surfaces" },
    availability = { yearFrom = 0, yearTo = 0 },
    skipCollision = true,
    autoRemovable = false,
    params = {},
    updateScript = { fileName = "druttzen_osm_vanilla::/osm/scenery.script@updateFn" },
  }
end

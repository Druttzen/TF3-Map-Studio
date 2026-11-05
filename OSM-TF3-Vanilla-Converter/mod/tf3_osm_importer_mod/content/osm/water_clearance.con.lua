function data()
  return {
    description = {name="OSM water vegetation clearance"},
    availability = {yearFrom=0,yearTo=0},
    skipCollision = false,
    autoRemovable = false,
    params = {},
    updateScript = {fileName="druttzen_osm_vanilla::/osm/scenery.script@updateFn"},
  }
end

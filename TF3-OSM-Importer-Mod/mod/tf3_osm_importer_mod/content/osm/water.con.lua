function data()
  return {
    description={name="OSM experimental water test",description="Decorative water surface at a chosen height; not navigable water"},
    availability={yearFrom=0,yearTo=0},skipCollision=false,autoRemovable=false,params={},
    updateScript={fileName="druttzen_osm_vanilla::/osm/water.script@updateFn"},
  }
end

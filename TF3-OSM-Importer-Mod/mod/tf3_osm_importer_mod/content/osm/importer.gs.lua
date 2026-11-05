function data()
  return {
    updateScript = { fileName = "druttzen_osm_vanilla::/osm/importer.script@wakeUpdate" },
    postUpdateScript = { fileName = "druttzen_osm_vanilla::/osm/importer.script@engineTick" },
    handleEventScript = { fileName = "druttzen_osm_vanilla::/osm/importer.script@queueEvent" },
    guiHandleEventScript = { fileName = "druttzen_osm_vanilla::/osm/ui_bridge.script@guiHandleEvent" },
  }
end

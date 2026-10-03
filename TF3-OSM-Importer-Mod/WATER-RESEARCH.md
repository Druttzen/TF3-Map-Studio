# Local water in TF3: evidence and experimental implementation

Scope: `druttzen_osm_vanilla`, tool 4, inside Transport Fever 3. Heightmap Studio is unchanged. Inspected on 3 October 2026 against installed TF3 Windows build 40408, Steam build 25533170.

## What the installed game actually exposes

The installed `api/tealdef/api/engine.d.tl` defines a single `Engine.Component.Terrain.waterLevel` (line 1233). Its `UtilTerrain.isOnWater` documentation describes positions below the water level (line 1742). `api/tealdef/api/type.d.tl` defines one `GameMap.waterLevel` (line 305). The map editor reads and writes that global value. This establishes the documented global water model; it does **not** establish that independent navigable lake levels can be created.

`Engine.Component.WaterMesh` also has a `waterLevel` field (engine definition line 1601), but it describes a water tile returned by the engine. No command for adding or editing independent water tiles was found in the installed command API. A component record and its constructor are not evidence of a supported world-editing command. The importer does not write these fields or claim local ship navigation.

Vanilla fountains and other models contain separate water meshes and transparent materials. The installed HQ water material, `::/landmarks/hq/modules/mat/hq_water_tile.mtl`, uses `PHYS_TRANSPARENT_NRML_MAP`. The opera house material additionally has texture animation. Construction scripts expose model transforms and optional terrain alignment faces. These are the documented ingredients for a **decorative local surface and basin**, rather than independent navigable game water.

The mod's triangle and binary mesh are original geometry. Only a material resource name is referenced; no game mesh, texture or material file is redistributed. Mesh attributes use float32, indices use int32, and their offsets/counts are byte offsets/counts. Native loading rejected the initial uint16 probe with `count % sizeof(int) == 0`; the original triangle now uses 32-bit indices. An earlier native load rejected an unversioned mod model with `legacyLocation || version >= 2`; the model now explicitly sets `version = 2`.

Public primary references: [TF3 resource formats](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes) and [TF3 mesh documentation](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:msh). Native tests remain the evidence for compatibility with the installed build.

## Prototype available in the game panel

**Read water support** reads the current global water level without changing the map. **Check test water area** validates the configured local patch and resource availability without building. **Build experimental test water** queues a construction for an engine build step. No map objects are deleted and native proposal errors are retained.

Each probe is a rectangular patch, 1–100 metres in each direction, with an explicit start and end height in game coordinates. Equal heights test a flat lake/pond surface; unequal heights test an inclined river/stream surface. This is a representation experiment, **not automatic OSM water import**, flowing-water simulation, a dam structure, or ship navigation. Every accepted patch is recorded with its actual entity IDs and settings. Ownership retry reuses that record instead of building twice. **Prepare another water patch** retains it and unlocks the next settings. Overlapping recorded rectangles are refused, with at most 100 probes per save.

The elevated-model probe now has no terrain shaping. Both native 50→45 m basin tests (unbounded and with a sampled 10 m perimeter) were accepted but generated large terrain spikes and buried the neighbouring 20 m surface. Neither failed test was saved. That raised-basin path is disabled in settings, command preparation and resource callbacks. Command acceptance alone is not acceptable visual evidence.

## Mapped shallow water: requested Landscaping treatment

The installed `base/content/terrain/materials/water_dirty.zip` contains `water_dirty/water_dirty.tmat.lua`, named **Water Dirty**, described as paint for the materials brush. It references the game's albedo, normal and metal/gloss/AO/height textures, has the landscaping `misc` category and priority 1000000. This is terrain material, not the global water renderer. The mod supplies only an original one-pixel `.gtex` mask pointing at `::/terrain/materials/water_dirty/water_dirty.tmat`; no game asset bytes are copied.

Tool 1 now preserves OSM water way/multipolygon geometry, islands, names, IDs, widths and raw `ele`. Preparation triangulates mapped ponds/basins and buffers stream/river/ditch/drain/canal lines. Missing widths are exposed as a configurable approximation (initially 2 m), not measured data. Each face is subdivided to maximum 8 m edges, with a 30,000-face dataset budget and complete-feature omission on overflow. Planned road/rail corridors are conservatively excluded by 20 m rectangles; this may omit more water than the exact corridor requires.

The game mod samples base terrain at build time and persists each sample for rejection/reload. A `LESS` alignment sets the authored bed samples 0.5 m lower, with ground fill using Water Dirty. Unlike the failed elevated basin, it never raises a bed to a chosen water level. Native octree checks refuse nearby existing network edges and other constructions; accepted importer scenery batches are allowed at shared banks. The game terrain grid can interpolate between samples: exact cell coverage, 0.5 m native excavation and boundary influence still need native measurement. **This new shallow-water path is not yet native-validated.** A synthetic two-feature, 112-face probe has been prepared but not installed because the game is showing a map being edited.

Mapped lakes/reservoirs have status `local-sea-level-unsupported`, keeping boundaries and raw height tags. A regional sea-level edit has not been found in the installed API and is not invented. No global water level is changed. `ele` is retained with datum `OSM-untransformed`; transforming it to game coordinates still requires actual map elevation calibration.

## Roads and railways have priority at construction time

New imports use `getBaseHeightAt`, whose installed API documentation explicitly excludes construction terrain alignments. Height references are cached as each network proposal is prepared and saved for retry/reload. Existing imported junction nodes keep their actual accepted positions. Road/rail proposals carry those node heights; TF3's normal network builder applies its terrain alignment when the segment is built. The mod does not pre-flatten the heightmap or alter Heightmap Studio.

An optional prepared node elevation can override the reference:

```lua
elevation={metres=31.25,datum="game",source="Survey transformed to this map's vertical coordinates"}
```

Only finite values within TF3's height range are accepted. The source must be named and the vertical datum must explicitly be `game`. Raw OSM `ele` values are not silently treated as road-deck elevations or converted into game heights. These fields are optional; existing datasets use the game's base terrain. Bridge/tunnel guide heights remain estimates unless explicit node elevations are provided. Older started saves retain their prior height policy.

Accepted road/rail node heights are journalled and **Verify built objects** detects subsequent vertical movement. This check verifies node elevations, not every terrain cell around an embankment. Basin/road overlap and actual vehicle travel still require native tests before expanding terrain manipulation to arbitrary OSM water polygons.

## Remaining work and evidence boundary

The command lifecycle, triangle transforms, blob bounds, disabled unsafe basin mode, shallow-bed samples, network exclusion, rejected proposals, accepted-ownership retry, retained independent heights and overlap prevention are covered by automated tests. These tests do not establish native appearance.

A native 20 × 20 metre surface at game height 20 m was accepted and visibly rendered with the transparent water material on an empty Small map. Global water was separately read as 0 m. The water surface and completed-build lock survived saving and reloading `MapStudio-Water-Rev6-Flat20-20261003.sav` (656099 bytes, SHA256 `ad1fd07de630f2aba40708c8e5dbc06f251d8421ccb1f8c6f1872e5f2359263a`). This establishes a decorative elevated surface, not ship navigation or arbitrary OSM water geometry. The probe had no terrain alignment.

Native loading, appearance at two different elevations, inclined surfaces, terrain-bank influence, and save/reload must be recorded separately. Mapped shallow-water preparation now preserves multipolygon islands and supports small waterway widths, bounded geometry and conservative network exclusions. Remaining work includes native terrain/paint validation, lake height calibration, a verified local lake representation, and less conservative corridor clipping. Missing elevations must be exposed to the user; they cannot be presented as measured values.

# Mapped objects and functioning towns â€” revision 8

Checked against the installed TF3 build 40408 / Steam build 25533170 on 2026-10-04. The implementation also uses the official [resource repository documentation](https://wiki.transportfever3.com/script-doc/api/res.html), [native command documentation](https://wiki.transportfever3.com/script-doc/api/cmd.html) and [engine/map generation documentation](https://wiki.transportfever3.com/script-doc/api/engine.html).

## What the panel offers

Before Start import, select roads, rails, vegetation, ground paint, experimental shallow waters, the original decorative objects, additional mapped objects, decorative building substitutes, named markers and functioning towns. Each category shows its available dataset count. Present object types also get individual checkboxes; each needs its parent category enabled. Counts are cached for the immutable dataset rather than rescanning the whole map on each GUI refresh. Run **Check map and match objects** to see substitutions and objects lacking a safe match. Start repeats the complete check. Options and matches are saved with the import; selections lock after starting.

Preview 0.14 retains building outlines, orientation, dimensions, original tags and source IDs. It also retains mapped benches, bins, drinking-water points, post boxes, bicycle parking, street lamps, rocks, memorials, monuments, water towers, lighthouses, storage tanks and power towers. An eligible kind is a search request, not a promise that TF3 contains a suitable model. Unsupported tagged objects are counted in the panel; they do not silently become stations or industries. Full automatic stations, depots, industry construction and signals remain unimplemented.

Matching reads `api.res.modelRep.getAll(true)` and model metadata/bounding boxes. These are the resources loaded by the current game, including activated mods. It searches vanilla (`::/`) first, then other loaded namespaces if the checkbox allows it. It does not read folders of inactive mods. Transport vehicles, signals, animals and railway-crossing models are excluded. Static class matches use verified vanilla paths, complete filename tokens or an active mod's explicit `metadata.osmImporter.kind` declaration. Ambiguous tokens are rejected. Mod authors can use this metadata for non-English filenames.

Building classes are residential, commercial or industrial where OSM explicitly supplies that information; generic `building=yes` selects a decorative footprint fit without inventing a simulated building class. Candidates must fit the complete source polygon, including concave cuts, without scaling. Explicit numeric building `height` tags in metres or feet can rank otherwise suitable models; `building:levels` is not estimated as a height. Native bounding-box centres are offset to the mapped centre. Courtyards, multiple outer rings, incomplete and partly off-map outlines are left unsupported. Original OSM elevation and level tags stay in metadata; they are not substituted for game heights. Models follow live terrain at construction time.

## Functioning towns

`place=city/town/village/hamlet` plus a name can create a native simulated town instead of a marker. Suburbs, quarters and neighbourhoods remain markers. Area/place-node duplicates with the same name within 300 map metres are merged; distinct settlements with duplicate names stop preflight for review. Existing towns bearing the requested name are protected against duplication.

The installed `base/content/gui.zip`, `gui/map_editor/map_editor.tl`, lines 1745â€“1762, provides the concrete constructor `api.type.Map.Town.new()`, world-coordinate `pos`, default `{1,1,1}` size factors and cargo-needs table. The SDK calls this record `GameMap.Town`; that documentation name is not used as the Lua constructor. Lines 1622 and 1636 use `api.engine.mapgen.createTowns` followed by `api.cmd.makeTownCreateCmd`. The importer follows that native preparation path and checks the returned name and world position before any drawing. Its removal list is never executed. TF3 chooses its native initial town settings; retained OSM population tags are not interpreted as a game population target.

Each accepted town is journalled before its growth-setting command. Retry completes a rejected growth-setting command without creating another town. An unknown accepted outcome blocks replay. Read-only verification checks native TOWN/NAME components, unique journalled IDs, completion and development policy. It also requires simulated buildings in the native town-building map before claiming the town is functional. These automated boundaries use API substitutes, not a physical game run.

## Road growth: the verified limitation

The installed `api/tealdef/api/engine.d.tl`, lines 1295â€“1297, defines `Town.developmentActive` as the flag that stops town growth. The native `game_mechanics/towns/town_growth.script.tl`, lines 27â€“29, stops adding growth experience when that flag is false. `makeTownSetDevelopmentActiveCmd` controls that flag. It freezes building growth as well as new-road development.

`makeTownDevelopAtCmd(position, developStreets, upgradeBuildings)` controls one explicit development command. It is not a persistent prohibition on the game's automatic road growth. `BaseEdge.roadDevelopmentLocked` protects an existing imported road against town updates/extensions; it is not a general ban on town road creation. Imported roads retain that protection.

The panel therefore says **Allow new town roads and automatic town growth**. Turning it off freezes all future automatic development of imported towns, while leaving existing towns alone. Native town creation can still generate initial streets. No supported persistent road-only switch was found in this build's API or native town scripts. A road-only freeze while keeping full native building/XP growth is **not implemented**.

## Validation scope

Tests cover source retention, multipolygon suppression, loaded-mod fallback, repository ID zero, semantic exclusions, footprint fit, source-coordinate immutability, matched-model XYZ journals, town command failures, rejected-versus-unknown outcomes, reload/retry and checkbox locks. Every literal vanilla model reference is checked against installed files/ZIP names. Revision 8's new matching and native town behaviour still require a physical TF3 test, including settlement placement, initial roads, simulation growth and save/reload. Historical revision 4 import success does not establish these new features.

For older datasets, reconvert the original OSM/XML with Preview 0.14 for the new tags and categories. Preserve a dataset already used by a started import. Upgrading runtime files retains older marker behaviour and import progress.

A separate read-only check fed 1,867 installed static-model names and bounding boxes into the Lua matcher. All ten tested classes found fitting vanilla models (seven point-object classes and residential/commercial/industrial footprints). This checks resource geometry and matching logic; it does not execute the native engine.

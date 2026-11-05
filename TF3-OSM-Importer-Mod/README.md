# TF3-OSM-Importer-Mod

Tool 4 in TF3 Map Studio is the standalone **in-game OSM importer** for
Transport Fever 3. New imports use base terrain or explicitly sourced
road and rail heights. Mapped lakes and waterways can use the game's Water
Dirty material and fixed terrain alignments. A separate elevated-water test
builds a decorative surface.

The mod imports a prepared Lua dataset using vanilla roads, railways, vegetation, ground surfaces, decorative objects and place marker models. It provides an **OSM Import** button, separate scroll areas for messages and controls, and saved import progress. **Show place names** displays names and coordinates from saved importer records. TF3 can optimize models into unnamed asset groups, so their ordinary game windows may not show those names. Use [OSM-TF3-Vanilla-Converter](../OSM-TF3-Vanilla-Converter/README.md) to download/convert OSM XML and prepare `dataset.lua`.

Revision 11 protects ground surfaces against float32 coordinate collapse. In the reported Huge map, one thin triangle became a line at native precision and stopped the batch after 172,300 scenery items; this was not evidence of a general object limit. Duplicate polygon vertices are cleaned before building. Only unbuildable ground faces are omitted, with their count and original source indices saved and logged; other items in the batch continue. The original dataset, source cursor and accepted objects are preserved. Retry now distinguishes command preparation failures from uncertain submitted commands. An older saved uncertain-outcome error is recoverable only after a live-world check confirms there are no unjournalled accepted constructions. A complete Huge-map import remains unverified.

## Install and try the sample

1. In the source tree, copy `mod/tf3_osm_importer_mod` to your TF3 local mods folder. In the release ZIP, extract its top-level `tf3_osm_importer_mod` folder there directly:
   `<Steam folder>/userdata/<your Steam user ID>/3493540/local/mods/`
2. Confirm the resulting path ends in `mods/tf3_osm_importer_mod/mod.json`.
3. Enable the mod on a fresh, flat test map. The included fictional sample is 1000 Ãƒâ€” 1000 metres, with 10 road/rail segments, 117 scenery items and one named marker; it fits within 500 metres of the map centre.
4. Click **OSM Import** in the game's mod button area, then **Check map and match objects** before **Start import**.

The game displays **TF3-OSM-Importer-Mod**. The installable folder is `tf3_osm_importer_mod`; the internal mod identity remains `druttzen_osm_vanilla`, revision 12, to preserve saved resource references. TF3 identifies mods by this ID independently of their folder. Its [mod definition](https://wiki.transportfever3.com/doku.php?id=modding:general:moddefinition) restricts IDs to lowercase letters, digits and underscores and excludes hyphens from installation folder names. Tool 1 bundles the same mod: **install only one copy**, and do not enable a second renamed copy. Keep the mod enabled on saves containing its scenery. The original TF2 importer and its mods folder are separate.

When upgrading, close TF3, back up the installed mod, then replace its runtime files while preserving your `content/osm/dataset.lua` and `import-report.json`. The ZIP contains a fictional sample; copying that file over custom data replaces the prepared map. The converter's **Update installed mod** updates the dataset and report only; install revision 12's runtime separately. Restart the game completely after upgrading.

## Use your own OSM data

Put converted `.lua` maps in `mods/tf3_osm_importer_mod/content/osm/maps` inside TF3's userdata folder, then start TF3. Keep different maps under different filenames. In the game, open **OSM Import → Choose .lua map**, select a file from that folder, then **Check map and match objects** before **Start import**. Restart TF3 after adding or replacing map files. The native engine resource reader loads the original converter format directly; arbitrary external paths and the game's unrelated userdata-preset format are not used. A converted Lua map is not a heightmap, saved game or mod script. Match its dimensions and geographic bounds to the game map and heightmap.

The selected resource name, map identity and compact counts are saved; source geometry stays in the engine's runtime memory. On save/reload the engine restores the original file before building can continue. Missing or changed files block progress and expose **Restore original Lua map**. A started import cannot change to another dataset. Keep its original file and filename available. **Use installed dataset.lua** retains the traditional workflow. Close TF3 before replacing any installed resource and restart afterwards.

Revision 10 also removes idle script-state writes and computes category totals from cached aggregates. Selecting categories no longer rescans every map item. The GUI reads compact persisted metadata instead of loading its own copy of the full dataset.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground surfaces, decorative objects and named markers. These selections lock once import starts. **Scenery items per step** (1Ã¢â‚¬â€œ100) and **delay between steps** (0Ã¢â‚¬â€œ2 simulation seconds) remain adjustable while running or paused.

Large datasets are checked in blocks of at most 1000 source items, with persisted progress and no building until the entire selected dataset passes. **Pause import / cancel check** cancels a check without building; selections cannot change during checking. A prepared area larger than the current game map is rejected immediately with both dimensions. Small centered samples are allowed; matching dimensions alone do not prove heightmap alignment.

TF3 rejects coordinates exactly on its positive X/Y boundary. The importer applies a one-centimetre inward margin there during checking, building and object verification, including scenery and bridge/tunnel height guides. Original Lua files, dimensions and geographic bounds are preserved; genuinely outside coordinates still fail.

**Automatic pause** limits each run to 1Ã¢â‚¬â€œ10000 successful build steps, or 0 for unlimited. A step is one accepted road/rail group, one scenery group or one marker. New datasets with over 1000 items default to 100 steps unless explicitly configured; existing imports retain their unlimited setting. Save and inspect the map when paused. Resume resets the run counter; retry completes accepted ownership without consuming another step. Excluded categories are also scanned in bounded blocks.

Revision 12 can build up to 100 road/rail segments or 1,000 scenery items per
successful step. The default network group is one segment. On a rejected
network group the panel gives its source range; reduce the group and Retry to
isolate the segment without losing accepted progress. For a single segment it
also displays its OSM way when available. Short rail continuations align with
the accepted neighbour's tangent. See the [Partille system test](../SYSTEM-TEST-2026-11-05.md)
for the verified scope and remaining full-network limitation.

The panel offers check, start, pause, resume, retry, skip, progress, **Verify built objects**, **Show place names** and map-size commands. Retry repeats a rejected proposal using the selected group size. If geometry was accepted but ownership or naming failed, retry completes that step without rebuilding it; skip is refused for an accepted object. Skip omits the recorded rejected source range, potentially an entire network or scenery group. Progress and scenery entity references are saved with the map. Keep the original dataset when resuming: changing it stops the importer. A started or finished dataset cannot restart in the same save; use a fresh map for another import.

After import, use **Verify built objects**. It reads recorded nodes, road/rail types, ownership, vehicle-compatible lanes and graph connections. For optimized model groups it compares live model resource IDs, positions, rotations and scales; retained constructions are checked through saved item parameters. Ground paint appearance and actual vehicle routes require inspection in the game. Old saves without scenery entity records cannot reliably identify unnamed model groups and may report missing objects. **Show place names** cycles through twenty names per page with coordinates measured from the map centre.

The optional Lua console helper supports the same commands, for example:

```lua
ug_require("druttzen_osm_vanilla::/osm/console.lua").status()
```

See the installed mod's [README.txt](mod/tf3_osm_importer_mod/README.txt) for controls and limits.

## Road/rail heights and experimental local water

For new imports, construction terrain alignments are excluded from the road/rail height reference. Optional sourced elevations must explicitly use the map's game coordinates; raw OSM `ele` is not assumed to be road-deck height. Height references survive rejected proposals and reload. Existing started imports keep their previous height policy. Verify built objects also detects movement from recorded accepted node heights. The game aligns terrain when building a network proposal. Heightmap Studio can optionally prepare dry corridors before importing a map with coastal roads.

Select **Mapped lakes and waterways: Water Dirty** before starting a new
import. The converter preserves valid OSM outlines and island holes. The mod
uses the game's Water Dirty material and holds the visible terrain to a
fixed surface. Each lake, pond or reservoir shares one sampled base height
across its triangles and batches. Waterway triangles follow the terrain.
Older converted maps with the 0.5 m shallow-bed treatment retain their
previous alignment. Reconvert the OSM source for the new behavior.

OSM `width` or `est_width` is retained for lines. If missing, the converter exposes **Small water width if OSM width is missing**, initially 2 m; a warning identifies this as an approximation. Widths outside 0.1Ã¢â‚¬â€œ20 m require review. Preparation is limited to 30,000 shallow-water triangles per dataset; an oversized feature is omitted whole rather than partially filling it. Water in conservative 20 m corridors around prepared roads/rails is omitted, and native proposals also reject nearby existing networks and other constructions. These checks protect current mapped networks; future manually constructed roads still need inspection.

Lake and reservoir boundaries, names, OSM IDs and raw `ele` tags are preserved
in `waterFeatures`. Surface elevations come from the game's terrain. Water
Dirty is a terrain material. The game continues to use its single global
water level for navigation.

The panel also provides **Read water support**, **Check test water area**, **Build experimental test water** and **Prepare another water patch** for separate rectangular elevated model surfaces. These use a vanilla transparent material at chosen heights; accepted objects are retained without duplication, with at most 100 separate non-overlapping patches. The earlier raised-basin experiment produced large terrain spikes in native TF3, both with and without a sampled perimeter. That terrain-shaping path is now disabled, including console and resource callbacks.

See [the system test report](../SYSTEM-TEST-2026-11-05.md) and
[WATER-RESEARCH.md](WATER-RESEARCH.md) for the current native and historical
water tests.

[The fictional water test](../OSM-TF3-Vanilla-Converter/examples/water-test.osm)
contains a pond, a 4 m stream and a lake with a raw elevation. Convert it at
**1000 × 1000 m** and select the water option in a fresh test map. Keep the
original dataset with any already-started import.

## Preview status and development checks

TF3 script resources expose global `data()` entry points, and helper modules/datasets return Lua tables. The panel uses the game's window wrapper and reads persisted script state through the permitted render API. The importer explicitly schedules build steps and assigns ownership through native entity commands. Tests use the resource identifier types observed in the installed game, including string ground-texture identifiers.

Automated checks simulate TF3 commands and UI recipes. They verify persistence, pause/resume, rejected proposals, selected categories, duplicate prevention, live object checks and panel callbacks. A separate audit checks resource names without copying assets. Native sample import completed in TF3 Windows build 40408 (Steam build 25533170): 10 road/rail segments, 117 scenery items and one marker. See [validation.json](validation.json) for the precise scope of completed native checks and remaining validation. A small fictional sample does not establish reliability for large real-world maps, steep terrain, bridges, tunnels or vehicle routing.

Development only (Python 3.10+):

```text
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tests/check_resources.py "<your Transport Fever 3 installation folder>"
python scripts/package_mod.py
```

The portable package script works from any current directory and defaults to `dist/TF3-OSM-Importer-Mod-Preview.zip`; use `--output <path>` for another destination. Its archive contains only the installable `tf3_osm_importer_mod/` folder. Tests and Python source remain in the repository. Lupa is required only for tests; packaging uses Python's standard library. Playing with the mod needs neither Python nor external asset packs. [validation.json](validation.json) records the checks and remaining game validation.

## Limits and attribution

Networks prefer vanilla resources; matched scenery can also use loaded active mods; the experimental water triangle is original geometry referencing a vanilla material. Roads/rails follow the selected native profile; footpaths have road traffic semantics, narrow gauge becomes standard gauge, and bridge/tunnel heights require manual inspection. Named markers are decorative; explicit settlement tags can instead create optional functioning towns. Functional stations, depots, signals and local lake flooding require further implementation; base terrain comes from a separate heightmap. Imported geometry does not automatically snap to existing nodes.

GPL-3.0; see [LICENSE](LICENSE) and [NOTICE.txt](NOTICE.txt). Original concept: VacuumTube's OSM-TPF2-Importer; TF3 rebuild prepared for Druttzen. The sample data is fictional. Real OSM maps require attribution to [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) under ODbL. Vanilla assets remain game-owned and are not redistributed.

## Mapped objects and functioning towns

Revision 8 adds source counts and checkboxes for additional mapped objects, decorative building substitutes and functioning towns. **Check map and match objects** previews vanilla-first matches and fallback to models loaded by active mods. Candidates without a safe semantic/footprint fit are left unbuilt with a visible reason. Preview 0.16 exports the original tags, IDs and building geometry needed by these choices. Reconvert an original OSM/XML on a fresh import; preserve data already used in a started save.

`place=city/town/village/hamlet` with a name can create a native simulated town. Other place names remain markers. TF3 generates the initial town settings and may generate initial streets. Turning off **Allow new town roads and automatic town growth** freezes **all** future automatic town development, including buildings. There is no verified persistent road-only switch in this build. Existing towns retain their policies. Accepted-town records prevent duplicates when applying a growth policy fails and is retried.

New matching/town behaviour has automated tests and resource checks but awaits physical TF3 testing. See [the native API investigation and exact limits](TOWNS-OBJECTS-RESEARCH.md).

Revision 9 rejects checks of a different dataset during a paused import before
saved model matches can be overwritten. The original dataset of any started
import must still be retained. See the [25 October review](../CODE-REVIEW-2026-10-25.md).

Revision 10 native Windows verification selected a Lua map in the in-game file dialog, restored it after a full restart, and completed the fictional sample: 10/10 road/rail segments, 117/117 scenery items and 1/1 marker, with no skipped steps. See [the exact scope and API findings](NATIVE-MAP-SELECTION-2026-10-25.md).

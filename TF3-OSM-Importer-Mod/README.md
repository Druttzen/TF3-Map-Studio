# TF3-OSM-Importer-Mod

Tool 4 in TF3 Map Studio: the standalone **in-game OSM importer** for Transport Fever 3, revision 8, also bundled with tool 1 Preview 0.14. New imports use base-terrain or explicitly sourced road/rail heights at construction time and save accepted heights for verification. Mapped ponds and small waterways have an experimental 0.5 m bed and Landscaping Water Dirty treatment. A separate elevated-water test builds a decorative surface without terrain alignment. Incremental checks, automatic pause and positive-boundary handling are retained.

The mod imports a prepared Lua dataset using vanilla roads, railways, vegetation, ground surfaces, decorative objects and place marker models. It provides an **OSM Import** button, separate scroll areas for messages and controls, and saved import progress. **Show place names** displays names and coordinates from saved importer records. TF3 can optimize models into unnamed asset groups, so their ordinary game windows may not show those names. Use [OSM-TF3-Vanilla-Converter](../OSM-TF3-Vanilla-Converter/README.md) to download/convert OSM XML and prepare `dataset.lua`.

## Install and try the sample

1. In the source tree, copy `mod/tf3_osm_importer_mod` to your TF3 local mods folder. In the release ZIP, extract its top-level `tf3_osm_importer_mod` folder there directly:
   `<Steam folder>/userdata/<your Steam user ID>/3493540/local/mods/`
2. Confirm the resulting path ends in `mods/tf3_osm_importer_mod/mod.json`.
3. Enable the mod on a fresh, flat test map. The included fictional sample is 1000 Ãƒâ€” 1000 metres, with 10 road/rail segments, 117 scenery items and one named marker; it fits within 500 metres of the map centre.
4. Click **OSM Import** in the game's mod button area, then **Check map and match objects** before **Start import**.

The game displays **TF3-OSM-Importer-Mod**. The installable folder is `tf3_osm_importer_mod`; the internal mod identity remains `druttzen_osm_vanilla`, revision 8, to preserve saved resource references. TF3 identifies mods by this ID independently of their folder. Its [mod definition](https://wiki.transportfever3.com/doku.php?id=modding:general:moddefinition) restricts IDs to lowercase letters, digits and underscores and excludes hyphens from installation folder names. Tool 1 bundles the same mod: **install only one copy**, and do not enable a second renamed copy. Keep the mod enabled on saves containing its scenery. The original TF2 importer and its mods folder are separate.

When upgrading, close TF3, back up the installed mod, then replace its runtime files while preserving your `content/osm/dataset.lua` and `import-report.json`. The ZIP contains a fictional sample; copying that file over custom data replaces the prepared map. The converter's **Update installed mod** updates the dataset and report only; install revision 8's runtime separately. Restart the game completely after upgrading.

## Use your own OSM data

Close TF3 before changing a dataset. In tool 1, choose **Update installed mod** and select your existing `tf3_osm_importer_mod` folder (older `druttzen_osm_vanilla` installations are also accepted), or export a Lua map and copy it to `content/osm/dataset.lua` in that folder. Match the converter's dimensions and geographic bounds to the game map and heightmap. A converted Lua file is an importer dataset, not a heightmap or game save. Restart TF3 after updating.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground surfaces, decorative objects and named markers. These selections lock once import starts. **Scenery items per step** (1Ã¢â‚¬â€œ100) and **delay between steps** (0Ã¢â‚¬â€œ2 simulation seconds) remain adjustable while running or paused.

Large datasets are checked in blocks of at most 1000 source items, with persisted progress and no building until the entire selected dataset passes. **Pause import / cancel check** cancels a check without building; selections cannot change during checking. A prepared area larger than the current game map is rejected immediately with both dimensions. Small centered samples are allowed; matching dimensions alone do not prove heightmap alignment.

TF3 rejects coordinates exactly on its positive X/Y boundary. The importer applies a one-centimetre inward margin there during checking, building and object verification, including scenery and bridge/tunnel height guides. Original Lua files, dimensions and geographic bounds are preserved; genuinely outside coordinates still fail.

**Automatic pause** limits each run to 1Ã¢â‚¬â€œ10000 successful build steps, or 0 for unlimited. A step is one road/rail segment, one scenery batch or one marker. New datasets with over 1000 items default to 100 steps unless explicitly configured; existing imports retain their unlimited setting. Save and inspect the map when paused. Resume resets the run counter; retry completes accepted ownership without consuming another step. Excluded categories are also scanned in bounded blocks.

The panel offers check, start, pause, resume, retry, skip, progress, **Verify built objects**, **Show place names** and map-size commands. Retry repeats a rejected proposal. If geometry was accepted but ownership or naming failed, retry completes that step without rebuilding it; skip is refused for an accepted object. Skip omits a rejected proposal, potentially an entire scenery batch. Progress and scenery entity references are saved with the map. Keep the original dataset when resuming: changing it stops the importer. A started or finished dataset cannot restart in the same save; use a fresh map for another import.

After import, use **Verify built objects**. It reads recorded nodes, road/rail types, ownership, vehicle-compatible lanes and graph connections. For optimized model groups it compares live model resource IDs, positions, rotations and scales; retained constructions are checked through saved item parameters. Ground paint appearance and actual vehicle routes require inspection in the game. Old saves without scenery entity records cannot reliably identify unnamed model groups and may report missing objects. **Show place names** cycles through twenty names per page with coordinates measured from the map centre.

The optional Lua console helper supports the same commands, for example:

```lua
ug_require("druttzen_osm_vanilla::/osm/console.lua").status()
```

See the installed mod's [README.txt](mod/tf3_osm_importer_mod/README.txt) for controls and limits.

## Road/rail heights and experimental local water

For new imports, construction terrain alignments are excluded from the road/rail height reference. Optional sourced elevations must explicitly use the map's game coordinates; raw OSM `ele` is not assumed to be road-deck height. Height references survive rejected proposals and reload. Existing started imports keep their previous height policy. Verify built objects also detects movement from recorded accepted node heights. The game's network proposal aligns terrain when each segment is built; Heightmap Studio is unchanged.

OSM XML water ways and multipolygons are prepared by tool 1; the **terrain changes happen only inside this mod**, through Start import. Select **Mapped small waters: 0.5 m bed + Water Dirty**, initially off while native validation is pending. Closed pond/basin polygons and river/stream/ditch/drain/canal lines become small triangles with at most 8 m edges. Multipolygon islands remain unpainted. Crossing, incomplete or excessively complex boundaries are retained for review without partial filling. The mod samples and saves base terrain heights when each batch is built, sets the bed 0.5 m lower with a **LESS** alignment, and paints an original mask referencing the game's exact Landscaping `Water Dirty` material. Rejected proposals and reload reuse the saved heights; terrain is not excavated repeatedly.

OSM `width` or `est_width` is retained for lines. If missing, the converter exposes **Small water width if OSM width is missing**, initially 2 m; a warning identifies this as an approximation. Widths outside 0.1Ã¢â‚¬â€œ20 m require review. Preparation is limited to 30,000 shallow-water triangles per dataset; an oversized feature is omitted whole rather than partially filling it. Water in conservative 20 m corridors around prepared roads/rails is omitted, and native proposals also reject nearby existing networks and other constructions. These checks protect current mapped networks; future manually constructed roads still need inspection.

Lake/reservoir boundaries, names, OSM IDs and raw `ele` tags are preserved in `waterFeatures`. **The requested per-lake sea level is not implemented:** the installed API exposes global water and no supported command for raising sea level inside one polygon was found. No global water change or automatic lake flooding occurs. Raw OSM elevations are not assumed to equal game elevations. Reconvert an older OSM file with Preview 0.14 to include the water geometry; keep the old dataset with any already-started import.

The panel also provides **Read water support**, **Check test water area**, **Build experimental test water** and **Prepare another water patch** for separate rectangular elevated model surfaces. These use a vanilla transparent material at chosen heights; accepted objects are retained without duplication, with at most 100 separate non-overlapping patches. The earlier raised-basin experiment produced large terrain spikes in native TF3, both with and without a sampled perimeter. That terrain-shaping path is now disabled, including console and resource callbacks.

This version's new shallow-water treatment passes automated geometry and state-machine tests but **has not yet been validated in native TF3**. A prior surface-only 20 m elevated model was rendered and saved/reloaded successfully; that result does not validate excavation or ground paint. Water Dirty is ground texture, not flowing or ship-navigable water. Use a separate test map. Read [WATER-RESEARCH.md](WATER-RESEARCH.md) and [validation.json](validation.json) for exact evidence.

[The fictional water test](../OSM-TF3-Vanilla-Converter/examples/water-test.osm) contains a pond, a 4 m stream and a lake with a raw elevation. Convert it at **1000 Ãƒâ€” 1000 m**, install it only for a separate fresh test map, and explicitly select Mapped small waters. The pond/stream are prepared for shallow treatment; the lake remains pending. Never replace the dataset belonging to an already-started import.

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

Revision 8 adds source counts and checkboxes for additional mapped objects, decorative building substitutes and functioning towns. **Check map and match objects** previews vanilla-first matches and fallback to models loaded by active mods. Candidates without a safe semantic/footprint fit are left unbuilt with a visible reason. Preview 0.14 exports the original tags, IDs and building geometry needed by these choices. Reconvert an original OSM/XML on a fresh import; preserve data already used in a started save.

`place=city/town/village/hamlet` with a name can create a native simulated town. Other place names remain markers. TF3 generates the initial town settings and may generate initial streets. Turning off **Allow new town roads and automatic town growth** freezes **all** future automatic town development, including buildings. There is no verified persistent road-only switch in this build. Existing towns retain their policies. Accepted-town records prevent duplicates when applying a growth policy fails and is retried.

New matching/town behaviour has automated tests and resource checks but awaits physical TF3 testing. See [the native API investigation and exact limits](TOWNS-OBJECTS-RESEARCH.md).

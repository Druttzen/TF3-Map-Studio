# TF3-OSM-Importer-Mod

Tool 4 in TF3 Map Studio: the standalone **in-game OSM importer** for Transport Fever 3, revision 4. The same runtime is bundled with tool 1, OSM-TF3-Vanilla-Converter Preview 0.10. This revision fixes native panel loading, engine scheduling, resource checks and ownership, and adds a read-only check of built objects.

The mod imports a prepared Lua dataset using vanilla roads, railways, vegetation, ground surfaces, decorative objects and place marker models. It provides an **OSM Import** button, separate scroll areas for messages and controls, and saved import progress. **Show place names** displays names and coordinates from saved importer records. TF3 can optimize models into unnamed asset groups, so their ordinary game windows may not show those names. Use [OSM-TF3-Vanilla-Converter](../OSM-TF3-Vanilla-Converter/README.md) to download/convert OSM XML and prepare `dataset.lua`.

## Install and try the sample

1. In the source tree, copy `mod/druttzen_osm_vanilla` to your TF3 local mods folder. In the release ZIP, extract its top-level `druttzen_osm_vanilla` folder there directly:
   `<Steam folder>/userdata/<your Steam user ID>/3493540/local/mods/`
2. Confirm the resulting path ends in `mods/druttzen_osm_vanilla/mod.json`.
3. Enable the mod on a fresh, flat test map. The included fictional sample is 1000 × 1000 metres, with 10 road/rail segments, 117 scenery items and one named marker; it fits within 500 metres of the map centre.
4. Click **OSM Import** in the game's mod button area, then **Check map and resources** before **Start import**.

The mod identity remains `druttzen_osm_vanilla`, now with revision 4. Tool 1 bundles the same mod: **install only one copy**, and do not enable a second renamed copy. Keep the mod enabled on saves containing its scenery. The original TF2 importer and its mods folder are separate.

When upgrading, close TF3, back up the installed mod, then replace its runtime files while preserving your `content/osm/dataset.lua` and `import-report.json`. The ZIP contains a fictional sample; copying that file over custom data replaces the prepared map. The converter's **Update installed mod** updates the dataset and report only; install revision 4's runtime separately. Restart the game completely after upgrading.

## Use your own OSM data

Close TF3 before changing a dataset. In tool 1, choose **Update installed mod** and select your existing `druttzen_osm_vanilla` folder, or export a Lua map and copy it to `content/osm/dataset.lua` in that folder. Match the converter's dimensions and geographic bounds to the game map and heightmap. A converted Lua file is an importer dataset, not a heightmap or game save. Restart TF3 after updating.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground surfaces, decorative objects and named markers. These selections lock once import starts. **Scenery items per step** (1–100) and **delay between steps** (0–2 simulation seconds) remain adjustable while running or paused.

The panel offers check, start, pause, resume, retry, skip, progress, **Verify built objects**, **Show place names** and map-size commands. Retry repeats a rejected proposal. If geometry was accepted but ownership or naming failed, retry completes that step without rebuilding it; skip is refused for an accepted object. Skip omits a rejected proposal, potentially an entire scenery batch. Progress and scenery entity references are saved with the map. Keep the original dataset when resuming: changing it stops the importer. A started or finished dataset cannot restart in the same save; use a fresh map for another import.

After import, use **Verify built objects**. It reads recorded nodes, road/rail types, ownership, vehicle-compatible lanes and graph connections. For optimized model groups it compares live model resource IDs, positions, rotations and scales; retained constructions are checked through saved item parameters. Ground paint appearance and actual vehicle routes require inspection in the game. Old saves without scenery entity records cannot reliably identify unnamed model groups and may report missing objects. **Show place names** cycles through twenty names per page with coordinates measured from the map centre.

The optional Lua console helper supports the same commands, for example:

```lua
ug_require("druttzen_osm_vanilla::/osm/console.lua").status()
```

See the installed mod's [README.txt](mod/druttzen_osm_vanilla/README.txt) for controls and limits.

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

The portable package script works from any current directory and defaults to `dist/TF3-OSM-Importer-Mod-Preview.zip`; use `--output <path>` for another destination. Its archive contains only the installable `druttzen_osm_vanilla/` folder. Tests and Python source remain in the repository. Lupa is required only for tests; packaging uses Python's standard library. Playing with the mod needs neither Python nor external asset packs. [validation.json](validation.json) records the checks and remaining game validation.

## Limits and attribution

Only vanilla game resource references are included. Roads/rails follow the selected native profile; footpaths have road traffic semantics, narrow gauge becomes standard gauge, and bridge/tunnel heights require manual inspection. Named markers are not functioning towns. Buildings, stations, depots, towns, signals and water features require the game tools; terrain comes from a separate heightmap. Imported geometry does not automatically snap to existing nodes.

GPL-3.0; see [LICENSE](LICENSE) and [NOTICE.txt](NOTICE.txt). Original concept: VacuumTube's OSM-TPF2-Importer; TF3 rebuild prepared for Druttzen. The sample data is fictional. Real OSM maps require attribution to [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) under ODbL. Vanilla assets remain game-owned and are not redistributed.

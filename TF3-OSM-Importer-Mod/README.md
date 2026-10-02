# TF3-OSM-Importer-Mod

Tool 4 in TF3 Map Studio: the standalone **in-game OSM importer** for Transport Fever 3. Extracted from the current mod supplied with tool 1, OSM-TF3-Vanilla-Converter Preview 0.9; the mod keeps revision 3. This packaging split makes no changes to game scripts, metadata or the sample dataset.

The mod imports a prepared Lua dataset using vanilla roads, railways, vegetation, ground surfaces, decorative objects and named markers. It provides an **OSM Import** button, a scrollable control panel and saved import progress. Use [OSM-TF3-Vanilla-Converter](../OSM-TF3-Vanilla-Converter/README.md) to download/convert OSM XML and prepare `dataset.lua`.

## Install and try the sample

1. In the source tree, copy `mod/druttzen_osm_vanilla` to your TF3 local mods folder. In the release ZIP, extract its top-level `druttzen_osm_vanilla` folder there directly:
   `<Steam folder>/userdata/<your Steam user ID>/3493540/local/mods/`
2. Confirm the resulting path ends in `mods/druttzen_osm_vanilla/mod.json`.
3. Enable the mod on a fresh, flat test map. The included fictional sample is 1000 × 1000 metres, with 10 road/rail segments, 117 scenery items and one named marker; it fits within 500 metres of the map centre.
4. Click **OSM Import** in the game's mod button area, then **Check map and resources** before **Start import**.

The mod identity remains `druttzen_osm_vanilla` with revision 3. Tool 1 bundles the same mod: **install only one copy**, and do not enable a second renamed copy. Keep the mod enabled on saves containing its scenery. The original TF2 importer and its mods folder are separate.

## Use your own OSM data

Close TF3 before changing a dataset. In tool 1, choose **Update installed mod** and select your existing `druttzen_osm_vanilla` folder, or export a Lua map and copy it to `content/osm/dataset.lua` in that folder. Match the converter's dimensions and geographic bounds to the game map and heightmap. A converted Lua file is an importer dataset, not a heightmap or game save. Restart TF3 after updating.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground surfaces, decorative objects and named markers. These selections lock once import starts. **Scenery items per step** (1–100) and **delay between steps** (0–2 simulation seconds) remain adjustable while running or paused.

The panel offers check, start, pause, resume, retry, skip, progress and map-size commands. Retry repeats a rejected proposal; skip omits the whole failed proposal, potentially an entire scenery batch. Progress is saved with the map. Keep the original dataset when resuming: changing it stops the importer. A started or finished dataset cannot restart in the same save; use a fresh map for another import.

The optional Lua console helper supports the same commands, for example:

```lua
ug_require("druttzen_osm_vanilla::/osm/console.lua").status()
```

See the installed mod's [README.txt](mod/druttzen_osm_vanilla/README.txt) for controls and limits.

## Preview status and development checks

The existing fix for `function data() not defined` is preserved: TF3 script resources expose global `data()` entry points, and helper modules/datasets return Lua tables. Tests load resources in isolated environments and resolve every referenced script callback.

Automated checks simulate TF3 commands and UI recipes. They verify Lua loading, persistence, pause/resume, rejected proposals, retry/skip, selected categories, settings and panel callback wiring. A separate read-only audit checks vanilla resources against an installed game without copying assets. These checks do **not** verify an actual TF3 import, native panel rendering/scrolling, proposal acceptance, ownership, or road/rail connectivity. The next check is the sample on a temporary map with this mod alone, followed by pause/retry and save/reload.

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

TF3-OSM-IMPORTER-MOD
Extracted from companion Preview 0.9 | Mod revision 3 | GPL-3.0

INSTALL
Copy this druttzen_osm_vanilla folder into:
<Steam folder>/userdata/<your Steam user ID>/3493540/local/mods/
The result must end in mods/druttzen_osm_vanilla/mod.json.

This is the same mod bundled with OSM-TF3-Vanilla-Converter (tool 1).
Install only one copy. Keep modId druttzen_osm_vanilla; do not rename a
second copy and enable both. Do not put it in the original TF2 mods folder.

FIRST TEST
Enable the mod on a fresh, flat test map. The included fictional dataset
is 1000 x 1000 metres, with 10 road/rail segments, 117 scenery items and
one named marker. Its geometry fits within 500 metres of the map centre.
Click OSM Import in the mod button area, then Check map and resources.
Start import begins the selected import. Use a temporary map first.

DATASET PREPARATION
Use the companion OSM-TF3-Vanilla-Converter to download/convert OSM XML.
Close TF3 before changing its data. Choose Update installed mod in the
converter and select this folder, or export a Lua map and copy it to
content/osm/dataset.lua. Match the game dimensions and heightmap bounds.
Restart TF3 afterwards. The dataset is not a heightmap or a game save.

PANEL CONTROLS
OSM Import toggles a movable window. Scroll its list for commands/settings.
The window shows progress, notices and errors; its close button closes
the panel. No debug mode or console is required for these controls.

- Check map and resources checks without building anything.
- Start import builds the selected dataset categories.
- Pause import keeps the current position; Resume import continues it.
- Retry failed step repeats the rejected proposal.
- Skip failed step omits the whole proposal, possibly a scenery batch.
- Show progress refreshes the message and writes it to the game log.
- Read map size shows width and height for the companion converter.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground
surfaces, decorative objects and named markers. These selections lock
after starting. Scenery items per step (1-100) and delay between steps
(0-2 simulation seconds) can change while running or paused. Delay uses
simulation time; the fastest setting can continue with the game paused.

Progress is stored in the save. The importer builds scenery, roads/rails,
then named markers and stops at a rejected proposal. It does not bulldoze
existing map objects or deliberately suppress build errors. A started or
finished dataset cannot restart in the same save. Use a fresh map for
another dataset, keep its original dataset.lua when resuming, and keep
this mod enabled on saves containing its scenery. A changed dataset stops
the importer. Messages use the prefix [OSM Vanilla].

OPTIONAL CONSOLE
Enable Debug Mode in the game's settings and open its Lua/debug console.
The console shortcut can vary with game build and keyboard layout.

ug_require("druttzen_osm_vanilla::/osm/console.lua").start()

The helper also supports .validate(), .status(), .pause(), .resume(),
.retry(), .skip(), .configure(options), and .mapSize().

LIMITS
Vanilla assets only; no workshop dependency or bundled game assets.
Road/rail widths, speeds and lanes follow their chosen native profiles.
Footpaths/cycleways/steps are small roads with road traffic semantics.
Narrow gauge is approximated with standard gauge. Trees, shrubs and
ground surfaces use vanilla resources; bollards use a mooring bollard.
Named markers are not functioning towns. Bridge/tunnel heights are
estimated from terrain endpoints: inspect grades and clearances.
Signals, buildings, stations, depots, functioning towns and water features
require the game tools. Terrain comes from a separate heightmap.
Imported geometry does not automatically snap to existing map nodes.

PREVIEW STATUS
Lua/state-machine and panel callback tests simulate TF3 boundaries.
The existing startup fix is preserved: script resources expose global
data() functions; helpers and datasets remain normal Lua table modules.
Restart TF3 completely after updating, rather than using Reload UI on a
failed startup. Automated checks do not verify native proposal acceptance,
ownership, connectivity, panel placement, rendering or scrolling.
Actual in-game validation is pending: import the sample with this mod
alone, inspect the result, test pause/retry and save/reload the map.
See the source package's validation.json for exact completed checks.

ATTRIBUTION
Original concept/mod: VacuumTube, OSM-TPF2-Importer, GPL-3.0.
TF3 rebuild prepared for Druttzen. See LICENSE and NOTICE.txt.
The included sample is fictional. Real OSM maps require attribution to
OpenStreetMap contributors and compliance with ODbL:
https://www.openstreetmap.org/copyright

The companion desktop converter and its Pillow library are not bundled in
this game mod. NOTICE.txt retains the original concept and GPL attribution.

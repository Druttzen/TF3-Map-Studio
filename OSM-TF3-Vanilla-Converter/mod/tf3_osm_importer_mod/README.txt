TF3-OSM-Importer-Mod
Companion Preview 0.12 | Mod revision 6 | GPL-3.0 | 3 October 2026

INSTALL
Copy this tf3_osm_importer_mod folder into:
<Steam folder>/userdata/<your Steam user ID>/3493540/local/mods/
The result must end in mods/tf3_osm_importer_mod/mod.json.

This is the same mod bundled with OSM-TF3-Vanilla-Converter (tool 1).
The game displays TF3-OSM-Importer-Mod. The folder is tf3_osm_importer_mod.
The internal modId remains druttzen_osm_vanilla for existing saves.
Install only one copy; do not enable both old and renamed installations. Do not put it in the original TF2 mods folder.

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

- Check map and resources checks without building. Large datasets are
  checked in blocks of at most 1000 items; progress is saved and displayed.
  Pause cancels a running check without building. Selections lock during
  checking. No geometry is built until every selected item passes.
  Prepared dimensions larger than the game map are rejected immediately.
  Smaller sample areas are allowed; custom OSM and heightmaps must still
  share their intended bounds and dimensions.
- Start import builds the selected dataset categories.
- Pause import keeps the current position; Resume import continues it.
- Retry failed step repeats a rejected proposal, or completes ownership and
  naming for an accepted object without rebuilding it. An accepted object
  cannot be skipped.
- Skip failed step omits the whole proposal, possibly a scenery batch.
- Show progress refreshes the message and writes it to the game log.
- Verify built objects reads live road/rail nodes, profiles, ownership,
  vehicle-compatible lanes and connections. It checks optimized models by
  live resource ID and transform; retained constructions by saved items.
- Show place names displays twenty recorded names and map coordinates per
  page. Click again for the next page. TF3 may optimize marker models into
  unnamed asset groups; ordinary game windows may not show their names.
- Read map size shows width and height for the companion converter.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground
surfaces, decorative objects and named markers. These selections lock
after starting. Scenery items per step (1-100) and delay between steps
(0-2 simulation seconds) can change while running or paused. Delay uses
simulation time; the fastest setting can continue with the game paused.

Automatic pause can stop each run after 1-10000 successful build steps;
0 disables it. One step is one road/rail segment, one scenery batch or one
marker, not one object. New datasets with over 1000 items default to 100
steps unless the dataset explicitly sets a limit. Existing imports keep
their prior unlimited setting. Choose a small limit for a first trial.
Save and inspect each paused run; Resume resets its step counter. Pending
ownership finalization completes before an automatic pause. Rejected
proposals and excluded items do not consume the successful-step limit.

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
.retry(), .skip(), .verify(), .placeNames(), .configure(options), and .mapSize().

LIMITS
Vanilla assets only; no workshop dependency or bundled game assets.
Road/rail widths, speeds and lanes follow their chosen native profiles.
Footpaths/cycleways/steps are small roads with road traffic semantics.
Narrow gauge is approximated with standard gauge. Trees, shrubs and
ground surfaces use vanilla resources; bollards use a mooring bollard.
Place markers and their recorded names are not functioning towns. Bridge/tunnel heights are
estimated from terrain endpoints: inspect grades and clearances.
Signals, buildings, stations, depots, functioning towns and water features
require the game tools. Terrain comes from a separate heightmap.
Imported geometry does not automatically snap to existing map nodes.

PREVIEW STATUS
Lua/state-machine and panel callback tests simulate TF3 boundaries.
The existing startup fix is preserved: script resources expose global
data() functions; helpers and datasets remain normal Lua table modules.
Restart TF3 completely after updating, rather than using Reload UI on a
failed startup. The fictional sample completed in TF3 Windows build 40408
(Steam build 25533170): 10 road/rail segments, 117 scenery items and one
marker. Read validation.json in the source package for exact native checks.
Ground appearance and actual vehicle routes need inspection in the game.
Large real maps, terrain slopes, bridges and tunnels remain preview work.
Older saves without scenery entity records may report missing unnamed
objects because they cannot be reliably identified.
See the source package's validation.json for exact completed checks.

UPGRADING
Close TF3 and back up the installed mod. Replace runtime files while
preserving content/osm/dataset.lua and import-report.json for a custom map.
The release ZIP contains a fictional dataset. Update installed mod in the
desktop converter updates only the dataset/report, not the runtime.
Restart TF3 completely after installing the new runtime.

ATTRIBUTION
Original concept/mod: VacuumTube, OSM-TPF2-Importer, GPL-3.0.
TF3 rebuild prepared for Druttzen. See LICENSE and NOTICE.txt.
The included sample is fictional. Real OSM maps require attribution to
OpenStreetMap contributors and compliance with ODbL:
https://www.openstreetmap.org/copyright

The companion desktop converter and its Pillow library are not bundled in
this game mod. NOTICE.txt retains the original concept and GPL attribution.


ROAD/RAIL HEIGHT PRIORITY
New imports use TF3 base terrain, excluding construction alignments. Optional
node elevation={metres=31.25,datum="game",source="Survey transformed to this map"}
overrides it. Raw OSM ele is not silently converted. Saved references survive
retry/reload; accepted junction nodes keep their positions. Verify built objects
checks accepted heights. Older started saves keep their previous height rules.
Terrain alignment is applied by TF3 when each network segment is constructed.

MAPPED SMALL WATER - EXPERIMENTAL
Reconvert the original OSM XML with converter Preview 0.12. The converter
prepares boundaries; this mod performs terrain changes only when built.
Select Mapped small waters, then Check map and resources and Start import.
This selection is initially off while native validation is pending.
Ponds/basins and small stream/river/ditch/drain/canal zones receive a 0.5 m
bed below saved base-terrain samples and the exact Landscaping Water Dirty
ground material. LESS alignment lowers rather than raises terrain. Islands
remain outside the filled area. Faces are subdivided to at most 8 m edges.
OSM widths are used if present. Missing widths use a visible configured
approximation, initially 2 m. Widths over 20 m need separate review.
Prepared network corridors have a conservative 20 m water exclusion; existing
roads/rails and other constructions are also checked before each build.
Network elevations themselves are applied only when networks are built.
Native proposal errors are not bypassed. Retry reuses saved bed samples.
The new shallow bed/ground paint has automated tests but is NOT yet verified
in native TF3. Use a separate test map before applying it to real terrain.

LAKES
Lake/reservoir geometry, names and raw OSM ele remain in waterFeatures.
No supported per-lake sea-level command was found in the installed API.
The mod therefore leaves lakes pending rather than changing global water.
Raw OSM ele must not be assumed to be a game-height value.

EXPERIMENTAL ELEVATED WATER SURFACES
The separate water fields define rectangular model surfaces at chosen heights.
These have no terrain alignment. Raised-basin shaping is disabled after native
TF3 tests produced terrain spikes, even with an explicit sampled boundary.
Read water support and Check test water area are read-only. Build queues a
decorative surface. Prepare another water patch retains the accepted object
and unlocks the next settings. At most 100 separate patches; no overlap.
A surface at 20 m was visibly rendered and saved/reloaded in TF3. This proves
elevated decorative appearance, not ship navigation or shallow-water terrain.
No original game textures, materials or models are redistributed.
See WATER-RESEARCH.md in the repository for the exact native evidence.

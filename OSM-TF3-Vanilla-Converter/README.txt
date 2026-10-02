OSM IMPORTER â€” TRANSPORT FEVER 3 VANILLA
Preview 0.9 | GPL-3.0 | 2 October 2026

DOWNLOAD OPENSTREETMAP (0.9)
Project > Download OSM opens an interactive OpenStreetMap view. No OSM account
or sign-in is needed. The app connects to public HTTPS services when this
view opens or you request a download. It does not require firewall changes.

Choose any TF3 size/format, or custom dimensions. The yellow frame matches
the map's width/height ratio in the converter's Web Mercator projection.
At Area scale 1x its ground width and height at the centre match the game
dimensions in metres. Another scale selects a larger/smaller real-world
region to fit those game dimensions. Geographic variation across large
areas means this metre scale is exact at the centre, not everywhere.

Drag the map to pan, use the mouse wheel or +/- to zoom, and move the pointer
to position the yellow frame. Click the map without dragging to lock its
coordinates. Move frame unlocks it. Fit frame centres and fits its extent.
Latitude/longitude + Go to coordinates jumps to another location. The initial
view is Stockholm; existing selected bounds instead supply the initial area.
Changing dimensions or area scale unlocks the frame and requires another
click to lock. Pan/zoom after locking keeps the selected coordinates fixed.

Click Download locked area and choose a .osm file. The download includes OSM
nodes, ways, relations and their full referenced geometry. Complete objects
can extend beyond the yellow boundary; the converter clips to the exact
locked bounds. Those bounds are also embedded in the downloaded XML.
Each download also saves <name>.overview.png beside the OSM file. It shows
the entire locked yellow frame, coordinates, game dimensions and OSM
attribution. The view automatically fits the frame and waits for its visible
tiles before downloading; no extra-resolution or off-screen tiles are fetched.
The companion .download.json records bounds, TF3 dimensions, source, counts,
OSM and PNG checksums, overview coordinates and OpenStreetMap attribution. The converter automatically
selects the saved OSM, its locked bounds and its chosen TF3 dimensions.
Convert as usual; its Lua and JSON report hand the same area to Heightmap Studio.

Progress reports received MB, XML validation and saving. Cancel works while
waiting for map tiles or the data server and during transfer/validation.
Existing OSM, overview and log files are preserved on cancellation or failure;
a failed final save restores the previous files. If map tiles cannot load,
the download reports the problem and leaves existing files intact. A brief completed commit is reported as successful.

Visible map tiles use https://tile.openstreetmap.org with attribution and an
application User-Agent. Only visible tiles are requested; there is no bulk
tile download or prefetch. Tiles are cached locally for at least seven days
and expired cache entries use conditional requests. The map cache is under
%LOCALAPPDATA%\Druttzen\OSM-TF3\map-tiles. Advanced deployments can set
OSM_TF3_TILE_URL to another permitted HTTPS {z}/{x}/{y}.png tile service.
Tile usage policy: https://operations.osmfoundation.org/policies/tiles/

OSM XML is downloaded through https://overpass-api.de/api/interpreter, the
data-download service recommended by OSM. You can enter another public HTTPS
Overpass endpoint, including your own server. Downloads are single requests,
not parallel sweeps of a region. Public services may reject busy, very large,
or dense requests; wait and retry, use a smaller area or your own endpoint.
Incomplete responses, server error remarks, malformed XML and truncation
are rejected. Download size has no fixed client file-size cap.
OSM data: ODbL 1.0, © OpenStreetMap contributors.
https://www.openstreetmap.org/copyright
https://dev.overpass-api.de/overpass-doc/en/preface/commons.html

STATUS
This is a separate rebuild of VacuumTube's OSM-TPF2-Importer 1.5.
It uses TF3 scripts and references vanilla game resources only. No asset packs,
third-party game mods, Python installation, or downloaded assets are required
to use the Windows companion executable.

The converter, Windows executable, Lua state-machine and panel callback tests
passed (102 tests). All 37 vanilla visual/infrastructure resources and the six
base UI helper modules exist in the installed TF3 build 25533170.
An actual import in the TF3 engine has NOT yet been verified. This is a
preview for testing, not a confirmed playable release. The new in-game panel's
native rendering, placement and scrolling have not yet been verified in TF3.

INSTALL
1. Extract the archive to a normal folder.
2. Copy mod\druttzen_osm_vanilla into the game's LOCAL mods folder:
   <Steam folder>\userdata\<your Steam user ID>\3493540\local\mods\
   The result must be ...\mods\druttzen_osm_vanilla\mod.json.
   Do not put it under TF2's mods folder or overwrite the original TF2 mod.
3. Launch OSM-TF3-Vanilla-Converter.exe. It needs no Python installation.
   The exe includes the standalone mod scripts and can create a new mod itself.
4. Choose an OSM XML file ending in .osm.
5. Choose an output mode:
   - Save Lua map file: exports your chosen .lua file and a .report.json beside it.
     No game or installed mod is required. This is an importer dataset, not a
     heightmap or a game save. To import, use it as content/osm/dataset.lua.
   - Update installed mod: choose the existing druttzen_osm_vanilla folder.
     Writes content/osm/dataset.lua and import-report.json. Other files stay.
   - Create standalone mod folder: choose a parent folder. The app creates
     druttzen_osm_vanilla with the importer, panel, dataset and license.
     An existing mod folder is never replaced by this mode.
6. Choose TF3 map size and format, or enter custom width and height in metres.
   All eight sizes are available: Tiny, Small, Medium, Large, Very Large,
   Huge, Megalomaniac and Gigantomaniac. All five formats are available:
   1:1, 1:2, 1:3, 1:4 and 1:5. Dimensions use the installed TF3 build's
   exact terrain-tile lookup (256 metres per tile), including rounded formats.
   Tiny, Huge, Megalomaniac, Gigantomaniac and formats 1:4/1:5 require
   experimentalMapFeatures enabled in TF3. The converter labels these choices
   and does not change your game settings. Match the same size/format in TF3.
   Editing a dimension switches to Custom dimensions. The initial 1000 x 1000
   custom size matches the demonstration, not a native TF3 map preset.
   Exact dimensions are written to the Lua map and JSON log for Heightmap Studio.
   Custom geographic bounds
   use min latitude, min longitude, max latitude, max longitude. With custom
   bounds off, XML bounds are used, or node extents if XML has no bounds.
   Match these bounds to your heightmap. Geometry is clipped to the map edge.
7. Adjust the tabs, then click Convert map. Progress follows file reading,
   coordinate projection, networks, polygons, scenery and output writing.
   Cancel stops before commit and preserves existing outputs. Closing the
   app during conversion requests cancellation before it closes.
8. Review the map preview and Report tab. Large maps use a sampled preview;
   the full dataset is still exported. Open output folder shows the result.
   Close TF3 before updating its dataset; restart after conversion.

ADJUSTABLE DESKTOP SETTINGS
- Project: input, three output modes, all TF3 sizes/formats, custom width/height
  and geographic bounds.
- Features: roads/tram streets, railways, footpaths, disused tracks, bridges,
  tunnels, forests, shrubs, individual trees, ground surfaces, fountains,
  bollards, advertising columns and named place markers.
  Disabling bridges/tunnels excludes their ways instead of flattening them.
- Networks: automatic/town/country road style; automatic/simple/standard/
  high-speed track profile; automatic/always/never overhead rail wiring;
  high-speed threshold; maximum road/rail segment lengths; tunnel depth.
  One-way and tram streets keep suitable vanilla profiles. Speed/lane values
  follow the chosen native profile rather than arbitrary OSM numbers.
- Vegetation: separate forest/shrub spacing, shared generated-tree limit,
  position variation, repeatable random seed, three editable species palettes.
  Maximum generated trees/shrubs is 1,000,000; zero disables area vegetation.
- Vanilla objects: replacements for tagged trees, fountains, bollards and
  advertising columns; object rotation; asphalt/dirt/grass material mappings.
  All choices refer to verified built-in resources.
- In game: initial scenery batch size (1-100) and job delay (0-2 seconds).
  These travel with the dataset; saved game settings take precedence.
- Save settings / Load settings: JSON profiles retain every conversion option,
  map dimensions, bounds and paths. Profiles are validated before applying.
  Reset settings returns options and dimensions to defaults, retaining paths.

FIRST TEST
The mod contains a fictional 1000 x 1000 metre sample, not a real location.
It has 10 road/rail segments, 117 scenery items and one named marker.
Use a fresh, flat test map with this mod enabled. The sample fits within
500 metres of the map centre. Enable only this mod for the dependency check.
Never use a valuable existing save for the first test.

START AN IMPORT
Click OSM Import in TF3's mod button area to open the movable control window.
Scroll through the list to choose commands and settings. Check map and resources
runs a check without building anything; Start import begins the selected import.
The top of the window shows live progress, messages and errors.

Commands: Check map and resources, Start import, Pause import, Resume import,
Retry failed step, Skip failed step, Show progress and Read map size.
Command buttons are enabled only when the current import phase allows them.
The OSM Import button toggles the window; its close button closes only the panel.

Before starting, choose roads/tram streets, railways, trees/shrubs, ground
surfaces, decorative objects and named place markers with the checkboxes.
Selections are saved and locked once the import starts. For another selection,
use a fresh map. Scenery items per step (1-100) and delay between steps (0-2
simulation seconds) can be adjusted while running or paused. A delay depends
on simulation time; the fastest setting can continue with the game paused.
Preparing/changing the OSM file still uses the desktop companion while TF3
is closed. No debug mode or console is required by the panel.

OPTIONAL CONSOLE FALLBACK
Enable Debug Mode in the game's settings before loading the map, then open
the game's Lua/debug console using its console shortcut. The TF3 keybinding
can vary with build and keyboard layout; it has not been verified here.
Paste this optional command:

ug_require("druttzen_osm_vanilla::/osm/console.lua").start()

To read map dimensions before conversion:

ug_require("druttzen_osm_vanilla::/osm/console.lua").mapSize()

The importer builds scenery, then roads/rails, then named markers. It stores
progress in the save and builds one proposal per simulation update. Status
and errors are printed with the prefix [OSM Vanilla]. It stops at a rejected
proposal so you can inspect the problem. It does not bulldoze existing map
objects or deliberately suppress build errors.

CONTROLS
Use the same console helper with .status(), .pause(), .resume(), .retry(),
or .skip(). For example:

ug_require("druttzen_osm_vanilla::/osm/console.lua").status()

Retry repeats the failed proposal. Skip omits that proposal; a scenery
proposal can contain up to 100 items. A finished/started dataset cannot be
started again in the same save. Use a new map for a different dataset.
Keep the original dataset file when resuming a saved import. Changing it
causes the importer to stop. Keep this mod enabled on saves using its scenery.

VANILLA MAPPINGS AND LIMITS
- Roads: current vanilla small/medium/large town or country profiles.
  One-way direction -1 reverses the geometry; no/false/0 overrides a roundabout.
  Tram roads use the available electrified tram street profiles.
- Rails: vanilla simple, standard or high-speed profiles, with overhead
  electrification when requested. Narrow gauges become standard gauge.
- Footpaths/cycleways/steps: the smallest vanilla road; these have road
  traffic semantics. This is an approximation, not a dedicated pedestrian path.
- Lane counts, road widths and speed limits follow the selected vanilla
  profile. Original OSM values are retained in the dataset for inspection.
- Forests/shrubs: deterministic vanilla trees/shrubs. Open member ways are
  joined into multipolygons, and inner clearings are kept empty. The tree
  limit applies to generated area vegetation; individually tagged trees remain.
- Ground surfaces: vanilla asphalt, dirt or cut grass, including concave
  boundaries and holes. Materials such as cobblestone/gravel are approximated.
- Tree nodes, fountains, advertising columns and bollards: vanilla models.
  Bollards use a vanilla mooring bollard as a visual approximation.
- Places: separately named vanilla marker constructions. Select the marker
  to read its name. These are not functioning towns or town HUD labels.
- Bridges/tunnels: vanilla steel bridge and tunnel profile, with heights
  estimated from terrain endpoints. Inspect grades and clearances manually.
- Railway signals: add with the game's vanilla signal tool after import.
  Automatic signal placement is not enabled in this preview.
- Buildings, stations, depots, functioning towns, rivers and water bodies:
  create with the game tools. They are not generated by this rebuild.
- OSM XML only. Convert .pbf to .osm externally before using this tool.
- No heightmap generation, game-asset redistribution, or external mod lookup.
  Existing map nodes are not automatically snapped to imported geometry.

SOURCE AND DEVELOPMENT
Source is in tools/, tests/ and mod/. Use Python 3.10+ with Tk. The OSM map
picker, download and overview features require Pillow; install the runtime
dependency before running the desktop app. The command-line conversion core
uses only Python's standard library.

python -m pip install -r requirements.txt
python tools/gui.py

Or use the command-line converter:

python tools/converter.py examples/sample.osm --output map.lua --size 1000 1000

Or use --mod <installed-folder> or --new-mod <new-druttzen_osm_vanilla-folder>.
--settings <profile.json> applies saved desktop options; --bounds overrides XML.

Development checks/build use the optional requirements-dev.txt dependencies:

python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tests/check_resources.py "<your Transport Fever 3 installation folder>"
powershell -File build.ps1

The Lua tests simulate the command boundary and UI recipes; they cannot prove
native TF3 proposal acceptance, ownership conversion, construction loading,
button placement, window rendering or scrolling.
The next required check is a fresh game map, importing the sample, testing
pause/retry and saving/reloading the result, with no other mods enabled.

ATTRIBUTION
Original concept/mod: VacuumTube, OSM-TPF2-Importer, GPL-3.0.
Standalone TF3 rebuild prepared for Druttzen. See LICENSE and NOTICE.txt.
OpenStreetMap data: Â© OpenStreetMap contributors, ODbL. Follow its attribution
requirements when publishing maps made from real OSM data:
https://www.openstreetmap.org/copyright
The included test data is fictional. Vanilla assets remain game-owned; this
package contains references, not copies of those assets.

Technical references: the installed game's api/tealdef API definitions and
base game scripts; https://wiki.transportfever3.com/doku.php?id=modding

HEIGHTMAP STUDIO COMPANION
After conversion, launch the separate TF3-Heightmap-Studio.exe. Choose the
converter JSON report and original OSM file; the report now includes a source
SHA-256 checksum and the north-up map alignment. The terrain app supports
local DEM files and public terrain downloads. It supplies a 16-bit PNG and
exact height range for native TF3 import. See its separate README.

CONVERSION LOG CHECKSUMS
The JSON report contains sourceSha256 for original OSM and luaSha256 for
the exact generated Lua bytes. Keep the report with the Lua file. Heightmap
Studio uses both to align terrain with the converted map and verify identity.

STARTUP FIX - PREVIEW 0.6
The TF3 panel, importer, GUI bridge and scenery script resources now expose
their callbacks through global data() functions, as the TF3 resource loader
requires. Normal helper modules and converted datasets remain Lua tables.
Regression tests load each resource in a fresh environment and resolve all
.script@callback references. This addresses the reported startup failure
"function data() not defined" for panel.script@OsmImportButton.

Close TF3 completely and start it again after updating; do not use Reload UI
on a failed startup. Existing converted dataset.lua and import-report.json
files are preserved by the local update.

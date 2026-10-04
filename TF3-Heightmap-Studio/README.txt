TF3 HEIGHTMAP STUDIO - STEP 2
Preview 0.9 | GPL-3.0 | 4 October 2026

AUTOMATIC GAME FOLDERS
The app reads the installed TF3 and Steam Windows registry paths, checks the
game installation, then selects the active Steam account or the only existing
TF3 profile. It fills the PNG export path automatically. Use Find TF3 folders
to restore automatic selection, or Choose TF3 user folder for a manual profile.
When exporting to TF3: the heightmap PNG goes into local/heightmaps and the biome
PNG into local/biomes. GeoTIFF, previews, reports, project, attribution and import
instructions go into local/heightmap_studio/<map>. Defaults choose a new name
when an export already exists. Manually chosen/saved destinations remain usable.
The registry is not edited. Export creates import files; it does not change a
game save. See GAME-FOLDERS.md for selection, fallback and failure handling.

VANILLA BIOMES
The Biomes tab can export a native TF3 biome PNG alongside the heightmap.
Enable biome export, choose Temperate, Dry, Tropical or Subarctic, and create
your game map with the same climate. Biome IDs 0-4 describe regions within
that climate; the vanilla game supplies their terrain textures and vegetation.
The colour preview identifies regions and does not render final game textures.

Choose height/slope rules with or without OSM land cover, a single region,
or Import biome PNG. Height thresholds and steep-rock slope are adjustable.
Set replacements for lowlands, highlands, alpine/rock, woodland, scrub/heath,
grass/farmland, wetland and sand/beach. OSM multipolygon holes are retained.
Rules apply lowland, highland, alpine/rock, OSM cover, then underwater.
Underwater generation can be switched off; native TF3 may rederive water
biomes from its heights. Region rules do not change measured terrain heights.

Existing biome PNGs must be 8-bit grayscale, match the heightmap dimensions,
and use TF3's codes: 0, 63, 127, 191, 255 for biome IDs 0, 1, 2, 3, 4.
After Build terrain, tick Biomes above the preview. Enable the biome brush
in the Biomes tab, choose a region and radius, then click or drag to paint.
Paint takes precedence over generated/imported regions. Undo is available
for the latest eight biome stamps, within a 128 MB budget. Terrain changes
clear this undo history; saved biome paint still replays over the new heights.
Save/Load project keeps biome settings and up to 10,000 paint stamps;
imported PNG checksums are retained after a build and checked on project load.

Optional exports: name.biomes.png (native 8-bit grayscale),
name.biomes.preview.png (colour region legend preview), name.biomes.tif
(georeferenced IDs 0-4 for GIS). All use the converter bounds and map size.
Copy only the native biome PNG into TF3 local/biomes. After importing the
heightmap, open the map editor Biomes tab, choose the matching vanilla
Climate (Import) generator, select the PNG, inspect its preview and Apply.
Leave additional layer selectors empty; no extra terrain-shape layers are
exported. Biome data does not switch the climate of an existing game map.
The .import.txt gives the exact steps. No extra mods or game assets are needed.
The PNG encoding was checked against existing TF3-exported biome files;
native biome import/rendering still requires an in-game verification session.

TF3 MAP SIZES
The default 4-metre grid supports every native TF3 size and format, including
Gigantomaniac. Dimensions come from the converter Lua map and JSON log.
The working-grid limit is 53 million vertices and 16,385 pixels per side;
finer 1/2-metre grids on large maps may require a coarser or custom grid.

START
1. Run OSM-TF3-Vanilla-Converter.exe (0.7 recommended) to export the Lua dataset
   and its JSON report. Keep the original .osm XML file.
2. Launch TF3-Heightmap-Studio.exe. No Python installation is needed.
3. Project: choose that converter report, its converted .lua and original OSM.
   The source checksum is verified. The report fixes geographic bounds and
   physical game map dimensions; north is at the top.
4. Elevation: choose local files, Mapzen, Copernicus 30/90 m, OpenTopography
   or public direct GeoTIFF links. Click Check download area to inspect bounds.
5. Build terrain. Inspect the preview, source resolution and Report tab.
6. Optionally adjust Terrain / OSM terrain settings, then Build terrain again.
   For manual edits, open Brush, enable it, then click or drag on the preview.
7. Export heightmap. Follow the exact minimum / maximum / water level values
   in the exported .import.txt file when importing the PNG into TF3.
8. Use the matching OSM Lua dataset with the vanilla importer on that map.

LOCAL ELEVATION
Supported: .tif/.tiff GeoTIFF DEM, .asc georeferenced ASCII grids,
geographically named .hgt and .hgt.gz SRTM-compatible tiles.
Example HGT name: N59E018.hgt.gz (the southwest corner is 59 N, 18 E).
Add several files to cover the area, including local detailed GeoTIFF DEMs
alongside a public background download. Finest elevation first is the default
for new projects. Other sources fill real gaps; File list order gives manual
priority, and older projects retain that policy. Reports show actual contribution
per source and approximate source cell spacing near your OSM area.
Files remain local. The chosen DEM band, its scale and offset,
nodata and coordinate reference system are honored. Auto units recognizes
metres, international feet and US survey feet; override known units if metadata
is absent. Image/colour bands are rejected. Use ground DEM/DTM height data;
GeoTIFF is a file format and does not itself establish terrain accuracy.
If a source lacks a CRS, enter its known EPSG code. Do not guess the CRS.
Default missing data handling stops with an explanation. Optional nearest
filling is limited by the configured distance, reported in game metres.

MAPZEN ELEVATION
Downloads public Mapzen Skadi tiles from the unsigned AWS terrain bucket.
No account or API key. Requires internet for uncached tiles. One-degree tiles
are gzip-compressed signed 16-bit HGT heights; nodata is -32768. Download
progress and cancellation are supported. Valid tiles are cached under
%LOCALAPPDATA%\Druttzen\TF3-Heightmap\cache. Maximum tiles defaults to 16;
set a smaller limit to constrain downloads. A tile can be several MB.
Public terrain uses regional source datasets. The app reports approximate
source cell size, which is not a guarantee of measurement accuracy.
Provider details: https://registry.opendata.aws/terrain-tiles/
Full regional attribution is bundled and included with public exports.

ALIGNMENT AND PRECISION
Elevation samples use the same scaled Web Mercator rectangle as the OSM
converter. Corner sample centres fall exactly on the geographic bounds.
World north is positive Y; PNG rows run north to south. All sources are
reprojected with Rasterio/GDAL using your selected interpolation. Exact
coordinate transformation is used (warp approximation tolerance is zero).
Point interpolation at the corner vertices is maintained even when reducing
a source raster to a smaller or rectangular TF3 map.
Default export follows TF3's inspected 4-metre map creation grid. Native map
pixel dimensions normally use 64n+1. Choose matching map dimensions in both
apps and in TF3. Fine 2 m / 1 m and custom grids preserve the geographic
rectangle, but the game may resample them to its terrain grid.

The working elevation array and exported DEM use float64. PNG uses 16-bit
grayscale with a documented range, so one encoding step is (max-min)/65535.
This numerical precision does not establish the accuracy of the DEM. OSM
and converter logs provide geometry and alignment, not terrain measurements.
For more measured detail, use a suitably accurate local surveyed/LiDAR DEM.
HGT uses EGM96 height convention; GeoTIFF datum metadata is recorded where
available. The app does not automatically convert vertical datums. Check
source heights, datum and water level before using several DEM providers.
Native TF3 creation files inspected on this computer use 4 m horizontal and
0.05 m height spacing. Native import still needs a game-session check.

EDITING
Vertical scale, offset and smoothing apply before the optional OSM edits.
Lake/reservoir beds can be lowered below the chosen water level; islands
and polygon holes are retained. River channels follow local terrain heights.
TF3 has one water level: carving a high river does not create flowing water.
Road and rail corridors use converter feature selections, profile smoothing,
width, shoulder blending and grade limits. Bridge/tunnel interiors are
excluded. Grade limits apply to prepared profiles; inspect game junctions.
These changes are authored terrain edits, not extra measurements.

Brushes: Raise / Lower use metre deltas; Smooth / Flatten use a 0-1 strength.
Radius and flatten target are adjustable. The soft edge blends each stamp.
Hover over the preview for height, game coordinates and latitude/longitude.
The latest eight stamps are available for undo within a 128 MB memory budget.
Before OSM / brush edits shows terrain after global scale/offset/smoothing.
Save project preserves all settings, source paths and up to 10,000 brush
stamps. Load project + Build terrain reproduces the edits. Changed converter
alignment is rejected; clear old brush edits before selecting another map.

EXPORT FILES
name.png                    16-bit grayscale native import candidate
name.dem.tif                georeferenced float64 edited elevations
name.preview.png            north-up terrain/OSM preview
name.heightmap-report.json  bounds, range, settings, sources and quality
name.heightmap-project.json editable settings and brush history
name.import.txt             exact game import settings
name.attribution.txt        OSM and elevation provider attribution

Automatic height range preserves all heights. Manual ranges must include
all heights unless you explicitly enable PNG clipping. GeoTIFF retains the
unclipped elevations. Export protects source files, stages all outputs
and restores previous outputs if commit fails. Cancellation before commit
keeps existing exports. The brief final commit cannot be cancelled. If a
filesystem problem also prevents restoration, backup copies are retained
and their location is shown in the error.

EXAMPLE
Load examples\Synthetic-demo.heightmap-project.json, then Build terrain.
This is fictional OSM and a synthetic terrain surface, not surveyed land.
The example paths are relative so the extracted package is portable.
For biome controls, load examples\Synthetic-biomes-demo.heightmap-project.json.
Build terrain, then tick Biomes above the preview. This fictional example
includes all five regions and a saved paint stamp with the Temperate climate.

LIMITS / VERIFICATION
132 automated terrain and biome tests passed, including projection at high latitudes,
GeoTIFF/HGT, units and scale, nodata, mosaic priority, public cache/cancel,
polygon holes, bridge exclusion, brush replay, PNG quantization, GeoTIFF
georeferencing, project validation, cancellation and commit rollback.
A real public Mont Blanc tile produced 1025 x 513 aligned output with approx.
22 x 31 m source cells and heights around 1543-4796 m. This only checks data
acquisition/export, not native game height limits. The app does not install
heightmaps, create game saves or generate measured elevation from OSM.
No TF3 assets are bundled. The heightmap import and vanilla mod still require
native TF3 engine validation before claiming a confirmed playable release.

SOURCE / REBUILD
Complete application source, example, tests, pinned requirements and build.ps1
are included. GPL-3.0 applies to our code and the vendored OSM converter.
Third-party packages retain their own licences in third-party/.
Create a Python 3.14 virtual environment, install requirements-dev.txt,
run: python -m pytest tests
build: .\build.ps1 -Python <your venv Python.exe>
CLI alternative: python tools\cli.py <project.json> --output <map.png>

MULTIPLE ELEVATION WEBSITES (0.2)
Copernicus GLO-30 / GLO-90: public AWS downloads, no account or API key.
The app selects one-degree tiles from the OSM rectangle, including a small
border margin for interpolation. The output always uses the exact original
bounds, not the larger request area. Public coverage excludes ocean tiles
and some unreleased GLO-30 areas. Unavailable tiles stop with an explanation;
choose another source or add suitable local data. Copernicus is a surface
model and can include buildings and vegetation, rather than bare earth.
https://registry.opendata.aws/copernicus-dem/

OpenTopography: choose COP30, COP90, SRTMGL1/GL3, AW3D30, NASADEM, EU_DTM,
or USGS 10/30 m. Availability varies by region and account. Enter your own
API key in the session-only field. It is not stored in reports, projects,
cache filenames or download metadata. The app requests the matching WGS84
rectangle with a border margin, then crops it to the exact OSM rectangle.
Native server requests have not been verified with an account key; request
construction, returned-GeoTIFF processing, caching and key privacy were
verified with controlled API responses. CLI reads TF3_OPENTOPO_KEY from the
environment. No key is required for an already valid cached response.
https://opentopography.org/developers

Direct GeoTIFF links: paste one or more public HTTPS file URLs separated by
spaces. They may come from different DEM providers. HTML landing pages,
login pages and ZIP archives are not direct GeoTIFFs. Source files need a
CRS and must collectively cover the map. Each is downloaded, validated,
cached, then reprojected/cropped/mosaicked onto the same map rectangle.
Only paste public links: these source URLs are retained in project settings.
For sites without public direct links, download their georeferenced DEM in
your browser and import it with Add files. Retain their attribution.

Download limits apply to tile/file counts and MB per GeoTIFF file. Progress
reports received bytes; invalid/truncated/oversized responses do not replace
previous cache files. API keys and provider error URLs are not displayed.

SIZE AND COORDINATE MATCH
Choose the TF3 width and height in the OSM converter. Its report is the
single authority for both outputs. Changing only a terrain raster's pixel
count does not change the physical game map size. To resize the map, export
the OSM dataset with the new size, then load its new converter report in
Heightmap Studio. Rebuild terrain and use the same size inside TF3.
The Project tab now names South/West/North/East (WGS84 degrees), map width
and height, pixel dimensions and grid spacing. Check download area shows
source requests and their padded bounds. The heightmap report records both
map and request bounds, provider details, scaling factors and all four
corner coordinates. Existing projects with a changed converter report are
rejected; their brush history cannot silently move to a different map.

VALIDATION ADDED IN 0.2
Live Copernicus GLO-30, GLO-90 and a direct GeoTIFF link downloaded and
exported the Mont Blanc test rectangle at 4096 x 2048 m, 1025 x 513 pixels.
The same OSM coordinates were checked against analytical DEM heights after
scaling to 256 x 128, 1024 x 2048 and 8192 x 4096 m. A sloping projected UTM
DEM verified point interpolation against independent coordinate transforms.
These validate the file geometry; native TF3 import remains unverified.

CONVERTED LUA DATA AND LOGS
Select the converted .lua together with its JSON conversion report/log.
Standalone exports are found beside their .report.json. For a generated mod,
select content/osm/dataset.lua with import-report.json. Nearby Lua files are
selected automatically; Browse lets you select a moved file.

Road/rail preview and terrain refinement use actual exported nodes and edges,
including clipped/subdivided geometry and bridge/tunnel flags. Subdivision
segments join into corridors; branches and structure boundaries remain split.
Original OSM supplies lake boundaries, islands and waterways. The JSON report
locks geographic bounds, game size and conversion settings. Lua labels and
scenery counts are recorded; buildings/scenery do not become terrain heights.

Lua is read as restricted data tables and is never executed. Dataset, bounds,
size, settings, node positions and feature counts must match. Converter 0.5
adds SHA-256 of the exact Lua output alongside original OSM SHA-256. Older
reports are accepted with a note that Lua byte identity cannot be proved.
Saved built projects pin the Lua checksum; changed files require restoring
the matching export or starting a new project. Export reports record geometry
source, file checksum and road/track/bridge/tunnel counts.

GUI builds require the Lua input. Older command-line projects without a Lua
file retain OSM fallback with a visible warning; add convertedLua to use the
exported map. There is no fixed Lua input file-size limit. Files are read
in chunks with checksum verification and cancellation. Scenery and labels
are counted without storing their contents. Road/rail geometry and original
OSM features still use memory according to map complexity.

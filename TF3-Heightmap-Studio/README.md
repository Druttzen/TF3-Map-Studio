# TF3 Heightmap Studio

Preview 0.13 is the terrain companion to OSM-TF3-Vanilla-Converter. It uses the
converter's JSON report, exported Lua and original OSM file to align measured
elevation with a Transport Fever 3 map. It supports local and public elevation
sources, terrain editing, and optional vanilla biome exports.

Preview 0.13 offers an optional minimum clearance above global water for
ground road and rail corridors. It is disabled by default. Set both smoothing
and grade to zero for clearance alone, which preserves dry heights above the
floor. Bridge and tunnel corridors are excluded. Inspect the resulting
embankments and junctions before building; these are authored terrain changes.

The app joins compatible neighbouring elevation files before interpolation,
so their file boundaries do not create artificial flat strips or height steps.
The default export is one continuous 16-bit heightmap PNG on the native 4 m grid.
**Cubic** is the default for new projects; saved explicit Bilinear or Nearest
settings are retained. In **Elevation**, **Use smooth terrain settings** selects
the native grid, Cubic interpolation and finest-source priority, then requires a
terrain rebuild. It does not apply a blanket blur or change source files.

The preview and export report show actual contributing source cell spacing and
how much of the map comes from data coarser than the native grid. A source with
roughly 16.5 × 30.9 m cells remains that coarse when exported at 4 m; interpolation
can soften facets but cannot add measured detail. Use the **LiDAR** search for
finer ground DEMs, including Lantmäteriet 1 m data with approved personal access.

Preview 0.7 added map-coordinate data discovery, direct ground DEM downloads and
classified local LAS/LAZ/COPC import. Open the **LiDAR** tab to find data for the
selected map. See [sources, access and measured limitations](LIDAR-SOURCES.md).
It also fixes current OSM-report compatibility and authoritative GeoTIFF masks.

Preview 0.8 added detailed GeoTIFF DEMs over downloaded or local background
elevation, within the exact OSM converter bounds. **Finest elevation first** is
the default for new projects: finer source cells take precedence and other
sources fill their real gaps. **File list order** retains manual priority;
older saved projects keep that policy when reopened. Reports show each file's
actual map contribution and approximate source spacing near the selected area.

Load the matching OSM/report/Lua, choose a background download if needed, then
use **Elevation → Add files** for your detailed `.tif`/`.tiff` DEMs. Use Cubic
for continuous interpolation and keep global smoothing at zero unless you
intend to soften measured features.
Choose ground DEM/DTM data: an orthophoto or coloured GeoTIFF is not elevation.
Projects retain local detail files when combined with downloads. Exact float64
heights and the 16-bit PNG are exported; finer source data improves the sampled
terrain, while TF3's base heightmap still has a 4 m grid.

XY is reprojected to the OSM map and measured Z keeps its vertical reference.
Scale, offset, metres, international feet and US survey feet are handled once.
Different declared vertical references are reported for contributing files;
align these references before game import. Unrecognized unit labels require an explicit
known unit choice. No source accuracy is inferred from the GeoTIFF file format.
See [GeoTIFF processing and verified references](GEOTIFF-DETAIL.md).

Preview 0.9 finds the installed TF3 game through Windows registry keys and
selects the current Steam account's user folder, or the only existing TF3
profile. The PNG destination is filled automatically. Native exports place
the heightmap in **local/heightmaps**, biome PNGs in **local/biomes**, and
GeoTIFFs, reports, previews, projects and instructions in
**local/heightmap_studio/<map>**. Default names preserve existing exports.
Saved/manual paths remain available; **Find TF3 folders** restores automatic
selection. Multiple unidentified profiles require selecting the user folder.
The registry is read without changes. See [automatic game export](GAME-FOLDERS.md).

In **Biomes**, enable biome export and **Also export Mountains and supported
Rivers masks** to add the game's independent layer PNGs. Mountains marks high
or steep land above the configured water level. With a current conversion
report, Rivers uses the same terrain-following triangles as the OSM importer's
water paint. The automatic OSM biome map also uses those footprints and the
flat lake triangles to mark water. Older reports use original OSM river areas
and buffered centerlines for Rivers. All four vanilla climates support
Mountains. Temperate and Dry also support Rivers.

Assign each PNG to its named selector in the game's **Biomes** tab and wait
for the preview to finish. Click **Apply**, wait for it to finish and save.
The layer export uses the heightmap grid and leaves elevations intact. The
game can adjust the masks and generate vegetation on Apply. Run the OSM
import afterwards with **Mapped waterways** and **Vegetation** enabled. The
importer clears existing plants from the painted footprint and excludes its
own vegetation from accepted water faces. On large maps, check the converter
report for water features that exceeded the face budget. To verify the saved
masks, reopen the map and export with **Biomes Data** enabled in **Generate
Heightmap**.

This folder contains the application source, existing tests, pinned dependencies,
portable synthetic examples and licence notices. See the
[system test report](../SYSTEM-TEST-2026-11-05.md) for native import results.

## Set up and run

In Preview 0.12, open **LiDAR** after choosing the map. **Automatic for map**
selects the regional catalog. Choose a local folder to find matching elevation
and LAS/LAZ files from their geographic headers, including subfolders. Local
results appear before the online search finishes. **Search local only** avoids
waiting for a catalog. Search never downloads terrain automatically.

Header metadata and successful searches are cached. Unknown CRS, missing
geotransforms, GCP/RPC rasters and HGT remain manual-review candidates. RGB
imagery is excluded. **Add all matching local files** includes only known,
non-review matches. Terrain building still validates samples, units and gaps.

**API access setup** accepts approved Lantmäteriet credentials and a personal
OpenTopography key in masked fields. **Test Lantmäteriet access** checks a
selected ground-model file. Credentials stay in this session. Official links
guide personal key creation and product approval; no shared key is supplied.
See [data sources and access](LIDAR-SOURCES.md).

Over-limit catalog results remain visible. **Allow selected tile count**
explicitly changes the download limit, up to 512 files, without starting a
download. Incomplete catalog results remain blocked.

Use Python 3.14 with Tkinter. In PowerShell, from this folder:

```powershell
# First provision this tool's complete .runtime following ../PRIVATE-RUNTIMES.md.
.\.runtime\python.exe -I ..\scripts\private_runtime.py run --tool . -- tools/gui.py
```

In the app, load `examples\Synthetic-demo.heightmap-project.json` and select
**Build terrain**. The biome example is
`examples\Synthetic-biomes-demo.heightmap-project.json`. Both use fictional OSM
and a synthetic elevation surface; their file paths are relative to the project.

To export the example without the GUI:

```powershell
.\.runtime\python.exe -I ..\scripts\private_runtime.py run --tool . -- tools/cli.py examples\Synthetic-demo.heightmap-project.json --output outputs\synthetic-heightmap.png
```

Add `--to-tf3` instead of `--output` to export into the automatically selected
installed game's user folders. This places import files; it does not import
them into a running game or change an existing game save.

## Test and build

```powershell
.\.runtime\python.exe -I ..\scripts\private_runtime.py run --tool . -- -m pytest tests
.\build.ps1
```

The build creates `dist\TF3-Heightmap-Studio.exe`. The Windows executable includes
its Python runtime and does not require a separate Python installation.
The build requires this folder's complete `.runtime` and verifies its ownership.
It checks dependencies before packaging, includes the HTTPS certificate bundle,
and runs the executable's headless terrain/LiDAR/certificate check afterwards.
Missing dependencies stop the build with an installation command instead of
producing a successful-looking executable. `dist\runtime-check.json` records
the packaged check result.

See [README.txt](README.txt) for elevation providers, alignment, editing, export
instructions and limitations. [validation.json](validation.json) preserves the
original Preview 0.6 validation record; its executable checksum refers to that
previously built release, not a new build from this folder.

Application and vendored converter code are distributed under [GPL-3.0](LICENSE).
See [NOTICE.txt](NOTICE.txt) and [third-party](third-party) for attribution and
dependency licences. No Transport Fever game assets or downloaded DEM datasets
are included.

## Report compatibility in Preview 0.10

Use **Mod folder…** to select the importer folder containing `import-report.json`,
or select the converter `.report.json` directly. The matching Lua is found from
the actual report location. Download logs and Heightmap export reports have
distinct error messages. Large converter reports are validated as a stream;
their full water/object source graphs no longer trigger a 64 MB rejection or
need to be retained in memory. Bounds, settings, dataset and checksums remain
mandatory where present. Invalid or truncated JSON is rejected.

Saved projects now verify their recorded OSM checksum even with older reports.
Independently tagged meadow/farmland boundaries within forest holes retain
their own biome classification. The packaged runtime check exercises report
parsing, HTTPS certificates, elevation, compressed LiDAR and native export
folder routing with fictional temporary data. No new game import is claimed.

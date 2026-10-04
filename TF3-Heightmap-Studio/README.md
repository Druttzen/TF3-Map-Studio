# TF3 Heightmap Studio

Preview 0.8 is the terrain companion to OSM-TF3-Vanilla-Converter. It uses the
converter's JSON report, exported Lua and original OSM file to align measured
elevation with a Transport Fever 3 map. It supports local and public elevation
sources, terrain editing, and optional vanilla biome exports.

Preview 0.7 added map-coordinate data discovery, direct ground DEM downloads and
classified local LAS/LAZ/COPC import. Open the **LiDAR** tab to find data for the
selected map. See [sources, access and measured limitations](LIDAR-SOURCES.md).
It also fixes current OSM-report compatibility and authoritative GeoTIFF masks.

Preview 0.8 combines detailed GeoTIFF DEMs with downloaded or local background
elevation, within the exact OSM converter bounds. **Finest elevation first** is
the default for new projects: finer source cells take precedence and other
sources fill their real gaps. **File list order** retains manual priority;
older saved projects keep that policy when reopened. Reports show each file's
actual map contribution and approximate source spacing near the selected area.

Load the matching OSM/report/Lua, choose a background download if needed, then
use **Elevation → Add files** for your detailed `.tif`/`.tiff` DEMs. Keep the
default interpolation and zero smoothing to retain the measured height profile.
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

This folder contains the application source, existing tests, pinned dependencies,
portable synthetic examples and licence notices. Native TF3 heightmap and biome
import still require verification in a game session.

## Set up and run

Use Python 3.14 with Tkinter. In PowerShell, from this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools\gui.py
```

In the app, load `examples\Synthetic-demo.heightmap-project.json` and select
**Build terrain**. The biome example is
`examples\Synthetic-biomes-demo.heightmap-project.json`. Both use fictional OSM
and a synthetic elevation surface; their file paths are relative to the project.

To export the example without the GUI:

```powershell
.\.venv\Scripts\python.exe tools\cli.py examples\Synthetic-demo.heightmap-project.json --output outputs\synthetic-heightmap.png
```

## Test and build

```powershell
.\.venv\Scripts\python.exe -m pytest tests
.\build.ps1 -Python .\.venv\Scripts\python.exe
```

The build creates `dist\TF3-Heightmap-Studio.exe`. The Windows executable includes
its Python runtime and does not require a separate Python installation.

See [README.txt](README.txt) for elevation providers, alignment, editing, export
instructions and limitations. [validation.json](validation.json) preserves the
original Preview 0.6 validation record; its executable checksum refers to that
previously built release, not a new build from this folder.

Application and vendored converter code are distributed under [GPL-3.0](LICENSE).
See [NOTICE.txt](NOTICE.txt) and [third-party](third-party) for attribution and
dependency licences. No Transport Fever game assets or downloaded DEM datasets
are included.

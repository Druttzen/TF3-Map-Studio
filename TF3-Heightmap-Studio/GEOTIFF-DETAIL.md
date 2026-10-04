# GeoTIFF detail within the OSM area

Preview 0.8 uses measured GeoTIFF DEM/DTM elevation as detail sources for the
final TF3 heightmap. Local detail files can be combined with a selected public
background download. They also work together with local HGT, ASCII-grid, LiDAR
ground rasters or other GeoTIFF sources. The converter report's selected bounds
remain authoritative; the output does not expand to the full extent of a DEM.

In **Elevation**, add your elevation `.tif`/`.tiff` files with **Add files**.
Use **Finest elevation first** to prioritize the source with the smallest
approximate ground cell spacing near this map. The larger axis of each cell
determines priority. Equal spacing retains file order. Valid heights from that
source take precedence; other sources fill missing/masked cells and areas
outside its coverage. This policy uses declared grid spacing, not an estimate of
survey accuracy. Select known ground DEM/DTM products rather than canopy/building
DSM data when the desired result is bare-earth terrain.

**File list order** permits manual priority. Earlier saved projects keep that
policy so reopening them does not silently change overlap behavior. Downloaded
background files follow the selected local files in manual mode. Saved projects
retain original local detail paths; downloads are recreated from the saved
provider settings/cache. Source files are never replaced by heightmap export.

All sources are transformed onto the same north-up corner-vertex grid as the
OSM map, with exact coordinate transformation and the selected interpolation.
The existing point interpolation kernel is retained when reducing a finer DEM;
source heights are not automatically averaged over wider areas. Bilinear is the
default, cubic and nearest are available. No artificial height detail or automatic
smoothing is added. The report records each file's available samples, selected
samples, percentage of the map, source priority and approximate cell spacing.
An outside or wholly invalid file contributes zero and is identified in notes.

Image colour, palette and alpha bands are rejected as height sources. Other
scalar DEM bands need a known CRS and valid elevation semantics. A GeoTIFF file
extension alone does not prove that its values are measured elevations.
Band scale/offset and selected/declared elevation units are applied once.
Auto units recognize metres, international feet and US survey feet; unfamiliar
units require an explicit known unit choice or prior conversion. Horizontal CRS
units do not imply height units. Explicit validity masks take precedence over
scalar nodata. Invalid heights remain gaps until covered by another source or
the user's limited gap-fill option.

Only XY is reprojected. Compound CRS height references are recorded, and Z is
not automatically shifted between geoids/datums. Multiple contributing files
with different declared vertical references are identified; the user must align
these references before import. The final float64 `.dem.tif` preserves the
prepared heights; the grayscale 16-bit PNG records its numeric encoding step and
exact import range. TF3's base heightmap has 4 m grid spacing. A finer export can
help editing but does not prove a finer native game grid or measurement accuracy.
Road/rail terrain changes remain off by default and are not part of this feature.

## Verified primary references

- [Rasterio resampling](https://rasterio.readthedocs.io/en/stable/topics/resampling.html):
  interpolation, upsampling/downsampling, and bilinear/cubic for continuous data.
- [GDAL raster reprojection](https://gdal.org/en/stable/programs/gdal_raster_reproject.html):
  explicit output extent/grid, contributing source pixels, interpolation and nodata.
- [GDAL vertical transformations](https://gdal.org/en/stable/programs/gdalwarp.html#vertical-transformation):
  single-band compound CRS can otherwise trigger a geoid shift and unit change.
- [TF3 terrain engine API](https://wiki.transportfever3.com/script-doc/api/engine.html):
  base terrain height and tile heightmap vertices use a 4 m resolution.

Regression fixtures verify coarse/fine overlap in both input orders, real nodata
fallback, a narrow height feature, unchanged OSM corner vertices, manual priority,
downloads plus local detail across save/reload, float64/16-bit export, compound
CRS height preservation, scale/offset, both foot units, outside tiles, mismatched
vertical references and RGB rejection. Native TF3 import remains unverified.

## Live GeoTIFF verification — 4 October 2026

A previously downloaded public USGS 3DEP 1 m bare-earth raster was tested in a
separate Colorado coordinate area (south/west/north/east
`39.99550445,-105.34728357,39.99781987,-105.34427307`). A 16 m background and a
1 m detail patch were derived from the same measured source. The detail patch
provided 961 of 4,225 output vertices (22.75%); the background supplied the
remaining 77.25%, with no missing samples or PNG clipping. The 65 × 65 export
kept the chosen OSM bounds and 4 m game grid. Heights differed from the coarse
background by up to 2.121 m where the detail source contributed. This demonstrates
selection of measured detail, not an independent accuracy estimate. The user map
and game saves were not modified. Native game import is still unverified.

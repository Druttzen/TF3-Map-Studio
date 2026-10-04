# LiDAR and detailed ground elevation — Preview 0.7

The **LiDAR** tab searches the converter report's chosen crop. With only an
OSM/XML file selected, it searches its `<bounds>` or the extent of its nodes.
Export still requires the matching report, Lua dataset and original OSM checksums.
No account is needed to search the supported catalogs.

1. Select the report/OSM in Project and open LiDAR.
2. Choose a region or All available regions, then **Find data for this map**.
3. Select a ground DEM, inspect its access/coverage, then **Download selected data**.
4. Downloaded files appear in Elevation. **Build terrain** checks actual coverage;
   the output uses the converter's exact crop, orientation and game dimensions.
5. For raw point entries, open the provider, obtain LAS/LAZ/COPC and **Add files**.
   If its vertical units are absent, choose the known Metres or Feet explicitly.

## Verified sources and access

| Source | Implemented search/download | Access and coverage |
|---|---|---|
| Lantmäteriet | STAC AOI search, ground model GeoTIFF tiles, approved Basic API credentials | Free Swedish ground model; catalog open, data requires a Geotorget order and API access. Height model is derived from laser scanning and/or photogrammetry; origin varies by tile. |
| USGS / The National Map | AOI product search, regional 3DEP 1 m GeoTIFF ground DEMs | Anonymous HTTPS download, regional U.S. coverage. Earlier files take priority; later overlapping surveys fill gaps. |
| OpenTopography | Worldwide regional STAC search for explicitly bare-earth DEMs, direct GeoTIFF assets; raw point catalog lookup | Raster assets checked on download. Raw catalogs open their provider's survey page; processing/account requirements vary. No subscription or paid access is purchased. |
| Local LAS/LAZ/COPC | Stream points, crop to map, project XY and make an aligned ground raster | Only ASPRS classification 2, excluding withheld points. Local COPC is read as LAZ; HTTP range queries into remote point clouds/EPT are not implemented. |

These are regional sources, **not a globally complete 1 m LiDAR model**. The
existing Copernicus/Mapzen options provide broader, coarser coverage and remain
explicit source choices. Copernicus DSM includes buildings/vegetation and is not
renamed as bare-earth LiDAR. Unavailable fine data is not silently replaced.

Primary provider contracts:

- [Lantmäteriet ground model API](https://geotorget.lantmateriet.se/dokument/projects/markhoejdmodell-nedladdning/released/1/)
- [Lantmäteriet laser forest API](https://geotorget.lantmateriet.se/dokument/projects/laserdata-nedladdning-skog-api/released/1/)
- [USGS National Map API](https://tnmaccess.nationalmap.gov/api/v1/docs)
- [USGS LiDAR Explorer](https://www.usgs.gov/tools/lidarexplorer)
- [OpenTopography developer APIs](https://opentopography.org/developers)
- [OpenTopography raster STAC catalog](https://portal.opentopography.org/stac/raster_catalog.json)
- [laspy streaming and classification](https://laspy.readthedocs.io/en/latest/basic.html)
- [TF3 terrain API](https://wiki.transportfever3.com/script-doc/api/engine.html)

## Precision, height datum and failure handling

Raw points are averaged per aligned output cell. Empty cells stay nodata; the
ordinary gap policy either stops or explicitly estimates small gaps. The raster
spacing and point density do not establish measurement uncertainty. Choosing a
1 m output retains a finer grid, but does not change TF3's base heightmap grid.
XY is reprojected; Z is kept in its original datum/units. No geoid or vertical
datum transformation is guessed. US survey foot Z needs an explicit prior unit
conversion. Height offset/vertical scale remain user-controlled.

LiDAR import does not enable water excavation or road/rail corridor reshaping.
Those switches remain optional and off by default. The in-game importer still
applies its road/rail height policy when construction happens. This feature does
not introduce local sea levels, flowing water, or inferred bridge deck heights.

Point reads use bounded chunks and disk-backed accumulators; downloads have
per-file and tile limits, cancellation, temporary files and GeoTIFF validation.
Download cache checksums detect changed cached files. An explicit GeoTIFF mask
overrides scalar nodata. Source attribution and LiDAR provenance are included
in heightmap reports. API credentials stay in memory and are stripped on a
redirect to a different HTTPS origin; they are not saved in project/report files.

## Live verification — 4 October 2026

Separate geographic test areas, not the user's `partille_test` map, were used:

- Sweden, S/W/N/E `57.7,12,57.8,12.15`: public STAC returned 42 overlapping
  ground-model assets; anonymous asset access returned HTTP 401. Increase the
  tile limit when such a map needs more than its default 16 downloads.
- Colorado, `40,-105.3,40.1,-105.2`: USGS returned 13 ground-model assets.
  A real **10,425,274-byte** GeoTIFF was downloaded anonymously and validated.
- OpenTopography's documented `AK05_Pavlis` bare-earth asset returned HTTP 200
  without credentials. Its advertised 1 GB size exceeds the default 512 MB
  per-file limit; the limit can be changed before download. A map inside that actual asset footprint returned one downloadable ground DEM with no catalog errors.

LAS and LAZ round-trip fixtures verify classified-ground filtering, withheld/
building exclusion, exact alignment, absence of invented heights, cancellation,
CRS/unit errors and point limits. Native TF3 heightmap import is still unverified.

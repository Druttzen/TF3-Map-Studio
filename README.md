# TF3 Map Studio

Four Transport Fever 3 tools in one project. Each folder includes its source, tests, dependencies, build instructions, and license notices.

| # | Tool | Purpose | Source and instructions |
| --- | --- | --- | --- |
| 1 | **OSM-TF3-Vanilla-Converter** | Convert OpenStreetMap XML into TF3 Lua data and a vanilla-resource mod template; download and inspect OSM selections. | [OSM-TF3-Vanilla-Converter](OSM-TF3-Vanilla-Converter/) |
| 2 | **TF3-Heightmap-Studio** | Prepare elevation and biome maps aligned with the converter's map bounds; preview, edit, and export terrain. | [TF3-Heightmap-Studio](TF3-Heightmap-Studio/) |
| 3 | **TRF3-Mod-Converter** | Scan mod collections into a removable queue and export supported mods sequentially, with recovery and per-mod results. | [TRF3-Mod-Converter](TRF3-Mod-Converter/) |
| 4 | **TF3-OSM-Importer-Mod** | Import the converter's Lua dataset in TF3 through an in-game control panel, with saved progress, pause/resume, retry, and vanilla resources. | [TF3-OSM-Importer-Mod](TF3-OSM-Importer-Mod/) |

## Windows downloads

Download and extract the package for the tool you need, then open its `.exe`. The packages include the runtime, so a separate Python installation is not required.

- [OSM-TF3-Vanilla-Converter — Preview 0.16.3](https://github.com/Druttzen/TF3-Map-Studio/releases/download/map-studio-review-2026-10-25-fix4/OSM-TF3-Vanilla-Converter-0.16.3-Windows.zip)
- [TF3-Heightmap-Studio — Preview 0.11](https://github.com/Druttzen/TF3-Map-Studio/releases/download/map-studio-review-2026-10-25-fix2/TF3-Heightmap-Studio-0.11-Windows.zip)
- [TRF3-Mod-Converter — 0.15.0](https://github.com/Druttzen/TF3-Map-Studio/releases/download/converter-v0.15.0/TRF3-Mod-Converter-0.15.0-Windows.zip)

The [reviewed 25 October release](https://github.com/Druttzen/TF3-Map-Studio/releases/tag/map-studio-review-2026-10-25-fix4) includes the complete Windows bundle, standalone importer revision 11, source and checksums. Use the `main` branch for current source; older version tags retain their historical code.

Heightmap Studio 0.11 reads large converter reports without the former 64 MB rejection. Select the converter JSON or use **Mod folder…** to select the folder containing `import-report.json`; the app discovers its matching Lua. A `.download.json` is a download log, and `.heightmap-report.json` describes an exported terrain: neither replaces the OSM conversion report.

TRF3-Mod-Converter source and Windows runtime are **0.15.0**, focusing on vehicles and appearance patches, supported TF2 data retention and recorded class-average noise/pollution. Exported drafts still require game tests. See [the converter instructions and limitations](TRF3-Mod-Converter/EXPORT_PROFILES.md).

## In-game importer mod — tool #4

Current source is **revision 11**, bundled with converter Preview 0.16.3. Ground faces that collapse at TF3 coordinate precision are omitted and explicitly counted, fixing the identified Huge-map stop after 172,300 scenery items. Existing datasets and saved source positions are retained. Retry preserves accepted objects; a legacy uncertain-outcome failure requires a live construction inventory before recovery. Put converted `.lua` maps in the installed importer’s `content/osm/maps` folder before starting TF3, then choose a file in the in-game panel. The engine loads and restores the selected resource directly. Retain the original file of a started import. The GUI reads compact metadata, category totals use cached aggregates, and idle updates do not rewrite saved script state.

[Download TF3-OSM-Importer-Mod revision 11](https://github.com/Druttzen/TF3-Map-Studio/releases/download/map-studio-review-2026-10-25-fix4/TF3-OSM-Importer-Mod-Revision-11.zip). Extract `tf3_osm_importer_mod` into TF3's local mods folder and keep one installed copy. Preserve custom datasets and saved progress when updating; do not replace them with the fictional sample. The internal mod ID remains `druttzen_osm_vanilla` for existing saves. See [the importer instructions](TF3-OSM-Importer-Mod/README.md).

Experimental shallow-water excavation, model matching and functioning towns retain the documented testing limits. Read [the water investigation](TF3-OSM-Importer-Mod/WATER-RESEARCH.md) and [the review findings and fixes](CODE-REVIEW-2026-10-25.md).

These are preview tools. The fictional OSM sample imports in TF3 Windows build 40408 and passes its built-object check after a full restart and save reload. Read [the native validation scope](TF3-OSM-Importer-Mod/NATIVE-VALIDATION.md): large real maps, bridges, tunnels and actual vehicle routes still need testing. Place names are stored by the importer and displayed in its panel. Heightmap Studio's native TF3 terrain import remains unverified. The mod converter exports verified literal vehicle/resource profiles and metadata/layout; arbitrary gameplay APIs and unverified schemas require manual porting. New profile exports still need native gameplay tests.

## Development

Clone this repository and follow the README in each tool folder. Use a separate Python environment for each tool to keep its dependencies independent. Run the tests from the tool's own folder.

| Tool | Tests | Build/package |
| --- | --- | --- |
| OSM-TF3-Vanilla-Converter | `python -m unittest discover -s tests` | `build.ps1` |
| TF3-Heightmap-Studio | `python -m pytest tests` | `build.ps1` |
| TRF3-Mod-Converter | `python -m pytest -q` | `python scripts/build_windows.py` |
| TF3-OSM-Importer-Mod | `python -m unittest discover -s tests` | `python scripts/package_mod.py` |

The local `work/`, `outputs/`, and `.relocation-recovery/` folders contain working environments, generated packages, and recovery files. Git ignores them; source is maintained in the four named tool folders and packages are distributed through Releases.

## Licensing and provenance

Licenses apply per tool. OSM-TF3-Vanilla-Converter, TF3-Heightmap-Studio, and TF3-OSM-Importer-Mod include their GPL licenses and applicable third-party notices. TRF3-Mod-Converter uses the MIT license. Preserve the license and notice files when distributing a tool.

TRF3-Mod-Converter originated in [Druttzen/TRF3-mod-converter](https://github.com/Druttzen/TRF3-mod-converter). This combined project includes the local desktop edition and keeps the original repository available separately.

Current Heightmap Studio source is Preview 0.11, with AOI-based LiDAR/ground-model discovery, classified LAS/LAZ import, detailed GeoTIFF enhancement and registry-based automatic TF3 export folders. See [LiDAR sources and access](TF3-Heightmap-Studio/LIDAR-SOURCES.md), [GeoTIFF detail](TF3-Heightmap-Studio/GEOTIFF-DETAIL.md) and [game folders](TF3-Heightmap-Studio/GAME-FOLDERS.md). The downloads above identify the current reviewed packages; local generated packages remain in `outputs/`. All four tools now run through root GitHub Actions workflows.

OSM Preview 0.16.1 corrects garbled desktop text and places the executable
directly in its standalone portable folder with START-HERE.txt. Its Windows
build runs an offline frozen-app export/template/SQLite/TLS/PNG check.

Heightmap Preview 0.11 adds automatic regional discovery, local-folder LiDAR/elevation matching, cached searches and session-only provider access setup. No shared provider key is included.

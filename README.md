# TF3 Map Studio

Three Transport Fever 3 mapping tools in one project. Each folder includes its source, tests, dependencies, build instructions, and license notices.

| # | Tool | Purpose | Source and instructions |
| --- | --- | --- | --- |
| 1 | **OSM-TF3-Vanilla-Converter** | Convert OpenStreetMap XML into TF3 Lua data and a vanilla-resource mod template; download and inspect OSM selections. | [OSM-TF3-Vanilla-Converter](OSM-TF3-Vanilla-Converter/) |
| 2 | **TF3-Heightmap-Studio** | Prepare elevation and biome maps aligned with the converter's map bounds; preview, edit, and export terrain. | [TF3-Heightmap-Studio](TF3-Heightmap-Studio/) |
| 3 | **TF3-OSM-Importer-Mod** | Import the converter's Lua dataset in TF3 through an in-game control panel, with saved progress, pause/resume, retry, and vanilla resources. | [TF3-OSM-Importer-Mod](TF3-OSM-Importer-Mod/) |

[TRF3 Mod Converter](https://github.com/Druttzen/TRF3-mod-converter) is maintained separately, with its own [Windows downloads](https://github.com/Druttzen/TRF3-mod-converter/releases).

## Windows downloads

**TF3 Map Studio Setup** installs both desktop apps for the current Windows user. It detects Transport Fever 3 and proposes a user folder when it can identify the profile. Confirm both paths, browse to a different folder, or leave the user folder blank to install just the desktop apps. Use **Settings → Advanced → Open User Data Folder** in TF3 if you need to check which profile the game is using.

Setup adds the OSM Importer to the selected profile's `mods` folder. If that profile already has the importer, setup keeps that copy and uses it for the converter's **Update installed mod** destination. Enable the mod in TF3. Heightmap Studio uses the same profile for `heightmaps` and `biomes`. Uninstalling the desktop apps leaves the game-side importer and maps in the profile.

Build the installer with `./installer/build.ps1` after provisioning the private development runtimes. GitHub Actions publishes the installer and its dependency manifest in the **TF3-Map-Studio-Windows** artifact.

Download and extract the package for the tool you need, then open its `.exe`. The packages include the runtime, so a separate Python installation is not required.

- [OSM-TF3-Vanilla-Converter — Preview 0.16.3](https://github.com/Druttzen/TF3-Map-Studio/releases/download/map-studio-review-2026-11-05/OSM-TF3-Vanilla-Converter-0.16.3-Windows.zip)
- [TF3-Heightmap-Studio — Preview 0.12](https://github.com/Druttzen/TF3-Map-Studio/releases/download/map-studio-review-2026-11-05/TF3-Heightmap-Studio-0.12-Windows.zip)

The [5 November system-test release](https://github.com/Druttzen/TF3-Map-Studio/releases/tag/map-studio-review-2026-11-05) contains the historical Windows packages, importer revision 11, source, dependency manifests and checksums. See [the system-test scope](SYSTEM-TEST-2026-11-05.md). Use the `main` branch for current source. Older version tags retain their historical code.

Heightmap Studio 0.12 joins compatible neighbouring elevation files before interpolation and defaults to one continuous 16-bit PNG on the native 4 m grid. New projects use Cubic interpolation; saved explicit choices remain. **Use smooth terrain settings** selects continuous interpolation without a blanket blur. The quality summary reports actual contributing source spacing: enlarging coarse data does not create measured detail. Finer ground DEMs, including Lantmäteriet 1 m data, can be found through LiDAR search with the provider's required personal access.

Heightmap Studio reads large converter reports without the former 64 MB rejection. Select the converter JSON or use **Mod folder…** to select the folder containing `import-report.json`; the app discovers its matching Lua. A `.download.json` is a download log, and `.heightmap-report.json` describes an exported terrain: neither replaces the OSM conversion report.

## In-game importer mod

Current development source is **revision 12**, bundled with converter Preview 0.16.4. The reviewed downloads above retain their release versions. Ground faces that collapse at TF3 coordinate precision are omitted and explicitly counted, fixing the identified Huge-map stop after 172,300 scenery items. Existing datasets and saved source positions are retained. Retry preserves accepted objects; a legacy uncertain-outcome failure requires a live construction inventory before recovery. Put converted `.lua` maps in the installed importer’s `content/osm/maps` folder before starting TF3, then choose a file in the in-game panel. The engine loads and restores the selected resource directly. Retain the original file of a started import. The GUI reads compact metadata, category totals use cached aggregates, and idle updates do not rewrite saved script state.

[Download TF3-OSM-Importer-Mod revision 11](https://github.com/Druttzen/TF3-Map-Studio/releases/download/map-studio-review-2026-11-05/TF3-OSM-Importer-Mod-Revision-11.zip). Extract `tf3_osm_importer_mod` into TF3's local mods folder and keep one installed copy. Preserve custom datasets and saved progress when updating; do not replace them with the fictional sample. The internal mod ID remains `druttzen_osm_vanilla` for existing saves. See [the importer instructions](TF3-OSM-Importer-Mod/README.md).

Experimental shallow-water excavation, model matching and functioning towns retain the documented testing limits. Read [the water investigation](TF3-OSM-Importer-Mod/WATER-RESEARCH.md) and [the review findings and fixes](CODE-REVIEW-2026-10-25.md).

These are preview tools. The fictional OSM sample imports in TF3 Windows build 40408 and passes its built-object check after a full restart and save reload. Read [the native validation scope](TF3-OSM-Importer-Mod/NATIVE-VALIDATION.md): large real maps, bridges, tunnels and actual vehicle routes still need testing. Place names are stored by the importer and displayed in its panel. Heightmap Studio's native TF3 terrain import remains unverified.

## Development

Clone this repository and follow [the private-runtime instructions](PRIVATE-RUNTIMES.md) to provision a complete private Python copy for each tool. A venv backed by global Python does not satisfy the standalone requirement. Run the tests from the tool's own folder.

| Tool | Tests | Build/package |
| --- | --- | --- |
| OSM-TF3-Vanilla-Converter | Private runner: `-m unittest discover -s tests` | `build.ps1` |
| TF3-Heightmap-Studio | Private runner: `-m pytest tests` | `build.ps1` |
| TF3-OSM-Importer-Mod | Private runner: `-m unittest discover -s tests` | Private runner: `scripts/package_mod.py` |

The local `work/`, `outputs/`, and `.relocation-recovery/` folders contain working environments, generated packages, and recovery files. Git ignores them. Source is maintained in the three tool folders and packages are distributed through Releases.

## Licensing and provenance

Licenses apply per tool. OSM-TF3-Vanilla-Converter, TF3-Heightmap-Studio, and TF3-OSM-Importer-Mod include their GPL licenses and applicable third-party notices. Preserve the license and notice files when distributing a tool.

Current Heightmap Studio development source is Preview 0.13, with optional transport clearance above global water, continuous sampling across compatible tile boundaries, source-quality reporting, AOI-based LiDAR/ground-model discovery, classified LAS/LAZ import, detailed GeoTIFF enhancement and registry-based automatic TF3 export folders. See [LiDAR sources and access](TF3-Heightmap-Studio/LIDAR-SOURCES.md), [GeoTIFF detail](TF3-Heightmap-Studio/GEOTIFF-DETAIL.md) and [game folders](TF3-Heightmap-Studio/GAME-FOLDERS.md). The downloads above identify the current reviewed packages. Local generated packages remain in `outputs/`. GitHub Actions tests all three tools.

OSM Preview 0.16.1 corrects garbled desktop text and places the executable
directly in its standalone portable folder with START-HERE.txt. Its Windows
build runs an offline frozen-app export/template/SQLite/TLS/PNG check.

Heightmap Preview 0.11 adds automatic regional discovery, local-folder LiDAR/elevation matching, cached searches and session-only provider access setup. No shared provider key is included.

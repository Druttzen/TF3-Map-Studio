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

- [OSM-TF3-Vanilla-Converter — Preview 0.10](https://github.com/Druttzen/TF3-Map-Studio/releases/download/importer-revision-4-2026-10-03/OSM-TF3-Vanilla-Preview-0.10-Windows.zip)
- [TF3-Heightmap-Studio — Preview 0.6](https://github.com/Druttzen/TF3-Map-Studio/releases/download/preview-2026-10-02/TF3-Heightmap-Studio-Preview-0.6-Windows.zip)
- [TRF3-Mod-Converter — 0.2.0](https://github.com/Druttzen/TF3-Map-Studio/releases/download/preview-2026-10-02/TRF3-Mod-Converter-Windows.zip)

TRF3-Mod-Converter source is now **0.10.0**, with road/rail/tram/water/air export profiles, automatic completion of missing data from sufficiently similar installed TF3 vehicles, same-class TF3 freight additions and protected queued exports. Existing data stays authoritative, every completion records its source, and uncertain matches receive **Needs review**. Dynamic/API mods still require manual migration; completed drafts require tests in TF3. The download above is the earlier published package. See [the current converter instructions and limitations](TRF3-Mod-Converter/EXPORT_PROFILES.md).

The [preview release](https://github.com/Druttzen/TF3-Map-Studio/releases/tag/preview-2026-10-02) also includes checksums. Source archives are available on that page.

## In-game importer mod — tool #4

Current source is revision 6 (bundled with converter source Preview 0.12), adding saved road/rail heights at construction time and experimental mapped small waters with a 0.5 m bed and Landscaping Water Dirty. Read [the water investigation and native test scope](TF3-OSM-Importer-Mod/WATER-RESEARCH.md). Shallow-water excavation and paint await native validation; local lake sea levels and ship navigation are not implemented. The downloads below are the earlier revision 4 until a newer release is published.

[Download TF3-OSM-Importer-Mod revision 4](https://github.com/Druttzen/TF3-Map-Studio/releases/download/importer-revision-4-2026-10-03/TF3-OSM-Importer-Mod-Revision-4.zip), extract it, and copy the `druttzen_osm_vanilla` folder into TF3's local mods folder. Prepare custom OSM datasets with tool #1 and enable the importer in a fresh test map. The mod package contains Lua scripts, a fictional demonstration dataset, instructions, and license notices; Python is required only for development tests and packaging.

Current source and new packages use the folder `tf3_osm_importer_mod` and the game display name **TF3-OSM-Importer-Mod**. The earlier revision 4 download above still contains `druttzen_osm_vanilla`. The internal mod ID is preserved for existing saves. Keep one installed copy and preserve your custom dataset when updating. See [the importer instructions](TF3-OSM-Importer-Mod/README.md) and [the revision 4 release and checksums](https://github.com/Druttzen/TF3-Map-Studio/releases/tag/importer-revision-4-2026-10-03).

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

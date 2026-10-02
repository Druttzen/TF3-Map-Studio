# TF3 Map Studio

Three Transport Fever 3 tools in one project. Each folder includes its source, tests, dependencies, build instructions, and license notices.

| Tool | Purpose | Source and instructions |
| --- | --- | --- |
| **OSM-TF3-Vanilla-Converter** | Convert OpenStreetMap XML into TF3 Lua data and a vanilla-resource mod template; download and inspect OSM selections. | [OSM-TF3-Vanilla-Converter](OSM-TF3-Vanilla-Converter/) |
| **TF3-Heightmap-Studio** | Prepare elevation and biome maps aligned with the converter's map bounds; preview, edit, and export terrain. | [TF3-Heightmap-Studio](TF3-Heightmap-Studio/) |
| **TRF3-Mod-Converter** | Inspect and convert older mod metadata and folder layouts into TF3 format. | [TRF3-Mod-Converter](TRF3-Mod-Converter/) |

## Windows downloads

Download and extract the package for the tool you need, then open its `.exe`. The packages include the runtime, so a separate Python installation is not required.

- [OSM-TF3-Vanilla-Converter — Preview 0.9](https://github.com/Druttzen/TF3-Map-Studio/releases/download/preview-2026-10-02/OSM-TF3-Vanilla-Preview-0.9-Windows.zip)
- [TF3-Heightmap-Studio — Preview 0.6](https://github.com/Druttzen/TF3-Map-Studio/releases/download/preview-2026-10-02/TF3-Heightmap-Studio-Preview-0.6-Windows.zip)
- [TRF3-Mod-Converter — 0.2.0](https://github.com/Druttzen/TF3-Map-Studio/releases/download/preview-2026-10-02/TRF3-Mod-Converter-Windows.zip)

The [preview release](https://github.com/Druttzen/TF3-Map-Studio/releases/tag/preview-2026-10-02) also includes checksums. Source archives are available on that page.

These are preview tools. OSM's native TF3 import and Heightmap Studio's native TF3 terrain import still need in-game verification. The mod converter handles metadata and layout; gameplay APIs, models, materials, and translations may require manual porting. Read each tool's detailed instructions before using it on a real project.

## Development

Clone this repository and follow the README in each tool folder. Use a separate Python environment for each tool to keep its dependencies independent. Run the tests from the tool's own folder.

| Tool | Tests | Windows build |
| --- | --- | --- |
| OSM-TF3-Vanilla-Converter | `python -m unittest discover -s tests` | `build.ps1` |
| TF3-Heightmap-Studio | `python -m pytest tests` | `build.ps1` |
| TRF3-Mod-Converter | `python -m pytest -q` | `python scripts/build_windows.py` |

The local `work/`, `outputs/`, and `.relocation-recovery/` folders contain working environments, generated packages, and recovery files. Git ignores them; source is maintained in the three named tool folders and Windows packages are distributed through Releases.

## Licensing and provenance

Licenses apply per tool. OSM-TF3-Vanilla-Converter and TF3-Heightmap-Studio include their GPL licenses and third-party notices. TRF3-Mod-Converter uses the MIT license. Preserve the license and notice files when distributing a tool.

TRF3-Mod-Converter originated in [Druttzen/TRF3-mod-converter](https://github.com/Druttzen/TRF3-mod-converter). This combined project includes the local desktop edition and keeps the original repository available separately.

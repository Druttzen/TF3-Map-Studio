# TRF3 Mod Converter

A local desktop app and command-line tool for converting Transport Fever mod metadata and folder layout, with a separate **TF2 electric-locomotive port profile**. It never executes source Lua. Exported mods remain drafts until tested in TF3.

## Windows app

Extract **TRF3-Mod-Converter-Windows.zip** and double-click **TRF3-Mod-Converter.exe**. No separate Python installation is needed.

1. Choose a mod folder or JSON/Lua metadata file.
2. Choose a separate output folder, or type a new folder path.
3. Click **Preview mod**.
4. Review required changes and generated metadata. Edit the basic fields and preview again if needed.
5. Click **Convert mod** and open the converted folder.

The left panel scrolls on smaller displays. Leave the author override blank to preserve the original authors.

Existing non-empty output is protected. The replacement checkbox (or CLI --overwrite) keeps the previous output beside it in a backup folder. Copy failures leave existing output untouched; final rename failures restore its backup.

When the output is immediately inside a folder named mods, backups go to the parent folder's trf3_mod_backups instead. TF3 discovers sibling backups as duplicate installed mods. Keep backups outside its active mod directory.

Output contains mod.json, _metadata/modinfo.json, content/, and conversion-report.json. Legacy res/ resources move into content/ in the output. Original source files are preserved.
The final output folder name must use letters, digits, underscores, or spaces.

## Install from source

Requires Python 3.10+ with Tkinter (included with the standard Windows Python installer; often python3-tk on Linux).

~~~console
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m trf3_mod_converter gui
~~~

On Linux/macOS, use .venv/bin/python instead.

## CLI

~~~console
trf3-mod-converter inspect "C:\mods\old_mod"
trf3-mod-converter convert "C:\mods\old_mod" "C:\mods\converted_mod"
trf3-mod-converter convert "C:\mods\old_mod" "C:\mods\converted_mod" --name "My Mod" --author "Creator" --mod-id "creator_my_mod" --revision 2 --summary "A short description"
~~~

Both inspect and convert accept metadata overrides. Inspection prints blockers, warnings, canConvert, and generated metadata. Errors/manual changes exit with code 2; success exits with code 0. **python -m trf3_mod_converter** is equivalent to the installed command.

Try **examples/legacy_mod**, a metadata-only example.

## General content analysis (0.5)

The app and CLI currently process one mod at a time. Selecting a Workshop container with multiple child mods gives an explicit message that batch conversion is not available; it does not merge the children into one mod. A future batch queue must inspect and export each package separately, map stable IDs/dependencies and record unsupported items without claiming universal TF3 compatibility.

The conversion scope includes complete mod packages and all vehicle families. Use `trf3-mod-converter analyze "C:\mods\any_mod"` to identify road, rail, tram, water and air vehicles, mixed content and the migration requirements for construction, infrastructure, terrain, cargo, sound, rendering, scripts and localization. Identification uses metadata and resource types; unknown or computed models remain explicit. Analysis does not execute source Lua.

Inspection, desktop preview and conversion reports include this plan. Shared mesh/blob checks validate ranges, component counts, separate attribute indices and triangles for every model category. Invalid buffers block export; non-finite values are reported without automatic repair. Unsupported descriptors remain unverified.

**Analysis coverage is broader than automated export support.** The additional category adapters are not yet exporters. Ordinary conversion still changes metadata/layout; the separate draft exporter still supports only its strict electric-locomotive profile. Native TF3 compatibility is never inferred from recognition or parsing. See [GENERAL_CONVERSION.md](GENERAL_CONVERSION.md) for the reusable pipeline, category requirements and verified references. The `analyze` command exits 2 when unknown resources, geometry warnings/errors or layout problems require review; otherwise it exits 0, meaning analysis completed, not gameplay passed.

## TF2 electric-locomotive port (0.4)

The separate **Port TF2 electric locomotive…** button rewrites supported version-1 models to version 2 and migrates their materials, units, wheel/bogie node references, headlights, sound, translations and thumbnails. Fill in the source folder, separate output folder, name and ID, then choose your installed TF3 directory. Cancel the optional repair-file dialog when no texture repair is needed. Other metadata overrides apply to this export too.

~~~console
trf3-mod-converter port-tf2 "F:\TF2\mods\electric_locomotive" "F:\exports\electric_locomotive_tf3" --tf3-game "B:\SteamLibrary\steamapps\common\Transport Fever 3" --name "Electric Locomotive Test" --mod-id "creator_electric_test"
~~~

`--repairs repairs.json` accepts explicit texture substitutions within the original mod, for example `{"missing.dds":"existing.dds"}`. Missing resources are never guessed. Unused repair entries are rejected. The report records every substitution. The port checks native material properties and base resources against the chosen installation; game assets are referenced rather than copied.

This profile supports literal electric-locomotive resources with no passenger/cargo capacity, custom crew models, arbitrary behavior resources, or meaningful lifecycle callbacks. Only provably empty lifecycle functions can be removed. Unsupported fields stop export. Other TF2 vehicle types need separate profiles.

Version 0.6 also migrates custom TF2 sound sets with direct tracks/events tables and recognized update patterns: literal gain/pitch, speed01 sample curves (including constant audioutil.plotSqrt), squeal, brake and clacks. The independent sound adapter preserves order, distances and curves, converts clack reference weights from tonnes to kilograms, and uses the installed TF3 soundset_default script. Local clips retain their bytes and get namespaced lowercase paths. The known TF2 train base-audio root maps to the installed TF3 shared train sound directory; every target must exist. TF3 base clips can differ from TF2 clips. Arbitrary helpers, computed controls and side effects stop export. Original sound-set text is archived. This adapter is reusable across vehicle profiles; the current complete exporter remains electric-locomotive only.

The vehicle exporter can fold finite constant arithmetic and math.pow in resource tables without running Lua. Shadowed math bindings, undefined calculations and other calls are rejected. Uppercase source directories are rebuilt with lowercase names in the staged output, including on Windows. Path collisions stop export.

The output must be outside the source mod. SHA-256 hashes verify source preservation; changed model/material text, `mod.lua` and `strings.lua` are retained in `_port_originals/`. Meshes, blobs, textures, audio and animation files are retained byte for byte, with resource paths normalized. `pathMapping`, `explicitRepairs`, `baseGameResources` and `portCounts` describe the migration in `conversion-report.json`. Store previews reuse original thumbnails. Default metal/gloss/AO references and automatic emissions follow the installed TF3 defaults; inspect their appearance and balancing in the game.

The ordinary **Convert mod** button continues to convert metadata and layout only. A successful static export does not prove rendering, animations, audio or operation in TF3. See [VALIDATION.md](VALIDATION.md) for the actual tested scope.

## Input and precedence

Supports JSON objects and static Lua tables: bare tables, returned chunks, and direct literal returns in data(). Lua comments, long strings, escapes, semicolon separators, literal concatenation, translation-key calls, and legacy field aliases are supported.

Folder metadata merges in this order: modinfo.lua, mod.lua, modinfo.json, info.json, mod.json, _metadata/modinfo.json. Later canonical fields win, including explicit empty/null values. Mod-browser dependency ids remain separate from technical dependencies.

Selecting any recognized metadata file reads the complete containing mod, using the same precedence as folder input. Selecting _metadata/modinfo.json uses the parent mod folder and retains its mod.json identity, revision, dependencies and script configuration. An independently named JSON/Lua file reads only that file and copies its containing folder. Keep unrelated files out of that source folder.

Native extension fields and complete script-reference objects (including params) are retained. conversion-report.json also archives sourceMetadata with the original JSON and statically readable Lua values; unsupported Lua expressions are described without being executed. Additional legacy fields are reported when they cannot be mapped into native metadata. Explicitly empty descriptions stay empty.

Version 0.6.1 fixes inspection of unnamed numeric metadata entries. Mixed numeric/string Lua table keys are archived as typed luaTableEntries, and malformed metadata is blocked for review instead of crashing or guessing a missing dependency. Legacy .module files are recognized in general analysis and explicitly blocked by the vehicle-only exporter.

TF3 mod lifecycle functions receive configDict/allModParams (and baseConfig for preRun); selected mod parameters come from top-level mod.params. This differs from general resource scripts with captureParams. Nested lifecycle-reference params are preserved and explicitly flagged for review, never silently converted into selected mod parameters.

An existing modId is preserved when changing the display name or installation folder. An explicit name override also updates existing localized names. An ID override updates manifest lifecycle references only when copied resources and retained configuration contain no references to the old namespace. Otherwise conversion stops with the affected files; migrate their references explicitly. The tool does not blindly replace strings inside scripts or binary assets.

## Resource and script checks (0.3)

Preview and final staged export scan Lua/JSON text resources, models, mesh indexes, materials and animations without executing them. They resolve literal local resource paths relative to their referring file, absolute paths in the mod, and qualified mod paths. Missing local targets, forbidden parent paths, invalid resource names, UTF-8 BOMs, unparsable Lua resources and missing mesh blobs block export.

TF2 sound clips, version-1 models and flat materials in the legacy layout use resource-type roots with a base-game fallback. Inspection records local legacy targets and unverified base/other-mod targets instead of falsely calling them missing relative TF3 files. Their required migration still blocks metadata-only conversion. Empty inline lifecycle callbacks are omitted with a warning; callbacks with behavior still require migration.

Referenced lifecycle and literal .script callbacks are checked against keys returned by global data(). A provably missing or non-callable callback blocks conversion. Computed data() tables and Teal callbacks remain explicitly unverified. Literal ug_require calls are checked too; computed references, external mods, base-game resources, binary formats and gameplay APIs require further checks in TF3.

The GUI preview and JSON report include resourceAudit. A static_checks_passed status is a partial offline check, not evidence that the mod works in the engine. nativeTest remains not_run in generated conversion reports: this converter does not launch or observe the game.

Parameter numbers arrays are validated and exported as JSON decimals. The installed TF3 build 40408 rejects integer tokens in this double array even when their mathematical values are valid; the original metadata remains archived in the report.

Try examples/native_smoke_mod for an authored native script fixture with legacy res/ layout. It exercises ID retention, callback parameters and a local helper resource and prints distinct preRun/run markers when enabled on a separate test map. It does not test automatic migration of TF2 APIs or assets.

Nested outputs are supported. Current output, temporary stages, recognized previous backups, and development caches (.git, __pycache__, .pytest_cache) are excluded. Symbolic links and junctions are rejected.

## Migration limits

Inline callbacks, computed metadata, legacy options, and unsupported parameter/dependency definitions require manual migration and block conversion. Legacy script paths require native TF3 module references; referenced local modules must exist.

The ordinary metadata conversion does not port gameplay APIs, models/materials or translations. Its Lua translation calls yield literal keys. The separate TF2 profile converts supported literal `strings.lua` tables to `strings.json`, without executing them.

A successful report confirms metadata checks, static reference checks and copying. Test converted resources and scripts in TF3 before publishing. See [VALIDATION.md](VALIDATION.md) for the tested scope.

Format references: [Mod definition](https://wiki.transportfever3.com/doku.php?id=modding:general:moddefinition), [resources and callback parameters](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes), [syntax](https://wiki.transportfever3.com/doku.php?id=modding:general:syntax).

## Development

~~~console
python -m pip install -e ".[dev]"
python -m pytest -q
python -m build
python scripts/build_windows.py
~~~

The last command requires Windows and creates the executable and ZIP under dist/. The build command creates a Python wheel and source archive.

Tests cover parsing, mixed metadata, source preservation, backups, recovery, CLI, and the desktop workflow. Desktop tests skip without a display. Run tests and builds from this tool's folder; its standalone workflow is retained under `.github/workflows/` as a reference.

MIT license. See [LICENSE](LICENSE).


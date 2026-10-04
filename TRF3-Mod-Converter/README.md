# TRF3 Mod Converter

A local desktop app and command-line tool, version **0.11.0**, with a removable mod queue, metadata/layout conversion and **TF2 vehicle, cargo and resource export profiles**. Missing required vehicle data can be completed from a sufficiently similar object in the selected TF3 installation. It never executes source Lua. Exported mods remain drafts until tested in TF3.

Version 0.11 fixes ordered cargo exclusions/reinclusions, rejects shadowed
localization helpers and invalid/version-1 native donors, and checks the TF3
mount inventory plus SHA-256 fingerprints of used resource/donor inputs when
resuming a queue. Earlier version receipts require a fresh export folder.

## Windows app

Extract **TRF3-Mod-Converter-Windows.zip** and double-click **TRF3-Mod-Converter.exe**. No separate Python installation is needed.

1. Choose a mod folder or collection such as `F:\SteamLibrary\steamapps\workshop\content\1066780`. All subfolders are scanned automatically. You can also enter a folder path and press Enter.
2. Choose a separate export folder, or type a new folder path. The installed TF3 folder is detected from Steam when possible; choose it manually if necessary.
3. Review the list of display names. Each **−** button removes that mod from the queue without deleting its source files. Click a name to read its details.
4. Click **Convert all listed mods**. Each remaining package is processed in list order, into its own folder. A successful export turns the name green and adds **✓**. A failed mod shows **Needs review**, and the queue continues with the next one.
5. Use **Stop after current mod** to leave the remaining mods pending. Select the same source/export folders and run again to verify existing completed exports and continue.

The desktop app has one conversion action. It automatically selects the supported TF2 content profile or the metadata/native validation path. Unsupported TF2 content fails explicitly instead of receiving a misleading metadata-only success. Author data is preserved; individual overrides and explicit repairs remain available through the CLI.

The queue never overwrites existing mod folders. Source and output SHA-256 fingerprints, converter version, mod ID and TF3 installation path must match a completed receipt before an existing export receives a green checkmark again. Results are saved after each mod in `.tf3-batch-report.json`. An operating-system lock prevents simultaneous queues writing to the same output folder and releases automatically if the app crashes. Staged exports protect final output from ordinary copy/validation failures. An unrecognized or changed output is retained for review; use a different export folder to make a new draft.

Workshop packages receive stable IDs from their Workshop folder numbers. Other legacy packages receive IDs based on their source path; explicit mod IDs are retained. Duplicate explicit IDs fail rather than overwrite each other. Linked folders are skipped during scanning and linked resources are rejected during export. No original mod is changed and no source Lua is executed. A green checkmark confirms an export, not operation in TF3.

Individual CLI conversion retains its explicit `--overwrite` option with backups and recovery. Keep those backups outside TF3's active mod directory.

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
trf3-mod-converter scan "F:\SteamLibrary\steamapps\workshop\content\1066780"
trf3-mod-converter batch "F:\SteamLibrary\steamapps\workshop\content\1066780" "F:\exports\tf3_drafts" --tf3-game "B:\SteamLibrary\steamapps\common\Transport Fever 3"
trf3-mod-converter convert "C:\mods\old_mod" "C:\mods\converted_mod"
trf3-mod-converter convert "C:\mods\old_mod" "C:\mods\converted_mod" --name "My Mod" --author "Creator" --mod-id "creator_my_mod" --revision 2 --summary "A short description"
~~~

Both inspect and convert accept metadata overrides. Inspection prints blockers, warnings, canConvert, and generated metadata. `scan` lists packages without exporting; `batch` uses the desktop queue's sequential conversion and recovery logic. A batch exits 2 if any listed mod failed. Other errors/manual changes also exit with code 2; success exits with code 0. **python -m trf3_mod_converter** is equivalent to the installed command.

Try **examples/legacy_mod**, a metadata-only example.

## General content analysis (0.5)

Version 0.8 adds recursive collection scanning and sequential batch export to the desktop app and CLI. Each package keeps its own output, result and source identity. Scanning stops at a package boundary so metadata inside a helper library is not mistaken for another mod. Mod names are read statically, including literal translated names; malformed/computed metadata stays listed with an explicit error. Referenced dependencies still require the existing validation and manual migration where needed.

The conversion scope includes complete mod packages and all vehicle families. Use `trf3-mod-converter analyze "C:\mods\any_mod"` to identify road, rail, tram, water and air vehicles, mixed content and the migration requirements for construction, infrastructure, terrain, cargo, sound, rendering, scripts and localization. Identification uses metadata and resource types; unknown or computed models remain explicit. Analysis does not execute source Lua.

Inspection and conversion reports include this plan. Shared mesh/blob checks validate ranges, component counts, separate attribute indices and triangles for every model category. Invalid buffers block export; non-finite values are reported without automatic repair. Unsupported descriptors remain unverified.

**Analysis coverage is broader than automated export support.** Version 0.10 exports verified literal road/rail/tram/water/air vehicles, render assets and selected configuration/construction resources, with completion of supported missing vehicle fields from installed TF3 definitions. Unknown fields, dynamic scripts and unsupported layouts remain explicit blockers. Ordinary `convert` still changes metadata/layout; `batch` and `port-tf2` select the content exporters. Native TF3 compatibility is never inferred from recognition or parsing. See [GENERAL_CONVERSION.md](GENERAL_CONVERSION.md) for the reusable pipeline, category requirements and verified references. The `analyze` command exits 2 when unknown resources, geometry warnings/errors or layout problems require review; otherwise it exits 0, meaning analysis completed, not gameplay passed.

## TF2 vehicle and resource export (0.10)

The queue automatically selects each supported TF2 vehicle/resource profile, including mixed packages and packages containing only supported configurations. It rewrites supported version-1 models to version 2 and migrates their materials, units, wheel/bogie node references, headlights, sound, translations and thumbnails. The installed TF3 inventory is reused across the queue, with independent resource reports for each mod. The standalone `port-tf2` command provides optional metadata overrides and explicit texture repairs:

~~~console
trf3-mod-converter port-tf2 "F:\TF2\mods\electric_locomotive" "F:\exports\electric_locomotive_tf3" --tf3-game "B:\SteamLibrary\steamapps\common\Transport Fever 3" --name "Electric Locomotive Test" --mod-id "creator_electric_test"
~~~

`--repairs repairs.json` accepts explicit texture substitutions within the original mod, for example `{"missing.dds":"existing.dds"}`. Missing resources are never guessed. Unused repair entries are rejected. The report records every substitution. The port checks native material properties and base resources against the chosen installation; game assets are referenced rather than copied.

Profiles cover horse/steam/diesel/electric rail and road vehicles, unpowered wagons, buses, trucks, AI cars, trams, ships, aircraft, people and static/tree/rock models. Cargo and passenger compartments, seats, hidden nodes and generic cargo visuals are migrated. Multiple units, crossings, auto ground textures, ground textures, terrain materials, grass, tracks/streets, verified default bridges and constant decorative asset constructions have separate adapters. Per-LOD identity and unit changes are handled by each profile. Unmatched or conflicting aircraft radii, active ship flags, nonstandard blink timing, explicit TF2 emissions, custom callbacks or unverified metadata can still block an individual mod. Only provably empty mod lifecycle functions can be removed. Dynamic stations/industries/depots/modules, custom cargo economies and arbitrary game/API scripts require manual migration; there is no claim of universal automatic conversion.

Version 0.6 also migrates custom TF2 sound sets with direct tracks/events tables and recognized update patterns: literal gain/pitch, speed01 sample curves (including constant audioutil.plotSqrt), squeal, brake and clacks. The independent sound adapter preserves order, distances and curves, converts clack reference weights from tonnes to kilograms, and uses the installed TF3 soundset_default script. Local clips retain their bytes and get namespaced lowercase paths. The known TF2 train base-audio root maps to the installed TF3 shared train sound directory; every target must exist. TF3 base clips can differ from TF2 clips. Arbitrary helpers, computed controls and side effects stop export. Original sound-set text is archived. This adapter is shared by the expanded vehicle profiles; audio resolution uses the relevant vehicle family.

The exporter can fold finite constant arithmetic, literal local bindings and narrow verified bridge/texture helper factories without running Lua. Shadowed built-ins/helpers, undefined calculations, arbitrary calls and local overrides of known helper modules are rejected. Uppercase source directories are rebuilt with lowercase names in the staged output, including on Windows. Path collisions stop export.

### Automatic missing-data completion

The queue and `port-tf2` fill supported absent/None values from a sufficiently similar installed TF3 vehicle. This includes speed, empty mass, power/tractive effort in already declared engines, required aircraft/ship simulation values, loading speed and compatible cargo capacities. Existing values, including explicit zero capacities and unpowered engine arrays, remain authoritative. Invalid supplied values, unknown cargo identities, missing carrier/SMALL/BIG markers or unverified propulsion for propulsion-dependent fields require review.

Matching uses verified vehicle family, carrier, size restrictions, passenger/freight role, engine types, cargo classes and available physical evidence. Dimensions, supplied simulation values and capacity contribute to the comparison; a name or filename cannot establish similarity. Propulsion-dependent ship/air values require verified propulsion evidence. If sufficiently close alternatives would supply different requested values, conversion stops with **Needs review**. Cargo capacities require compatible independent compartments and unambiguous cargo-type or same-class correspondence; source seats, hidden nodes, load visuals and existing capacities stay intact.

Missing aircraft gear radii first use an existing corresponding source LOD with the same explicit node names and full world transforms. A native estimate additionally requires matching named gear roles/counts, body dimensions with uniform scaling within 5%, compatible normalized positions within 2% and uniform node transforms. Source node positions and control bindings remain intact. A missing ship waterline can use an aligned, scaled native hull outline only with uniformly comparable hull dimensions. These geometry estimates require inspection in TF3.

`migrationAudit.dataCompletions` and `nativeDonorMatches` record fields, completed values, donor resources, unit changes, match evidence and estimates. Native definitions supply data and verified references; donor scripts, identities and asset files are not copied. A cached metadata projection reads installed model definitions without constructing unused LOD trees; geometry is parsed fully when required. Completion does not establish historical accuracy, equivalent vehicle physics or in-game operation. [EXPORT_PROFILES.md](EXPORT_PROFILES.md) describes the gates and limits.

### Automatic same-class TF3 freight additions

The default policy is the user-selected **same verified cargo class** policy. The selected TF3 installation supplies the catalog; this installation currently contains 37 cargo types, six classes and 28 formats. Original cargo alternatives retain their raw capacity and visuals. Additional eligible types become separate alternatives in the same compartment; independent compartments retain simultaneous capacity. BULK, LIQUID, GOODS and FLATBED expansions honor source exclusions and never add passengers as freight. The broad UNIVERSAL class alone does not authorize crossing specific freight classes.

Legacy aggregate cargo IDs have explicit catalog mappings, including FOOD and CONSTRUCTION_MATERIALS; OIL denotes the liquid category and is not confused with CRUDE. Unknown/custom IDs require a verified explicit mapping. Fixed authored cargo models must have a generic bay/dynamic format alternative before they can represent newly added cargo. An unsupported mixed visual/layout blocks export rather than disappearing. `migrationAudit.cargoMigrations` records original definitions, every addition, template, class, capacity and installed evidence. Land/ship maximum payload uses the matched native vehicle's declared payload per raw capacity unit and the converted model's maximum simultaneous capacity. Installed native aircraft omit the optional payload field; a matched aircraft follows that omission. The former blanket 300 kg estimate is no longer used. Completed capacities and payload decisions are recorded and still require loaded-mass/acceleration checks in TF3.

`migrationAudit.vehicleProfiles` and `capabilities` describe the actual selected adapters and remaining manual categories. References and cached catalogs remain isolated between queued mods. Native gameplay status stays `not_run` until independently tested. [EXPORT_PROFILES.md](EXPORT_PROFILES.md) lists the verified implementation and research sources.

### Borrowed TF2 resources (0.7)

The TF2 port automatically replaces borrowed base-game textures, particle textures, sound sets and audio with verified installed TF3 counterparts. A shared resolver serves every category adapter: sound sets retain their vehicle family (bus, car, truck, tram, train, wagon, plane or ship), instead of always looking under train resources. Recognized resource roles can use updated TF3 assets whose bytes differ from TF2. Other relocated textures, clips and animations require an identical SHA-256 hash and filename; a similar name alone is insufficient. Unknown or ambiguous equivalents stop export with an explicit migration requirement.

The TF2 base inventory is detected from the source's Steam library or the TF3 installation's sibling directory. CLI users can provide `--tf2-game "F:\SteamLibrary\steamapps\common\Transport Fever 2"`. Both loose and archived TF2 resources are read without executing Lua. When a mod bundles a texture, clip, animation or sound set identical to TF2's base resource at the same path, the verified TF3 replacement is referenced and the borrowed file is omitted from the exported content. Authored modifications, including files using a standard base-game name, stay local. Without a TF2 installation, known mappings still work, but bundled files cannot be identified safely and remain local.

Every substitution records its source, TF3 target, origin and proof method in `baseResourceReplacements`. `omittedBorrowedResources` lists omitted copies and `tf2BaseInventory` records the inspected installation. TF3 assets are referenced through `::/` and never copied into the output. A missing TF3 target is not replaced with a random default. Literal particle emitters now preserve named parents, frequency, lifetime, color, velocity and size/alpha endpoints as explicit TF3 curves. The report records the linear size/fade policy. TF2 emitters lack semantic IDs; engine-dependent steam/smoke timing needs native verification. Unknown emitter fields block export. Verified default driver roles and track resources also reference installed TF3 counterparts.

The output must be outside the source mod. SHA-256 hashes verify source preservation; changed resource text, `mod.lua` and `strings.lua` are retained in `_port_originals/`. Geometry indices/attributes and authored blobs, textures, audio and animation files remain unchanged. Mesh descriptor text changes only for verified material references; missing legacy defaults require unanimous explicit model-slot evidence. Unchanged mesh descriptors retain their exact bytes. `pathMapping`, `explicitRepairs`, `baseGameResources` and `portCounts` describe the migration in `conversion-report.json`. Store previews reuse original thumbnails. Default metal/gloss/AO references and automatic emissions follow the installed TF3 defaults; inspect their appearance and balancing in the game.

The standalone `convert` command continues to convert metadata and layout only. A successful static export does not prove rendering, animations, audio or operation in TF3. See [VALIDATION.md](VALIDATION.md) for the actual tested scope.

## Input and precedence

Supports JSON objects and static Lua tables: bare tables, returned chunks, and direct literal returns in data(). Lua comments, long strings, escapes, semicolon separators, literal concatenation, translation-key calls, and legacy field aliases are supported.

Folder metadata merges in this order: modinfo.lua, mod.lua, modinfo.json, info.json, mod.json, _metadata/modinfo.json. Later canonical fields win, including explicit empty/null values. Mod-browser dependency ids remain separate from technical dependencies.

Selecting any recognized metadata file reads the complete containing mod, using the same precedence as folder input. Selecting _metadata/modinfo.json uses the parent mod folder and retains its mod.json identity, revision, dependencies and script configuration. An independently named JSON/Lua file reads only that file and copies its containing folder. Keep unrelated files out of that source folder.

Native extension fields and complete script-reference objects (including params) are retained. conversion-report.json also archives sourceMetadata with the original JSON and statically readable Lua values; unsupported Lua expressions are described without being executed. Additional legacy fields are reported when they cannot be mapped into native metadata. Explicitly empty descriptions stay empty.

Version 0.6.1 fixes inspection of unnamed numeric metadata entries. Mixed numeric/string Lua table keys are archived as typed luaTableEntries, and malformed metadata is blocked for review instead of crashing or guessing a missing dependency. Legacy .module files are recognized in general analysis and explicitly blocked by the vehicle-only exporter.

TF3 mod lifecycle functions receive configDict/allModParams (and baseConfig for preRun); selected mod parameters come from top-level mod.params. This differs from general resource scripts with captureParams. Nested lifecycle-reference params are preserved and explicitly flagged for review, never silently converted into selected mod parameters.

An existing modId is preserved when changing the display name or installation folder. An explicit name override also updates existing localized names. An ID override updates manifest lifecycle references only when copied resources and retained configuration contain no references to the old namespace. Otherwise conversion stops with the affected files; migrate their references explicitly. The tool does not blindly replace strings inside scripts or binary assets.

## Resource and script checks (0.3)

Inspection and final staged export scan Lua/JSON text resources, models, mesh indexes, materials and animations without executing them. They resolve literal local resource paths relative to their referring file, absolute paths in the mod, and qualified mod paths. Missing local targets, forbidden parent paths, invalid resource names, UTF-8 BOMs, unparsable Lua resources and missing mesh blobs block export.

TF2 sound clips, version-1 models and flat materials in the legacy layout use resource-type roots with a base-game fallback. Inspection records local legacy targets and unverified base/other-mod targets instead of falsely calling them missing relative TF3 files. Their required migration still blocks metadata-only conversion. Empty inline lifecycle callbacks are omitted with a warning; callbacks with behavior still require migration.

Referenced lifecycle and literal .script callbacks are checked against keys returned by global data(). A provably missing or non-callable callback blocks conversion. Computed data() tables and Teal callbacks remain explicitly unverified. Literal ug_require calls are checked too; computed references, external mods, base-game resources, binary formats and gameplay APIs require further checks in TF3.

Individual conversion JSON reports include resourceAudit. A static_checks_passed status is a partial offline check, not evidence that the mod works in the engine. nativeTest remains not_run in generated conversion reports: this converter does not launch or observe the game.

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


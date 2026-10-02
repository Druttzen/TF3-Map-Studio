# TRF3 Mod Converter

A local desktop app and command-line tool for converting Transport Fever mod **metadata and folder layout**. It never executes source Lua.

## Windows app

Extract **TRF3-Mod-Converter-Windows.zip** and double-click **TRF3-Mod-Converter.exe**. No separate Python installation is needed.

1. Choose a mod folder or JSON/Lua metadata file.
2. Choose a separate output folder, or type a new folder path.
3. Click **Preview mod**.
4. Review required changes and generated metadata. Edit the basic fields and preview again if needed.
5. Click **Convert mod** and open the converted folder.

The left panel scrolls on smaller displays. Leave the author override blank to preserve the original authors.

Existing non-empty output is protected. The replacement checkbox (or CLI --overwrite) keeps the previous output beside it in a backup folder. Copy failures leave existing output untouched; final rename failures restore its backup.

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

## Input and precedence

Supports JSON objects and static Lua tables: bare tables, returned chunks, and direct literal returns in data(). Lua comments, long strings, escapes, semicolon separators, literal concatenation, translation-key calls, and legacy field aliases are supported.

Folder metadata merges in this order: modinfo.lua, mod.lua, modinfo.json, info.json, mod.json, _metadata/modinfo.json. Later canonical fields win, including explicit empty/null values. Mod-browser dependency ids remain separate from technical dependencies.

Single-file input inspects that file and copies its containing mod folder. Selecting _metadata/modinfo.json uses the parent mod folder. Keep unrelated files out of that source folder.

Nested outputs are supported. Current output, temporary stages, recognized previous backups, and development caches (.git, __pycache__, .pytest_cache) are excluded. Symbolic links and junctions are rejected.

## Migration limits

Inline callbacks, computed metadata, legacy options, and unsupported parameter/dependency definitions require manual migration and block conversion. Legacy script paths require native TF3 module references; referenced local modules must exist.

Gameplay APIs, models/materials, and translations are not automatically ported. Lua translation calls yield literal keys; strings.lua is not executed or converted.

A successful report confirms metadata checks and copying. Test converted resources and scripts in TF3 before publishing.

Format references: [Mod definition](https://wiki.transportfever3.com/doku.php?id=modding:general:moddefinition), [parameters and scripts](https://wiki.transportfever3.com/doku.php?id=modding:general:modscripts), [syntax](https://wiki.transportfever3.com/doku.php?id=modding:general:syntax).

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


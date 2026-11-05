# Private development and build runtimes

Each tool owns a complete `.runtime` CPython copy and a `.runtime-state` folder
for temporary files, caches and configuration. Portable Windows executables
also contain their own interpreters and packages. A venv backed by another
installation does not meet this project's isolation requirement.

From the repository root, explicitly select a full Windows CPython distribution
as the bootstrap source. Its standard library, DLLs and Tcl/Tk are copied; its
global packages and startup hooks are excluded. No global installation is changed.

```powershell
$Bootstrap = 'F:\your-owned-python\python.exe'
$Source = Split-Path $Bootstrap
$Tool = 'TF3-Heightmap-Studio'
& $Bootstrap -I scripts/private_runtime.py provision --tool $Tool --source $Source
& "$Tool/.runtime/python.exe" -I scripts/private_runtime.py install --tool $Tool
& "$Tool/.runtime/python.exe" -I scripts/private_runtime.py run --tool $Tool -- -m pytest -q "$Tool/tests"
```

Repeat separately for `OSM-TF3-Vanilla-Converter`, `TRF3-Mod-Converter` and
the importer development tests. Select a compatible CPython version for each
tool; different versions coexist. Run tests from the tool folder, or supply
its test directory when running from the root.

Launch source entry points through `run --tool <folder> -- <folder>/tools/gui.py`.
The wrapper starts an isolated child with explicit app-owned paths and excludes
inherited Python, Conda, user-site and pip configuration. It does not modify
machine/user settings. For the mod converter, `install` also installs its source
package into that tool's private environment.

Build OSM and Heightmap with their `build.ps1`. Build the mod converter from its
folder with `.runtime/python.exe -I ../scripts/private_runtime.py run --tool .
-- scripts/build_windows.py`. External Python arguments are rejected. Every
desktop build runs its frozen executable's offline `--self-check`.

`.runtime/ownership.json` records ownership, sources, interpreter hashes, actual
Python and package versions. `verify` checks these records. `install` uses only
that runtime and the tool's declared requirements. After an intentional package
change, `refresh` records the new inventory; it does not repair packages.

To repair or replace a runtime, repeat `provision` with `--backup` pointing to a
new app-specific directory under `F:\project-backups`, then `install`. The old
owned runtime is preserved. `uninstall --tool <folder> --backup <new-backup-path>`
removes only that tool's runtime by moving it into the explicit recoverable
backup; source, projects, outputs and other apps remain untouched.

The optional `--seed-packages` accepts an explicitly selected, ABI-compatible
package directory for offline provisioning. Files are copied independently,
startup `.pth` hooks are excluded, and sources and resulting package versions
are recorded. No dependency directories are shared or hardlinked.

Tcl/Tk 8 directory layouts and Tcl/Tk 9 zipfs archives are supported. Archived
script libraries are materialized only within that runtime, retaining their
original archives. See [Tcl initialization and TCL_LIBRARY](https://www.tcl-lang.org/man/tcl9.0/TclLib/Init.html).

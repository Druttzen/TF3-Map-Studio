# TF3 Map Studio system test — 5 November 2026

The four reported review findings are addressed: release verification now checks
the actual required runtime modules, GUI-saved legacy Heightmap projects retain
and validate actual OSM hashes, Windows builds require complete app-owned
interpreters, and root agent/runtime policy files are version controlled.
The Windows test fixture's transient directory rename now uses the existing
bounded Windows-lock retry helper.
The frozen-app desktop check additionally found action buttons below the
taskbar at 150% display scaling. All three app windows and the OSM/provider
dialogs now reserve screen space for window decorations and the taskbar,
and constrain their minimum size to the available screen.
The frozen OSM self-check also exposed a transient Windows lock during a new
mod-folder commit. That commit now retries only Windows sharing/access locks,
remains cancellable and refuses a competing destination on every attempt.

## Automated suites on Windows

- OSM converter: 353 passed, plus 616 subtests.
- Heightmap Studio: 301 passed; 2 symbolic-link tests skipped because the account
  cannot create those links. Includes GUI save/reload and rebuild regressions.
- Mod converter: 1,586 passed; 3 symbolic-link tests skipped for the same reason.
- In-game importer: 225 passed, plus 487 subtests.
- Repository release/runtime guards: 9 passed.

The suite total is 2,474 passed, excluding the separately reported subtests.
Affine deprecation warnings and deliberately duplicated archive-fixture entries
remain warnings, not application failures. Linux CI covers link behavior where
supported; no Windows security setting was changed to bypass the skips.

## Complete offline workflow and Windows packages

`scripts/test_map_pipeline.py` passed with fictional source data, using each
tool's own interpreter: OSM to standalone mod/Lua/report, verified Lua/report
identity, measured DEM to a 65 × 65 16-bit grayscale PNG and biome files,
project reload, CLI rebuild with identical PNG bytes, actual Lua evaluation,
and importer ZIP integrity/source-byte comparison. Source OSM bytes were retained.

All three Windows executables were built and passed their offline frozen-app
checks. Each frozen check initializes a hidden Tk window and the actual clam
theme, so missing Tk scripts cannot be mistaken for a passing dependency check.
The map/terrain apps also create a real Pillow/Tk preview image in that hidden
window to check the image bridge against the packaged Tk version.
Checks include TLS roots, Tcl/Tk, SQLite, PNG, OSM export/template bytes,
streamed reports, DEM tile seams, LAZ compression/ground filtering, projection,
biome/native-folder export routing, mod conversion and receipt-based recovery.
Release verification compares embedded code with source for 11 OSM, 19 Heightmap
and 33 mod-converter modules. Per-app dependency manifests bind recorded Python
and packaged distribution versions to each executable's SHA-256.

## Runtime ownership and coexistence

App-owned Windows interpreters run without global Python, user-site packages,
inherited PYTHONPATH/PYTHONHOME, external Conda or ambient tool PATH. Local OSM
uses Python 3.10.11; the other tool copies use Python 3.14.4. Windows CI provisions
independent complete copies from its explicitly selected CPython distribution.
Private Tcl/Tk script directories are discovered from their actual library
files, rather than assuming version 8.6; missing or ambiguous private libraries
stop provisioning/building instead of falling back to another installation.
Newer Windows Python distributions ship Tcl/Tk 9 script data in zipfs archives.
Provisioning retains those archives and materializes their initialization-root
trees inside the owning runtime for PyInstaller collection. Archive paths and
library roots are validated; no external Tcl/Tk installation is used.

`scripts/test_runtime_coexistence.py` installed two independent fixture apps with
Python 3.10.11 and 3.14.4, rejected a deliberately damaged interpreter, repaired
that app, and removed its runtime into a recoverable backup. The second app's
persistent runtime files, versions, settings, project data and functioning
Python/Tcl stayed unchanged. Generated Python bytecode caches are excluded from
the persistent-file comparison. Existing apps and interpreter sources were read-only.
Backups are under `F:\project-backups`; generated fixtures/logs are ignored.

## Native TF3 validation

On Windows TF3 build 40425, installed revision 11 scripts were compared with the
repository. In a separate empty test save, the fictional `choice.lua` fixture
loaded through the native selector, passed resource matching and completed
10/10 road/rail segments, 117/117 scenery items and 1/1 marker, with zero skipped
jobs. The live-world audit passed: nodes 12/12, roads 8/8, rails 2/2, vehicle lane
edges 10/10, models 115/115, ground items 2/2, markers 1/1 and connected groups 2/2.
The result was saved under a new filename containing `SystemTest-20261105`;
the earlier test save and the user's large dataset were not replaced.
A full game restart in a new process restored the selected native Lua resource
and all progress. A fresh live-world audit then passed the same counts again.

## Limits

This is broad regression, integration, packaging, ownership and native importer
testing, not an exhaustive claim for every map, mod or game build. Native TF3
heightmap/biome importing, real vehicle driving/rendering/audio, large real maps,
bridge/tunnel clearances and experimental water still require their documented
scenario-specific native checks. No personal provider credentials were used.
The release build manifest identifies the exact successful GitHub CI run and
reviewed source commit for the published binaries; local artifacts are not
silently substituted for CI artifacts.

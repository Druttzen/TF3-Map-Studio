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

## Additional native Partille scenario

The actual OSM download tool acquired the 16,384 × 16,384 m extent centred on
Partille (57.73906 N, 12.10218 E). The downloader retained 1,608,804 nodes,
247,165 ways and 3,913 relations. Its OSM SHA-256 is
`15e3ed03add994e01bd2ad11a22ae3ca5bfdd8eee2650447829a7c74fa42af8a`;
the converted Lua SHA-256 is
`5025472ffb17b5ba8f93e505b6d8ff91c9374254d545b1d9f089d407b8bfb6ef`.
Dataset `690679e8c96265c38d047ba3` contains 328,727 road/rail segments,
895,895 scenery items and 135 place markers. A full native preflight checked
all 1,224,757 source items.

Heightmap Studio downloaded Copernicus GLO-30 elevation and exported a
4,097 × 4,097 16-bit heightmap with Temperate biomes. Native TF3 imported the
height range −21 to 169 m and water level 0 m. Nine base-height samples across
the map matched the PNG within 0.02010 m; north–south orientation, biome import,
save and full-process reload were checked. The 4 m output grid interpolates
the approximately 30 m source DSM; it does not add measured terrain detail.

The native scenery phase accepted 817,613 selected items, with no skipped
build steps. One clipped ground polygon collapsed at native float precision
and was explicitly recorded as an omission. Model matching can leave source
objects unmatched; those objects are not silently replaced with arbitrary
models. Batches of 1,000 objects and automatic pause after exactly ten accepted
batches passed in the native game. Saved accepted XYZ evidence decoded in
native Lua after a complete restart.

The subsequent network phase exposed `StreetGeometry::InvalidTransition` at
source segment 8, a short rail continuation. Aligning new rail tangents with
accepted neighbouring rails passed that exact native failure and continued to
68 accepted segments. Source segment 69 then exposed a coastal DSM pixel at
approximately −1.47 m beneath an OSM E20 ground road. Native TF3 requires dry
terrain, so raising only the road node did not resolve `Place on Land`; that
insufficient candidate was removed. The panel now displays native warning/info
messages instead of an empty error. Heightmap Studio gained optional, explicitly
authored transport-corridor clearance, disabled for existing projects by default.

The full-profile refinement introduced a local road grade that TF3 rejected.
The follow-up clearance-only mode raises low terrain within the corridor and
preserves dry terrain at or above the clearance height. On the Partille coastal
test export, the specified 2 m clearance affected ground road/rail corridors
only; tagged bridges and tunnels were excluded. The maximum authored terrain
change was 22.36 m. Native import of the −3 to 169 m PNG and its biome map on
the 16,384 × 16,384 m world passed nine elevation checks within 0.01876 m.
Leaving the numeric field and waiting for the preview was necessary to apply
the requested native height range.

On that map, the first seven groups of ten network segments passed, including
the former E20 water failure at source 69. Six additional segments passed
individually. A group rejected by TF3 did not add partial geometry; reducing
the group and retrying preserved the 70 accepted segments. Source 77 (OSM
way 4040443) still fails alone with `Construction Not Possible` at a motorway
fork shared with source 60. The plan directions diverge by about 23 degrees;
the precise native restriction is not identified by that generic error. The
full 328,727-segment network is **not complete**. The importer now identifies
the rejected source range or single OSM way so the location can be inspected.

The driving test uses a separate extract from the same OSM download: 12 road
segments from bus 519 between Lexby and Lexby skola (442.68 m) and 85 track
segments from train 131 between Partille and Jonsered (4,354.54 m). OSM plan
coordinates, connectivity, and bridge/tunnel flags are unchanged. The raw DSM
produced up to 13.80% local rail grade and was rejected. The separate test
profile limits rail grades to 2%; its largest changed rail node is 2.57 m
from the sampled DSM. These are authored game elevations, not a survey. On
the coastal terrain, native TF3 built all 97 edges, with no skipped steps.
The live audit passed 99/99 nodes, 12/12 roads, 85/85 rails, 97/97 edges with
vehicle lanes and 2/2 connected groups. This verifies the imported network;
actual vehicle trips are checked separately.

The native train completed Partille–Jonsered–Partille and began another trip.
The test uses a vanilla diesel locomotive and passenger coach, native test
stations near the OSM endpoints, and a connected depot. The log recorded
145 vehicle samples, 139 moving samples, no path errors, and successive
departure events at Partille, Jonsered and Partille. The train and its line
were saved and continued moving after the save was reopened. The scenario
checks vehicle movement and station service; it does not simulate passenger
demand or claim an exact replica of the real stations.

All native testing uses separately named `MapStudio-Partille-*` saves, backed
up under `F:\project-backups\TF3-Map-Studio-Partille-20261105`. The user's
original dataset and saves were retained.

## Limits

This is broad regression, integration, packaging, ownership and native importer
testing, not an exhaustive claim for every map, mod or game build. The scope
of the real-map terrain and network checks is recorded above. Full large-map
network completion, general bridge/tunnel clearance, rendering/audio fidelity
and experimental water still require their documented scenario-specific
native checks. No personal provider credentials were used.
The release build manifest identifies the exact successful GitHub CI run and
reviewed source commit for the published binaries; local artifacts are not
silently substituted for CI artifacts.

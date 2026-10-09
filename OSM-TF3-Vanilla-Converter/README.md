# OSM-TF3-Vanilla-Converter

Preview 0.15 converts OpenStreetMap XML to a Transport Fever 3 importer dataset using vanilla resource references. The desktop app can download a selected OSM area, save its overview PNG, export a Lua map, update an installed importer mod, or create a standalone mod folder.

Large OSM downloads are fetched sequentially in smaller areas rather than one large server request. HTTP 504 and server XML resource-limit errors subdivide the affected area further. HTTP 429/502/503 receive one delayed retry, respecting a supported Retry-After value; cancellation remains available while waiting. Complete ways, nested relations and referenced nodes outside the selection are retained, shared objects are deduplicated on disk, and the saved bounds remain the exact selected frame. Conflicting objects or an incomplete part stop the download without replacing previous outputs. Limits of 64 completed areas and 128 requests prevent unbounded retries; a server that remains overloaded may still require a later retry or a regional .osm extract. The download log records successful area bounds and request count.

The `mod/tf3_osm_importer_mod` folder includes importer revision 8 and a fictional demonstration dataset. Its native panel has separate scrolling areas for progress/messages and commands. **Verify built objects** compares saved import records with live nodes, roads, rails and model groups without building anything. **Show place names** displays recorded marker names and coordinates; TF3 may remove model names when optimizing them into asset groups. The sample completed in TF3 Windows build 40408. Ground appearance, actual vehicle routes and large real-world imports still require testing.

Revision 5 checks large datasets in blocks of at most 1000 items and rejects prepared dimensions larger than the game map before scanning geometry. **Automatic pause** stops each run after a chosen number of successful build steps. New large datasets default to 100 steps; one step is one segment, one scenery batch or one marker. Save and inspect each run before resuming. Matching map dimensions alone do not establish heightmap alignment.

The importer keeps a one-centimetre inward margin at TF3's excluded positive map boundary. Checking, building and verification use the same margin without modifying the original dataset file or its geographic bounds.

No game assets are included. Read [README.txt](README.txt) for installation, settings, limitations, attribution and the Heightmap Studio handoff. [validation.json](validation.json) records the current checks and preserves earlier desktop validation with its original version.

The bundled revision 8 mod also includes road/rail height priority at construction time and an experimental local-water patch. These features run inside TF3; Heightmap Studio is unchanged. Preview 0.14 prepares mapped ponds and small waterways, preserving multipolygon islands, and the mod has an experimental 0.5 m bed plus Landscaping Water Dirty treatment. Missing widths use a configurable approximation. Lake geometry and raw heights are retained, but independent sea levels and lake flooding are unsupported. The shallow-water path has automated tests and awaits native validation; prior elevated model-water tests do not validate excavation. See [the water investigation](../TF3-OSM-Importer-Mod/WATER-RESEARCH.md).

Water source metadata is exported **even when small mapped waters are deselected**, incomplete or unsupported. Both the Lua dataset and its JSON report retain original OSM tags (including names, water types, width, depth, elevation and any supplied datum/source), geographic coordinates, ordered node references, relation members and their roles, including island boundaries and nested relations. Missing heights stay missing; source elevations are not converted into game heights. Untyped water areas are not assumed to be lakes, and dam/weir or point records are metadata only. Broken multipolygons do not import an outer boundary on its own.

Closed canal, river and stream centrelines remain width-based water corridors, including their closing join; their dry interiors are preserved. Only area tags select a filled water polygon. Conflicting water-area tags and `area=no` require review without excavation. Independently tagged inner meadow/farmland boundaries retain their own ground surfaces while remaining holes in the enclosing forest.

Exports stage both the Lua dataset and report before replacing existing files. If saving the report fails, the previous dataset is restored. If restoration also fails, the error gives the retained backup path so the previous dataset can be recovered; it is never deleted by temporary-file cleanup.

In Lua, `waterFeatures` contains the feature records and projected rings/centrelines. `waterMetadata` is a versioned source graph with `nodes`, `ways`, `relations`, `missingRefs` and coordinate conventions. Nodes retain named WGS84 `lat`/`lon` fields, their tags and projected `mapPos`; ways retain ordered `nodeRefs`; relations retain the original `members`. Each feature's `source` identifies its graph entry. The report retains the numeric `waterFeatures` count and includes the graph and feature records in `waterMetadata.features`. Shared members are stored once in the graph. Reconvert the original OSM/XML to obtain these fields in an older export; keep the dataset of an already-started game import unchanged.

## Run from source

Use Python 3.10 or later with Tk. Run these commands from this tool's folder:

```powershell
python -m pip install -r requirements.txt
python tools/gui.py
```

For command-line conversion:

```powershell
python tools/converter.py examples/sample.osm --output map.lua --size 1000 1000
```

The conversion core uses Python's standard library. Pillow supports the desktop map picker, downloaded tiles and overview PNGs. The Windows executable includes its dependencies.

## Test and build

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
powershell -File build.ps1
```

`build.ps1` creates `dist/OSM-TF3-Vanilla-Converter.exe` and bundles the mod template and third-party notices. To use another Python interpreter, pass `-Python` to the build script. Tests use Lupa to simulate Lua and TF3 callbacks; they do not replace an actual in-game import test.

The source is GPL-3.0. See [LICENSE](LICENSE), [NOTICE.txt](NOTICE.txt) and [Pillow's notices](third-party/Pillow-LICENSE.txt).

The mod is displayed in TF3 as **TF3-OSM-Importer-Mod** and new exports create `tf3_osm_importer_mod`. Its internal ID stays `druttzen_osm_vanilla` for existing saves. Update installed mod also accepts the older folder name.

## In-game selections, matching and towns

Preview 0.14 retains mapped building footprints, point objects, original tags/IDs and settlement types for the revision 8 importer. Its panel shows available counts and allows selection before drawing, with vanilla-first static-model matching and optional fallback to loaded active mods. Buildings are decorative substitutes fitted without scaling. Unsupported/unmatched categories are listed and left unbuilt.

City/town/village/hamlet names can instead create optional functioning towns using TF3's native preparation/commands. Disabling future town roads freezes all automatic town growth, including buildings; initial streets can still be created. These new engine features need physical TF3 validation. Read [the investigation](../TF3-OSM-Importer-Mod/TOWNS-OBJECTS-RESEARCH.md). Reconvert old XML for these fields on a new import; keep the original dataset of an already-started import.

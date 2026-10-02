# OSM-TF3-Vanilla-Converter

Preview 0.9 converts OpenStreetMap XML to a Transport Fever 3 importer dataset using vanilla resource references. The desktop app can download a selected OSM area, save its overview PNG, export a Lua map, update an installed importer mod, or create a standalone mod folder.

The `mod/druttzen_osm_vanilla` folder includes the importer and a fictional demonstration dataset. No game assets are included. Native TF3 import and panel rendering still need verification in the game. Read [README.txt](README.txt) for installation, settings, limitations, attribution and the Heightmap Studio handoff. [validation.json](validation.json) and [vanilla-resources.json](vanilla-resources.json) preserve the existing preview's validation records.

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

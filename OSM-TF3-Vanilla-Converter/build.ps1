param([string]$Python = 'python', [string]$DistPath = "$PSScriptRoot/dist")
$ErrorActionPreference = 'Stop'
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name OSM-TF3-Vanilla-Converter --distpath $DistPath --workpath "$PSScriptRoot/build" --specpath "$PSScriptRoot" --paths "$PSScriptRoot/tools" --add-data "$PSScriptRoot/mod/druttzen_osm_vanilla;mod_template" --add-data "$PSScriptRoot/third-party;third-party" "$PSScriptRoot/tools/gui.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }

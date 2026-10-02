param([string]$Python = 'python', [string]$DistPath = "$PSScriptRoot/dist")
$ErrorActionPreference = 'Stop'
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name TF3-Heightmap-Studio --distpath $DistPath --workpath "$PSScriptRoot/build" --specpath "$PSScriptRoot" --paths "$PSScriptRoot/tools" --paths "$PSScriptRoot/vendor" --collect-all rasterio --hidden-import scipy.ndimage --add-data "$PSScriptRoot/third-party;third-party" "$PSScriptRoot/tools/gui.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }

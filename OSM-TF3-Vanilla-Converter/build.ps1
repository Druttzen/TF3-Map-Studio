param([string]$Python = '', [string]$DistPath = "$PSScriptRoot/dist")
$ErrorActionPreference = 'Stop'
$PrivatePython = Join-Path $PSScriptRoot '.runtime/python.exe'
if (-not (Test-Path -LiteralPath $PrivatePython)) { throw 'Private Python is missing. Provision this tool with scripts/private_runtime.py; global Python is not used.' }
if ($Python -and [IO.Path]::GetFullPath($Python) -ne [IO.Path]::GetFullPath($PrivatePython)) { throw 'Use this app-owned .runtime/python.exe; external interpreters are not accepted.' }
$Python = $PrivatePython
$Runner = Join-Path $PSScriptRoot '../scripts/private_runtime.py'
$DistPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DistPath)
& $Python -I $Runner run --tool $PSScriptRoot -- -m PyInstaller --noconfirm --clean --onefile --windowed --name OSM-TF3-Vanilla-Converter --distpath $DistPath --workpath "$PSScriptRoot/build" --specpath "$PSScriptRoot" --paths "$PSScriptRoot/tools" --add-data "$PSScriptRoot/mod/tf3_osm_importer_mod;mod_template" --add-data "$PSScriptRoot/third-party;third-party" "$PSScriptRoot/tools/gui.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
$RuntimeReport = Join-Path $DistPath 'runtime-check.json'
$Executable = Join-Path $DistPath 'OSM-TF3-Vanilla-Converter.exe'
& $Python -I $Runner manifest --tool $PSScriptRoot --executable $Executable --report (Join-Path $DistPath 'dependency-manifest.json')
if ($LASTEXITCODE -ne 0) { throw 'Packaged dependency manifest failed.' }
& $Python -I $Runner check-executable --tool $PSScriptRoot --executable $Executable --report $RuntimeReport
if ($LASTEXITCODE -ne 0) { throw 'Packaged OSM runtime check failed.' }
if (-not (Test-Path -LiteralPath $RuntimeReport)) { throw 'Packaged OSM runtime check did not produce a report.' }
$RuntimeResult = Get-Content -LiteralPath $RuntimeReport -Raw | ConvertFrom-Json
if ($RuntimeResult.ok -ne $true) {
    throw "Packaged OSM runtime check failed: $($RuntimeResult.error)"
}
Write-Host "Packaged OSM runtime check passed: $RuntimeReport"

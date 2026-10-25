param([string]$Python = 'python', [string]$DistPath = "$PSScriptRoot/dist")
$ErrorActionPreference = 'Stop'
$DistPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DistPath)
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name OSM-TF3-Vanilla-Converter --distpath $DistPath --workpath "$PSScriptRoot/build" --specpath "$PSScriptRoot" --paths "$PSScriptRoot/tools" --add-data "$PSScriptRoot/mod/tf3_osm_importer_mod;mod_template" --add-data "$PSScriptRoot/third-party;third-party" "$PSScriptRoot/tools/gui.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
$RuntimeReport = Join-Path $DistPath 'runtime-check.json'
if (Test-Path -LiteralPath $RuntimeReport) { Remove-Item -LiteralPath $RuntimeReport }
$Executable = Join-Path $DistPath 'OSM-TF3-Vanilla-Converter.exe'
$CheckProcess = Start-Process -FilePath $Executable -ArgumentList @('--self-check', ('"{0}"' -f $RuntimeReport)) -PassThru -WindowStyle Hidden
if (-not $CheckProcess.WaitForExit(60000)) {
    & "$env:SystemRoot/System32/taskkill.exe" /PID $CheckProcess.Id /T /F | Out-Null
    throw 'Packaged OSM runtime check timed out; this executable is not ready for release.'
}
if (-not (Test-Path -LiteralPath $RuntimeReport)) { throw 'Packaged OSM runtime check did not produce a report.' }
$RuntimeResult = Get-Content -LiteralPath $RuntimeReport -Raw | ConvertFrom-Json
if ($CheckProcess.ExitCode -ne 0 -or $RuntimeResult.ok -ne $true) {
    throw "Packaged OSM runtime check failed: $($RuntimeResult.error)"
}
Write-Host "Packaged OSM runtime check passed: $RuntimeReport"

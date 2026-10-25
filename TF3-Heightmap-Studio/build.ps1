param([string]$Python = '', [string]$DistPath = "$PSScriptRoot/dist")
$ErrorActionPreference = 'Stop'
$DistPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($DistPath)
if (-not $Python) {
    $ProjectPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $Python = if (Test-Path -LiteralPath $ProjectPython) { $ProjectPython } else { 'python' }
}
& $Python "$PSScriptRoot/tools/build_check.py"
if ($LASTEXITCODE -ne 0) {
    throw "Build dependencies are incomplete. Run: & '$Python' -m pip install -r '$PSScriptRoot/requirements-dev.txt'"
}
& $Python -m PyInstaller --noconfirm --clean --onefile --windowed --name TF3-Heightmap-Studio --distpath $DistPath --workpath "$PSScriptRoot/build" --specpath "$PSScriptRoot" --paths "$PSScriptRoot/tools" --paths "$PSScriptRoot/vendor" --collect-all certifi --collect-all rasterio --collect-all pyproj --collect-all ijson --hidden-import lazrs --hidden-import scipy.ndimage --add-data "$PSScriptRoot/third-party;third-party" "$PSScriptRoot/tools/gui.py"
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
$RuntimeReport = Join-Path $DistPath 'runtime-check.json'
if (Test-Path -LiteralPath $RuntimeReport) { Remove-Item -LiteralPath $RuntimeReport }
$Executable = Join-Path $DistPath 'TF3-Heightmap-Studio.exe'
$CheckProcess = Start-Process -FilePath $Executable -ArgumentList @('--self-check', ('"{0}"' -f $RuntimeReport)) -PassThru -WindowStyle Hidden
if (-not $CheckProcess.WaitForExit(60000)) {
    & "$env:SystemRoot/System32/taskkill.exe" /PID $CheckProcess.Id /T /F | Out-Null
    throw 'Packaged runtime check timed out; this executable is not ready for release.'
}
if (-not (Test-Path -LiteralPath $RuntimeReport)) { throw 'Packaged runtime check did not produce a report.' }
$RuntimeResult = Get-Content -LiteralPath $RuntimeReport -Raw | ConvertFrom-Json
if ($CheckProcess.ExitCode -ne 0 -or $RuntimeResult.ok -ne $true) {
    throw "Packaged runtime check failed: $($RuntimeResult.error)"
}
Write-Host "Packaged runtime check passed: $RuntimeReport"

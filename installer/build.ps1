param(
    [string]$Output = "$PSScriptRoot/../outputs/windows-installer",
    [string]$AppDist = 'dist-installer',
    [switch]$UseBuiltApps
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path "$PSScriptRoot/..").Path
$Output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
$Toolchain = "$Repo/work/setup-toolchain"
$Compiler = "$Toolchain/Inno/ISCC.exe"
$CompilerVersion = '6.7.4'
$CompilerUrl = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe'
$CompilerHash = 'a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c'
$Converter = "$Repo/OSM-TF3-Vanilla-Converter"
$Importer = "$Repo/TF3-OSM-Importer-Mod"
$Runner = "$Repo/scripts/private_runtime.py"
$Stage = "$PSScriptRoot/build/$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $Stage, "$Toolchain/temp", $Output -Force | Out-Null

if (!(Test-Path -LiteralPath $Compiler)) {
    $Bootstrap = "$Toolchain/innosetup-$CompilerVersion.exe"
    Invoke-WebRequest $CompilerUrl -OutFile $Bootstrap
    if ((Get-FileHash -LiteralPath $Bootstrap).Hash -ne $CompilerHash) {
        throw 'Inno Setup bootstrap checksum mismatch.'
    }
    $OldTemp = $env:TEMP
    $OldTmp = $env:TMP
    try {
        $env:TEMP = "$Toolchain/temp"
        $env:TMP = $env:TEMP
        $Process = Start-Process -FilePath $Bootstrap -ArgumentList @(
            '/CURRENTUSER', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/PORTABLE=1', ('/DIR="{0}/Inno"' -f $Toolchain)
        ) -WindowStyle Hidden -Wait -PassThru
        if ($Process.ExitCode -ne 0) { throw "Inno Setup provisioning failed: $($Process.ExitCode)" }
    }
    finally {
        $env:TEMP = $OldTemp
        $env:TMP = $OldTmp
    }
}
if ((Get-FileHash -LiteralPath $Compiler).Hash -ne 'f02fa0e5f237b47d7ed1edae9b991866ec94fe02af61eb6a73e94f92fe8e0604' -or
    (Get-FileHash -LiteralPath "$Toolchain/Inno/ISCmplr.dll").Hash -ne '236555054ca65194c69544b4ef1d49ea345259745f5c4a2005aca7b5674e7cff') {
    throw "Use Inno Setup $CompilerVersion in $Toolchain/Inno."
}

foreach ($Tool in @('OSM-TF3-Vanilla-Converter', 'TF3-Heightmap-Studio')) {
    $ToolRoot = "$Repo/$Tool"
    $Dist = "$ToolRoot/$AppDist"
    if (!$UseBuiltApps) { & "$ToolRoot/build.ps1" -DistPath $Dist }
    $Manifest = Get-Content -LiteralPath "$Dist/dependency-manifest.json" -Raw | ConvertFrom-Json
    $Check = Get-Content -LiteralPath "$Dist/runtime-check.json" -Raw | ConvertFrom-Json
    if ($Manifest.application -ne $Tool -or $Check.ok -ne $true -or
        (Get-FileHash -LiteralPath "$Dist/$Tool.exe").Hash -ne $Manifest.executableSha256) {
        throw "Invalid standalone build for $Tool."
    }
    New-Item -ItemType Directory -Path "$Stage/$Tool" | Out-Null
    foreach ($File in @("$Dist/$Tool.exe", "$Dist/dependency-manifest.json", "$ToolRoot/LICENSE", "$ToolRoot/NOTICE.txt")) {
        Copy-Item -LiteralPath $File -Destination "$Stage/$Tool"
    }
}

# The setup-only helper bundles its own interpreter. Installed apps never call it.
$Python = "$Converter/.runtime/python.exe"
$HelperArgs = @(
    '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed', '--name', 'setup-game',
    '--distpath', $Stage, '--workpath', "$Stage/helper-build", '--specpath', $Stage,
    '--paths', "$Repo/TF3-Heightmap-Studio/tools", "$PSScriptRoot/setup_game.py"
)
& $Python -I $Runner run --tool $Converter -- @HelperArgs
if ($LASTEXITCODE -ne 0) { throw 'Setup helper build failed.' }
& "$Importer/.runtime/python.exe" -I $Runner run --tool $Importer -- "$Importer/scripts/package_mod.py" --output "$Stage/importer.zip"
if ($LASTEXITCODE -ne 0) { throw 'Importer packaging failed.' }
& $Compiler "/DPayload=$Stage" "/O$Output" "$PSScriptRoot/TF3-Map-Studio.iss"
if ($LASTEXITCODE -ne 0) { throw 'Windows installer build failed.' }

$Installer = "$Output/TF3-Map-Studio-Setup.exe"
$HelperVersion = & $Python -I -V
[ordered]@{
    installerSha256 = (Get-FileHash -LiteralPath $Installer).Hash.ToLowerInvariant()
    innoSetup = @{ version = $CompilerVersion; source = $CompilerUrl; sha256 = $CompilerHash }
    setupHelper = @{ python = $HelperVersion; source = 'OSM converter private build interpreter'; ownership = 'Private embedded copy used only during setup' }
    applications = @(foreach ($Tool in @('OSM-TF3-Vanilla-Converter', 'TF3-Heightmap-Studio')) {
        Get-Content -LiteralPath "$Stage/$Tool/dependency-manifest.json" -Raw | ConvertFrom-Json
    })
    importer = Get-Content -LiteralPath "$Importer/mod/tf3_osm_importer_mod/mod.json" -Raw | ConvertFrom-Json
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$Output/TF3-Map-Studio-Setup-manifest.json" -Encoding utf8

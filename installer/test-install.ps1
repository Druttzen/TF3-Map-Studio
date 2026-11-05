param([string]$Installer = "$PSScriptRoot/../outputs/windows-installer/TF3-Map-Studio-Setup.exe")
$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$StateKey = 'HKCU:/Software/TF3 Map Studio'
$UninstallKey = 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/Druttzen.TF3MapStudio_is1'
if ((Test-Path "$StateKey/Heightmap Studio") -or (Test-Path "$StateKey/OSM Converter") -or (Test-Path $UninstallKey)) {
    throw 'Run the installer smoke test under a Windows account without an existing TF3 Map Studio setup.'
}
$TestRoot = Join-Path (Resolve-Path "$PSScriptRoot/..").Path "work/setup-smoke/$([guid]::NewGuid())"
$Game = "$TestRoot/Game/Transport Fever 3"
$Profile = "$TestRoot/Profil Åland"
$Apps = "$TestRoot/Applications"
$Mod = "$Profile/mods/tf3_osm_importer_mod"
$Dataset = "$Mod/content/osm/dataset.lua"
$Map = "$Mod/content/osm/maps/my-map.lua"
$OldTemp = $env:TEMP
$OldTmp = $env:TMP
New-Item -ItemType Directory -Path "$Game/base/content", $Profile, "$TestRoot/temp" -Force | Out-Null
New-Item -ItemType File -Path "$Game/TransportFever3.exe", "$Profile/settings.lua" | Out-Null

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    $Process = Start-Process -FilePath $Program -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "$Program returned $($Process.ExitCode). See $TestRoot for test logs."
    }
}

$Quiet = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
$InstallArgs = $Quiet + @(
    ('/DIR="{0}"' -f $Apps), ('/TF3GAME="{0}"' -f $Game),
    ('/TF3USER="{0}"' -f $Profile)
)
try {
    $env:TEMP = "$TestRoot/temp"
    $env:TMP = $env:TEMP
    Invoke-Checked $Installer ($InstallArgs + ('/LOG="{0}/install.log"' -f $TestRoot))
    $Heightmap = Get-ItemProperty "$StateKey/Heightmap Studio"
    $Converter = Get-ItemProperty "$StateKey/OSM Converter"
    if ($Heightmap.Installation -ne [IO.Path]::GetFullPath($Game) -or
        $Heightmap.UserData -ne [IO.Path]::GetFullPath($Profile) -or
        $Heightmap.Importer -ne [IO.Path]::GetFullPath($Mod) -or
        $Converter.Importer -ne $Heightmap.Importer -or !(Test-Path -LiteralPath $Dataset)) {
        throw 'The apps did not receive the selected TF3 folders and importer.'
    }
    foreach ($Tool in @('OSM-TF3-Vanilla-Converter', 'TF3-Heightmap-Studio')) {
        $Report = "$TestRoot/$Tool-runtime.json"
        Invoke-Checked "$Apps/$Tool/$Tool.exe" @('--self-check', ('"{0}"' -f $Report))
        $Runtime = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
        if ($Runtime.ok -ne $true) { throw "Installed $Tool failed its runtime check." }
        if ($Tool -eq 'TF3-Heightmap-Studio' -and
            (!$Runtime.tf3RegistryDiscovery.installationFound -or !$Runtime.tf3RegistryDiscovery.userFolderSelected)) {
            throw 'Installed Heightmap Studio did not load its TF3 paths.'
        }
    }
    New-Item -ItemType Directory -Path (Split-Path $Map) -Force | Out-Null
    Set-Content -LiteralPath $Map -Value 'custom map'
    Set-Content -LiteralPath $Dataset -Value 'custom dataset'
    Invoke-Checked $Installer ($InstallArgs + ('/LOG="{0}/repair.log"' -f $TestRoot))
    if ((Get-Content -LiteralPath $Dataset) -ne 'custom dataset') { throw 'Repair replaced a custom dataset.' }
    Invoke-Checked "$Apps/unins000.exe" ($Quiet + ('/LOG="{0}/uninstall.log"' -f $TestRoot))
    if ((Get-Content -LiteralPath $Map) -ne 'custom map' -or
        (Get-Content -LiteralPath $Dataset) -ne 'custom dataset' -or (Test-Path $UninstallKey) -or
        (Test-Path "$StateKey/Heightmap Studio") -or (Test-Path "$StateKey/OSM Converter") -or
        (Test-Path "$Apps/OSM-TF3-Vanilla-Converter/OSM-TF3-Vanilla-Converter.exe") -or
        (Test-Path "$Apps/TF3-Heightmap-Studio/TF3-Heightmap-Studio.exe")) {
        throw 'Uninstall did not remove both apps and preserve game-side files.'
    }
    Invoke-Checked $Installer ($InstallArgs + '/NOIMPORTER=1' + ('/LOG="{0}/apps-only.log"' -f $TestRoot))
    if ((Get-ItemProperty "$StateKey/OSM Converter").Importer -or
        (Get-ItemProperty "$StateKey/Heightmap Studio").UserData) {
        throw 'The apps-only install configured a TF3 profile.'
    }
    Invoke-Checked "$Apps/unins000.exe" ($Quiet + ('/LOG="{0}/uninstall-apps-only.log"' -f $TestRoot))
    Write-Host "Windows installer smoke test passed. Logs: $TestRoot"
}
catch {
    Get-ChildItem -LiteralPath $TestRoot -Filter '*.log' | ForEach-Object {
        Write-Host "----- $($_.Name) -----"
        Get-Content -LiteralPath $_.FullName -Tail 45 | Write-Host
    }
    throw
}
finally {
    $env:TEMP = $OldTemp
    $env:TMP = $OldTmp
}

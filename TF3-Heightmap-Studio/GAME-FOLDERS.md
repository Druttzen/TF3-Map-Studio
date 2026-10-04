# Automatic TF3 folders

Preview 0.9 selects the native export destination when Heightmap Studio opens.
On Windows it reads the TF3 `InstallLocation` in
`SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 3493540`,
checking both 32-bit and 64-bit registry views. It reads Steam's `SteamPath` /
`InstallPath` separately because the game and Steam userdata can be on different
drives. Registry access uses read-only handles; no keys are created or edited.

The installation must contain `TransportFever3.exe` and `base/content`.
If the game registry entry is stale or absent, Steam library paths and the
TF3 app manifest provide a checked fallback. Manifest app IDs and installation
names are validated; an unrelated game's folder is not selected.

The Steam `ActiveProcess/ActiveUser` registry value identifies the current
account when available. Otherwise the only existing TF3 profile is used.
If multiple profiles remain unidentified, **Choose TF3 user folder** makes
the selection explicit. No profile is chosen by folder timestamps or guessed
from the TF3 installation drive. Discovery does not create directories.
Known active accounts can receive a new TF3 local folder on export.

The app shows the selected installation, heightmap and biome directories.
The suggested PNG name follows the OSM/report map name and adds a numeric suffix
when matching heightmaps, biomes or companion exports already exist.
**Find TF3 folders** refreshes detection and restores the native destination.
**Browse** retains a manually chosen PNG destination. Loaded projects keep their
saved path; a saved TF3 profile can be selected again without moving its export
to another profile.

## Export placement

For a chosen TF3 userdata destination:

| File | Destination relative to TF3 `local` userdata |
| --- | --- |
| 16-bit grayscale heightmap PNG | `heightmaps/<map>.png` |
| Optional grayscale biome PNG | `biomes/<map>.biomes.png` |
| GeoTIFF, previews, report, project, attribution, import instructions | `heightmap_studio/<map>/` |

Only native import PNGs are placed in the game's map/biome pickers. The report
records all paths and how the installation/profile were selected. Import
instructions explain that native PNGs have already been placed in the game
folders. Export does not open the game, apply terrain, change saves or alter
installation resources. Original input files cannot be overwritten by export.

Export stages and verifies all files before replacing outputs. If a write fails,
previous exports across the heightmap, biome and companion folders are restored.
If restoration itself fails, the backup files are retained and their location is
reported. Cancellation during preparation keeps existing export files.

Normal manually selected export directories retain the original single-folder
layout. Non-Steam installations can select their known userdata folder manually
(the folder containing `settings.lua`). Their registry discovery is not claimed.

The command-line app supports `--to-tf3` instead of `--output`. It requires an
identified current/unique TF3 user folder. For multiple profiles, select the
folder in the app or supply `--output` inside a known TF3 `heightmaps` folder.

## Verification and primary references

Registry discovery was checked on this installed Windows system: the TF3
installation is on B:, while Steam userdata is on C:. Startup filled the correct
heightmap destination. Source and frozen-runtime probes test native export in
fictional temporary directories, including biome separation, saved projects
and source protection. Failure tests verify restoration across output folders
and retained backups when recovery also fails. The tests do not replace a game
save or export synthetic probe maps into the user's real game folders.

- [TF3 game file locations](https://wiki.transportfever3.com/doku.php?id=gamemanual:installation:gamefilelocations)
  defines Steam userdata `3493540/local`, `heightmaps`, and `biomes`.
- [TF3 map editor](https://wiki.transportfever3.com/doku.php?id=gamemanual:gamemodes:mapeditor)
  reads native grayscale import files from those respective folders.
- [Steam install script registry handling](https://partner.steamgames.com/doc/sdk/installscripts)
  documents registry virtualization and the separate Windows registry views.

Actual terrain/biome application in a running TF3 game remains unverified.

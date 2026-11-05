"""Game discovery and importer installation for the Windows setup wizard."""
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'TF3-Heightmap-Studio/tools'))
from game_paths import APP_ID, detect, select_user_folder, valid_installation


MOD_ID = 'druttzen_osm_vanilla'
MOD_FOLDER = 'tf3_osm_importer_mod'


def is_importer(folder):
    try:
        definition = folder / 'mod.json'
        if definition.stat().st_size <= 65536:
            data = json.loads(definition.read_text(encoding='utf-8-sig'))
            return isinstance(data, dict) and data.get('modId') == MOD_ID
    except (OSError, ValueError):
        pass
    return False


def install_importer(local, archive):
    mods = local / 'mods'
    mods.mkdir(exist_ok=True)
    if mods.resolve() != mods:
        raise ValueError('The mods folder points outside the selected TF3 user folder.')
    target = mods / MOD_FOLDER
    copies = [folder for folder in mods.iterdir() if folder.is_dir() and is_importer(folder)]
    if len(copies) > 1:
        raise ValueError('Several OSM Importer mods are installed in this profile. Keep one copy, then retry.')
    if copies:
        if copies[0].resolve().parent != mods:
            raise ValueError('The existing importer points outside the selected mods folder.')
        return copies[0]
    if target.exists() or target.is_symlink():
        raise ValueError(f'The importer folder already exists with different contents: {target}')

    # Stage outside mods so TF3 never sees a partially extracted mod.
    with TemporaryDirectory(prefix='.tf3-map-studio-', dir=local) as temporary:
        stage = Path(temporary) / MOD_FOLDER
        with ZipFile(archive) as package:
            package.extractall(temporary)
        if not is_importer(stage) or not (stage / 'content/osm/dataset.lua').is_file():
            raise ValueError('The bundled importer mod is incomplete.')
        # On Windows rename fails if another installer has already created target.
        stage.rename(target)
    return target


def selected_paths(game_value, profile_value, app_value, archive):
    app = Path(app_value).resolve()
    game = Path(game_value).resolve() if game_value else None
    if game and not valid_installation(game):
        raise ValueError('Select the folder containing TransportFever3.exe and base/content, or leave it blank.')
    if profile_value and not game:
        raise ValueError('Select the Transport Fever 3 installation before choosing a user folder.')
    local = select_user_folder(profile_value).local if profile_value else None
    if local and local.name.lower() == 'local' and local.parent.parent.parent.name.lower() == 'userdata':
        if local.parent.name != APP_ID:
            raise ValueError('This Steam user folder belongs to a different game. Choose the TF3 folder for app 3493540.')
    for folder in (game, local):
        if folder and (app.is_relative_to(folder) or folder.is_relative_to(app)):
            raise ValueError('Select an app installation folder separate from the game and its user folder.')
    importer = install_importer(local, archive) if local else None
    return game, local, importer


def main():
    mode, result_file, *args = sys.argv[1:]
    try:
        if mode == 'detect':
            paths = detect(configured=False)
            profile = paths.local if paths.local and paths.local.is_dir() else None
            values = [paths.installation, profile, *paths.profiles]
        elif mode == 'install':
            selection, archive = map(Path, args)
            values = selected_paths(*selection.read_text(encoding='utf-8-sig').split('\n')[:3], archive)
        else:
            raise ValueError('Unknown setup operation.')
        Path(result_file).write_text('OK\n' + ''.join(f'{value or ""}\n' for value in values), encoding='utf-8-sig')
    except (OSError, ValueError, TypeError, BadZipFile) as exc:
        Path(result_file).write_text(f'ERROR\n{exc}\n', encoding='utf-8-sig')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

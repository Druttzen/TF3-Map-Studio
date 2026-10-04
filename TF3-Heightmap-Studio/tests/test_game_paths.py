"""Installed-game discovery and transactional export to native user folders."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_terrain import source
import game_paths
from game_paths import GamePaths, detect, suggested_output, export_destination
from terrain import prepare, export, load_project


def installation(path):
    (path/'base/content').mkdir(parents=True)
    (path/'TransportFever3.exe').write_bytes(b'test fixture')
    return path


def profile(steam, user):
    local=steam/'userdata'/str(user)/game_paths.APP_ID/'local'
    local.mkdir(parents=True)
    return local


def test_tf3_install_registry_and_separate_steam_user_folder(tmp_path):
    steam=tmp_path/'Steam on C';steam.mkdir()
    local=profile(steam,12)
    game=installation(tmp_path/'Game on B')
    with patch('game_paths.registry_locations',return_value=([(game,'TF3 install registry')],[steam],'')):
        result=detect()
    assert result.installation==game and result.local==local
    assert result.heightmaps==local/'heightmaps' and result.biomes==local/'biomes'
    assert not result.heightmaps.exists()  # Discovery never changes game folders.


def test_active_steam_account_wins_over_other_game_profiles(tmp_path):
    steam=tmp_path/'Steam';steam.mkdir();profile(steam,12);current=profile(steam,34)
    game=installation(tmp_path/'Game')
    with patch('game_paths.registry_locations',return_value=([(game,'registry')],[steam],'34')):
        result=detect()
    assert result.local==current
    assert result.profile_source=='Active Steam account registry'


def test_known_active_account_without_game_profile_is_not_replaced_by_old_account(tmp_path):
    steam=tmp_path/'Steam';steam.mkdir();old=profile(steam,12)
    game=installation(tmp_path/'Game')
    with patch('game_paths.registry_locations',return_value=([(game,'registry')],[steam],'34')):
        result=detect()
    assert result.local==steam/'userdata/34/3493540/local'
    assert not result.local.exists() and old.exists()


def test_multiple_profiles_without_active_account_require_selection(tmp_path):
    steam=tmp_path/'Steam';steam.mkdir();profile(steam,12);profile(steam,34)
    game=installation(tmp_path/'Game')
    with patch('game_paths.registry_locations',return_value=([(game,'registry')],[steam],'')):
        result=detect()
    assert result.local is None and len(result.profiles)==2
    assert suggested_output(result)==''


def test_stale_registry_uses_actual_library_and_manifest(tmp_path):
    steam=tmp_path/'Steam';(steam/'steamapps').mkdir(parents=True)
    library=tmp_path/'Second library'
    game=installation(library/'steamapps/common/TF3 custom name')
    text=str(library).replace('\\','\\\\')
    (steam/'steamapps/libraryfolders.vdf').write_text('"libraryfolders" { "1" { "path" "'+text+'" } }')
    (library/'steamapps/appmanifest_3493540.acf').write_text('"AppState" { "appid" "3493540" "installdir" "TF3 custom name" }')
    local=profile(steam,12)
    with patch('game_paths.registry_locations',return_value=([(tmp_path/'removed game','stale registry')],[steam],'')):
        result=detect()
    assert result.installation==game and result.local==local
    assert result.installation_source=='Steam TF3 app manifest'


@pytest.mark.parametrize('appid,name',[('1066780','Other game'),('3493540','../../Other game'),('3493540','C:\\Other game')])
def test_wrong_or_escaping_manifest_is_not_used(tmp_path,appid,name):
    steam=tmp_path/'Steam';(steam/'steamapps').mkdir(parents=True)
    installation(tmp_path/'Other game');profile(steam,12)
    (steam/'steamapps/appmanifest_3493540.acf').write_text(f'"appid" "{appid}" "installdir" "{name}"')
    with patch('game_paths.registry_locations',return_value=([],[steam],'')):
        result=detect()
    assert result.installation is None and result.local is None


def test_both_registry_views_are_read_without_writing(tmp_path):
    calls=[]
    class Handle:
        def __init__(self,key):self.key=key
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def open_key(hive,key,reserved,access):
        calls.append((hive,key,access));return Handle((hive,key,access))
    def query(handle,name):
        hive,key,access=handle.key
        if key==game_paths.UNINSTALL_KEY and access&0x200:return str(tmp_path/'32-bit install'),'string'
        if key==r'Software\Valve\Steam' and name=='SteamPath':return str(tmp_path/'Steam'),'string'
        if name=='ActiveUser':return 34,'dword'
        raise OSError('Missing registry value')
    fake=SimpleNamespace(HKEY_LOCAL_MACHINE='machine',HKEY_CURRENT_USER='user',KEY_READ=1,
                         KEY_WOW64_64KEY=0x100,KEY_WOW64_32KEY=0x200,OpenKey=open_key,QueryValueEx=query)
    with patch.dict(sys.modules,winreg=fake):games,roots,active=game_paths.registry_locations()
    assert any(path==tmp_path/'32-bit install' for path,label in games)
    assert active=='34' and tmp_path/'Steam' in roots
    assert any(access&0x100 for _,_,access in calls) and any(access&0x200 for _,_,access in calls)


def test_default_filename_uses_osm_name_and_keeps_existing_heightmaps(tmp_path):
    local=tmp_path/'local';(local/'heightmaps').mkdir(parents=True)
    original=local/'heightmaps/partille_test.png';original.write_bytes(b'existing map')
    paths=GamePaths(local=local)
    assert Path(suggested_output(paths,'partille_test.osm')).name=='partille_test-2.png'
    assert Path(suggested_output(paths,'partille_test.report.json')).name=='partille_test-2.png'
    assert original.read_bytes()==b'existing map'
    assert Path(suggested_output(paths,'CON.osm')).name=='map_CON.png'


@pytest.mark.parametrize('existing',['biomes/partille.biomes.png','heightmap_studio/partille/partille.report.json'])
def test_default_filename_preserves_biome_and_companion_exports_without_heightmap(tmp_path,existing):
    local=tmp_path/'local';file=local/existing;file.parent.mkdir(parents=True);file.write_bytes(b'existing export')
    assert Path(suggested_output(GamePaths(local=local),'partille.osm')).name=='partille-2.png'
    assert file.read_bytes()==b'existing export'


def test_native_export_routes_only_import_pngs_to_game_folders(source,tmp_path):
    local=profile(tmp_path/'Steam',12);paths=GamePaths(local=local)
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True})
    output=local/'heightmaps/partille_test.png'
    report=export(result,output,game_paths=paths)
    assert list((local/'heightmaps').iterdir())==[output]
    assert list((local/'biomes').iterdir())==[local/'biomes/partille_test.biomes.png']
    details=local/'heightmap_studio/partille_test'
    for key,path in report['files'].items():
        assert Path(path).is_file()
        if key not in {'png','biomes'}:assert Path(path).parent==details
    project=load_project(report['files']['project'])
    assert project['output']==str(output)
    assert report['gameExport']['nativeFolders']
    instructions=Path(report['files']['instructions']).read_text(encoding='utf-8')
    assert 'already exported into the TF3 heightmaps' in instructions
    assert 'already exported into TF3' in instructions
    assert 'Copy the PNG' not in instructions and 'Copy the biome PNG' not in instructions


def test_manual_export_folder_keeps_existing_layout(source,tmp_path):
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True})
    output=tmp_path/'chosen/manual.png'
    report=export(result,output,game_paths=GamePaths(local=tmp_path/'game local'))
    assert not report['gameExport']['nativeFolders']
    assert all(Path(path).parent==output.parent for path in report['files'].values())


def test_existing_profile_export_can_be_selected_without_active_profile_redirect(tmp_path):
    old=profile(tmp_path/'Steam',12);current=profile(tmp_path/'Steam',34)
    layout=export_destination(old/'heightmaps/test.png',GamePaths(local=current,profiles=(old,current)))
    assert layout['native'] and layout['biomes']==old/'biomes'
    assert layout['location']['userData']==str(old)


def test_native_export_failure_restores_all_folders(source,tmp_path):
    local=profile(tmp_path/'Steam',12);paths=GamePaths(local=local)
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True})
    output=local/'heightmaps/test.png';report=export(result,output,game_paths=paths)
    before={path:Path(path).read_bytes() for path in report['files'].values()}
    from terrain import os
    replace=os.replace;failed=False
    def fail(src,dst):
        nonlocal failed
        if Path(dst).parent==local/'biomes' and not failed:
            failed=True;raise OSError('Simulated failure writing biome folder')
        return replace(src,dst)
    with patch('terrain.os.replace',side_effect=fail),pytest.raises(OSError):
        export(result,output,game_paths=paths)
    assert all(Path(path).read_bytes()==value for path,value in before.items())
    assert not list((local/'heightmaps').glob('.tf3-heightmap-export-*'))


def test_native_export_preserves_original_backups_when_recovery_fails(source,tmp_path):
    local=profile(tmp_path/'Steam',12);paths=GamePaths(local=local)
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True})
    output=local/'heightmaps/test.png';report=export(result,output,game_paths=paths)
    before=output.read_bytes()
    from terrain import os
    replace=os.replace
    def fail(src,dst):
        if Path(dst).parent==local/'biomes' or Path(src).name=='backup-test.png':
            raise OSError('Simulated write/recovery failure')
        return replace(src,dst)
    with patch('terrain.os.replace',side_effect=fail),pytest.raises(OSError,match='backup files are retained'):
        export(result,output,game_paths=paths)
    staging=list((local/'heightmaps').glob('.tf3-heightmap-export-*'))
    assert len(staging)==1 and (staging[0]/'backup-test.png').read_bytes()==before


def test_native_export_cannot_replace_its_input_dem(source,tmp_path):
    local=profile(tmp_path/'Steam',12);paths=GamePaths(local=local)
    result=prepare(source['report'],source['xml'],[source['dem']])
    output=local/'heightmaps/test.png';report=export(result,output,game_paths=paths)
    result=prepare(source['report'],source['xml'],[report['files']['dem']])
    with pytest.raises(ValueError,match='source elevation'):
        export(result,output,game_paths=paths)


def test_native_export_protects_input_reached_through_linked_biome_folder(source,tmp_path):
    local=profile(tmp_path/'Steam',12);paths=GamePaths(local=local)
    actual=tmp_path/'actual-biome-data';actual.mkdir()
    try:(local/'biomes').symlink_to(actual,target_is_directory=True)
    except OSError:pytest.skip('Creating directory links is unavailable for this account')
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True})
    report=export(result,local/'heightmaps/test.png',game_paths=paths)
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True,'biome_mode':'Import biome PNG','biome_source':report['files']['biomes']})
    with pytest.raises(ValueError,match='source elevation'):
        export(result,local/'heightmaps/test.png',game_paths=paths)


def test_selected_user_folder_must_be_a_known_tf3_folder(tmp_path):
    unknown=tmp_path/'unrelated';unknown.mkdir()
    with pytest.raises(ValueError,match='TF3 local user folder'):
        game_paths.select_user_folder(unknown)
    local=profile(tmp_path/'Steam',12)
    assert game_paths.select_user_folder(local).local==local


def test_cli_exports_to_detected_game_profile(source,tmp_path):
    result=prepare(source['report'],source['xml'],[source['dem']],{'biomes':True})
    project=export(result,tmp_path/'project/map.png')['files']['project']
    local=profile(tmp_path/'Steam',12)
    import cli
    with patch('cli.detect',return_value=GamePaths(local=local)),patch.object(sys,'argv',['cli.py',project,'--to-tf3']):
        cli.main()
    assert (local/'heightmaps/demo.png').is_file()
    assert (local/'biomes/demo.biomes.png').is_file()
    assert (local/'heightmap_studio/demo/demo.heightmap-project.json').is_file()

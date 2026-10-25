"""Result identity, background searches and secret-free project preferences."""
import json,queue,sys,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from gui import App
from height_settings import normalize

class Var:
 def __init__(self,value=''):self.value=value
 def get(self):return self.value
 def set(self,value):self.value=value


def result_app():
 return SimpleNamespace(discovery_generation=2,discovery_running=True,stop_search_button=Mock(),lidar_rows=[{'name':'current'}],lidar_list=Mock(),lidar_info=Var(),busy=False,show=Mock())


def test_stale_background_results_do_not_replace_current_map():
 app=result_app()
 App.handle_discovery(app,'discovery_result',(1,{'rows':[{'name':'old'}]}))
 assert app.lidar_rows==[{'name':'current'}]
 app.lidar_list.delete.assert_not_called()


def test_local_partial_result_keeps_online_search_running():
 app=result_app();row={'name':'local','path':'file.tif','access':'local','coverage':'overlap'}
 App.handle_discovery(app,'discovery_partial',(2,{'rows':[row],'warnings':[],'details':['headers checked'],'bounds':[0,0,1,1]}))
 assert app.discovery_running and app.lidar_rows==[row]
 app.stop_search_button.configure.assert_not_called()


def test_map_changes_clear_stale_rows_even_with_auto_search_off():
 app=result_app();app.loading=False;app.auto_lidar=Var(False);app.discovery_timer=None;app.stop_lidar_search=Mock()
 App.schedule_lidar_search(app)
 assert app.lidar_rows==[]
 app.lidar_list.delete.assert_called_once_with(0,'end')
 app.stop_lidar_search.assert_called_once()


def test_folder_and_online_searches_do_not_block_or_mark_terrain_busy(tmp_path):
 app=SimpleNamespace(loading=False,busy=False,report_path=Var('report.json'),osm_path=Var(),local_folder=Var(str(tmp_path)),values={'public_max_tiles':Var('16'),'download_max_mb':Var('512')},lidar_provider=Var('Automatic for map'),lidar_cache=lambda:tmp_path,discovery_cancel=threading.Event(),discovery_generation=0,stop_search_button=Mock(),lidar_info=Var(),events=queue.Queue())
 local={'rows':[{'name':'local'}],'warnings':[],'scanned':1,'cached':0}
 online={'rows':[{'name':'online'}],'warnings':[]}
 with patch('lidar_sources.area_bounds',return_value=[0,0,1,1]),patch('lidar_sources.discover',return_value=online),patch('local_sources.discover_local',return_value=local):
  App.search_lidar(app)
  first=app.events.get(timeout=2);last=app.events.get(timeout=2)
 assert first[0]=='discovery_partial' and first[1][1]['rows']==local['rows']
 assert last[0]=='discovery_result' and last[1][1]['rows']==online['rows']+local['rows']
 assert not app.busy


def test_add_all_local_omits_unknown_and_review_only_candidates():
 app=SimpleNamespace(busy=False,lidar_rows=[{'access':'local','coverage':'overlap','path':'good.tif'},{'access':'local','coverage':'unknown','path':'unknown.laz'},{'access':'local','coverage':'overlap','needsReview':True,'path':'multiband.tif'}],use_local_paths=Mock())
 App.add_matching_local(app)
 app.use_local_paths.assert_called_once_with(['good.tif'])


def test_project_preferences_do_not_include_api_secrets(tmp_path):
 report=tmp_path/'map.report.json';report.write_text(json.dumps({'dataset':'fixture','bounds':[0,0,1,1],'mapSize':[256,256]}))
 app=SimpleNamespace(report_path=Var(str(report)),check_brush_alignment=Mock(),osm_path=Var('map.osm'),lua_path=Var('map.lua'),lua_sha=None,sources=[],options=lambda:normalize(),strokes=[],biome_strokes=[],result=None,output_path=Var('out.png'),local_folder=Var('data'),auto_lidar=Var(True),lidar_provider=Var('Automatic for map'),api_key=Var('PRIVATE_OT_KEY'),lidar_user=Var('PRIVATE_USERNAME'),lidar_password=Var('PRIVATE_PASSWORD'))
 project=App.form_project(app);serialized=json.dumps(project)
 assert project['discovery']['localFolder']=='data'
 assert all(secret not in serialized for secret in ['PRIVATE_OT_KEY','PRIVATE_USERNAME','PRIVATE_PASSWORD'])

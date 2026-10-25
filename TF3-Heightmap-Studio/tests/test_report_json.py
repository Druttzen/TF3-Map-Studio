"""Current OSM report contracts, large source graphs and actionable errors."""
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from alignment import read_report


def metadata():
 return {'dataset':'report-fixture','input':'original.osm','bounds':[57,12,57.1,12.1],
         'mapSize':[24576,24576],'settings':{},'edges':0,'sceneryItems':0,'placeLabels':0,
         'sourceSha256':'a'*64,'luaSha256':'b'*64}


def test_report_over_64mb_streams_source_graph_without_retaining_it(tmp_path):
 p=tmp_path/'large.report.json'
 record=b'{"id":"1","tags":{"name":"'+b'x'*950+b'"}},'
 with p.open('wb') as out:
  out.write(b'{"waterMetadata":{"nodes":[')
  for _ in range(70):out.write(record*1024)
  out.write(b'{}]},'+json.dumps(metadata())[1:].encode())
 assert p.stat().st_size>64*1024*1024
 report=read_report(p)
 assert report['dataset']=='report-fixture' and report['mapSize']==[24576,24576]
 assert report['sourceSha256']=='a'*64 and 'waterMetadata' not in report
 assert report['reportPath']==str(p.resolve())


def test_importer_folder_and_bom_resolve_the_actual_report(tmp_path):
 p=tmp_path/'import-report.json';p.write_text(json.dumps(metadata()),encoding='utf-8-sig')
 assert read_report(tmp_path)['reportPath']==str(p.resolve())


def test_folder_context_discovers_moved_lua_without_absolute_output(tmp_path):
 from alignment import load_context
 import osm_converter
 xml=tmp_path/'original.osm'
 xml.write_text('<osm version="0.6"><bounds minlat="0" minlon="0" maxlat=".01" maxlon=".01"/><node id="1" lat=".005" lon=".005"/></osm>')
 lua=tmp_path/'content/osm/dataset.lua';lua.parent.mkdir(parents=True)
 report=tmp_path/'import-report.json'
 osm_converter.write_outputs(xml,lua,report,None,[256,256],18,100000,None,None,None)
 data=json.loads(report.read_text());data['output']='old-install/content/osm/dataset.lua';report.write_text(json.dumps(data))
 context=load_context(tmp_path,xml)
 assert context['convertedLua']['file']==str(lua.resolve())


def test_gui_uses_resolved_folder_report_without_tk(tmp_path):
 from types import SimpleNamespace
 from gui import App
 from unittest.mock import Mock,patch
 p=tmp_path/'import-report.json';p.write_text(json.dumps(metadata()))
 lua=tmp_path/'content/osm/dataset.lua';lua.parent.mkdir(parents=True);lua.write_text('return {}')
 original=tmp_path/'original.osm';original.write_text('<osm version="0.6"/>')
 var=lambda value='':SimpleNamespace(set=Mock(),get=Mock(return_value=value))
 app=SimpleNamespace(check_brush_alignment=Mock(),report_path=var(),lua_path=var(),map_info=var(),osm_path=var(),output_path=var(),apply_game_paths=Mock())
 with patch('gui.messagebox.showerror') as error:App.use_report(app,tmp_path)
 error.assert_not_called()
 app.report_path.set.assert_called_once_with(str(p.resolve()))
 app.lua_path.set.assert_called_once_with(str(lua.resolve()))
 app.osm_path.set.assert_called_once_with(str(original))


@pytest.mark.parametrize('payload,expected',[
 ({'format':'Druttzen-OSM-download'},'download log'),
 ({'format':'TF3-Heightmap-Studio-report'},'Heightmap export report'),
 ({'converterDataset':'example'},'Heightmap export report'),
 ({'other':1},'OSM converter'),
 ([], 'JSON object'),
])
def test_wrong_json_types_explain_the_required_file(tmp_path,payload,expected):
 p=tmp_path/'wrong.json';p.write_text(json.dumps(payload))
 with pytest.raises(ValueError,match=expected):read_report(p)


@pytest.mark.parametrize('tail',[
 ',"waterMetadata":{"nodes":[{"id":"1"}',
 ',"waterMetadata":{"nodes":[1,2,]}}',
 ',"waterMetadata":{"nodes":[NaN]}}',
 ',"waterMetadata":{"nodes":[1e999]}}',
 '} trailing',
 '}{"second":1}',
])
def test_invalid_skipped_source_graph_or_trailing_bytes_are_rejected(tmp_path,tail):
 p=tmp_path/'bad.report.json';p.write_text(json.dumps(metadata())[:-1]+tail)
 with pytest.raises(ValueError):read_report(p)


def test_duplicate_alignment_fields_are_rejected(tmp_path):
 p=tmp_path/'duplicate.report.json';p.write_text(json.dumps(metadata())[:-1]+',"mapSize":[1,1]}')
 with pytest.raises(ValueError,match='repeated'):read_report(p)


@pytest.mark.parametrize('field,value',[('bounds',[57,12,57.1]),('mapSize',[True,1]),('input',[]),('settings',{'unknown':True}),('luaSha256','bad')])
def test_critical_alignment_validation_remains_strict(tmp_path,field,value):
 payload=metadata();payload[field]=value
 p=tmp_path/'bad.report.json';p.write_text(json.dumps(payload))
 with pytest.raises(ValueError):read_report(p)

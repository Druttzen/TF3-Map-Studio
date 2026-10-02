import hashlib,json,sys,threading
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from lua_map import parse,parse_stream,read_map,find_map,ArrayCount
from alignment import read_report,load_context
from terrain import prepare,export,project_dict,load_project
from job import Job,Cancelled
import osm_converter as osm

@pytest.fixture
def dataset(tmp_path):
 source=ROOT/'examples/sample.osm';target=tmp_path/'map.lua'
 osm.export_file(source,target,None,[1024,1024])
 return source,target,target.with_suffix('.report.json')

def test_matches_converter_and_joins_subdivisions(dataset):
 source,lua,report=dataset;r=read_report(report);lines,info=read_map(lua,r)
 assert info['edges']==r['edges']==10 and info['reportChecksumVerified']
 assert info['roadSegments']+info['railSegments']==10
 assert len(lines)<info['edges']
 context=load_context(report,source)
 assert context['convertedLua']['sha256']==hashlib.sha256(lua.read_bytes()).hexdigest()
 assert [v for v in context['lines'] if v['kind']!='river']==lines

@pytest.mark.parametrize('text',[
 'return os.execute("anything")', 'return { ["a"]=function() end }',
 'return {["x"]=1}; os.execute("anything")', 'return {["x"]=1,["x"]=2}',
 'return {["x"]=1,2}', 'return {["x"]=1e999}',
 'return {["x"]=(1+2)}','return {["x"]=nil,["x"]=1}',
 'return {["x"]="\\255"}', 'return {'+'{'*34+'}'*34+'}',
])
def test_rejects_executable_or_ambiguous_content(text):
 with pytest.raises(ValueError):parse(text)

def test_unicode_controls_and_scientific_notation():
 value={'name':'quote" slash\\ newline\n snow ☃','n':-2e-6,'yes':True,'no':False,'empty':None,'a':[1,2.5]}
 assert parse(' -- comment\nreturn '+osm.lua(value))==value

def test_changed_lua_checksum_rejected(dataset):
 source,lua,report=dataset;lua.write_text(lua.read_text(encoding='utf-8')+'\n-- changed',encoding='utf-8')
 with pytest.raises(ValueError,match='checksum'):load_context(report,source,lua_path=lua)

@pytest.mark.parametrize('field,value,reason',[
 ('id','wrong','dataset'),('bounds',[0,0,.02,.01],'coordinates'),('size',[512,1024],'size'),
 ('conversionSettings',{'features':{'roads':False}},'settings'),('schema',2,'schema'),
 ('edges',[],'count'),('nodes',{'1':{'pos':[10000,0]}},'outside'),
])
def test_mismatch_and_invalid_geometry(dataset,field,value,reason):
 source,lua,report=dataset;r=read_report(report);r.pop('luaSha256');data=parse(lua.read_text(encoding='utf-8'));data[field]=value
 lua.write_text('return '+osm.lua(data),encoding='utf-8')
 with pytest.raises(ValueError,match=reason):read_map(lua,r)

def test_missing_edge_node_rejected(dataset):
 _,lua,report=dataset;r=read_report(report);r.pop('luaSha256');data=parse(lua.read_text(encoding='utf-8'));data['edges'][0]['node1']='missing'
 lua.write_text('return '+osm.lua(data),encoding='utf-8')
 with pytest.raises(ValueError,match='missing'):read_map(lua,r)

def test_converted_geometry_is_authoritative(dataset):
 source,lua,report=dataset;r=json.loads(report.read_text());data=parse(lua.read_text(encoding='utf-8'))
 # Keep only a bridge, move its corridor; the original OSM still contains roads.
 edge=data['edges'][0];edge['bridge']=True;data['edges']=[edge]
 for node in (edge['node0'],edge['node1']):data['nodes'][node]['pos'][1]=300
 lua.write_text('return '+osm.lua(data),encoding='utf-8');r['edges']=1;r['luaSha256']=hashlib.sha256(lua.read_bytes()).hexdigest();report.write_text(json.dumps(r))
 context=load_context(report,source,lua_path=lua);roads=[v for v in context['lines'] if v['kind']=='road']
 assert len(roads)==1 and roads[0]['bridge'] and all(p[1]==300 for p in roads[0]['points'])
 result=prepare(report,source,[ROOT/'examples/synthetic-elevation.tif'],{'roads':True},lua_path=lua)
 assert result['maximumRefinementMetres']==0 # Bridge interior is never graded.
 assert result['context']['convertedLua']['bridgeSegments']==1

def test_saved_project_rejects_changed_dataset_and_export_records_provenance(dataset,tmp_path):
 source,lua,report=dataset;result=prepare(report,source,[ROOT/'examples/synthetic-elevation.tif'],lua_path=lua)
 exported=export(result,tmp_path/'height.png')
 assert exported['roadRailGeometrySource']=='converted Lua' and exported['convertedLua']['reportChecksumVerified']
 p=load_project(exported['files']['project']);assert p['convertedLua']==str(lua.resolve())
 assert p['luaSha256']==hashlib.sha256(lua.read_bytes()).hexdigest()
 lua.write_text(lua.read_text(encoding='utf-8')+'\n-- edited',encoding='utf-8')
 with pytest.raises(ValueError,match='checksum'):load_project(exported['files']['project'])

def test_cancellation_is_checked(dataset):
 _,lua,report=dataset;event=threading.Event();event.set()
 with pytest.raises(Cancelled):read_map(lua,read_report(report),Job(cancel=event))

def test_old_report_warns_and_portable_neighbor_takes_priority(dataset):
 source,lua,report=dataset;r=json.loads(report.read_text());r.pop('luaSha256');r['output']='missing.lua';report.write_text(json.dumps(r))
 assert find_map(report,r)==str(lua.resolve())
 c=load_context(report,source);assert c['convertedLua'] and any('no Lua checksum' in v for v in c['warnings'])

def test_closed_and_branched_chains(dataset):
 _,lua,report=dataset;r=read_report(report);r.pop('luaSha256');data=parse(lua.read_text(encoding='utf-8'));edge=data['edges'][0]
 data['nodes']={str(i):{'pos':p} for i,p in enumerate([[0,0],[10,0],[10,10],[0,10],[20,0]])}
 data['edges']=[dict(edge,node0=str(a),node1=str(b)) for a,b in [(0,1),(1,2),(2,3),(3,0),(1,4)]];r['edges']=5
 lua.write_text('return '+osm.lua(data),encoding='utf-8');lines,info=read_map(lua,r)
 assert sum(len(v['points'])-1 for v in lines)==5
 assert len(lines)==2 # Cycle from branch to itself, plus spur.

def test_empty_feature_tables(dataset):
 _,lua,report=dataset;r=read_report(report);r.pop('luaSha256');data=parse(lua.read_text(encoding='utf-8'))
 data.update(nodes={},edges=[],scenery=[],labels=[]);r.update(edges=0,sceneryItems=0,placeLabels=0)
 lua.write_text('return '+osm.lua(data),encoding='utf-8');lines,info=read_map(lua,r)
 assert lines==[] and info['nodes']==0

def test_modified_converted_road_changes_only_its_exported_corridor(dataset):
 import numpy as np
 source,lua,report=dataset;r=json.loads(report.read_text());data=parse(lua.read_text(encoding='utf-8'));edge=data['edges'][0]
 data['edges']=[edge]
 data['nodes'][edge['node0']]['pos']=[-400,300];data['nodes'][edge['node1']]['pos']=[400,300]
 lua.write_text('return '+osm.lua(data),encoding='utf-8');r['edges']=1;r['luaSha256']=hashlib.sha256(lua.read_bytes()).hexdigest();report.write_text(json.dumps(r))
 result=prepare(report,source,[ROOT/'examples/synthetic-elevation.tif'],{'roads':True,'road_smoothing':100,'road_grade':1},lua_path=lua)
 delta=np.abs(result['terrain']-result['baseline'])
 assert delta.max()>0.01
 assert delta[128].max()==0 # Original OSM road was near Y=0; it must not be graded.
 assert delta[53].max()>0.01 # Exported Lua corridor is now near Y=300.

@pytest.mark.parametrize('chunk_size',[1,2,3,7,31,65536])
def test_streaming_token_boundaries(chunk_size):
 data={'name':'snow ☃ slash\\ quote" newline\n decimal\x01end','values':[1,-2e-6,3.14159,True,False,None]}
 text='-- ignored comment\nreturn '+osm.lua(data)+'\n-- trailing comment without newline'
 assert parse_stream(text[i:i+chunk_size] for i in range(0,len(text),chunk_size))==data

def test_streaming_discards_scenery_and_labels():
 row='{"unicode ☃",1e-6,true,nil},'
 data=parse_stream(iter(['return {["scenery"]={']+[row]*10000+['},["labels"]={{"demo"}}}']),summarize=True)
 assert isinstance(data['scenery'],ArrayCount) and len(data['scenery'])==10000
 assert isinstance(data['labels'],ArrayCount) and len(data['labels'])==1

def test_lua_file_over_previous_limit_is_streamed(dataset):
 import tracemalloc
 _,lua,report=dataset;r=read_report(report);digest=hashlib.sha256()
 # A long valid comment also checks that a single huge line is never buffered.
 with lua.open('ab') as dst:
  dst.write(b'\n-- ')
  chunk=b'padding '*131072
  for _ in range(129):dst.write(chunk)
 assert lua.stat().st_size>128*1024*1024
 with lua.open('rb') as source:
  while chunk:=source.read(65536):digest.update(chunk)
 r['luaSha256']=digest.hexdigest()
 tracemalloc.start()
 try:
  lines,info=read_map(lua,r);_,peak=tracemalloc.get_traced_memory()
 finally:tracemalloc.stop()
 assert info['reportChecksumVerified'] and info['edges']==10 and lines
 assert peak<8*1024*1024 # File bytes and the enormous comment must not accumulate.

def test_cancel_during_streaming_read(dataset):
 _,lua,report=dataset;r=read_report(report);event=threading.Event()
 class CancelAfterChunk(Job):
  def update(self,percent,stage,detail='',force=False):
   if ' MB' in detail:event.set()
   super().update(percent,stage,detail,force)
 with pytest.raises(Cancelled):read_map(lua,r,CancelAfterChunk(cancel=event))

def test_utf8_character_split_between_file_chunks(dataset):
 _,lua,report=dataset;r=read_report(report)
 original=lua.read_bytes();lua.write_bytes(b'-- '+b' '*(65535-3)+'☃'.encode('utf-8')+b'\n'+original)
 r['luaSha256']=hashlib.sha256(lua.read_bytes()).hexdigest()
 _,info=read_map(lua,r);assert info['reportChecksumVerified']

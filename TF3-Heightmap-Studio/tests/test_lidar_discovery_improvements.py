"""Map-directed discovery, bounded complete catalogs, cache and cancellation."""
import io
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import lidar_sources as sources
from height_settings import normalize
from job import Job,Cancelled

SWEDEN=[57.1,12.1,57.2,12.2]


def row():
 return {'id':'fixture','name':'Ground fixture','provider':'Lantmäteriet','assets':[],
         'access':'account','resolution':'1 m cells','verticalDatum':'RH2000',
         'site':sources.LM_SITE,'surface':'Ground model','attribution':'Fictional fixture'}


def feature(index,**extra):
 return {'collection':'dtm-cog','bbox':[12,57,13,58],
         'assets':{'data':{'href':f'https://dl1.lantmateriet.se/fixture-{index}.tif'}},
         'properties':{'geometriskupplosning':1,'lagesosakerhethojd':.1,
                       'huvudsakliglagesbestamningsmetod':'Luftburen laserskanning'},**extra}


@pytest.mark.parametrize('bounds,expected',[(SWEDEN,'Lantmäteriet'),([40,-105.3,40.1,-105.2],'USGS'),([-30,20,-29,21],'OpenTopography')])
def test_automatic_queries_only_the_recommended_region(tmp_path,bounds,expected):
 with patch.object(sources,'sweden',return_value=[row()]) as lm,patch.object(sources,'usa',return_value=[row()]) as us,patch.object(sources,'worldwide',return_value=([row()],[])) as ot:
  result=sources.discover(bounds,sources.PROVIDERS[-1],normalize(),tmp_path)
 assert result['providersSearched']==[expected]
 assert sum(f.call_count for f in (lm,us,ot))==1
 assert result['complete'] and not result['fromCache']


def test_sweden_only_requests_ground_collection_and_retains_over_limit_matches(tmp_path):
 data={'features':[feature(i) for i in range(3)]+[feature(10,collection='dsm-skoglig-copc')],'links':[]}
 with patch.object(sources,'fetch_json',return_value=data) as fetch:
  match=sources.sweden(SWEDEN,Job(),2)[0]
 assert 'collections=dtm-cog' in fetch.call_args.args[0]
 assert len(match['assets'])==3 and match['tileCount']==3
 assert match['downloadBlocked'] and match['requiredTileLimit']==3
 assert not match['catalogTruncated']
 assert match['assets'][0]['surveyMethod']=='Luftburen laserskanning'
 with patch.object(sources,'fetch_geotiff') as download,pytest.raises(ValueError,match='tile limit'):
  sources.download_selection(match,SWEDEN,normalize({'public_max_tiles':2}),tmp_path,credentials=('fixture-user','fixture-password'))
 download.assert_not_called()
 with patch.object(sources,'fetch_geotiff',return_value=tmp_path/'fictional.tif') as download:
  assert len(sources.download_selection(match,SWEDEN,normalize({'public_max_tiles':3}),tmp_path,credentials=('fixture-user','fixture-password')))==3
 assert download.call_args.args[-1]['resolutionMetres']==1
 assert 'fixture-password' not in json.dumps(download.call_args.args[-1])


def test_catalog_safety_cap_is_explicit_and_cannot_be_downloaded_as_complete(tmp_path):
 with patch.object(sources,'CATALOG_MAX_ASSETS',2),patch.object(sources,'fetch_json',return_value={'features':[feature(i) for i in range(3)],'links':[]}):
  match=sources.sweden(SWEDEN,Job(),64)[0]
 assert match['catalogTruncated'] and match['downloadBlocked']
 assert match['tileCountAtLeast']==3 and len(match['assets'])==2
 with pytest.raises(ValueError,match='incomplete'):
  sources.download_selection(match,SWEDEN,normalize({'public_max_tiles':64}),tmp_path)


def test_successful_repeated_discovery_uses_cache_and_limit_or_source_changes_invalidate(tmp_path):
 with patch.object(sources,'sweden',return_value=[row()]) as fetch:
  first=sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)
  cached=sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)
  changed=sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize({'public_max_tiles':32}),tmp_path)
  with patch.object(sources,'LM_SEARCH',sources.LM_SEARCH+'-new'):
   changed_source=sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)
 assert first['rows']==cached['rows'] and cached['fromCache']
 assert not changed['fromCache'] and not changed_source['fromCache']
 assert fetch.call_count==3


def test_failed_catalog_is_not_cached_and_partial_search_stays_visible(tmp_path):
 with patch.object(sources,'sweden',side_effect=ValueError('offline')) as fetch:
  for _ in range(2):
   result=sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)
   assert not result['complete'] and not result['fromCache'] and result['warnings']
 assert fetch.call_count==2
 assert not list(tmp_path.glob('discovery-*.json'))


def test_expired_or_invalid_cache_is_refreshed(tmp_path):
 with patch.object(sources,'sweden',return_value=[row()]) as fetch:
  sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)
  path=next(tmp_path.glob('discovery-*.json'));data=json.loads(path.read_text())
  data['created']-=sources.DISCOVERY_CACHE_SECONDS+1;path.write_text(json.dumps(data))
  assert not sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)['fromCache']
  data=json.loads(path.read_text());data['result']=[];path.write_text(json.dumps(data))
  assert not sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path)['fromCache']
 assert fetch.call_count==3


def test_catalog_cancel_while_waiting_for_headers_returns_promptly():
 entered=threading.Event();release=threading.Event();cancel=threading.Event()
 class Response(io.BytesIO):
  def geturl(self):return 'https://example.invalid/catalog'
 def opener(*args,**kwargs):
  entered.set();release.wait(3);return Response(b'{}')
 timer=threading.Timer(.15,cancel.set);start=time.monotonic()
 try:
  with patch.object(sources.ssl,'create_default_context',return_value=object()),patch.object(sources,'urlopen',side_effect=opener),pytest.raises(Cancelled):
   timer.start()
   sources.fetch_json('https://example.invalid/catalog',Job(cancel=cancel))
  assert entered.is_set() and time.monotonic()-start<1
 finally:release.set();timer.cancel()


def test_parallel_all_searches_preserve_order_and_progress_stays_on_caller(tmp_path):
 barrier=threading.Barrier(2);caller=threading.get_ident();updates=[]
 def lm(*args):barrier.wait(timeout=2);return [row()]
 def ot(*args):barrier.wait(timeout=2);return [],['Some remote catalog is unavailable']
 with patch.object(sources,'sweden',side_effect=lm),patch.object(sources,'worldwide',side_effect=ot):
  result=sources.discover(SWEDEN,sources.PROVIDERS[0],normalize(),tmp_path,Job(progress=lambda *args:updates.append(threading.get_ident())))
 assert result['providersSearched']==['Lantmäteriet','OpenTopography']
 assert result['rows'][0]['id']=='fixture' and not result['complete']
 assert updates and set(updates)=={caller}


def test_cancel_during_tls_setup_does_not_start_a_later_request():
 entered=threading.Event();release=threading.Event();cancel=threading.Event();requested=threading.Event()
 def context(**kwargs):entered.set();release.wait(3);return object()
 def opener(*args,**kwargs):requested.set();raise AssertionError('No request may start after cancellation')
 timer=threading.Timer(.15,cancel.set)
 try:
  with patch.object(sources.ssl,'create_default_context',side_effect=context),patch.object(sources,'urlopen',side_effect=opener):
   timer.start()
   with pytest.raises(Cancelled):sources.fetch_json('https://example.invalid/catalog',Job(cancel=cancel))
   assert entered.is_set()
   release.set()
   assert not requested.wait(.2)
 finally:release.set();timer.cancel()


def test_cancelled_search_does_not_publish_results_or_cache(tmp_path):
 event=threading.Event()
 def search(*args):
  event.set();return [row()]
 with patch.object(sources,'sweden',side_effect=search),pytest.raises(Cancelled):
  sources.discover(SWEDEN,sources.PROVIDERS[-1],normalize(),tmp_path,Job(cancel=event))
 assert not list(tmp_path.glob('discovery-*.json'))

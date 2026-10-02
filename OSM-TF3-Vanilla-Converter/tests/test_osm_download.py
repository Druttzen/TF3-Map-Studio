"""Area selection, XML download integrity and OSM tile usage behavior."""
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import osm_download as d
from map_sizes import SIZES,FORMATS,dimensions
from converter import export_file,read_osm
from job import Cancelled

class Response(io.BytesIO):
    def __init__(self,data,url=d.OVERPASS,headers=None):super().__init__(data);self.url=url;self.headers=headers or {'Content-Length':str(len(data))}
    def geturl(self):return self.url

class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.bounds=[0,0,.01,.01];self.size=[1000,1000];self.source=(ROOT/'tests/sample.osm').read_bytes()
    def tearDown(self):self.temp.cleanup()
    def run_download(self,data=None,**kwargs):
        return d.download(self.bounds,self.size,self.folder/'area.osm',opener=lambda *a,**k:Response(self.source if data is None else data),**kwargs)

    def test_all_game_sizes_have_correct_ground_scale_and_mercator_aspect(self):
        for lat in (-75,0,59,80):
            for name in SIZES:
                for fmt in FORMATS:
                    size=dimensions(name,fmt);s,w,n,e=d.area_bounds((lat,18),size)
                    x,y=d.mercator(s,w);xx,yy=d.mercator(n,e)
                    self.assertAlmostEqual((xx-x)/(yy-y),size[0]/size[1],places=9)
                    self.assertAlmostEqual((xx-x)*math.cos(math.radians(lat)),size[0],places=6)
                    mid=d.geographic((x+xx)/2,(y+yy)/2)
                    self.assertAlmostEqual(mid[0],lat,places=10);self.assertAlmostEqual(mid[1],18,places=10)

    def test_selection_click_lock_unlock_and_resize(self):
        selection=d.Selection([1000,2000]);selection.move((60,18));selection.lock((61,19));old=list(selection.bounds)
        selection.move((20,10));selection.lock((20,10));self.assertEqual(selection.bounds,old)
        selection.unlock();selection.move((20,10));self.assertNotEqual(selection.bounds,old)
        selection.lock((20,10));selection.resize([2000,4000],2);self.assertFalse(selection.locked)
        s,w,n,e=selection.bounds;x,y=d.mercator(s,w);xx,yy=d.mercator(n,e)
        self.assertAlmostEqual((xx-x)*math.cos(math.radians(20)),4000,places=6)

    def test_invalid_frame_preserves_selection(self):
        selection=d.Selection([1000,1000]);old=selection.bounds.copy()
        for center in [(90,0),(0,180),(float('nan'),0)]:
            with self.assertRaises(ValueError):selection.lock(center)
            self.assertEqual(selection.bounds,old);self.assertFalse(selection.locked)
        for size,scale in [([0,1000],1),([1000,1000],0),([1000,1000],float('inf'))]:
            with self.assertRaises(ValueError):selection.resize(size,scale)
            self.assertEqual(selection.bounds,old)

    def test_projection_pixel_round_trip_and_fit(self):
        for zoom in (2,9,19):
            for center in ((-70,-170),(0,0),(59,18),(80,170)):
                result=d.pixel_geographic(*d.pixel(*center,zoom),zoom)
                self.assertAlmostEqual(result[0],center[0],places=10);self.assertAlmostEqual(result[1],center[1],places=10)
        bounds=d.area_bounds((59,18),[12800,64000]);zoom=d.fit_zoom(bounds,600,500)
        a,b=d.pixel(bounds[2],bounds[1],zoom);c,e=d.pixel(bounds[0],bounds[3],zoom)
        self.assertLessEqual(c-a,500);self.assertLessEqual(e-b,400)

    def test_visible_tiles_only_and_no_off_world_requests(self):
        for center in ((0,0),(84,179.9),(-84,-179.9)):
            tiles=d.visible_tiles(center,3,650,480)
            self.assertLessEqual(len(tiles),16)
            for z,x,y,px,py in tiles:
                self.assertTrue(0<=x<2**z and 0<=y<2**z)
                self.assertLess(px,650);self.assertGreater(px+256,0);self.assertLess(py,480);self.assertGreater(py+256,0)

    def test_query_exact_bounds_order_all_types_and_full_descendants(self):
        bounds=[59.1234567890123,18.1,59.3,18.4]
        query=d.query_for(bounds)
        self.assertIn('nwr('+','.join(format(v,'.17g') for v in bounds)+')',query)
        self.assertIn('>>',query);self.assertIn('out body',query);self.assertIn('[out:xml]',query)

    def test_xml_and_log_handoff_through_real_conversion(self):
        result=self.run_download()
        root=ET.parse(result['output']).getroot();node=root.find('bounds')
        self.assertEqual([float(node.get(key)) for key in ('minlat','minlon','maxlat','maxlon')],self.bounds)
        self.assertEqual(len(root.findall('bounds')),1)
        original=ET.fromstring(self.source)
        for key in ('node','way','relation'):
            for x in root.findall(key)+original.findall(key):x.tail=None
            self.assertEqual([ET.tostring(x) for x in root.findall(key)],[ET.tostring(x) for x in original.findall(key)])
        metadata=json.loads(Path(result['log']).read_text(encoding='utf-8'))
        self.assertEqual(metadata['osmSha256'],hashlib.sha256(Path(result['output']).read_bytes()).hexdigest())
        exported=export_file(result['output'],self.folder/'map.lua',result['bounds'],result['mapSize'])
        self.assertEqual(exported['bounds'],self.bounds);self.assertEqual(exported['mapSize'],self.size);self.assertGreater(exported['edges'],0)
        self.assertEqual(list(read_osm(result['output'])[3]),self.bounds)

    def test_failure_keeps_both_previous_outputs(self):
        self.run_download();old={p.name:p.read_bytes() for p in self.folder.iterdir()}
        for payload in (b'<html>failure</html>',b'<osm version="0.6"><remark>runtime error: timeout</remark></osm>',b'<osm version="0.6"><node',b'',b'<osm version="0.6"><node id="1" lat="NaN" lon="2"/></osm>'):
            with self.assertRaises((ValueError,ET.ParseError)):self.run_download(payload)
            self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_xml_declarations_are_rejected(self):
        payload=b'<!DOCTYPE osm [<!ENTITY x "test">]><osm version="0.6"><node id="1" lat="0" lon="0"/></osm>'
        with self.assertRaises(ValueError):self.run_download(payload)
        with self.assertRaises(ValueError):self.run_download('<?xml version="1.0" encoding="UTF-16"?><osm version="0.6"/>'.encode('utf-16'))
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_truncated_content_length_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'truncated'):
            d.download(self.bounds,self.size,self.folder/'area.osm',opener=lambda *a,**k:Response(self.source,headers={'Content-Length':str(len(self.source)+100)}))
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_cancel_waiting_for_server_returns_promptly(self):
        cancel=threading.Event();entered=threading.Event();release=threading.Event()
        def opener(*a,**k):entered.set();release.wait(3);return Response(self.source)
        timer=threading.Timer(.2,cancel.set);timer.start();start=time.monotonic()
        try:
            with self.assertRaises(Cancelled):d.download(self.bounds,self.size,self.folder/'area.osm',cancel=cancel,opener=opener)
            self.assertLess(time.monotonic()-start,1);self.assertTrue(entered.is_set());self.assertEqual(list(self.folder.iterdir()),[])
        finally:release.set();timer.cancel()

    def test_cancel_during_stream_keeps_previous_files(self):
        self.run_download();old={p.name:p.read_bytes() for p in self.folder.iterdir()};cancel=threading.Event()
        def progress(p,stage,detail):
            if stage=='Downloading OSM XML':cancel.set()
        with self.assertRaises(Cancelled):self.run_download(cancel=cancel,progress=progress)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_cancel_during_validation_keeps_previous_files(self):
        self.run_download();old={p.name:p.read_bytes() for p in self.folder.iterdir()};cancel=threading.Event()
        def progress(p,stage,detail):
            if p==85:cancel.set()
        with self.assertRaises(Cancelled):self.run_download(cancel=cancel,progress=progress)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_failed_log_commit_restores_old_xml_and_log(self):
        self.run_download();old={p.name:p.read_bytes() for p in self.folder.iterdir()};original=d.os.replace
        def replace(a,b):
            if Path(b).name=='area.download.json':raise OSError('Commit failed')
            return original(a,b)
        with patch.object(d.os,'replace',side_effect=replace),self.assertRaises(OSError):self.run_download(self.source.replace(b'Sample',b'Changed'))
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_cancel_at_commit_boundary_keeps_previous_files(self):
        self.run_download();old={p.name:p.read_bytes() for p in self.folder.iterdir()};cancel=threading.Event()
        def progress(p,stage,detail):
            if p==98:cancel.set()
        with self.assertRaises(Cancelled):self.run_download(cancel=cancel,progress=progress)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_no_old_output_removed_on_failed_first_log_commit(self):
        original=d.os.replace
        def replace(a,b):
            if Path(b).name=='area.download.json':raise OSError('Commit failed')
            return original(a,b)
        with patch.object(d.os,'replace',side_effect=replace),self.assertRaises(OSError):self.run_download()
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_failed_restore_retains_backup(self):
        self.run_download();previous=(self.folder/'area.osm').read_bytes();original=d.os.replace
        def replace(a,b):
            if Path(b).name=='area.download.json' or Path(a).name=='previous.osm':raise OSError('Commit/restore failed')
            return original(a,b)
        with patch.object(d.os,'replace',side_effect=replace),self.assertRaisesRegex(RuntimeError,'Backup retained'):self.run_download()
        backups=list(self.folder.glob('.osm-download-*/previous.osm'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),previous)

    def test_service_errors_and_request_identity(self):
        seen=[]
        def opener(request,**kwargs):
            seen.append(request);raise urllib.error.HTTPError(request.full_url,429,'Busy',{},None)
        with self.assertRaisesRegex(ValueError,'busy'):d.download(self.bounds,self.size,self.folder/'area.osm',opener=opener)
        self.assertEqual(len(seen),1);self.assertEqual(seen[0].get_method(),'POST');self.assertEqual(seen[0].get_header('User-agent'),d.USER_AGENT)
        self.assertNotIn('no-cache',str(seen[0].headers));self.assertEqual(list(self.folder.iterdir()),[])
        for url in ('http://overpass-api.de/api/interpreter','https://user:password@example.org/api','https://example.org/#x'):
            with self.assertRaises(ValueError):d.download(self.bounds,self.size,self.folder/'area.osm',endpoint=url)

    def test_progress_reports_bytes_and_commit_completion(self):
        updates=[];self.run_download(progress=lambda *args:updates.append(args))
        self.assertEqual(updates[0][0],None);self.assertIn('MB received',' '.join(u[2] for u in updates));self.assertEqual(updates[-1][0],100)

    def test_empty_area_is_valid_xml_with_bounds(self):
        result=self.run_download(b'<osm version="0.6" generator="Overpass"><meta osm_base="2026-10-02"/></osm>')
        self.assertEqual(result['counts'],{'nodes':0,'ways':0,'relations':0});self.assertIsNotNone(ET.parse(result['output']).find('bounds'))

    def snapshot(self):
        a,b=d.mercator(self.bounds[0],self.bounds[1]);c,e=d.mercator(self.bounds[2],self.bounds[3])
        center=d.geographic((a+c)/2,(b+e)/2);size=(650,450);zoom=d.fit_zoom(self.bounds,*size)
        file=io.BytesIO();Image.new('RGB',(256,256),'#aaccee').save(file,format='PNG')
        return {'center':center,'size':size,'zoom':zoom,'tiles':{(z,x,y):file.getvalue() for z,x,y,_,_ in d.visible_tiles(center,zoom,*size)}}

    def test_overview_geography_pixels_checksum_and_attribution(self):
        result=self.run_download(overview=self.snapshot())
        with Image.open(result['overview']) as png:
            self.assertEqual(png.format,'PNG');self.assertEqual(png.size,(650,604))
            metadata=json.loads(png.info['TF3 Map Overview'])
            self.assertEqual(metadata['bounds'],self.bounds);self.assertEqual(metadata['mapSize'],self.size)
            self.assertEqual(metadata['attribution'],'© OpenStreetMap contributors')
            x,y,xx,yy=metadata['framePixels']
            self.assertEqual(png.getpixel((x+1,y+1)),(255,219,0))
            self.assertEqual(png.getpixel((325,325)),(170,204,238))
            self.assertTrue(0<x<xx<650 and 100<y<yy<550)
        report=json.loads(Path(result['log']).read_text(encoding='utf-8'))
        self.assertEqual(report['overviewMetadata'],metadata)
        self.assertEqual(report['overviewSha256'],hashlib.sha256(Path(result['overview']).read_bytes()).hexdigest())

    def test_failed_overview_or_log_commit_restores_all_three_files(self):
        self.run_download(overview=self.snapshot());old={p.name:p.read_bytes() for p in self.folder.iterdir()};original=d.os.replace
        for filename in ('area.overview.png','area.download.json'):
            def replace(a,b):
                if Path(b).name==filename and not Path(a).name.startswith('previous.'):raise OSError('Commit failed')
                return original(a,b)
            with patch.object(d.os,'replace',side_effect=replace),self.assertRaises(OSError):self.run_download(self.source.replace(b'Sample',b'Changed'),overview=self.snapshot())
            self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_first_overview_commit_failure_leaves_no_partial_outputs(self):
        original=d.os.replace
        def replace(a,b):
            if Path(b).name=='area.overview.png':raise OSError('Commit failed')
            return original(a,b)
        with patch.object(d.os,'replace',side_effect=replace),self.assertRaises(OSError):self.run_download(overview=self.snapshot())
        self.assertEqual(list(self.folder.iterdir()),[])

    def test_incomplete_or_offscreen_overview_keeps_previous_outputs(self):
        self.run_download(overview=self.snapshot());old={p.name:p.read_bytes() for p in self.folder.iterdir()}
        missing=self.snapshot();missing['tiles'].pop(next(iter(missing['tiles'])))
        offscreen=self.snapshot();offscreen['center']=(10,10)
        for snapshot in (missing,offscreen):
            with self.assertRaises(ValueError):self.run_download(overview=snapshot)
            self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

    def test_overview_generation_cancellation_keeps_previous_outputs(self):
        self.run_download(overview=self.snapshot());old={p.name:p.read_bytes() for p in self.folder.iterdir()};cancel=threading.Event()
        def progress(p,*args):
            if p==94:cancel.set()
        with self.assertRaises(Cancelled):self.run_download(overview=self.snapshot(),cancel=cancel,progress=progress)
        self.assertEqual({p.name:p.read_bytes() for p in self.folder.iterdir()},old)

class TileTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def png(self):
        file=io.BytesIO();Image.new('RGB',(256,256),'white').save(file,format='PNG');return file.getvalue()
    def test_visible_tile_cache_minimum_week_and_identity(self):
        calls=[];data=self.png()
        def opener(request,**kwargs):calls.append(request);return Response(data,request.full_url,{'ETag':'tile-v1'})
        cache=d.TileCache(self.folder,opener=opener)
        self.assertEqual(cache.get(14,10,20),data);self.assertEqual(cache.get(14,10,20),data);self.assertEqual(len(calls),1)
        request=calls[0];self.assertEqual(request.full_url,'https://tile.openstreetmap.org/14/10/20.png');self.assertEqual(request.get_header('User-agent'),d.USER_AGENT)
        meta=next(self.folder.rglob('20.json'));info=json.loads(meta.read_text());self.assertGreater(info['expires'],time.time()+6.99*86400)
    def test_expired_cache_conditional_request_and_304(self):
        calls=[];data=self.png()
        def opener(request,**kwargs):
            calls.append(request)
            if len(calls)>1:raise urllib.error.HTTPError(request.full_url,304,'Not modified',{},None)
            return Response(data,request.full_url,{'ETag':'version-1','Last-Modified':'Thu, 01 Oct 2026 00:00:00 GMT'})
        cache=d.TileCache(self.folder,opener=opener);cache.get(1,1,1)
        meta=next(self.folder.rglob('1.json'));info=json.loads(meta.read_text());info['expires']=0;meta.write_text(json.dumps(info))
        self.assertEqual(cache.get(1,1,1),data);self.assertEqual(calls[1].get_header('If-none-match'),'version-1');self.assertIsNotNone(calls[1].get_header('If-modified-since'))
    def test_bad_tile_and_cancel_do_not_write_cache(self):
        cache=d.TileCache(self.folder,opener=lambda request,**k:Response(b'<html>error</html>',request.full_url))
        with self.assertRaises((ValueError,OSError)):cache.get(1,1,1)
        self.assertEqual(list(self.folder.iterdir()),[])
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):cache.get(1,1,1,cancel)

    def test_corrupted_cached_png_is_replaced(self):
        calls=[];data=self.png()
        def opener(request,**kwargs):calls.append(request);return Response(data,request.full_url)
        cache=d.TileCache(self.folder,opener=opener);cache.get(1,1,1)
        next(self.folder.rglob('1.png')).write_bytes(b'broken')
        self.assertEqual(cache.get(1,1,1),data);self.assertEqual(len(calls),2)

if __name__=='__main__':unittest.main()

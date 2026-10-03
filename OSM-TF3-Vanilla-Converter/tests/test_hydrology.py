"""Mapped water boundaries, metadata and conservative network protection."""
from pathlib import Path
import tempfile
import unittest
from converter import convert, signed_area, inside, lua


def fixture(nodes,ways,relations=''):
    text='<osm version="0.6"><bounds minlat="0" minlon="0" maxlat="1" maxlon="1"/>'
    for id,(x,y) in nodes.items():
        text+=f'<node id="{id}" lon="{.5+x/100}" lat="{.5+y/100}"/>'
    for id,refs,tags in ways:
        text+=f'<way id="{id}">'+''.join(f'<nd ref="{n}"/>' for n in refs)
        text+=''.join(f'<tag k="{k}" v="{v}"/>' for k,v in tags.items())+'</way>'
    return text+relations+'</osm>'


class HydrologyTests(unittest.TestCase):
    def convert(self,text,options=None):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'water.osm'; path.write_text(text)
            return convert(path,None,(100,100),options=options)

    def test_pond_is_prepared_as_dirty_water_with_exact_half_metre_depth(self):
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{'natural':'water','water':'pond'})]))
        water=[i for i in d['scenery'] if i['category']=='waterways']
        self.assertTrue(water)
        self.assertTrue(all(i['depth']==.5 and i['texture'].endswith('/dirty_water.gtex') for i in water))
        self.assertTrue(all(len(i['face'])==3 for i in water))
        self.assertEqual(d['waterFeatures'][0]['status'],'prepared')
        self.assertIn('waterFeatures',lua(d))
        self.assertAlmostEqual(sum(signed_area(i['face']) for i in water),400,delta=.1)

    def test_lake_elevation_is_retained_without_global_or_local_sea_claim(self):
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{'natural':'water','water':'lake','ele':'72.4'})]))
        self.assertEqual(d['waterFeatures'][0]['height'],{'raw':'72.4','datum':'OSM-untransformed'})
        self.assertEqual(d['waterFeatures'][0]['status'],'local-sea-level-unsupported')
        self.assertFalse(d['scenery'])

    def test_stream_missing_width_has_visible_configured_fallback(self):
        d=self.convert(fixture({'1':(-10,0),'2':(0,0),'3':(10,10)},[
            ('11',['1','2','3'],{'waterway':'stream'})]),{'waterway_width':3})
        f=d['waterFeatures'][0]
        self.assertEqual(f['width'],3)
        self.assertEqual(f['widthSource'],'configured fallback')
        self.assertIn('waterFeatures',lua(d))
        self.assertTrue(any('approximation' in w for w in d['warnings']))

    def test_multipolygon_island_and_relation_members_are_not_double_imported(self):
        nodes={'1':(-20,-20),'2':(20,-20),'3':(20,20),'4':(-20,20),
               '5':(-5,-5),'6':(5,-5),'7':(5,5),'8':(-5,5)}
        relation='<relation id="20"><member type="way" ref="11" role="outer"/><member type="way" ref="12" role="inner"/><tag k="type" v="multipolygon"/><tag k="natural" v="water"/><tag k="water" v="pond"/></relation>'
        d=self.convert(fixture(nodes,[('11',['1','2','3','4','1'],{'water':'pond'}),('12',['5','6','7','8','5'],{})],relation))
        self.assertEqual(len(d['waterFeatures']),1)
        self.assertAlmostEqual(sum(signed_area(i['face']) for i in d['scenery']),1500,delta=.2)
        self.assertFalse(any(inside((0,0),i['face']) for i in d['scenery']))

    def test_future_network_corridor_is_reserved_without_changing_nodes(self):
        nodes={'1':(-40,-40),'2':(40,-40),'3':(40,40),'4':(-40,40),'5':(-45,0),'6':(45,0)}
        d=self.convert(fixture(nodes,[('11',['1','2','3','4','1'],{'water':'pond'}),('12',['5','6'],{'highway':'residential'})]))
        self.assertTrue(d['edges']); self.assertTrue(d['scenery'])
        self.assertTrue(all(all(abs(p[1])>19.99 for p in i['face']) for i in d['scenery']))
        self.assertTrue(all(len(n['pos'])==2 for n in d['nodes'].values()))

    def test_missing_water_nodes_never_connect_across_the_missing_segment(self):
        d=self.convert(fixture({'1':(-10,0),'3':(10,0)},[('11',['1','2','3'],{'waterway':'stream'})]))
        self.assertFalse(d['scenery']); self.assertFalse(d['waterFeatures'])

    def test_water_feature_selection_is_independent_of_ground_surfaces(self):
        text=fixture({'1':(-10,0),'2':(10,0)},[('11',['1','2'],{'waterway':'stream','width':'4'})])
        self.assertTrue(self.convert(text,{'features':{'surfaces':False}})['waterFeatures'])
        self.assertFalse(self.convert(text,{'features':{'waterways':False}}).get('waterFeatures'))

    def test_incomplete_pond_outline_is_never_buffered_as_a_stream(self):
        d=self.convert(fixture({'1':(-10,0),'2':(10,0)},[('11',['1','2'],{'water':'pond'})]))
        self.assertFalse(d['scenery']); self.assertFalse(d['waterFeatures'])

    def test_osm_xml_extension_is_supported_for_mapped_water(self):
        text=fixture({'1':(-10,0),'2':(10,0)},[('11',['1','2'],{'waterway':'stream','width':'3'})])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'water.xml';path.write_text(text)
            d=convert(path,None,(100,100))
        self.assertTrue(d['waterFeatures']);self.assertTrue(d['scenery'])

    def test_self_crossing_area_is_preserved_for_review_without_excavation(self):
        d=self.convert(fixture({'1':(-10,-10),'2':(10,10),'3':(-10,10),'4':(10,-10)},[
            ('11',['1','2','3','4','1'],{'water':'pond'})]))
        self.assertFalse(d['scenery'])
        self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
        self.assertIn('Self-intersecting',d['waterFeatures'][0]['reason'])

    def test_oversized_feature_is_omitted_whole_when_geometry_budget_is_exceeded(self):
        text=fixture({'1':(-40,-40),'2':(40,-40),'3':(40,40),'4':(-40,40)},[
            ('11',['1','2','3','4','1'],{'water':'pond'})])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'water.osm';path.write_text(text)
            d=convert(path,None,(10000,10000))
        self.assertFalse(d['scenery'])
        self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
        self.assertIn('budget',d['waterFeatures'][0]['reason'])

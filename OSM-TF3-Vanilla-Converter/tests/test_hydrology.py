"""Mapped water boundaries, metadata and conservative network protection."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from converter import convert, export_file, signed_area, inside, lua
from lupa import LuaRuntime


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

    def test_closed_linear_waterways_keep_dry_interiors_and_join_the_closure(self):
        nodes={'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)}
        for waterway in ('canal','stream','river','ditch','drain'):
            for explicit_area in ({},{'area':'no'}):
                with self.subTest(waterway=waterway,area=explicit_area):
                    d=self.convert(fixture(nodes,[('11',['1','2','3','4','1'],
                        {'waterway':waterway,'width':'1',**explicit_area})]))
                    f=d['waterFeatures'][0]
                    faces=[item['face'] for item in d['scenery'] if item['category']=='waterways']
                    self.assertEqual(f['status'],'prepared')
                    self.assertEqual(f['rings'],[])
                    self.assertEqual(f['outerRingCount'],0)
                    self.assertEqual(len(f['centreline']),5)
                    self.assertEqual(f['centreline'][0],f['centreline'][-1])
                    self.assertEqual(f['width'],1)
                    self.assertFalse(any(inside((0,0),face) for face in faces))
                    self.assertLess(sum(signed_area(face) for face in faces),100)
                    # Outside both adjoining rectangles, these corner points
                    # require a join disk, including the first/last vertex.
                    for p in f['centreline'][:-1]:
                        corner=(p[0]+(.2 if p[0]>0 else -.2),
                                p[1]+(.2 if p[1]>0 else -.2))
                        self.assertTrue(any(inside(corner,face) for face in faces),corner)

    def test_explicit_waterway_area_uses_polygon_instead_of_line_width(self):
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{'waterway':'canal','area':'yes','width':'1'})]))
        f=d['waterFeatures'][0]
        self.assertEqual(f['status'],'prepared')
        self.assertEqual(f['centreline'],[])
        self.assertEqual(len(f['rings']),1)
        self.assertNotIn('width',f)
        self.assertAlmostEqual(sum(signed_area(i['face']) for i in d['scenery']),400,delta=.1)

    def test_conflicting_area_no_and_water_area_tags_require_review(self):
        nodes={'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)}
        for tags in ({'natural':'water','water':'pond'},
                     {'natural':'water','water':'river'},
                     {'waterway':'riverbank'},{'water':'lake'}):
            with self.subTest(tags=tags):
                d=self.convert(fixture(nodes,[('11',['1','2','3','4','1'],
                                              {**tags,'area':'no'})]))
                self.assertFalse(d['scenery'])
                self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
                self.assertIn('conflict',d['waterFeatures'][0]['reason'])
                self.assertEqual(d['waterMetadata']['ways']['11']['tags'],{**tags,'area':'no'})

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
        self.assertFalse(d['scenery'])
        self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
        self.assertEqual(d['waterMetadata']['ways']['11']['nodeRefs'],['1','2','3'])
        self.assertEqual(d['waterMetadata']['missingRefs'],[{'type':'node','ref':'2'}])
        self.assertNotIn('2',d['waterMetadata']['nodes'])
        self.assertFalse(d['waterFeatures'][0]['centreline'])

    def test_water_feature_selection_is_independent_of_ground_surfaces(self):
        text=fixture({'1':(-10,0),'2':(10,0)},[('11',['1','2'],{'waterway':'stream','width':'4'})])
        self.assertTrue(self.convert(text,{'features':{'surfaces':False}})['waterFeatures'])
        disabled=self.convert(text,{'features':{'waterways':False}})
        self.assertFalse(disabled['scenery'])
        self.assertEqual(disabled['waterFeatures'][0]['status'],'metadata-only')
        self.assertEqual(disabled['waterFeatures'][0]['tags']['width'],'4')
        self.assertEqual(len(disabled['waterFeatures'][0]['centreline']),2)

    def test_incomplete_pond_outline_is_never_buffered_as_a_stream(self):
        d=self.convert(fixture({'1':(-10,0),'2':(10,0)},[('11',['1','2'],{'water':'pond'})]))
        self.assertFalse(d['scenery'])
        self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
        self.assertEqual(d['waterFeatures'][0]['tags'],{'water':'pond'})

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

    def test_lua_and_json_export_preserve_raw_tags_coordinates_and_height_provenance(self):
        tags={'waterway':'stream','name':'Ån & "Dammen"','width':'4 m',
              'depth':'0.8','ele':'72.4','intermittent':'yes','tunnel':'culvert',
              'source:ele':'survey','ele:datum':'RH2000','source':'local survey'}
        import xml.etree.ElementTree as ET
        root=ET.fromstring(fixture({'1':(-10,0),'2':(10,0)},[('11',['1','2'],{})]))
        for k,v in tags.items(): ET.SubElement(root.find('way'),'tag',k=k,v=v)
        ET.SubElement(root.find('node'),'tag',k='ele',v='71.8')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'water.xml';path.write_bytes(ET.tostring(root,encoding='utf-8'))
            output=Path(folder)/'map.lua'
            result=export_file(path,output,None,(100,100),options={'features':{'waterways':False}})
            report=json.loads(output.with_suffix('.report.json').read_text(encoding='utf-8'))
            runtime=LuaRuntime()
            dataset=runtime.execute(output.read_text(encoding='utf-8'))
            metadata=report['waterMetadata']; feature=metadata['features'][0]
            self.assertEqual(report['waterFeatures'],1)
            self.assertEqual(feature['tags'],tags)
            self.assertEqual(feature['height'],{'raw':'72.4','datum':'OSM-untransformed'})
            self.assertEqual(feature['source'],{'type':'way','ref':'11'})
            self.assertEqual(metadata['ways']['11']['nodeRefs'],['1','2'])
            self.assertEqual(metadata['nodes']['1']['tags'],{'ele':'71.8'})
            self.assertEqual(metadata['nodes']['1']['lat'],.5)
            self.assertEqual(metadata['nodes']['1']['lon'],.4)
            self.assertEqual(metadata['coordinates']['geographic'],'EPSG:4326')
            self.assertEqual(metadata['coordinates']['mapFields'],['x','y'])
            for k,v in tags.items():
                self.assertEqual(dataset.waterFeatures[1].tags[k],v)
                self.assertEqual(dataset.waterMetadata.ways['11'].tags[k],v)
            self.assertEqual(dataset.waterMetadata.nodes['1'].tags.ele,'71.8')
            self.assertEqual(dataset.waterMetadata.nodes['1'].lon,.4)
            self.assertEqual(dataset.waterMetadata.ways['11'].nodeRefs[2],'2')
            self.assertEqual(report['luaSha256'],hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(result['dataset'],dataset.id)
            self.assertEqual(dataset.scenery[1],None)

    def test_relation_source_preserves_island_roles_member_tags_and_node_order(self):
        nodes={'1':(-20,-20),'2':(20,-20),'3':(20,20),'4':(-20,20),
               '5':(-5,-5),'6':(5,-5),'7':(5,5),'8':(-5,5)}
        relation='<relation id="20"><member type="way" ref="12" role="inner"/><member type="way" ref="11" role="outer"/><tag k="type" v="multipolygon"/><tag k="water" v="lake"/><tag k="ele" v="72.4"/></relation>'
        d=self.convert(fixture(nodes,[('11',['1','2','3','4','1'],{'water':'lake','source':'survey'}),
                                      ('12',['8','7','6','5','8'],{'natural':'island'})],relation))
        m=d['waterMetadata'];f=d['waterFeatures'][0]
        self.assertEqual(m['relations']['20']['members'],[
            {'type':'way','ref':'12','role':'inner'},{'type':'way','ref':'11','role':'outer'}])
        self.assertEqual(m['ways']['11']['tags']['source'],'survey')
        self.assertEqual(m['ways']['12']['nodeRefs'],['8','7','6','5','8'])
        self.assertEqual(m['ways']['12']['tags']['natural'],'island')
        self.assertEqual(len(f['rings']),2)
        self.assertEqual(f['outerRingCount'],1)
        self.assertFalse(d['scenery'])

    def test_broken_relation_retains_missing_members_and_never_imports_outer_alone(self):
        relation='<relation id="20"><member type="way" ref="11" role="outer"/><member type="way" ref="missing" role="inner"/><tag k="type" v="multipolygon"/><tag k="water" v="pond"/></relation>'
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{'water':'pond'})],relation))
        self.assertFalse(d['scenery'])
        self.assertEqual(len(d['waterFeatures']),1)
        self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
        self.assertEqual(d['waterMetadata']['missingRefs'],[{'type':'way','ref':'missing'}])
        self.assertEqual(d['waterMetadata']['ways']['11']['tags'],{'water':'pond'})

    def test_nested_relations_are_preserved_without_double_building(self):
        relation='<relation id="20"><member type="way" ref="11" role="outer"/><tag k="type" v="multipolygon"/><tag k="water" v="pond"/></relation><relation id="21"><member type="relation" ref="20" role="outer"/><tag k="type" v="multipolygon"/><tag k="water" v="pond"/></relation>'
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{})],relation))
        self.assertEqual(set(d['waterMetadata']['relations']),{'20','21'})
        self.assertEqual(d['waterMetadata']['relations']['21']['members'][0]['ref'],'20')
        self.assertAlmostEqual(sum(signed_area(i['face']) for i in d['scenery']),400,delta=.1)
        self.assertEqual(sum(f['status']=='prepared' for f in d['waterFeatures']),1)

    def test_cyclic_water_relations_preserve_source_graph_without_recursing_forever(self):
        relation='<relation id="20"><member type="relation" ref="21" role="outer"/><tag k="type" v="multipolygon"/><tag k="water" v="pond"/></relation><relation id="21"><member type="relation" ref="20" role="outer"/><tag k="type" v="multipolygon"/></relation>'
        d=self.convert(fixture({'1':(0,0)},[],relation))
        self.assertEqual(set(d['waterMetadata']['relations']),{'20','21'})
        self.assertFalse(d['scenery'])
        self.assertFalse(d['waterMetadata']['missingRefs'])
        self.assertTrue(all(f['status']=='metadata-only' for f in d['waterFeatures']))

    def test_waterway_relations_and_dam_tags_are_retained_without_inventing_a_surface(self):
        relation='<relation id="20"><member type="way" ref="11" role="main_stream"/><tag k="type" v="waterway"/><tag k="name" v="Test stream"/></relation>'
        d=self.convert(fixture({'1':(-10,0),'2':(10,0)},[
            ('11',['1','2'],{'waterway':'dam','height':'2','ele':'unknown'})],relation))
        self.assertFalse(d['scenery'])
        self.assertEqual(d['waterMetadata']['ways']['11']['tags']['height'],'2')
        self.assertEqual(d['waterMetadata']['relations']['20']['members'][0]['role'],'main_stream')
        self.assertTrue(all(f['status']=='metadata-only' for f in d['waterFeatures']))

    def test_deep_nested_source_survives_the_geometry_recursion_limit(self):
        count=sys.getrecursionlimit()+20
        relations=''
        for i in range(count):
            member=f'<member type="relation" ref="{i+1}" role="outer"/>' if i+1<count else '<member type="way" ref="11" role="outer"/>'
            water='<tag k="water" v="pond"/>' if i==0 else ''
            relations+=f'<relation id="{i}">{member}<tag k="type" v="multipolygon"/>{water}</relation>'
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{})],relations))
        self.assertEqual(len(d['waterMetadata']['relations']),count)
        self.assertEqual(d['waterMetadata']['ways']['11']['nodeRefs'],['1','2','3','4','1'])
        self.assertEqual(d['waterFeatures'][0]['status'],'needs-review')
        self.assertFalse(d['scenery'])

    def test_unspecified_water_has_no_assumed_lake_type_or_elevation(self):
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{'natural':'water'})]))
        f=d['waterFeatures'][0]
        self.assertEqual(f['kind'],'water-area')
        self.assertIsNone(f['height']['raw'])
        self.assertEqual(f['status'],'metadata-only')
        self.assertFalse(d['scenery'])
        self.assertEqual(len(f['rings'][0]),4)

    def test_member_tagged_water_container_is_retained_with_its_island(self):
        relation='<relation id="20"><member type="way" ref="11" role="outer"/><member type="way" ref="12" role="inner"/><tag k="type" v="multipolygon"/></relation>'
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10),
                               '5':(-2,-2),'6':(2,-2),'7':(2,2),'8':(-2,2)},[
            ('11',['1','2','3','4','1'],{'water':'pond'}),('12',['5','6','7','8','5'],{})],relation))
        self.assertFalse(d['scenery'])
        self.assertEqual(d['waterFeatures'][0]['osmId'],'relation:20')
        self.assertEqual(len(d['waterFeatures'][0]['rings']),2)
        self.assertEqual(set(d['waterMetadata']['ways']),{'11','12'})

    def test_water_node_tags_are_preserved_with_the_original_point_position(self):
        text=fixture({'1':(0,0)},[]).replace('lat="0.5"/>',
            'lat="0.5"><tag k="natural" v="spring"/><tag k="ele" v="78.2"/></node>')
        d=self.convert(text)
        self.assertEqual(d['waterFeatures'][0]['osmId'],'node:1')
        self.assertEqual(d['waterFeatures'][0]['status'],'metadata-only')
        self.assertEqual(d['waterMetadata']['nodes']['1']['tags']['ele'],'78.2')
        self.assertFalse(d['scenery'])

    def test_water_area_river_subtype_is_not_mistaken_for_a_lake(self):
        d=self.convert(fixture({'1':(-10,-10),'2':(10,-10),'3':(10,10),'4':(-10,10)},[
            ('11',['1','2','3','4','1'],{'natural':'water','water':'river'})]))
        self.assertEqual(d['waterFeatures'][0]['kind'],'shallow')
        self.assertEqual(d['waterFeatures'][0]['tags']['water'],'river')
        self.assertTrue(d['scenery'])

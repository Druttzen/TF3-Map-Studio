import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('converter',ROOT/'tools/converter.py')
c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c)

class ConverterTests(unittest.TestCase):
    def test_report_checksums_actual_source_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'map.lua'
            source=ROOT/'tests/sample.osm'
            result=c.export_file(source,output,None,(1000,1000))
            self.assertEqual(result['sourceSha256'],hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(result['luaSha256'],hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(result['alignment']['pngRows'],'north to south')

    def test_oneway_variants_and_override(self):
        for value in ['yes','true','1']:
            self.assertEqual(c.direction({'oneway':value}),1)
        self.assertEqual(c.direction({'oneway':'-1'}),-1)
        self.assertEqual(c.direction({'oneway':'no','junction':'roundabout'}),0)
        self.assertEqual(c.direction({'highway':'motorway'}),1)

    def test_speed_units(self):
        self.assertAlmostEqual(c.speed({'maxspeed':'30 mph'}),48.28032)
        self.assertEqual(c.speed({'maxspeed':'50 km/h'}),50)
        self.assertIsNone(c.speed({'maxspeed':'signals'}))
        self.assertIsNone(c.speed({'maxspeed':'nan'}))

    def test_join_reversed_unordered_members(self):
        rings=c.join_rings([[3,2,1],[1,4,3]])
        self.assertEqual(len(rings),1); self.assertEqual(set(rings[0]),{1,2,3,4})

    def test_incomplete_polygon_rejected(self):
        with self.assertRaises(ValueError): c.join_rings([[1,2,3]])

    def test_ground_hole_area_preserved(self):
        outer=[(0,0),(10,0),(10,10),(0,10)]
        inner=[(3,3),(7,3),(7,7),(3,7)]
        triangles=list(c.triangulate([outer,inner]))
        self.assertAlmostEqual(sum(abs(c.signed_area(t)) for t in triangles),84)
        for triangle in triangles:
            p=tuple(sum(v[axis] for v in triangle)/3 for axis in [0,1])
            self.assertFalse(c.inside(p,inner))

    def test_concave_surface_area(self):
        ring=[(0,0),(5,0),(5,2),(2,2),(2,5),(0,5)]
        self.assertAlmostEqual(sum(abs(c.signed_area(t)) for t in c.triangulate([ring])),16)

    def test_segment_clipped_to_map(self):
        a,b,low,high=c.clip_segment((-10,0),(10,0),10,10)
        self.assertEqual(a,(-5,0)); self.assertEqual(b,(5,0))
        self.assertAlmostEqual(low,.25); self.assertAlmostEqual(high,.75)
        self.assertIsNone(c.clip_segment((-10,10),(10,10),10,10))

    def test_projection_center_and_corners(self):
        bounds=(0,0,1,1); size=(100,200)
        self.assertEqual(c.project(0,0,bounds,size),(-50,-100))
        self.assertAlmostEqual(c.project(1,1,bounds,size)[1],100)

    def test_invalid_configuration(self):
        for bounds in [(0,0,0,1),(1,0,0,1),(0,0,1,0),(-90,0,1,1),(0,0,float('nan'),1)]:
            with self.assertRaises(ValueError): c.validate_bounds(bounds,(100,100))
        with self.assertRaises(ValueError): c.validate_bounds((0,0,1,1),(-1,100))

    def test_pbf_useful_error(self):
        with self.assertRaisesRegex(ValueError,'PBF'): c.read_osm(ROOT/'tests/sample.pbf')

    def test_xml_header_and_sample(self):
        nodes,ways,relations,bounds=c.read_osm(ROOT/'tests/sample.osm')
        self.assertEqual(len(nodes),24); self.assertEqual(bounds,(0,0,.01,.01))
        self.assertIn('200',relations)

    def test_tram_on_road_stays_road(self):
        name,kind=c.choose_template({'highway':'residential','railway':'tram'})
        self.assertEqual(kind,'STREET'); self.assertIn('_tram_electrified',name)

    def test_tram_tracks_survive_small_oneway_and_country_profiles(self):
        for tags in [{'highway':'primary','railway':'tram'},
                     {'highway':'pedestrian','railway':'tram'},
                     {'highway':'residential','railway':'tram','oneway':'yes','lanes':'1'}]:
            name,kind=c.choose_template(tags)
            self.assertEqual(kind,'STREET'); self.assertIn('_tram_electrified',name)

    def test_failed_relation_preserves_independent_closed_area(self):
        import xml.etree.ElementTree as ET
        tree=ET.parse(ROOT/'tests/sample.osm'); root=tree.getroot()
        way=root.find("way[@id='110']")
        for child in list(way): way.remove(child)
        for ref in ['9','10','11','12','9']: ET.SubElement(way,'nd',ref=ref)
        ET.SubElement(way,'tag',k='landuse',v='forest')
        root.find("relation[@id='200']/member[@ref='111']").set('ref','missing')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'area.osm'; tree.write(path)
            data=c.convert(path,None,(1000,1000))
        self.assertTrue(any('missing' in w for w in data['warnings']))
        self.assertGreater(sum(item.get('model') in c.TREES for item in data['scenery']),1)

    def test_bad_node_coordinates_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.osm'
            path.write_text('<osm><node id="1" lat="nan" lon="0"/></osm>')
            with self.assertRaisesRegex(ValueError,'coordinates'): c.read_osm(path)

    def test_explicit_bounds_override_xml_header(self):
        bounds=(0,0,.02,.02)
        data=c.convert(ROOT/'tests/sample.osm',bounds,(1000,1000))
        self.assertEqual(data['bounds'],list(bounds))
        self.assertAlmostEqual(data['nodes']['2']['pos'][0],-250)

    def test_export_reversed_street_and_property_transitions(self):
        data=c.convert(ROOT/'tests/sample.osm',None,(1000,1000))
        reverse=[e for e in data['edges'] if e['osmWay']=='102']
        self.assertEqual(reverse[0]['node0'],'5'); self.assertEqual(reverse[-1]['node1'],'2')
        self.assertTrue(all(e['oneway'] and e['lanes']=='1' for e in reverse))
        normal=[e for e in data['edges'] if e['osmWay']=='101']
        self.assertTrue(all(e['lanes']=='2' and e['speed']==30 for e in normal))
        self.assertIn('2',data['nodes'])

    def test_forest_holes_and_determinism(self):
        a=c.convert(ROOT/'tests/sample.osm',None,(1000,1000))
        b=c.convert(ROOT/'tests/sample.osm',None,(1000,1000))
        self.assertEqual(a,b)
        trees=[x for x in a['scenery'] if x.get('model') in c.TREES]
        self.assertGreater(len(trees),0)
        nodes,_,_,bounds=c.read_osm(ROOT/'tests/sample.osm')
        hole=[c.project(*nodes[id][:2],bounds,(1000,1000)) for id in ['20','21','22','23']]
        self.assertTrue(all(not c.inside(x['pos'],hole) for x in trees))

    def test_independently_tagged_inner_landuse_keeps_its_surface(self):
        import xml.etree.ElementTree as ET
        for landuse,texture in [('meadow',c.GROUND['grass']),('farmland',c.GROUND['dirt'])]:
            with self.subTest(landuse=landuse),tempfile.TemporaryDirectory() as folder:
                tree=ET.parse(ROOT/'tests/sample.osm'); root=tree.getroot()
                ET.SubElement(root.find("way[@id='112']"),'tag',k='landuse',v=landuse)
                source=Path(folder)/'areas.osm';tree.write(source)
                data=c.convert(source,None,(1000,1000),options={'max_generated_trees':0})
                inner_faces=[item['face'] for item in data['scenery'] if item.get('texture')==texture]
                self.assertEqual(len(inner_faces),2)
                # The enclosing relation must not change the clearing's own area.
                root.remove(root.find("relation[@id='200']"));tree.write(source)
                standalone=c.convert(source,None,(1000,1000),options={'max_generated_trees':0})
                self.assertEqual(inner_faces,[item['face'] for item in standalone['scenery']
                                              if item.get('texture')==texture])

    def test_tagged_inner_relation_is_built_once_and_still_excludes_forest(self):
        import xml.etree.ElementTree as ET
        tree=ET.parse(ROOT/'tests/sample.osm');root=tree.getroot()
        ET.SubElement(root.find("way[@id='112']"),'tag',k='landuse',v='meadow')
        nested=ET.SubElement(root,'relation',id='201')
        ET.SubElement(nested,'member',type='way',ref='112',role='outer')
        ET.SubElement(nested,'tag',k='type',v='multipolygon')
        ET.SubElement(nested,'tag',k='landuse',v='meadow')
        member=root.find("relation[@id='200']/member[@ref='112']")
        member.set('type','relation');member.set('ref','201')
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'nested.osm';tree.write(source)
            data=c.convert(source,None,(1000,1000))
            nodes,_,_,bounds=c.read_osm(source)
        inner_faces=[item['face'] for item in data['scenery'] if item.get('texture')==c.GROUND['grass']]
        self.assertEqual(len(inner_faces),2)
        hole=[c.project(*nodes[id][:2],bounds,(1000,1000)) for id in ['20','21','22','23']]
        trees=[item for item in data['scenery'] if item.get('category')=='vegetation']
        self.assertTrue(trees)
        self.assertTrue(all(not c.inside(item['pos'],hole) for item in trees))

    def test_tagged_outer_outline_does_not_duplicate_relation_vegetation(self):
        import xml.etree.ElementTree as ET
        tree=ET.parse(ROOT/'tests/sample.osm');root=tree.getroot()
        way=root.find("way[@id='110']")
        for child in list(way):way.remove(child)
        for ref in ['9','10','11','12','9']:ET.SubElement(way,'nd',ref=ref)
        relation=root.find("relation[@id='200']")
        relation.remove(relation.find("member[@ref='111']"))
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'outer.osm';tree.write(source)
            baseline=c.convert(source,None,(1000,1000))
            ET.SubElement(way,'tag',k='landuse',v='forest');tree.write(source)
            tagged=c.convert(source,None,(1000,1000))
        vegetation=lambda data:[item for item in data['scenery'] if item.get('category')=='vegetation']
        self.assertTrue(vegetation(baseline))
        self.assertEqual(vegetation(baseline),vegetation(tagged))

    def test_tree_limit(self):
        data=c.convert(ROOT/'tests/sample.osm',None,(1000,1000),max_trees=2)
        self.assertEqual(sum(item.get('model') in c.TREES for item in data['scenery']),2)
        self.assertTrue(any('limit reached' in warning for warning in data['warnings']))

    def test_atomic_export_and_input_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'mod'; target.mkdir()
            (target/'mod.json').write_text(json.dumps({'modId':c.MOD_ID}))
            source=ROOT/'tests/sample.osm'; before=source.read_bytes()
            report=c.export(source,target,None,(1000,1000))
            self.assertGreater(report['edges'],0)
            self.assertTrue((target/'content/osm/dataset.lua').exists())
            self.assertEqual(source.read_bytes(),before)
            self.assertEqual(json.loads((target/'import-report.json').read_text())['dataset'],report['dataset'])

    def test_wrong_mod_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError): c.export(ROOT/'tests/sample.osm',tmp,None,(100,100))

    def test_serializer_control_characters(self):
        text=c.lua('quote" newline\n snow â˜ƒ slash\\')
        self.assertIn('\\010',text); self.assertIn('\\"',text)
        self.assertNotIn('\n',text)

class ClippedStructureTests(unittest.TestCase):
    def converters(self):
        yield c
        vendor=ROOT.parent/'TF3-Heightmap-Studio/vendor/osm_converter.py'
        if not vendor.is_file():return
        spec=importlib.util.spec_from_file_location('heightmap_vendor_structure_review',vendor)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        yield module

    def fixture(self,kind='bridge',middle=''):
        return f'''<osm version="0.6"><bounds minlat="0" minlon="0" maxlat="1" maxlon="1"/>
        <node id="1" lat="0.5" lon="-0.5"/><node id="2" lat="0.5" lon="0.25"/>
        <node id="3" lat="0.5" lon="0.75"/><node id="4" lat="0.5" lon="1.5"/>
        <way id="10"><nd ref="1"/>{middle}<nd ref="4"/>
        <tag k="highway" v="residential"/><tag k="{kind}" v="yes"/></way></osm>'''

    def convert(self,module,text):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'structure.osm';source.write_text(text,encoding='utf-8')
            return module.convert(source,None,(1000,1000))

    def test_crossing_structures_parameterize_the_whole_visible_chain(self):
        for module in self.converters():
            for kind in ('bridge','tunnel'):
                for middle in ('','<nd ref="2"/><nd ref="3"/>'):
                    with self.subTest(module=module.__name__,kind=kind,middle=middle):
                        data=self.convert(module,self.fixture(kind,middle))
                        guides=[e['heightGuide'] for e in data['edges']]
                        self.assertEqual(guides[0]['t0'],0)
                        self.assertEqual(guides[-1]['t1'],1)
                        for edge in data['edges']:
                            guide=edge['heightGuide']
                            self.assertAlmostEqual(guide['start'][0],-500)
                            self.assertAlmostEqual(guide['finish'][0],500)
                            for key,node_key in (('t0','node0'),('t1','node1')):
                                self.assertAlmostEqual(guide[key],(data['nodes'][edge[node_key]]['pos'][0]+500)/1000,places=8)

    def test_visible_chains_do_not_interpolate_across_an_off_map_gap(self):
        refs=['a','b','c','d','e','f']
        positions={'a':(-1000,0),'b':(-250,0),'c':(-250,1000),
                   'd':(250,1000),'e':(250,0),'f':(1000,0)}
        for module in self.converters():
            guides=module.structure_height_guides(refs,positions,(1000,1000))
            self.assertEqual(set(guides),{0,1,3,4})
            self.assertEqual(guides[0]['start'],[-500,0])
            self.assertEqual(guides[0]['finish'],[-250,500])
            self.assertEqual(guides[3]['start'],[250,500])
            self.assertEqual(guides[4]['finish'],[500,0])
            self.assertEqual(guides[0]['offset'],0)
            self.assertEqual(guides[3]['offset'],0)

    def test_actual_lua_builder_joins_clipped_bridge_to_sloping_terrain(self):
        import test_game_scripts as game
        data=self.convert(c,self.fixture('bridge','<nd ref="2"/><nd ref="3"/>'))
        harness=game.GameScriptTests();harness.setUp()
        harness.lua.globals().dataset=harness.lua.execute('return '+c.lua(data))
        harness.lua.globals().modules['druttzen_osm_vanilla::/osm/dataset.lua']=harness.lua.globals().dataset
        harness.script=game.load_script(harness.lua,game.CONTENT/'importer.script.lua')
        harness.lua.execute('api.engine.terrain.getBaseHeightAt=function(p) return p.x/10 end; api.engine.terrain.getHeightAt=api.engine.terrain.getBaseHeightAt')
        harness.event('start');harness.finish()
        proposals=harness.edge_proposals()
        for proposal in proposals:
            comp=proposal.streetProposal.edgesToAdd[1].comp
            for point in (comp.position0,comp.position1):
                self.assertAlmostEqual(point.z,point.x/10,delta=.001)


if __name__=='__main__': unittest.main()

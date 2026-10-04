"""OSM source tags, building footprints, settlements and unsupported categories."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from converter import convert, lua
from map_objects import tagged_height
from lupa import LuaRuntime


OSM='''<osm version="0.6"><bounds minlat="0" minlon="0" maxlat="0.01" maxlon="0.01"/>
<node id="1" lat="0.004" lon="0.004"/><node id="2" lat="0.004" lon="0.006"/>
<node id="3" lat="0.006" lon="0.006"/><node id="4" lat="0.006" lon="0.004"/>
<node id="5" lat="0.005" lon="0.005"><tag k="place" v="city"/><tag k="name" v="Partille"/><tag k="population" v="30000"/></node>
<node id="6" lat="0.002" lon="0.002"><tag k="amenity" v="bench"/><tag k="material" v="wood"/></node>
<node id="7" lat="0.008" lon="0.008"><tag k="railway" v="station"/><tag k="name" v="Station"/></node>
<way id="11"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
<tag k="building" v="apartments"/><tag k="building:levels" v="4"/><tag k="ele" v="18"/></way>
</osm>'''


class MappedObjectTests(unittest.TestCase):
    def convert(self,text=OSM,**options):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mapped.osm'; path.write_text(text,encoding='utf8')
            return convert(path,None,size=(1000,1000),options=options or None)

    def test_buildings_keep_class_polygon_and_original_height_without_game_height_guess(self):
        data=self.convert()
        building=next(s for s in data['scenery'] if s['category']=='buildings')
        self.assertEqual(building['match']['kind'],'residential')
        self.assertEqual(len(building['footprint']),4)
        self.assertEqual(building['osm']['tags'],{'building':'apartments','building:levels':'4','ele':'18'})
        self.assertEqual(building['osm']['id'],'11')
        self.assertEqual(len(building['pos']),2)
        self.assertNotIn('model',building)

    def test_city_and_amenity_tags_survive_lua_roundtrip_and_unsupported_station_is_visible(self):
        data=self.convert(); runtime=LuaRuntime()
        restored=runtime.execute('return '+lua(data))
        self.assertEqual(restored.labels[1].place,'city')
        self.assertEqual(restored.labels[1].osm.tags.population,'30000')
        bench=next(s for s in data['scenery'] if s['category']=='mappedObjects')
        self.assertEqual(bench['match']['kind'],'bench')
        self.assertEqual(bench['osm']['tags']['material'],'wood')
        self.assertIn({'tag':'railway=station','count':1},data['unavailableObjects'])

    def test_relation_building_does_not_duplicate_its_outer_way(self):
        text=OSM.replace('</osm>','''<relation id="21"><member type="way" ref="11" role="outer"/>
        <tag k="type" v="multipolygon"/><tag k="building" v="apartments"/></relation></osm>''')
        buildings=[s for s in self.convert(text)['scenery'] if s['category']=='buildings']
        self.assertEqual(len(buildings),1)
        self.assertEqual(buildings[0]['osm']['type'],'relation')

    def test_place_area_and_node_are_deduplicated_and_conversion_is_repeatable(self):
        text=OSM.replace('<tag k="building" v="apartments"/>','<tag k="building" v="apartments"/><tag k="place" v="city"/><tag k="name" v="Partille"/>')
        first=self.convert(text); second=self.convert(text)
        self.assertEqual(len(first['labels']),1)
        self.assertEqual(first['id'],second['id'])

    def test_partial_or_outside_footprints_are_not_filled_with_arbitrary_buildings(self):
        text=OSM.replace('<nd ref="4"/>','<nd ref="99"/>')
        data=self.convert(text)
        self.assertFalse(any(s['category']=='buildings' for s in data['scenery']))
        self.assertIn({'tag':'incomplete_object_geometry','count':1},data['unavailableObjects'])

    def test_courtyard_outer_is_not_reimported_as_a_solid_building(self):
        text=OSM.replace('</osm>','''<node id="31" lat="0.0045" lon="0.0045"/>
        <node id="32" lat="0.0045" lon="0.0055"/><node id="33" lat="0.0055" lon="0.0055"/>
        <node id="34" lat="0.0055" lon="0.0045"/>
        <way id="35"><nd ref="31"/><nd ref="32"/><nd ref="33"/><nd ref="34"/><nd ref="31"/></way>
        <relation id="21"><member type="way" ref="11" role="outer"/><member type="way" ref="35" role="inner"/>
        <tag k="type" v="multipolygon"/><tag k="building" v="apartments"/></relation></osm>''')
        data=self.convert(text)
        self.assertFalse(any(s['category']=='buildings' for s in data['scenery']))
        self.assertIn({'tag':'complex_object_geometry','count':1},data['unavailableObjects'])

    def test_explicit_height_units_can_rank_models_without_guessing_levels_or_elevation(self):
        self.assertAlmostEqual(tagged_height({'height':'30 ft'}),9.144)
        self.assertEqual(tagged_height({'height':'12 m'}),12)
        self.assertIsNone(tagged_height({'height':'unknown','building:levels':'4','ele':'18'}))
        self.assertIsNone(tagged_height({'building:levels':'4'}))
        data=self.convert(OSM.replace('<tag k="ele" v="18"/>','<tag k="ele" v="18"/><tag k="height" v="12 m"/>'))
        building=next(s for s in data['scenery'] if s['category']=='buildings')
        self.assertEqual(building['match']['height'],12)
        self.assertEqual(len(building['pos']),2)

if __name__=='__main__': unittest.main()

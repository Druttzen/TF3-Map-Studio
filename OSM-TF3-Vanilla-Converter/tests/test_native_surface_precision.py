"""Huge-map ground faces must remain polygons at native coordinate precision."""
import unittest
from unittest.mock import patch

import test_converter as converter_tests

c=converter_tests.c

# The face at scenery source index 172332 in the reported Huge-map failure.
COLLAPSED=[(-10240,8821.498023327178),
           (-10239.531158446041,8821.498332458224),
           (-10240,8821.498332458224)]


class NativeSurfacePrecisionTests(unittest.TestCase):
    def test_reported_face_has_area_but_collapses_in_native_coordinates(self):
        self.assertGreater(c.signed_area(COLLAPSED),1e-5)
        self.assertEqual(c.native_surface_area(COLLAPSED),0)

    def test_valid_thin_face_survives_without_a_broad_area_cutoff(self):
        face=[(-10240,8821.498),(-10239.5,8821.499),(-10240,8821.499)]
        self.assertGreater(c.native_surface_area(face),0)
        self.assertLess(c.native_surface_area(face),.001)

    def test_translated_area_avoids_large_coordinate_cancellation(self):
        face=[(10240,10240),(10240.001,10240),(10240,10240.001)]
        self.assertAlmostEqual(c.signed_area(face),.0000005,places=14)

    def test_clipped_duplicate_and_closing_vertices_are_removed(self):
        a,b,d=(0,0),(2,0),(0,2)
        self.assertEqual(c.clean_surface_face([a,a,b,b,d,a]),[a,b,d])

    def test_native_duplicate_pairs_are_cleaned_without_rounding_output(self):
        a,b,d=(10000,8000),(10002,8000),(10000,8002)
        near_a=(10000.0001,8000.0001)
        near_b=(10002.0001,8000.0001)
        self.assertEqual(c.clean_surface_face([a,near_a,b,near_b,d,near_a]),[a,b,d])

    def test_conversion_reports_only_native_collapsed_omission(self):
        good=[(-10240,8821.498),(-10239.5,8821.499),(-10240,8821.499)]
        features={key:key=='surfaces' for key in c.normalize_options()['features']}
        with patch.object(c,'triangulate',side_effect=lambda _: iter([COLLAPSED,good])):
            data=c.convert(converter_tests.ROOT/'tests/sample.osm',None,(20480,20480),
                           options={'features':features})
        surfaces=[item for item in data['scenery'] if item.get('category')=='surfaces']
        self.assertEqual(len(surfaces),1)
        self.assertEqual(surfaces[0]['face'],[list(p) for p in good])
        self.assertTrue(any('1 ground surface face(s) omitted' in text for text in data['warnings']))


if __name__=='__main__': unittest.main()

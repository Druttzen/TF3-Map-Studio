"""Game map presets, saved selections and export alignment."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from lupa import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from map_sizes import SIZES, FORMATS, dimensions, matching_preset, experimental
from gui import validate_profile
from converter import export_file


class MapSizeTests(unittest.TestCase):
    def test_every_game_size_and_format_has_exact_metres(self):
        # Independent snapshot of getNumTiles() in the installed game's source.
        expected=[
            [(4096,4096),(2560,5120),(2048,6144),(2048,6144),(1536,7680)],
            [(8192,8192),(5632,11264),(4608,13824),(4096,13824),(3584,17920)],
            [(11264,11264),(8192,16384),(6656,19968),(5632,22528),(5120,25600)],
            [(14336,14336),(10240,20480),(8192,24576),(7168,28672),(6144,32256)],
            [(16384,16384),(11264,22528),(9216,27648),(8192,32768),(7168,35840)],
            [(20480,20480),(14336,28672),(11776,35328),(10240,40960),(8704,43520)],
            [(24576,24576),(16896,33792),(13824,41472),(12288,49152),(10752,53760)],
            [(28672,28672),(20480,40960),(16384,49152),(14336,57344),(12800,64000)],
        ]
        self.assertEqual(len(SIZES),8); self.assertEqual(len(FORMATS),5)
        for name,row in zip(SIZES,expected):
            for fmt,metres in zip(FORMATS,row):
                with self.subTest(size=name,format=fmt):
                    self.assertEqual(dimensions(name,fmt),metres)

    def test_all_presets_export_exact_size_and_bounds_to_lua_and_log(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'map.lua'
            for name in SIZES:
                for fmt in FORMATS:
                    with self.subTest(size=name,format=fmt):
                        size=dimensions(name,fmt)
                        export_file(ROOT/'tests/sample.osm',output,None,size,
                                    options={'max_generated_trees':0})
                        report=json.loads(output.with_suffix('.report.json').read_text())
                        data=LuaRuntime().execute(output.read_text(encoding='utf-8'))
                        self.assertEqual(report['mapSize'],list(size))
                        self.assertEqual([data['size'][1],data['size'][2]],list(size))
                        self.assertEqual([data['bounds'][i] for i in range(1,5)],report['bounds'])

    def test_profiles_preserve_duplicate_formats_and_explicit_custom(self):
        for preset in [{'size':'Tiny','format':'1:3'},{'size':'Tiny','format':'1:4'},None]:
            profile={'version':1,'size':[2048,6144],'mapPreset':preset}
            loaded=validate_profile(json.loads(json.dumps(profile)))
            self.assertEqual(loaded['mapPreset'],preset)
            self.assertEqual(loaded['size'],profile['size'])
        self.assertEqual(matching_preset([2048,6144]),{'size':'Tiny','format':'1:3'})
        self.assertIsNone(matching_preset([1000,1000]))
        self.assertNotIn('mapPreset',validate_profile({'version':1,'size':[1000,1000]}))

    def test_mismatched_and_invalid_saved_presets_rejected(self):
        for preset in [{'size':'Medium','format':'1:1'}, {'size':'Unknown','format':'1:1'},
                       {'size':'Tiny','format':'2:1'}, {'size':[],'format':'1:1'}, [], {'size':'Tiny'}]:
            with self.subTest(preset=preset), self.assertRaises(ValueError):
                validate_profile({'version':1,'size':[2048,6144],'mapPreset':preset})

    def test_experimental_options_match_desktop_game_filters(self):
        for name in SIZES:
            for fmt in FORMATS:
                self.assertEqual(experimental(name,fmt),name in SIZES[:1]+SIZES[5:] or fmt in FORMATS[3:])


if __name__=='__main__': unittest.main()

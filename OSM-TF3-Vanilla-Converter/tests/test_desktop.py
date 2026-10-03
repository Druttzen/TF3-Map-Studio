"""Behavior checks for desktop settings, exports, progress and cancellation."""
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from lupa import LuaRuntime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import converter as c
from settings import DEFAULTS, FEATURES, MODELS, MATERIALS, normalize_options
from job import Cancelled
from gui import validate_profile, MODES
SAMPLE=ROOT/'tests/sample.osm'

class DesktopTests(unittest.TestCase):
    def convert(self,**options): return c.convert(SAMPLE,None,[1000,1000],options=options)

    def test_each_feature_can_be_disabled(self):
        baseline=self.convert()
        none=self.convert(features={key:False for key in FEATURES})
        self.assertEqual(none['edges'],[]); self.assertEqual(none['scenery'],[]); self.assertEqual(none['labels'],[])
        for key in ['roads','railways','forests','surfaces','fountains','bollards','advertising_columns','place_markers']:
            changed=self.convert(features={key:False})
            self.assertNotEqual((len(changed['edges']),len(changed['scenery']),len(changed['labels'])),(len(baseline['edges']),len(baseline['scenery']),len(baseline['labels'])),key)

    def test_disabling_roads_does_not_convert_tram_street_into_track(self):
        data=self.convert(features={'roads':False})
        self.assertTrue(data['edges']); self.assertTrue(all(e['kind']=='TRACK' for e in data['edges']))
        self.assertTrue(all(e['osmWay']=='103' for e in data['edges']))

    def test_profiles_and_electrification_change_native_templates(self):
        data=self.convert(rail_profile='High speed',electrification='Never overhead',road_style='Country')
        rails=[e for e in data['edges'] if e['kind']=='TRACK']
        self.assertTrue(all('high_speed/high_speed.street_template' in e['template'] for e in rails))
        self.assertTrue(any('/country/' in e['template'] for e in data['edges']))
        self.assertTrue(any('one_way' in e['template'] for e in data['edges']))
        t,k=c.choose_template({'railway':'rail'},normalize_options({'electrification':'Always overhead','rail_profile':'Simple'}))
        self.assertIn('simple_catenary',t)

    def test_subdivision_changes_count_and_preserves_length(self):
        short=self.convert(road_segment_length=10,rail_segment_length=15)
        default=self.convert()
        self.assertGreater(len(short['edges']),len(default['edges']))
        def length(data): return sum(__import__('math').dist(data['nodes'][e['node0']]['pos'],data['nodes'][e['node1']]['pos']) for e in data['edges'])
        self.assertAlmostEqual(length(short),length(default),places=4)

    def test_seed_palettes_density_and_limit(self):
        a=self.convert(seed='north',broadleaf_species=['Pine'],forest_spacing=30,max_generated_trees=12)
        b=self.convert(seed='north',broadleaf_species=['Pine'],forest_spacing=30,max_generated_trees=12)
        self.assertEqual(a,b)
        vegetation=[item for item in a['scenery'] if item.get('category')=='vegetation']
        self.assertEqual(len(vegetation),12)
        self.assertTrue(all(item['model']==MODELS['Pine'] for item in vegetation))
        self.assertNotEqual(a['scenery'],self.convert(seed='south',broadleaf_species=['Pine'],forest_spacing=30,max_generated_trees=12)['scenery'])
        self.assertFalse(any(item['category']=='vegetation' for item in self.convert(max_generated_trees=0)['scenery']))

    def test_object_and_surface_mappings_preserve_category(self):
        data=self.convert(object_models={'fountain':'Oak'},surface_materials={'asphalt':'Cut grass'},object_rotation=90)
        self.assertTrue(any(item.get('model')==MODELS['Oak'] and item['category']=='objects' for item in data['scenery']))
        self.assertTrue(all(item['texture']==MATERIALS['Cut grass'] for item in data['scenery'] if 'texture' in item))
        self.assertTrue(any(abs(item['rotation']-__import__('math').pi/2)<1e-9 for item in data['scenery'] if item['category']=='objects'))

    def test_invalid_settings_fail_with_clear_errors(self):
        for options in [{'forest_spacing':1},{'forest_spacing':float('nan')},{'max_generated_trees':1.5},
                        {'tree_jitter':.5},{'import_batch_size':0},{'import_delay':3},
                        {'features':{'roads':1}},{'features':{'unknown':True}},
                        {'object_models':{'tree':'external-mod::/tree.mdl'}},
                        {'object_models':{'tree':[]}},{'broadleaf_species':[]},
                        {'broadleaf_species':[['invalid']]},{'seed':False},{'unknown':1}]:
            with self.subTest(options=options),self.assertRaises(ValueError): normalize_options(options)

    def test_defaults_not_mutated(self):
        opts=normalize_options({'features':{'roads':False}}); opts['broadleaf_species'].append('Fir')
        self.assertTrue(DEFAULTS['features']['roads']); self.assertNotIn('Fir',DEFAULTS['broadleaf_species'])

    def test_standalone_lua_and_report_without_game(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'map.lua'
            report=c.export_file(SAMPLE,output,None,[1000,1000],options={'import_batch_size':17,'import_delay':.5})
            data=LuaRuntime().execute(output.read_text(encoding='utf-8'))
            self.assertEqual(len(data.edges),report['edges']); self.assertEqual(data.importOptions.batchSize,17)
            self.assertEqual(data.importOptions.interval,.5)
            stored=json.loads(output.with_suffix('.report.json').read_text())
            self.assertEqual(stored['dataset'],data.id); self.assertNotIn('_preview',stored)
            self.assertEqual(stored['settings']['import_batch_size'],17)
            self.assertEqual(set(p.name for p in Path(folder).iterdir()),{'map.lua','map.report.json'})

    def test_progress_monotonic_reaches_completion_after_files_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'map.lua'; updates=[]
            def progress(pct,stage,detail):
                updates.append(pct)
                if pct==100: self.assertTrue(output.exists() and output.with_suffix('.report.json').exists())
            c.export_file(SAMPLE,output,None,[1000,1000],progress=progress)
            self.assertEqual(updates,sorted(updates)); self.assertEqual(updates[0],0); self.assertEqual(updates[-1],100)
            self.assertGreater(len(updates),6)

    def test_cancel_at_each_stage_preserves_existing_outputs(self):
        for stage in ['Reading OSM','Building networks','Generating scenery','Writing Lua map','Saving output files']:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                output=Path(folder)/'map.lua'; output.write_text('old lua'); report=output.with_suffix('.report.json'); report.write_text('old report')
                event=threading.Event(); updates=[]
                def progress(pct,current,detail):
                    updates.append(pct)
                    if current==stage: event.set()
                with self.assertRaises(Cancelled): c.export_file(SAMPLE,output,None,[1000,1000],progress=progress,cancel=event)
                self.assertEqual(output.read_text(),'old lua'); self.assertEqual(report.read_text(),'old report')
                self.assertNotIn(100,updates); self.assertEqual(len(list(Path(folder).iterdir())),2)

    def test_report_commit_failure_rolls_back_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'map.lua'; output.write_text('old lua'); report=output.with_suffix('.report.json'); report.write_text('old report')
            replace=c.os.replace
            def fail_report(src,dst):
                if Path(dst)==report: raise OSError('simulated locked report')
                return replace(src,dst)
            with patch.object(c.os,'replace',side_effect=fail_report),self.assertRaises(OSError): c.export_file(SAMPLE,output,None,[1000,1000])
            self.assertEqual(output.read_text(),'old lua'); self.assertEqual(report.read_text(),'old report')
            self.assertEqual(len(list(Path(folder).iterdir())),2)

    def test_new_mod_is_self_contained_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/c.MOD_FOLDER
            report=c.export_new_mod(SAMPLE,target,None,[1000,1000])
            self.assertEqual(target.name,'tf3_osm_importer_mod')
            self.assertEqual(json.loads((target/'mod.json').read_text())['modId'],'druttzen_osm_vanilla')
            self.assertEqual(json.loads((target/'_metadata/modinfo.json').read_text())['name'],'TF3-OSM-Importer-Mod')
            self.assertTrue((target/'content/osm/panel.res.lua').is_file()); self.assertTrue((target/'LICENSE').is_file())
            self.assertEqual(Path(report['output']),target/'content/osm/dataset.lua')
            self.assertEqual(json.loads((target/'import-report.json').read_text())['output'],report['output'])
            with self.assertRaisesRegex(ValueError,'already exists'): c.export_new_mod(SAMPLE,target,None,[1000,1000])
            self.assertEqual(len(list(Path(folder).iterdir())),1)

    def test_cancel_new_mod_leaves_no_partial_mod(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/c.MOD_FOLDER; event=threading.Event()
            def progress(pct,stage,detail):
                if stage=='Generating scenery': event.set()
            with self.assertRaises(Cancelled): c.export_new_mod(SAMPLE,target,None,[1000,1000],cancel=event,progress=progress)
            self.assertFalse(target.exists()); self.assertEqual(list(Path(folder).iterdir()),[])

    def test_existing_legacy_and_renamed_folders_accept_dataset_updates_by_mod_id(self):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            for name in ('druttzen_osm_vanilla','tf3_osm_importer_mod'):
                target=Path(folder)/name
                shutil.copytree(c.template_folder(),target)
                report=c.export(SAMPLE,target,None,[1000,1000])
                self.assertEqual(Path(report['output']),target/'content/osm/dataset.lua')
                self.assertEqual(json.loads((target/'mod.json').read_text())['modId'],'druttzen_osm_vanilla')

    def test_profile_roundtrip_preserves_all_options_and_bounds(self):
        profile={'version':1,'options':normalize_options({'tree_jitter':.1,'seed':'Sweden','features':{'roads':False},'import_batch_size':25}),
                 'size':[4000,8000],'bounds':[59,18,60,19],'mode':MODES[2],'source':'input.osm','target':'new-mod'}
        self.assertEqual(validate_profile(json.loads(json.dumps(profile))),profile)
        for patch_value in [{'version':2},{'size':[0,4]},{'bounds':[60,18,59,19]},{'options':{'seed':0}}]:
            with self.assertRaises(ValueError): validate_profile({**profile,**patch_value})

    def test_wrong_output_extension_rejected(self):
        with self.assertRaisesRegex(ValueError,'.lua'): c.export_file(SAMPLE,'map.txt',None,[1000,1000])

    def test_structures_and_paths_filtered_and_tunnel_depth_exported(self):
        xml='<osm><bounds minlat="0" minlon="0" maxlat="1" maxlon="1"/><node id="1" lat="0.2" lon="0.2"/><node id="2" lat="0.8" lon="0.8"/>'
        for id,key,value in [('a','bridge','yes'),('b','tunnel','yes'),('c','highway','footway'),('d','railway','disused')]:
            tags=f'<tag k="{key}" v="{value}"/>'+( '<tag k="highway" v="residential"/>' if key!='highway' and key!='railway' else '')
            xml+=f'<way id="{id}"><nd ref="1"/><nd ref="2"/>{tags}</way>'
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'features.osm'; file.write_text(xml+'</osm>')
            data=c.convert(file,None,[1000,1000],options={'features':{'bridges':False,'footpaths':False,'disused_tracks':False},'tunnel_depth':20})
            self.assertTrue(data['edges']); self.assertTrue(all(e['osmWay']=='b' for e in data['edges']))
            self.assertTrue(all(e['heightGuide']['depth']==20 for e in data['edges']))
            data=c.convert(file,None,[1000,1000],options={'features':{'tunnels':False}})
            self.assertFalse(any(e['tunnel'] for e in data['edges']))

if __name__=='__main__': unittest.main()

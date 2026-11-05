"""Shallow beds in the game mod; saved geometry and priority protection."""
import unittest
import test_game_scripts as game
from test_game_scripts import CONTENT, load_script


class ShallowWaterTests(unittest.TestCase):
    def setUp(self):
        self.h=game.GameScriptTests(); self.h.setUp(); self.lua=self.h.lua
        self.lua.execute('''
          api.type.Vec4f={new=function(x,y,z,w) return {x,y,z,w} end}
          api.type.Mat4f={new=function(...) return {...} end}
          api.type.Box3={new=function(a,b) return {min=a,max=b} end}
          api.engine.system={octreeSystem={findIntersectingEntities=function(box,callback)
            waterQuery=box; if blockedWater then callback(blockedWater,{}) end end}}
          dataset.edges={}; dataset.labels={}; dataset.scenery={{category="waterways",depth=.5,
            texture="druttzen_osm_vanilla::/osm/dirty_water.gtex",face={{0,0},{4,0},{0,4}}}}
        ''')
        self.h.event('configure',dict(waterways=True))

    def test_bed_is_half_metre_below_base_terrain_only_when_built(self):
        self.h.event('validate'); self.assertEqual(len(self.lua.globals().commands),0)
        self.h.event('start'); self.h.step()
        item=self.lua.globals().commands[1].constructionsToAdd[1].params['items'][1]
        self.assertTrue(all(p[3]==9.5 for p in item.face.values()))
        sub=load_script(self.lua,CONTENT/'scenery.script.lua').updateFn(None,self.lua.globals().commands[1].constructionsToAdd[1].params).subconstructions[1]
        self.assertEqual(sub.terrainAlignmentLists[2].type,'LESS')
        self.assertEqual(sub.groundFaces[1].modes[1].key,'druttzen_osm_vanilla::/osm/dirty_water.gtex')
        self.assertEqual(len(sub.groundFaces[1].modes[1].texCoords),3)
        self.assertEqual(len(sub.models),0)

    def test_rejected_proposal_and_reload_reuse_original_bed_heights(self):
        self.lua.globals().failNext=True; self.h.event('start'); self.h.step()
        self.lua.execute('api.engine.terrain.getBaseHeightAt=function(_) return 40 end')
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.event('retry'); self.h.step()
        item=self.lua.globals().commands[2].constructionsToAdd[1].params['items'][1]
        self.assertEqual(item.face[1][3],9.5)

    def test_existing_network_blocks_excavation_before_native_command(self):
        self.lua.execute('blockedWater=100; components[100]={node0=1}')
        self.h.event('start'); self.h.step()
        self.assertEqual(self.h.state.value.phase,'error')
        self.assertIn('network heights have priority',self.h.state.value.error)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_nonfinite_or_out_of_range_height_never_builds(self):
        self.lua.execute('api.engine.terrain.getBaseHeightAt=function(_) return -1000 end')
        self.h.event('start'); self.h.step()
        self.assertEqual(len(self.lua.globals().commands),0)
        self.assertIn('Invalid shallow-water terrain height',self.h.state.value.error)

    def test_other_importer_batches_do_not_block_shared_water_boundaries(self):
        self.lua.execute('blockedWater=100; components[100]={fileName="druttzen_osm_vanilla::/osm/scenery.con"}')
        self.h.event('start'); self.h.finish()
        self.assertEqual(len(self.lua.globals().commands),1)

    def test_shallow_water_can_be_deselected_without_disabling_other_surfaces(self):
        self.h.event('configure',dict(waterways=False))
        self.h.event('start')
        self.assertIn('No dataset items match',self.h.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_lake_height_is_shared_across_batches_and_stream_follows_terrain(self):
        self.lua.execute('''
          local lake=dataset.scenery[1]
          lake.depth=nil; lake.waterSurface="flat"; lake.osmWater="way:123"; lake.waterAnchor={2,2}
          dataset.scenery[2]={category="waterways",waterSurface="flat",osmWater=lake.osmWater,
            waterAnchor=lake.waterAnchor,texture=lake.texture,face={{4,0},{4,4},{0,4}}}
          dataset.scenery[3]={category="waterways",waterSurface="follow",osmWater="way:456",
            texture=lake.texture,face={{30,0},{34,0},{30,4}}}
          api.engine.terrain.getBaseHeightAt=function(p) return 10+p.x+p.y end
        ''')
        self.h.event('configure',dict(batchSize=1))
        self.h.event('start')
        self.h.step()
        self.lua.execute('api.engine.terrain.getBaseHeightAt=function(p) return 20+p.x+p.y end')
        self.h.finish()
        script=load_script(self.lua,CONTENT/'scenery.script.lua')
        expected=[[14,14,14],[14,14,14],[50,54,54]]
        for index,heights in enumerate(expected,1):
            params=self.lua.globals().commands[index].constructionsToAdd[1].params
            self.assertEqual([p[3] for p in params['items'][1].face.values()],heights)
            alignment=script.updateFn(None,params).subconstructions[1].terrainAlignmentLists[1]
            self.assertEqual(alignment.type,'EQUAL')
            self.assertEqual(len(alignment.faces),1)

    def test_one_batch_places_distant_water_in_local_constructions(self):
        self.lua.execute('''
          local a=dataset.scenery[1]
          a.face={{8,8},{12,8},{8,12}}
          dataset.scenery[2]={category="waterways",depth=.5,texture=a.texture,
            face={{-120,80},{-116,80},{-120,84}}}
        ''')
        self.h.event('start')
        self.h.finish()
        constructions=self.lua.globals().commands[1].constructionsToAdd
        self.assertEqual(len(constructions),2)
        self.assertEqual(len(self.h.state.value.sceneryRecords[1].entities),2)
        script=load_script(self.lua,CONTENT/'scenery.script.lua')
        for construction, (x,y) in zip(constructions.values(), [(8,8),(-120,80)]):
            self.assertEqual(list(construction.transf[4].values()),[x,y,0,1])
            self.assertEqual(list(construction.params['items'][1].face[1].values()),[x,y,9.5])
            sub=script.updateFn(None,construction.params).subconstructions[1]
            self.assertEqual(list(sub.groundFaces[1].face[1].values()),[0,0,9.5,1])

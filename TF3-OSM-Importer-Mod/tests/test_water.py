"""Experimental water geometry and command lifecycle; not native rendering proof."""
from pathlib import Path
import struct
import unittest
import test_game_scripts as game
from test_game_scripts import load_script, CONTENT


class WaterTests(unittest.TestCase):
    def setUp(self):
        self.h=game.GameScriptTests()
        self.h.setUp()
        self.lua=self.h.lua
        self.water=self.lua.globals().modules['druttzen_osm_vanilla::/osm/water.lua']
        self.lua.execute('''
          api.type.Box3={new=function(a,b) return {min=a,max=b} end}
          api.engine.system={octreeSystem={findIntersectingEntities=function(box,callback)
            waterQuery=box
            if blockedWater then callback(blockedWater,{}) end
          end}}
        ''')

    def test_flat_and_sloping_faces_have_exact_authored_heights(self):
        p=self.water.settings(self.lua.table_from(dict(x=100,y=200,level=23,endLevel=17,length=40,width=10)))
        faces=self.water.faces(p)
        self.assertEqual(faces[1][1][3],23)
        self.assertEqual(faces[1][2][3],17)
        self.assertEqual(faces[2][3][3],23)
        for face in faces.values():
            t=self.water.transform(face)
            for local,point in (((0,0),face[1]),((1,0),face[2]),((0,1),face[3])):
                for k in range(3): self.assertAlmostEqual(t[13+k]+local[0]*t[1+k]+local[1]*t[5+k],point[1+k])

    def test_mesh_blob_indices_and_attribute_bounds_are_valid(self):
        model=load_script(self.lua,CONTENT/'water_triangle.mdl')
        self.assertEqual(model.version,2)
        definition=load_script(self.lua,CONTENT/'water_triangle.msh')
        blob=(CONTENT/'water_triangle.msh.blob').read_bytes()
        self.assertEqual(len(blob),136)
        for name,spec in definition.vertexAttr.items():
            self.assertEqual(spec.count % (spec.numComp*4),0)
            self.assertLessEqual(spec.offset+spec.count,len(blob))
            index=definition.subMeshes[1].indices[name]
            self.assertEqual(index.count,12)
            indices=struct.unpack_from('<3I',blob,index.offset)
            self.assertLess(max(indices),spec.count//(spec.numComp*4))
        self.assertEqual(struct.unpack_from('<9f',blob),(0,0,0,1,0,0,0,1,0))

    def test_surface_only_never_adds_terrain_alignment(self):
        script=load_script(self.lua,CONTENT/'water.script.lua')
        p=self.water.settings(None)
        result=script.updateFn(None,p)
        self.assertEqual(len(result.subconstructions[1].models),2)
        self.assertEqual(len(result.subconstructions[1].groundFaces),0)
        self.assertEqual(len(result.subconstructions[1].terrainAlignmentLists[1].faces),0)
        self.assertFalse(result.metadata.druttzenOsmWater.navigable)

    def test_failed_native_basin_is_rejected_by_resource_callback(self):
        script=load_script(self.lua,CONTENT/'water.script.lua')
        with self.assertRaisesRegex(Exception,'Basin shaping is disabled'):
            script.updateFn(None,self.lua.table_from(dict(carve=True)))

    def test_invalid_settings_are_atomic(self):
        for patch in (dict(width=101),dict(width=0),dict(depth=-2),dict(x=float('nan')),dict(carve='yes'),dict(unknown=1)):
            with self.subTest(patch=patch):
                self.h.event('waterConfigure',patch)
                self.assertEqual(self.h.state.value.waterSettings.width,20)
                self.assertEqual(self.h.state.value.waterSettings.x,0)
                self.assertEqual(len(self.lua.globals().commands),0)

    def test_basin_cannot_be_reenabled_through_console(self):
        self.h.event('waterConfigure',dict(carve=True))
        self.assertIn('Basin shaping is disabled',self.h.state.value.notice)
        self.assertFalse(self.h.state.value.waterSettings.carve)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_old_unsafe_settings_never_submit_a_native_proposal(self):
        self.h.state.value.waterSettings.carve=True
        self.h.event('waterBuild'); self.h.step()
        self.assertIn('Basin shaping is disabled',self.h.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)

    def test_existing_network_and_construction_prevent_any_build(self):
        for component in ('{node0=1}', '{fileName="::/existing.con"}'):
            self.lua.execute('blockedWater=100; components[100]='+component)
            self.h.event('waterBuild'); self.h.step()
            self.assertIn('near an existing',self.h.state.value.notice)
            self.assertEqual(len(self.lua.globals().commands),0)
            self.assertEqual(self.lua.globals().waterQuery.min.z,-1000)
            self.assertEqual(self.lua.globals().waterQuery.max.z,9000)

    def test_surface_query_keeps_local_guard_and_full_height_range(self):
        self.h.event('waterCheck')
        region=self.lua.globals().waterQuery
        self.assertEqual((region.min.x,region.max.x),(-30,30))
        self.assertEqual((region.min.z,region.max.z),(-1000,9000))

    def test_check_is_read_only_and_build_waits_for_engine_step(self):
        self.h.event('waterCheck')
        self.assertIn('No water or terrain changed',self.h.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),0)
        self.h.event('waterConfigure',dict(level=50,endLevel=45))
        self.h.event('waterBuild')
        self.assertEqual(len(self.lua.globals().commands),0)
        self.h.step()
        self.assertEqual(len(self.lua.globals().commands),1)
        self.assertTrue(self.h.state.value.waterRecord.complete)
        p=self.lua.globals().commands[1]
        self.assertEqual(p.constructionsToAdd[1].params.level,50)
        self.assertEqual(p.constructionsToAdd[1].params.endLevel,45)
        self.assertIsNone(p.streetProposal.edgesToRemove)
        self.assertIsNone(p.constructionsToRemove)
        self.h.event('waterBuild'); self.h.step()
        self.assertEqual(len(self.lua.globals().commands),1)

    def test_native_parameter_copy_preserves_required_seed(self):
        self.lua.execute('''
          local function copy(t)
            local result={}
            for k,v in pairs(t) do result[k]=v end
            return result
          end
          api.type.SimpleProposal.ConstructionEntity.new=function()
            local stored={}
            return setmetatable({}, {
              __index=function(_,key)
                if key=="params" then return copy(stored[key] or {}) end
                return stored[key]
              end,
              __newindex=function(_,key,value)
                stored[key]=key=="params" and copy(value) or value
              end
            })
          end
        ''')
        p=self.water.proposal(self.water.settings(None))
        self.assertEqual(p.constructionsToAdd[1].params.seed,0)
        self.assertEqual(p.constructionsToAdd[1].params.level,20)

    def test_ownership_retry_reload_does_not_duplicate_accepted_water(self):
        self.lua.globals().failOwnershipNext=True
        self.h.event('waterBuild'); self.h.step()
        self.assertFalse(self.h.state.value.waterRecord.complete or False)
        self.assertIn('ownership',self.h.state.value.notice)
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.event('waterBuild'); self.h.step()
        self.assertTrue(self.h.state.value.waterRecord.complete)
        self.assertEqual(len(self.lua.globals().commands),1)

    def test_multiple_heights_are_retained_and_overlap_is_refused_after_reload(self):
        self.h.event('waterBuild'); self.h.step()
        first=self.h.state.value.waterRecord.entities[1]
        self.h.event('waterNext')
        self.assertEqual(len(self.h.state.value.waterRecords),1)
        self.h.script=load_script(self.lua,CONTENT/'importer.script.lua')
        self.h.event('waterConfigure',dict(level=60,endLevel=55))
        self.h.event('waterBuild'); self.h.step()
        self.assertIn('overlaps',self.h.state.value.notice)
        self.assertEqual(len(self.lua.globals().commands),1)
        self.h.event('waterConfigure',dict(x=60))
        self.h.event('waterBuild'); self.h.step()
        self.assertEqual(len(self.lua.globals().commands),2)
        self.assertEqual(self.h.state.value.waterRecords[1].entities[1],first)
        self.assertEqual(self.h.state.value.waterRecords[1].settings.level,20)
        self.assertEqual(self.h.state.value.waterRecord.settings.level,60)
        self.h.event('waterConfigure',dict(level=10))
        self.assertEqual(self.h.state.value.waterSettings.level,60)
        self.assertIn('locked',self.h.state.value.notice)

    def test_another_patch_cannot_discard_pending_or_incomplete_ownership(self):
        self.h.event('waterNext')
        self.assertEqual(len(self.h.state.value.waterRecords),0)
        self.lua.globals().failOwnershipNext=True
        self.h.event('waterBuild')
        self.h.event('waterNext')
        self.assertIsNotNone(self.h.state.value.waterJob)
        self.h.step()
        accepted=self.h.state.value.waterRecord.entities[1]
        self.h.event('waterNext')
        self.assertEqual(len(self.h.state.value.waterRecords),0)
        self.assertEqual(self.h.state.value.waterRecord.entities[1],accepted)
        self.h.event('waterBuild'); self.h.step()
        self.h.event('waterNext')
        self.assertEqual(len(self.h.state.value.waterRecords),1)
        self.assertEqual(len(self.lua.globals().commands),1)

    def test_rejected_water_can_retry_and_never_records_success(self):
        self.lua.globals().failNext=True
        self.h.event('waterBuild'); self.h.step()
        self.assertIsNone(self.h.state.value.waterRecord)
        self.assertIn('Collision',self.h.state.value.notice)
        self.h.event('waterBuild'); self.h.step()
        self.assertTrue(self.h.state.value.waterRecord.complete)
        self.assertEqual(len(self.lua.globals().commands),2)

    def test_water_is_locked_during_active_import_and_running_check(self):
        for phase in ('scenery','edges','labels','checking','error'):
            with self.subTest(phase=phase):
                self.h.state.value.phase=phase
                self.h.event('waterBuild'); self.h.step()
                self.assertIsNone(self.h.state.value.waterRecord)

    def test_outside_patch_and_invalid_native_height_fail_before_build(self):
        for patch in (dict(x=499),dict(level=9500),dict(level=-1001)):
            self.h.state.value.waterSettings=self.water.settings(None)
            self.h.event('waterConfigure',patch); self.h.event('waterBuild'); self.h.step()
            self.assertIsNone(self.h.state.value.waterRecord)
            self.assertEqual(len(self.lua.globals().commands),0)


if __name__=='__main__': unittest.main()

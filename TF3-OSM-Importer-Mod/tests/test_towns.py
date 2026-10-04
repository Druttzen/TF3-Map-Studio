"""Native town command boundary, growth policy and accepted-save journals."""
import unittest
import test_game_scripts as _game


TOWN_MOCK=r'''
api.type.ComponentType.TOWN=8
api.type.Map={Town={new=function() return {} end}}
api.engine.getEntitiesWithComponent=function(kind)
 assert(kind==8); local result={}
 for id,c in pairs(components) do if c.town then result[#result+1]=id end end
 table.sort(result); return result
end
local originalGetComponent=api.engine.getComponent
api.engine.getComponent=function(id,kind)
 if kind==8 then local c=components[id]; return c and c.town end
 return originalGetComponent(id,kind)
end
api.engine.mapgen.createTowns=function(seed,requested)
 assert(type(seed)=="string" and #requested==1)
 local source=requested[1]
 assert(source.sizeFactors[1]==1)
 return {toAdd={{name=source.name,position=source.pos,initialLandUseCapacities={100,100,100},
   landUse2CargoNeedsCategories={{"native_res"},{"native_com"},{"native_ind"}},capacityScalingFactor=1}},toRemove={9999}}
end
api.engine.system=api.engine.system or {}
api.engine.system.townBuildingSystem={getTown2BuildingMap=function()
 local result={}; for id,c in pairs(components) do if c.town then result[id]={id+10000} end end
 return result
end}
api.cmd.makeTownCreateCmd=function(infos) return {createTown=true,infos=infos} end
api.cmd.makeTownSetDevelopmentActiveCmd=function(entity,active) return {setGrowth=true,entity=entity,active=active} end
townCreates=0; growthChanges=0; failGrowthNext=false; loseTownCallback=false; rejectTown=false
local originalSend=api.cmd.sendCommand
api.cmd.sendCommand=function(command,callback)
 if command.setGrowth then
  growthChanges=growthChanges+1
  if failGrowthNext then failGrowthNext=false; callback({},false,{}); return end
  components[command.entity].town.developmentActive=command.active; callback({},true,{}); return
 elseif command.createTown then
  townCreates=townCreates+1
  if rejectTown then rejectTown=false; callback({},false,{}); return end
  for _,source in ipairs(command.infos) do
   nextId=nextId+1; components[nextId]={town={developmentActive=true}}
   names[nextId]={name=source.name}
  end
  if not loseTownCallback then callback({},true,{{nextId,1}}) end
  return
 end
 originalSend(command,callback)
end
dataset.edges={}; dataset.scenery={}
dataset.labels={{name="Mapped city",place="city",pos={10,20}},
 {name="Mapped suburb",place="suburb",pos={100,100}}}
'''


class TownTests(unittest.TestCase):
    event=_game.GameScriptTests.event
    step=_game.GameScriptTests.step
    finish=_game.GameScriptTests.finish

    def setUp(self):
        _game.GameScriptTests.setUp(self)
        self.lua.execute(TOWN_MOCK)

    def test_city_tag_creates_a_native_town_suburb_remains_a_marker(self):
        self.event('configure',{'towns':True})
        self.event('validate')
        self.assertEqual(self.lua.globals().townCreates,0)
        self.event('start'); self.finish()
        self.assertEqual((self.state.value.builtTowns,self.state.value.labels),(1,1))
        record=self.state.value.townRecords[1]
        self.assertTrue(record.complete)
        self.assertTrue(record.allowGrowth)
        self.event('start'); self.step()
        self.assertEqual(self.lua.globals().townCreates,1)
        self.event('placeNames'); self.assertIn('functioning town',self.state.value.notice)

    def test_road_growth_off_explicitly_freezes_all_native_growth(self):
        self.event('configure',{'towns':True,'places':False,'townRoadGrowth':False})
        self.event('start'); self.finish()
        record=self.state.value.townRecords[1]
        self.assertFalse(record.allowGrowth)
        town=self.lua.globals().api.engine.getComponent(record.entities[1],8)
        self.assertFalse(town.developmentActive)
        self.assertEqual(self.state.value.labels,0)
        self.assertTrue(record.initialRoads)

    def test_policy_failure_reload_and_retry_never_creates_duplicate_town(self):
        self.event('configure',{'towns':True,'places':False,'townRoadGrowth':False})
        self.event('start'); self.lua.globals().failGrowthNext=True
        self.step()
        self.assertEqual(self.state.value.phase,'error')
        self.assertIsNotNone(self.state.value.pendingTown)
        self.assertFalse(self.lua.globals().modules['druttzen_osm_vanilla::/osm/controls.lua'].skippable(self.state.value))
        self.event('skip'); self.assertEqual(self.state.value.phase,'error')
        self.script=_game.load_script(self.lua,_game.CONTENT/'importer.script.lua')
        self.event('retry'); self.finish()
        self.assertEqual(self.lua.globals().townCreates,1)
        self.assertTrue(self.state.value.townRecords[1].complete)

    def test_existing_town_name_stops_before_importing_anything(self):
        self.lua.execute('components[99]={town={developmentActive=true}}; names[99]={name="Mapped city"}')
        self.event('configure',{'towns':True})
        self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertIn('already exists',self.state.value.notice)
        self.assertEqual(self.lua.globals().townCreates,0)

    def test_native_town_limit_is_checked_before_building(self):
        self.lua.execute('api.engine.mapgen.getMinMaxValidNumTowns=function() return {0,0} end')
        self.event('configure',{'towns':True})
        self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertIn('supported town count',self.state.value.notice)
        self.assertEqual(self.lua.globals().townCreates,0)

    def test_rejected_town_can_be_retried_but_unknown_outcome_cannot(self):
        self.event('configure',{'towns':True,'places':False})
        self.event('start'); self.lua.globals().rejectTown=True; self.step()
        self.assertEqual(self.state.value.errorKind,'proposal_rejected')
        self.event('retry'); self.finish()
        self.assertEqual(self.lua.globals().townCreates,2)

    def test_missing_callback_blocks_replay_of_unknown_accepted_command(self):
        self.event('configure',{'towns':True,'places':False})
        self.event('start'); self.lua.globals().loseTownCallback=True; self.step()
        self.assertEqual(self.state.value.errorKind,'command_state')
        self.assertTrue(self.state.value.acceptedUnjournalled)
        self.event('retry'); self.step()
        self.assertEqual(self.lua.globals().townCreates,1)

    def test_generator_relocation_is_rejected_before_town_command(self):
        self.lua.execute('api.engine.mapgen.createTowns=function() return {toAdd={{name="Mapped city",position={x=0,y=0}}}} end')
        self.event('configure',{'towns':True,'places':False})
        self.event('start')
        self.assertEqual(self.state.value.phase,'ready')
        self.assertIn('changed the mapped position',self.state.value.notice)
        self.assertEqual(self.lua.globals().townCreates,0)

    def test_town_journal_audit_detects_growth_policy_drift_without_commands(self):
        self.event('configure',{'towns':True,'places':False})
        self.event('start'); self.finish()
        module=self.lua.globals().modules['druttzen_osm_vanilla::/osm/towns.lua']
        report=module.inspect(self.lua.globals().dataset,self.state.value)
        self.assertEqual((report.current,report.expected,len(report.problems)),(1,1,0))
        record=self.state.value.townRecords[1]
        self.lua.globals().components[record.entities[1]].town.developmentActive=False
        report=module.inspect(self.lua.globals().dataset,self.state.value)
        self.assertGreater(len(report.problems),0)
        self.assertEqual(self.lua.globals().growthChanges,1)

    def test_town_entity_without_native_buildings_is_not_claimed_functional_by_audit(self):
        self.event('configure',{'towns':True,'places':False})
        self.event('start'); self.finish()
        self.lua.execute('api.engine.system.townBuildingSystem.getTown2BuildingMap=function() return {} end')
        report=self.lua.globals().modules['druttzen_osm_vanilla::/osm/towns.lua'].inspect(self.lua.globals().dataset,self.state.value)
        self.assertTrue(any('no simulated buildings' in p for p in report.problems.values()))

if __name__=='__main__': unittest.main()

"""Aggregate counting preserves selection rules without rescanning map items."""
from pathlib import Path
import unittest

from lupa import LuaRuntime


CONTENT = Path(__file__).resolve().parents[1] / 'mod/tf3_osm_importer_mod/content/osm'


class ControlsCountTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().controls = self.lua.execute(
            (CONTENT / 'controls.lua').read_text(encoding='utf-8'))

    def test_aggregates_match_direct_selection_across_option_combinations(self):
        self.lua.execute('''
            local d={id="counts",edges={},scenery={},labels={}}
            for i=1,80 do d.edges[i]={kind=i%3==0 and "TRACK" or "STREET"} end
            local categories={"vegetation","surfaces","objects","mappedObjects","buildings","waterways"}
            local kinds={"tree","bench","residential","custom_kind"}
            for i=1,480 do
              d.scenery[i]={category=categories[i%#categories+1],unmatched=i%13==0,
                match=i%5~=0 and {kind=kinds[math.floor(i/6)%#kinds+1]} or nil}
            end
            -- Include legacy category inference and place tags nested in OSM metadata.
            d.scenery[#d.scenery+1]={texture="ground"}
            d.scenery[#d.scenery+1]={model="::/assets/vegetation/tree.mdl"}
            d.scenery[#d.scenery+1]={model="::/assets/example.mdl"}
            for i=1,100 do d.labels[i]={place=i%2==0 and "village" or "suburb"} end
            d.labels[101]={osm={tags={place="city"}}}
            d.labels[102]={place="hamlet"}
            d.labels[103]={place="town"}
            d.labels[104]={}
            local counts,kindsAvailable=controls.available(d)
            assert(counts.roads==54 and counts.railways==26)
            assert(counts.places==104 and counts.towns==53)
            assert(kindsAvailable.custom_kind>0)
            math.randomseed(414)
            for iteration=1,250 do
              local options=controls.options()
              for _,category in ipairs(controls.categories) do options[category.key]=math.random(2)==1 end
              for _,kind in ipairs(controls.objectKinds) do options["object_"..kind.key]=math.random(2)==1 end
              options.object_custom_kind=math.random(2)==1
              local expected={edges=0,scenery=0,labels=0,towns=0}
              for _,edge in ipairs(d.edges) do
                if options[edge.kind=="TRACK" and "railways" or "roads"] then expected.edges=expected.edges+1 end
              end
              for _,item in ipairs(d.scenery) do
                if controls.selectedScenery(item,options) then expected.scenery=expected.scenery+1 end
              end
              for _,label in ipairs(d.labels) do
                local mode=controls.placeMode(label,options)
                if mode=="town" then expected.towns=expected.towns+1
                elseif mode=="marker" then expected.labels=expected.labels+1 end
              end
              local result=controls.totals(d,options)
              for key,count in pairs(expected) do assert(result[key]==count,key.." differs") end
            end
        ''')

    def test_category_changes_do_not_read_source_items_again(self):
        self.lua.execute('''
            local reads=0
            local item=setmetatable({}, {__index=function(_,key)
              reads=reads+1
              if key=="category" then return "mappedObjects" end
              if key=="match" then return {kind="bench"} end
            end})
            local d={edges={},scenery={},labels={}}
            for i=1,10000 do d.scenery[i]=item end
            controls.available(d)
            local initialReads=reads
            local options=controls.options()
            for i=1,100 do
              options.mappedObjects=i%2==0
              options.object_bench=i%3==0
              local result=controls.totals(d,options)
              assert(result.scenery==(options.mappedObjects and options.object_bench and 10000 or 0))
              controls.available(d)
            end
            assert(initialReads>0 and reads==initialReads,"Option changes reread source metadata")
        ''')

    def test_availability_includes_unmatched_but_selected_totals_do_not(self):
        self.lua.execute('''
            local d={edges={},labels={},scenery={
              {category="mappedObjects",match={kind="bench"},unmatched=true},
              {category="mappedObjects",match={kind="bench"}},
              {category="mappedObjects"},
            }}
            local available,kinds=controls.available(d)
            assert(available.mappedObjects==3 and kinds.bench==2)
            local options=controls.options()
            assert(controls.totals(d,options).scenery==2)
            options.object_bench=false
            assert(controls.totals(d,options).scenery==1)
        ''')

    def test_replaced_arrays_and_length_changes_refresh_both_counts(self):
        self.lua.execute('''
            local d={edges={{kind="STREET"}},scenery={{category="objects"}},labels={{place="town"}}}
            local options=controls.options()
            controls.available(d); controls.totals(d,options)
            d.edges={{kind="TRACK"}}
            d.scenery={{category="vegetation"}}
            d.labels={{place="suburb"}}
            local available=controls.available(d)
            assert(available.roads==0 and available.railways==1 and available.vegetation==1)
            assert(available.towns==0)
            options.railways=false; options.vegetation=false
            local result=controls.totals(d,options)
            assert(result.edges==0 and result.scenery==0)
            d.edges[2]={kind="STREET"}
            d.scenery[2]={category="objects"}
            d.labels[2]={place="village"}
            result=controls.totals(d,options)
            assert(result.edges==1 and result.scenery==1 and result.labels==2)
            assert(controls.available(d).towns==1)
        ''')

    def test_explicit_invalidation_and_dataset_identity_refresh_same_length_edits(self):
        self.lua.execute('''
            local d={id="first",edges={{kind="STREET"}},scenery={},labels={}}
            local options=controls.options(); options.railways=false
            assert(controls.totals(d,options).edges==1)
            d.edges[1].kind="TRACK"
            controls.invalidateCounts(d)
            assert(controls.totals(d,options).edges==0)
            d.edges[1].kind="STREET"; d.id="second"
            assert(controls.totals(d,options).edges==1)
            d.edges[1].kind="TRACK"
            controls.invalidateCounts()
            assert(controls.totals(d,options).edges==0)
        ''')

    def test_aggregate_cache_does_not_keep_an_unselected_dataset_alive(self):
        self.lua.execute('''
            local observed=setmetatable({}, {__mode="v"})
            do
              local d={edges={},scenery={{category="objects"}},labels={}}
              observed[1]=d
              controls.available(d); controls.totals(d,controls.options())
            end
            collectgarbage("collect"); collectgarbage("collect")
            assert(observed[1]==nil,"Counts cache retained the source dataset")
        ''')


if __name__ == '__main__':
    unittest.main()

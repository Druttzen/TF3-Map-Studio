"""Huge-map information must not bury native import recovery controls."""
import unittest

import test_panel as panel


class LargeDetailsPanelTests(unittest.TestCase):
    def setUp(self):
        self.h = panel.PanelTests()
        self.h.setUp()
        self.lua = self.h.lua
        self.lua.execute("""
          state.value.datasetInfo.warnings={}
          state.value.datasetInfo.unavailableObjects={}
        """)

    def snapshot(self):
        helper = self.lua.globals().modules[
            "druttzen_osm_vanilla::/osm/ui_snapshot.lua"]
        return helper.fromState(self.lua.globals().state.value,
                                self.lua.globals().api.engine.terrain.getBoundingBox())

    def rows(self):
        return self.h.node("scroll").params.content.params.layout.params.children

    def fill_details(self, count):
        self.lua.execute("""
          local count=...
          dataset.warnings={}; dataset.unavailableObjects={}
          for i=1,count do
            dataset.warnings[i]="Conversion note "..i
            dataset.unavailableObjects[i]={tag="unsupported:"..i,count=i}
          end
          state.value.datasetInfo.warnings=dataset.warnings
          state.value.datasetInfo.unavailableObjects=dataset.unavailableObjects
        """, count)

    def test_retry_and_pace_precede_map_selection_and_long_information(self):
        self.fill_details(10000)
        self.lua.execute("""
          state.value.phase="error"; state.value.resumePhase="scenery"
          state.value.datasetId=dataset.id; state.value.errorKind="preparation"
        """)
        rows = self.rows()
        positions = {}
        for index in range(1, len(rows) + 1):
            meta = rows[index].params.meta
            if meta and meta.id:
                positions[meta.id] = index
        retry = positions["druttzen-osm-command-retry"]
        pace = positions["druttzen-osm-step-limit"]
        choose = positions["druttzen-osm-map-choose"]
        self.assertLess(retry, 15)
        self.assertLess(retry, pace)
        self.assertLess(pace, choose)
        self.assertLess(positions["druttzen-osm-delay"], choose)
        self.assertTrue(self.h.node("command-retry").params.meta.enabled)

    def test_rows_and_snapshot_details_are_bounded_with_full_report_message(self):
        baseline = len(self.rows())
        self.fill_details(10000)
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot.warnings), 30)
        self.assertEqual(len(snapshot.unavailableObjects), 30)
        self.assertEqual(snapshot.warningsOmitted, 9970)
        self.assertEqual(snapshot.unavailableObjectsOmitted, 9970)
        rows = self.rows()
        self.assertLessEqual(len(rows), baseline + 63)
        texts = [rows[index].params.text for index in range(1, len(rows) + 1)]
        self.assertTrue(any(text and "9970 more conversion notes" in text
                            and "original conversion report" in text for text in texts))
        self.assertTrue(any(text and "9970 more unsupported object details" in text
                            and "original conversion report" in text for text in texts))
        count = len(rows)
        self.fill_details(30000)
        self.assertEqual(len(self.rows()), count)

    def test_snapshot_preserves_all_persisted_and_source_details(self):
        self.fill_details(10000)
        for _ in range(3):
            self.snapshot()
        self.h.tree()
        dataset = self.lua.globals().dataset
        info = self.lua.globals().state.value.datasetInfo
        self.assertEqual(len(dataset.warnings), 10000)
        self.assertEqual(len(dataset.unavailableObjects), 10000)
        self.assertEqual(len(info.warnings), 10000)
        self.assertEqual(len(info.unavailableObjects), 10000)
        self.assertEqual(info.warnings[10000], "Conversion note 10000")
        self.assertEqual(info.unavailableObjects[10000].tag, "unsupported:10000")
        self.assertEqual(len(self.lua.globals().emitted), 0)
        self.assertEqual(len(self.lua.globals().commands), 0)

    def test_refresh_reads_only_the_display_prefix(self):
        # A lazy list catches any full-warning traversal on each timer refresh.
        self.lua.execute("""
          warningReads=0; unavailableReads=0
          state.value.datasetInfo.warnings=setmetatable({},{
            __len=function() return 10000 end,
            __index=function(_,index)
              assert(index<=30,"Snapshot traversed hidden conversion notes")
              warningReads=warningReads+1
              return "Note "..index
            end})
          state.value.datasetInfo.unavailableObjects=setmetatable({},{
            __len=function() return 10000 end,
            __index=function(_,index)
              assert(index<=30,"Snapshot traversed hidden object details")
              unavailableReads=unavailableReads+1
              return {tag="unsupported:"..index,count=index}
            end})
        """)
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot.warnings), 30)
        self.assertEqual(snapshot.warningsOmitted, 9970)
        self.assertEqual(self.lua.globals().warningReads, 30)
        self.assertEqual(self.lua.globals().unavailableReads, 30)


if __name__ == "__main__":
    unittest.main()

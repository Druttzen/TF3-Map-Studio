# Native map selection — revision 10

Windows verification on 25 October 2026, TF3 build **40425**, Steam build **26129055**. The existing fictional 1000 m sample was copied into the installed importer's `content/osm/maps/choice.lua` with a distinct fictional dataset ID. User map data and the installed `dataset.lua` and `import-report.json` were preserved.

The **Choose .lua map** button opened the native Windows file dialog. Selecting that file loaded `osm/maps/choice.lua` through the engine's `ug_require` resource reader; the panel reported the selected resource and correct sample counts. The test was saved separately as `MapStudio-Selector-Rev10-20261025`, TF3 was exited completely, and the test copy was loaded again. The selected resource was restored automatically and the panel was ready without another file selection.

After reload, **Check map and match objects** passed, reporting 3 vanilla matches, no active-mod matches and no unmatched objects. **Start import** completed with:

```text
finished | roads/rails 10/10 | scenery 117/117 | markers 1/1 | skipped jobs 0
```

**Verify built objects** then passed: nodes 12/12, roads 8/8, rails 2/2, vehicle lane edges 10/10, models 115/115, ground items 2/2, markers 1/1 and connected groups 2/2. This verifies the recorded native objects and graph, not actual vehicle journeys or ground-paint appearance.

Source geometry is absent from the persisted UI description; automated tests inspect that state structure and cover separate callback instances, missing/changed sources, original-file restoration, selection locks and idle writes. Native completion alone does not establish actual vehicle routes or large-map performance. This test did not enable experimental water or functioning towns and does not validate those features.

The supported map library is `content/osm/maps` under the installed importer. Add or replace files while TF3 is closed, then restart it. The engine resource name is retained in the save; keep the original file and filename. The game’s `app.loadUserdata` reader is restricted to named preset directories and expects `function data()` files, so it is not used for ordinary converter Lua exports. The file dialog's documented `intiialPath` field was rejected by the installed engine and is omitted.

Native callbacks may have separate local environments. Every engine callback resolves the selected resource from saved state, rather than assuming a selection made in the event callback changes the update or build callback's local variables. A regression test models those separate callback instances.

Test saves and full logs remain local. No game assets, user datasets or private identifiers are distributed.

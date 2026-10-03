# Native TF3 sample validation — revision 4

Test date: 3 October 2026. Host: Windows, Transport Fever 3 build **40408**, Steam build **25533170**. The sample completed in the native map editor on a new flat temperate Small 1:1 map. Active content was this importer and the official Deluxe Upgrade and Pre-Order Pack; other gameplay mods were disabled. Debug mode was not needed.

The fictional 1000 × 1000 metre dataset was preserved byte for byte. SHA-256: `64e4e1e606830b9726910fa96387fe10785f24c66ea8cc2d96ba91d1663a9336`.

The importer finished with **10/10 road/rail segments, 117/117 scenery items, 1/1 marker and zero skipped jobs**. The map was saved separately as `Codex-OSM-Rev4-Journal-20261003`, TF3 was exited completely, and the save was loaded again. The final read-only native check returned:

```text
Saved built objects verified | nodes 12/12 | roads 8/8 | rails 2/2 |
vehicle lane edges 10/10 | models 115/115 | ground items 2/2 |
markers 1/1 | connected groups 2/2
```

This checks recorded endpoint positions and reuse, road/rail resource profiles and types, ownership, generated vehicle-compatible transport lanes and imported graph connections. The sample has a road junction of degree three and a rail node of degree two. Two separate connected groups are expected: the road network and the rail network.

TF3 optimized the first model-only scenery batch and the marker into **ASSET_GROUP** entities. Their saved IDs allow the check to inspect 100 vegetation models and one marker through **MODEL_INSTANCE_LIST**, comparing live resource IDs, XY positions, rotations and scale. The remaining 15 models and two ground items were retained in a **CONSTRUCTION** and checked through its saved item parameters. Those parameter checks do not independently inspect every rendered mesh or the appearance of ground paint.

The marker's native asset group has no **NAME** component. Revision 4 keeps its name in the importer journal. The native **Show place names** command displayed:

```text
Recorded place names, page 1/1: OSM test village (x -150 m, y -50 m).
Coordinates are metres from the map centre.
```

The ordinary asset window is not claimed to show this name. No artificial marker ground patch or extra infrastructure is added to force a name component.

The passed audit and recorded name were then saved separately as `Codex-OSM-Rev4-Verified-20261003` (591,944 bytes; SHA-256 `490c56ab1c97fdffd46b939c03f5c8e1875dfb875868dbc334d225033c3e16c1`). This final save is retained locally for inspection; the successful full restart/reload check above was performed on the earlier journal save.

## Native problems fixed

- The mod button extension requires a layout root, and singleton windows require the native window wrapper.
- Rendering cannot fire a GUI script event; the panel polls the persisted **GAME_SCRIPT** component using the permitted read API.
- An active engine script must return an update result to schedule its build callback.
- Ground texture lookup returns a string identifier rather than an integer repository index.
- A Lua table cannot be assigned to the native edge ownership field. The importer assigns ownership with the native entity command after accepted geometry and journals pending finalization before it.
- Model-only construction proposals can become unnamed asset groups. The name command cannot create a missing name component, so the importer records IDs and names separately.
- The installed `api/type.d.tl` comment describes matrix columns as 1–4, but the game's `game_mechanics/fun_elements/custom_entity_util.tl` uses 0–3. Reading column 1 caused a 90-degree rotation error in the audit. Column 0 matches the native transforms and passes after restart.
- `getEntitiesWithComponent(BASE_EDGE)` is unsupported in this build. The audit queries segments incident to recorded nodes and enumerates constructions through the callback API used by the game's mission savegame helper.
- Long notices previously had zero height. Messages now wrap in a separate scroll area and remain readable during failures.

Earlier native trials stopped on actual API errors, and an earlier saved sample continued through the failed road step after the ownership fix. Automated tests additionally cover pause/resume, rejected proposals, ownership/naming finalization failures, duplicate prevention and missing/changed world objects. A unit-test result is not labeled as a native game check.

## Limits of this evidence

This sample establishes native proposal acceptance, completion, persisted progress, ownership and the stated object check after full restart. It does **not** establish actual successful vehicle routes, native pause/resume under a large workload, bridge/tunnel clearance, non-flat terrain or reliability on large real OSM maps. Stations, depots, signals and functioning towns still require native game tools. Ground appearance needs visual inspection. Older saves without scenery entity references cannot reliably identify unnamed groups.

Raw local logs and test saves are kept outside Git under the project's ignored `outputs/importer-rebuild/` folder. Game assets, API source, private account identifiers and full logs are not distributed with the release. See `validation.json` for test counts and structured scope.

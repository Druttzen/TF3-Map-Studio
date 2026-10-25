# TF3 Map Studio review — 25 October 2026

**Verdict: APPROVE for the reviewed fixes. Native-game compatibility remains limited to the documented tests.**

The review covered all four tools through their complete automated suites, focused code inspection of report/terrain handoff, elevation/project integrity, OSM topology and native importer state, plus Windows/source package comparisons. Independent reviewers reproduced the findings before fixes. No new native TF3 gameplay session was performed; the review does not establish that every map or vehicle works in the game.

## Findings and completed fixes

| Priority | Finding | Resolution |
| --- | --- | --- |
| P1 | Valid converter reports could exceed Heightmap's fixed 64 MB limit after full water source metadata was added. | Report JSON is streamed and fully syntax-checked; only alignment fields are retained. Bounds, settings, dataset and available checksums remain validated. |
| P1 | A saved terrain project could accept changed same-named OSM data with an older report lacking a source checksum. | The project's own saved OSM checksum is validated against actual bytes. |
| P1 | Border-crossing bridges/tunnels mixed clipped height-guide endpoints with whole-way fractions. | Each continuous clipped chain receives consistent endpoints and normalized fractions; gaps and reentry remain distinct. |
| P1 | Checking a foreign dataset during a paused import could replace saved model matches. | A dataset-identity guard rejects the check before matches change. |
| P2 | Tagged meadow/farmland inside a forest polygon hole lost its independent biome. | Only effective outer outlines suppress duplicate land areas; inner features remain available, including nested relations. |
| P2 | Report selection gave generic errors and directory-based report resolution could miss a moved matching Lua. | Separate messages identify download/terrain logs. The Mod folder option resolves the actual report and Lua location. |
| P2 | Main downloads/documented versions pointed to superseded packages. | Current reviewed packages and historical version tags are identified explicitly. |
| P2 | Vehicle CI could skip authored Lua execution tests because Lupa was absent from its development extras. | Lupa is included in the development dependency set. |

## Validation

| Tool | Tests passed | Other results |
| --- | --- | --- |
| Heightmap Studio 0.10 | 211 | 1 environment skip; affine deprecation warnings. Includes a valid report larger than 64 MB, malformed skipped sections, wrong report types, folder/Lua discovery and project/biome regressions. |
| OSM converter 0.16 | 277 | 216 subtests, including current Lua execution of clipped structure guides. |
| OSM importer revision 9 | 159 | 87 subtests, including paused import → foreign check → original dataset restoration. |
| Vehicle converter 0.15.0 | 1585 | 3 environment skips, 14 duplicate-archive fixture warnings; 32 embedded Windows runtime modules match current source. |

These suites overlap and are not added together as unique tests. Two existing local converter reports, approximately 53 MB and 36 MB, pass the new reader. The 53 MB file also passed the previous source reader, so the 64 MB defect alone does **not** prove the exact origin of the user's generic “Invalid converter report” dialog. The new packaged application is checked with the reported mod folder, and its own version is visible in the title.

The report reader uses [ijson's supported event interface](https://github.com/ICRAR/ijson) to avoid retaining unrelated source graphs. Its licence and bundled parser notice are included. Windows packaging checks dependencies before building and then runs a headless certificate, report-parser, elevation, compressed-LiDAR and export-routing check. Synthetic tests do not establish measurement accuracy or native map import.

## Limits and operational notes

Preserve the original dataset of a started import. Bridge/tunnel export corrections apply when creating a new dataset; a runtime update does not rewrite an already exported map. Do not replace an installed custom dataset with the fictional sample from the mod ZIP.

Water excavation, detailed model matching, functioning towns, large real maps, terrain slopes and actual transport routes still need the native checks described in each tool's validation documents. No new vehicle driving/rendering/audio claim is made. Original OSM files, game datasets, elevation data and game saves were not rewritten by this review.

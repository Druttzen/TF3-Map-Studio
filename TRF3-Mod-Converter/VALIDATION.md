# Validation scope

Version 0.4 introduces a strict TF2 electric-locomotive draft profile alongside metadata/layout conversion. Automated tests use authored fixtures; they do not run TF3. Generated reports always mark `nativeTest` as `not_run`.

## Automated checks

Version 0.5 adds a general requirement planner and mesh checks shared across mod categories. Authored tests cover road/rail/tram/water/air classification, propulsion types and unpowered vehicles, mixed packages, computed metadata, unknown resources, source-code non-execution, independent attribute indices, out-of-range buffers, component/triangle counts and non-finite warnings. Analysis-only support is explicitly distinct from exporter support. No new native-game test was performed for these changes.

Read-only local analysis also covered the DH106 B757C aircraft package (14 air models, an asset construction and 6 mesh pairs), Autobahn Kreuz (construction, infrastructure, models/materials and 246 mesh pairs), and a modular-station adapter (construction and scripts). These are identification/buffer checks, not successful TF3 conversions. SJ Class D's 108 meshes were additionally checked: 101 passed these binary checks, seven had non-finite tangent warnings. No original assets or scripts were altered.

Coverage includes literal parsing, metadata preservation, stable IDs, script references, missing resources, material-property migration using an installed-resource inventory, locomotive units and named nodes, source hashes, binary preservation, unsupported behavior blockers, protected output, backups, recovery, CLI and the Tk desktop workflow. Game appearance, driving, audio, physics and animations require native tests.

## Local SJ Class D experiment — 2026-10-03

The local `transportfever_sweden_class_d_1` TF2 mod was exported as `transportfever_sweden_class_d_tf3_test`, using installed TF3 build 40408 as the format target. The source's 478 files remained unchanged. The profile migrated 15 models and 46 materials and retained 108 meshes with their blobs and 3 animation files. No third-party mod files or game assets are included in this repository.

One missing source texture was explicitly substituted in the local draft: `sj_class_d_002_body_cblend_dirt_rust.dds` uses the source's `sj_class_d_005_passageway_cblend_dirt_rust.dds`. This is a recorded visual compromise; the original author's intended appearance is unknown. The missing default metal/gloss/AO texture uses the installed TF3 default.

Native testing used a separate new map in 1980, saved as `SJ_Class_D_Port_Test_20261003`. TF3 loaded the draft, listed its vehicle groups, and successfully purchased SJ Du steel (1974). It also accepted a standard passenger wagon attached to the purchased locomotive. Initial native testing exposed missing default icon paths; explicit references to original thumbnails were subsequently implemented.

After restarting TF3 and reloading the test save, the SJ locomotive thumbnails appeared correctly in the vehicle manager and purchase/modify lists. The saved SJ locomotive and attached native wagon were retained.

Line assignment failed with the engine's generic message “Vehicles could not be assigned to line.” A control test replaced the SJ locomotive with the native German Class V 100 while keeping the same wagon, depot and line. The native locomotive was rejected with the same message. This test therefore cannot attribute the failure to the converted model; the test infrastructure or assignment workflow still needs investigation. Purchasing alone does **not** establish operational compatibility. Further native verification is required for assignment, physical rendering, textures, wheel/bogie/headlight animation, horn and sound, coupling, reversal, and all variants and LODs.

The profile is experimental and is not a general TF2 mod converter. Unsupported or dynamic behavior is blocked rather than silently discarded.

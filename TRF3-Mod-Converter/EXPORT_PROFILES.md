# TF2 export profiles — version 0.9

This release implements content export beyond the original electric locomotive profile. Every export uses an installed TF3 inventory, preserves the source, stages the complete package and audits its resources before publishing a separate draft. The queue uses the same exporters as `port-tf2`.

| Profile | Implemented behavior |
|---|---|
| Rail | Horse, steam, diesel and electric engines; unpowered freight/passenger wagons; named axles, per-LOD fake bogies, reversal lights, capacities and sound. |
| Road | Buses, trucks, horse vehicles and AI cars; shared land physics, wheels, steering, supported lights, cargo/passengers and sound. |
| Tram | Tram/electric-tram modes, land physics, wheels/bogies, supported alternating blink animations and cargo/passengers. |
| Water | Small/big ship modes, kg mass, power/waterline data, paddles and authored rudder-angle animations. Redundant zero-Z waterline coordinates are reduced with an audit. |
| Air | Small/big aircraft modes, kg mass, thrust/wing data, verified gear radii/positions, propellers and authored control-surface-angle animations. Missing/conflicting radii block export. |
| Cargo | Current/legacy/capacities schemas, passenger seats, simultaneous fixed compartments, alternative load configs, hidden nodes, generic bays and dynamic cargo slots. New types are alternatives within the same verified class. |
| Render models | Static assets, trees, rocks and people; stable named nodes, meshes/materials, supported inline/file animations, camera/label references and literal particle visuals. |
| Configurations | Multiple units, railroad crossings, auto ground textures, ground textures, terrain materials and grass with typed TF3 resource endings. |
| Infrastructure | Literal track/street templates and styles, supported catenary variants and built-in default bridge factory capture parameters. |
| Decorative construction | Constant ASSET_DEFAULT results become a separate authored TF3 script module; models, supported ground faces and terrain operations remain intact. |
| Common resources | Native-property material migration, recognized sound update patterns, translations, thumbnails, lowercase namespaces, geometry validation and verified base-resource substitutions. |

Coverage is conditional on known source schemas. Recognizing a class does not establish that every third-party implementation can be converted automatically. Meaningful mod lifecycle callbacks, arbitrary Lua/API/game scripts, native extensions, functional stations/industries/depots/modules, portal-only tunnels, custom cargo/economy definitions, unverified metadata, missing resources and opaque resource archives remain explicit migration blockers. They receive **Needs review**, never a successful metadata-only fallback.

Source Lua is parsed without execution. Straight-line literal locals, assignments and verified vec3/transf mathematical helpers can be folded; a narrow bridge/texture helper vocabulary is interpreted from verified semantics. Rebound helpers, unsupported calls, runtime translated concatenation and callback-dependent data are rejected. Generated filenames are deterministic and collision checked. Original changed files remain in `_port_originals`.

## Cargo and units

The installed catalog currently supplies 37 cargo types, six classes and 28 formats. Same-class freight expansion uses BULK, LIQUID, GOODS or FLATBED evidence, respects exclusions and avoids accidental expansion through UNIVERSAL into unrelated classes. Unknown cargo IDs need explicit verified mappings. Fixed source visual loads cannot be reused for unrelated newly added cargo without a generic visual template.

Source raw capacities remain unchanged. Maximum simultaneous capacity determines the native payload balancing value, using an explicit estimated fallback of 300 kg per raw capacity unit. Native TF3 passenger and freight ratios differ; the report records `balancingEstimates` and requires loaded-mass/acceleration tuning. This fallback does not establish equivalent physics. Rail/road empty mass changes from tonnes to kg; ship/air mass is already kg. Speed, power and thrust retain their documented units. Maintenance lifespan changes from TF2 half-day units to TF3 quarter-day units (factor two).

Literal particle visuals preserve source endpoints with linear size/fade curves. Source emitters do not identify exhaust versus cylinder steam; no semantic ID is inferred from color. Engine-dependent timing needs native verification and is recorded in `particleMigrations`.

Material properties must be declared by the selected installed material type; a standalone property file is insufficient evidence. Color blending uses the specific material's two/four-channel definition. Legacy scalar scales target the single source color channel; explicit source scales/colors are retained and empty/trailing channels use installed defaults. Every such change records its schema and policy. Editor backups keep an inert `.editor_backup` ending; normalization rejects empty, current and parent path segments before creating the destination.

Legacy material defaults in mesh descriptors are resolved directly. A missing default may use the explicit model material at the same submesh slot only when every model referrer has a complete verified material list and all agree on the target. The audit records this evidence; index/attribute values, embedded animations and binary blobs remain unchanged. LOD mesh variants may share a configuration only through explicit corresponding node names with identical full world transforms, never guessed filename suffixes. Empty/single literal URL wrappers are unwrapped with their source value recorded.

Three installed Workshop packages were inspected through complete draft export attempts with source hashes unchanged. The latest strict material checks stop MAN SL202 at an undeclared `alpha_scale` property and Cessna172 at `color_blend` on a material type without that property. Cessna also has unsupported aircraft engine metadata later in the model path. Opel Insignia uses computed/global metadata requiring migration. MAN's LOD references and three missing legacy mesh defaults now have verified adapters, including a read-only check of the actual mesh and matching door animations. None received a successful complete export or a gameplay claim.

## Evidence and research

Primary format references are the [TF2 vehicle types](https://wiki.transportfever2.com/doku.php?id=modding:vehicletypes), [TF3 vehicle types](https://wiki.transportfever3.com/doku.php?id=modding:vehicles:types), [TF3 model metadata](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mdl), [cargo definitions](https://wiki.transportfever3.com/doku.php?id=modding:misc:cargo), [TF2 meshes](https://wiki.transportfever2.com/doku.php?id=modding:resourcetypes:msh), [TF3 meshes](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:msh), [resource structure](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes), [tracks/streets](https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:tracksstreets) and [bridges/tunnels](https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:bridgestunnels). Installed definitions are checked when documentation and shipped fields differ.

External projects researched include [Tpf2 Mod Studio](https://github.com/CeberusOne/Tpf2-Mod-Studio) for static parsing, resource checks and dependency-aware inventories; [TpFMC](https://github.com/Enzojz/TpFMC) for historical model conversion; [modutram](https://github.com/eisfeuer/modutram) and [modular train stations](https://github.com/eisfeuer/tpf2-modular-train-station) for construction/module boundaries; and [Auto Line Namer Plus](https://github.com/AnujCtrl/tpf2-auto-line-namer-plus) for separating game API logic from testable data logic. These projects do not supply a universal TF3 exporter. No third-party implementation was copied into this MIT project.

Read-only checks of TF2's 374 native vehicle models validate the vehicle metadata adapter for 351 models: all 29 buses, 33 cars, 27 trams, 57 trucks, 64 wagons and 21 ships; 109 of 114 trains and 11 of 29 aircraft. Remaining failures are explicit emissions or missing/conflicting aircraft radii. These are **metadata adapter checks**, not full mod-package exports or in-game tests. Eight representative cargo layouts were checked against installed TF3 definitions. Automated package tests use authored fixtures for every vehicle family and selected resource configurations.

The report retains `nativeTest: not_run`. Rendering, audio, particle timing, cargo loading, motion, infrastructure use and save/reload still require native tests. Earlier SJ Class D runtime observations remain documented separately in [VALIDATION.md](VALIDATION.md).

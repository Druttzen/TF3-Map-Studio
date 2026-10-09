# TF2 export profiles — version 0.15.0

## Vehicle profile

The desktop enables `vehiclePolicy: tf2_complete`, `scope: vehicles`,
`dependenciesPolicy: continue_with_warnings` and `emissionsPolicy: class_average`.
Texture/appearance patches are accepted without confirming their original model.
Unavailable or ambiguous dependencies do not block a draft; verified available
inputs are included and freshness checked. Unresolved references are reported.
This policy is part of queue, report and receipt identity.

Authored TF2 vehicle values take precedence over donor replacements. TF2 constant
vehicle mass maps to zero additional payload mass; authored aircraft payload is
already kilograms. EMP's explicit payload hints retain their documented unit
conversion. Where the strict model profile is unsuitable, literal vehicle data
can use the installed TF3 metadata adapter. Every transitively imported native
helper is fingerprinted. Cargo is ported before the native adapter to preserve
capacities and canonical cargo references. Unrepresentable coupled layouts still
block rather than lose entries. Source Lua is never executed by the app.

Vehicle drafts retain unknown simple cargo identifiers as explicitly unverified
external `cargos/<id>/<id>.cargo` references, without guessing an equivalent
cargo or expanding its class. Capacities survive. Native `STRETCH_HEIGHT_NONE`
bay scaling, BIG/SMALL discrete defaults and MEDIUM4x1/MEDIUM2x1 LEVEL defaults
are supported. Combined cargo displays follow the installed native adapter's
custom-slot precedence without changing capacity. Literal unknown optional
scaling strings are retained with warnings. Invalid optional display attachments,
out-of-range variation palettes, inactive material fields, inert author asset tags,
unused invalid mesh descriptors and unsupported helper animations are archived
with warnings. Referenced meshes without geometry remain explicit external
references; no replacement geometry is invented. Empty authored menu models
and unsupported non-vehicle render examples with explicitly empty metadata do not block
the package's physical vehicles.
Blank mesh material defaults may use a unanimous, complete material-slot
assignment from all referring models. Conflicting assignments are retained as
review errors; mesh geometry and animation bytes are not changed by that binding.
Blank optional single-sampler texture bindings use the native shader default;
their originals and appearance warnings are retained. Legacy material coefficients
with no corresponding native shader input are archived with a warning. An unused,
empty cargo-slot provider can be archived when no custom load display uses it.
Menu models without geometry retain their authored physical and grouping values.
Conflicting authored and installed TF2 inputs are preserved separately under a
`tf2_base` resource folder. Installed dependencies retain their own author context;
their archives, target references and source hashes identify the exact input.
The non-blending `PHYS_TRANSPARENT` and `PHYS_TRANSPARENT_NRML_MAP` adapters
archive undeclared recoloring/aging blocks and samplers absent from their source
shaders, retaining the actual type and declared texture inputs. Declared native
properties still retain their authored channels. Mesh `.msh_`/`.msh.blob_`
backups use inert `.editor_backup` endings so their bytes cannot replace live
geometry. Stray mesh tables outside `children` retain the real graph and integer
bindings. Numeric custom-slot siblings follow the native helper's explicit
`configurations` field without adding slots. Visibility names absent from all
source LODs and literal external `rt_off` flags remain archived with warnings;
vehicle capacities and existing bindings are retained.
Format proofs can be reused across fresh readers only for the same validator,
canonical resource and exact current byte hashes. ZIP directory metadata is
reused only after reading and hashing the current directory bytes; each member
is still read from a newly opened archive. Size or timestamps never prove freshness.

Noise and pollution use separate arithmetic means of explicit installed native
scores, first within matching vehicle family, propulsion and size, then within
the same family. Negative/automatic scores, booleans and non-finite values are
excluded. The audit lists the population, values, method and estimated status.
No arbitrary score is substituted when a class has no usable population.

Unported behavior, menus and sound helpers remain in `_port_originals`, with
warnings. The native empty player-logo property receives empty parameters and
an appearance warning. Missing optional aircraft radii may use circular source
geometry or the native legacy default, with recorded evidence and warnings.
No output is certified playable without a TF3 test.

## Strict CLI and earlier releases

Version 0.14 records explicit noise/pollution choices in the per-mod report and
resume receipt. `--emissions-policy strict` is the default. `legacy_noise`
requires all three finite nonnegative coefficients within the documented TF3
ranges; they become noise idle/power/speed with automatic pollution.
`tf3_automatic` records the explicit replacement of valid legacy coefficients
with automatic noise and pollution. Neither choice proves gameplay equivalence;
all original values remain archived. Both `batch` and `port-tf2` accept the
option. The desktop exposes the choice for the selected emission blocker.

Optional aircraft payload omission can use evidence covering every installed
plane profile instead of requiring a similar vehicle donor for that field.
One explicit payload declaration or unclassified plane disables this policy.
Other missing fields still require the existing geometry and physical guards.

Supported exact soundeffectsutil and bbs2util editions have independent brake,
slow and squeal semantics. A recognized filename alone does not authorize an
adapter, and unsupported chuffs or missing authored event clips remain blockers.
Dependency-header inspection reads only sealed literal requiredMods and
identity fields; it never executes local helpers or imports. Equal pure literal
duplicate fields record both expressions and source locations in the audit.

Version 0.13 preserves supported RGB palettes and explicit seat poses, retains authored cargo coverage when inferred additions lack generic visuals, and adds bounded exact installed TF2 category adaptation. Automatic completion of supported missing vehicle data still uses sufficiently similar installed TF3 objects. Every export uses an installed TF3 inventory, preserves the source, stages the complete package and audits its resources before writing a separate local draft. The queue uses the same exporters as `port-tf2`.

| Profile | Implemented behavior |
|---|---|
| Rail | Horse, steam, diesel and electric engines; unpowered freight/passenger wagons; named axles, per-LOD fake bogies, reversal lights, capacities and sound. |
| Road | Buses, trucks, horse vehicles and AI cars; shared land physics, wheels, steering, supported lights, cargo/passengers and sound. |
| Tram | Tram/electric-tram modes, land physics, wheels/bogies, supported alternating blink animations and cargo/passengers. |
| Water | Small/big ship modes, kg mass, power/waterline data, paddles and authored rudder-angle animations. Redundant zero-Z waterline coordinates are reduced with an audit. |
| Air | Small/big aircraft modes, kg mass, thrust/wing data, gear radii/positions, propellers and authored control-surface-angle animations. Missing radii use evidenced source LODs or guarded native estimates; unmatched/conflicting radii block export. |
| Cargo | Current/legacy/capacities schemas, passenger seats, simultaneous fixed compartments, alternative load configs, hidden nodes, generic bays and dynamic cargo slots. Same-class additions require representable visuals; authored cargo coverage is preserved when an inferred addition lacks a generic template. |
| Render models | Static assets, trees, rocks and people; stable named nodes, meshes/materials, supported inline/file animations, ordered literal RGB palettes, camera/label references and literal particle visuals. |
| Configurations | Multiple units, railroad crossings, auto ground textures, ground textures, terrain materials and grass with typed TF3 resource endings. |
| Infrastructure | Literal track/street templates and styles, supported catenary variants and built-in default bridge factory capture parameters. |
| Decorative construction | Constant ASSET_DEFAULT/ASSET_TRACK results, verified ParamBuilder templates and finite model/color/height selectors become native script modules; authored selections, random branches, offsets, heights, track snapping and rotation remain parameterized. Unsupported loading, track-state and API callbacks remain blocked. |
| Rail signals | Literal PATH_SIGNAL, ONE_WAY_PATH_SIGNAL and WAYPOINT models become native edge constructions; geometry, animations, categories and explicit prices remain intact. |
| Common resources | Native-property material migration; speed/power, steam and bounded brake-gated sound controls; per-language translation composition; thumbnails; lowercase namespaces; geometry validation; verified native substitutions, recursive exact Workshop dependencies and bounded exact installed TF2 category adaptation. |

Coverage is conditional on known source schemas. Recognizing a class does not establish that every third-party implementation can be converted automatically. Meaningful mod lifecycle callbacks, arbitrary Lua/API/game scripts, native extensions, functional stations/industries/depots/modules, portal-only tunnels, custom cargo/economy definitions, unverified metadata, missing resources and opaque resource archives remain explicit migration blockers. They receive **Needs review**, never a successful metadata-only fallback.

Source Lua is parsed without execution. Straight-line literal locals, assignments and verified vec3/transf mathematical helpers can be folded; a narrow bridge/texture helper vocabulary is interpreted from verified semantics. Literal translated fragments are composed separately for each locale. Bounded recognized sound and asset callbacks produce newly authored native scripts. Finite decorative model/color/height selectors retain parameter indices, conditional uniform random calls, duplicate choice weights and independently selected trailer models. Rebound helpers, unsupported calls and other callback-dependent data remain explicit blockers. Generated filenames are deterministic and collision checked. Original changed files remain in `_port_originals`.

Native `::/` references retain exact shipped filename case, including uppercase letters. Generated local resource paths use lowercase names. Explicit `port-tf2 --revision` overrides apply before staged validation; a fractional legacy version can therefore use a chosen nonnegative integer revision for its separate TF3 draft while the original metadata remains archived.

Metadata localization arguments may use a string global assigned once in the same package's `strings.lua` data function. The static reader verifies the exact literal value, retains it as the translation key and leaves every locale table intact, including an empty table's literal fallback. Local/function/parameter shadows, repeated assignments, mutations, unresolved names and behavior remain blocked. `metadataMigrations` records the binding and its source; neither source file is executed or rewritten.

Imported descriptors use their owning Workshop package's exact resources,
requiredMods, helper files and language tables. Explicit translations receive a
provider namespace; plain display literals remain literal. Custom owner files
take precedence over native stock roles unless their bytes are verified stock.
Every contributing descriptor/blob/audio/helper/locale and relevant provider
metadata is recorded and revalidated. Conflicting descriptor author contexts
that would share one export path remain blockers.

Only complete known ParamBuilder, bbs2util and soundeffectsutil2 helper hashes
are accepted. Their source bytes are archived; adapted native scripts preserve
the verified formulas and choices. Changed or unknown helper variants require
their own profile. Stock audio helpers are verified against the installed TF3
API and preserve track/event counts, gain/pitch and sound attributes.

## Automatic missing-data completion

Completion fills only absent/None fields supported by an explicit adapter. Existing numeric values, zero capacities, cargo definitions, declared propulsion, empty/unpowered engine arrays, node geometry and identities remain authoritative. Malformed supplied values and unsupported behavior are errors; a similar object does not authorize replacing them.

| Missing data | Completion policy |
|---|---|
| Speed and empty mass | Copy a compatible native scalar, converting native kg back to TF2 tonnes for land vehicles before the existing unit adapter. |
| Declared land-engine power/tractive effort | Complete the missing value at its existing engine position from a donor with the same declared engine types/order; no engine or propulsion type is invented. |
| Ship simulation | Complete supported area, available power or maximum RPM. Power/RPM completion requires verified source propulsion evidence. |
| Aircraft simulation | Complete supported thrust, time to full thrust or wing area; propulsion-dependent fields require verified source propulsion evidence. |
| Loading speed | Use the selected compatible native transport profile's scalar value. |
| Typed cargo capacity | Fill an absent capacity through compatible independent compartments and unambiguous verified cargo-type or same-class correspondence. Preserve source cargo IDs, seats, layout and visuals. |
| Aircraft gear radii | Prefer existing corresponding source LOD evidence. Use guarded native geometric estimates only when named gear roles, positions and scales are compatible. |
| Ship waterline | Align and uniformly scale a comparable native hull outline, with an explicit estimate in the report. |

The donor must satisfy hard family, carrier, SMALL/BIG infrastructure restrictions, powered/unpowered status, engine types, passenger/freight role and cargo compatibility gates. Known source propulsion must match. Ship/air propulsion-dependent completion requires a verified standard marker. Unknown carrier, cargo identity or infrastructure class cannot be invented from a donor. An eligible native UNIVERSAL freight profile may inform numeric data for an already identified load; this never broadens the source cargo class or visuals.

Body dimension ratios must remain within 1.65 per axis. Available physical values must remain within a ratio of 2, with zero/nonzero conflicts rejected. A weighted comparison of body dimensions, supplied physical values and known raw capacity must remain within its allowed score. Names and filenames do not contribute. Close candidates that provide different requested values stop export; interchangeable requested values may share equivalent donor evidence. Missing source bounds and insufficient or ambiguous evidence produce **Needs review**.

Source gear correspondence requires explicit unique node names and identical full world transforms. Native gear estimates additionally require equal axle/wheel role-name sets and counts, uniform body scaling within 5%, normalized world gear positions within 2% of body extent, and uniform, unsheared node scaling. Local radii account for both donor and source node scales. Source mesh references, node positions and control bindings stay unchanged; authored zero radii are retained. A donor cannot repair arbitrary missing nodes, steering bindings or control surfaces. Native hull estimates require uniform body dimension scaling within 5%; the report records the aligned outline and scale. Geometry estimates require native inspection and do not reconstruct the original author's intended shape.

`migrationAudit.dataCompletions` records source field, new value, donor field/value/resource, unit conversion, method and estimate status. `nativeDonorMatches` records requested data, compatible classes, physical evidence, confidence, score and close alternatives. Exact source-LOD radius transfers are distinguished from native estimates. Reports retain `nativeTest: not_run` and required native checks.

The donor catalog uses a cached lexical projection of literal native model metadata/bounds; it avoids constructing unused LOD trees. Unsupported source shapes use the existing full static parser. A selected donor's full model is parsed lazily when geometry is needed and must agree with its projected metadata/bounds. Source Lua is never run. Donor asset files, scripts, names, mod IDs, crew/entrance bindings and node IDs are not transferred.

## Cargo and units

Same-class freight expansion uses the selected installed catalog's BULK, LIQUID, GOODS or FLATBED evidence, respects exclusions and avoids accidental expansion through UNIVERSAL into unrelated classes. Unknown cargo IDs need explicit verified mappings. Fixed source visual loads cannot be reused for newly inferred cargo without a verified generic visual template.

When a generic bay/dynamic format template can represent an eligible addition, the adapter retains that expansion. Otherwise it withholds only the newly inferred type and preserves every authored mapped cargo type, restriction, capacity, indicator and slot. It does not assign a fixed authored visual to an unrelated load or discard active authored behavior. `migrationAudit.cargoMigrations.omittedInferredExpansions` records the compartment, inferred type, installed class evidence and `no_verified_generic_visual_template` reason under the `preserve_authored_cargo_coverage` policy. Malformed authored data and unsupported combined visual systems still block export.

Existing source raw capacities remain unchanged; newly completed absent capacities are recorded separately. Land/ship maximum simultaneous capacity uses the selected donor's declared native payload/capacity ratio. The former blanket 300 kg per raw unit fallback has been removed. All 30 inspected native aircraft omit the optional `weightMaxPayload` field; a compatible matched aircraft follows that native omission. Zero capacity receives zero payload. Neither policy establishes equivalent physics; loaded mass and acceleration need native checks. Rail/road empty mass changes from tonnes to kg; ship/air mass is already kg. Speed, power and thrust retain their documented units. Maintenance lifespan changes from TF2 half-day units to TF3 quarter-day units (factor two).

Literal particle visuals preserve source endpoints with linear size/fade curves. Source emitters do not identify exhaust versus cylinder steam; no semantic ID is inferred from color. Engine-dependent timing needs native verification and is recorded in `particleMigrations`.

Literal model `colorConfig` RGB palettes retain their authored values and palette/channel order. Each palette must address the same supported color channels with finite RGB components in range. `colorMigrations` records the original palette, installed schema evidence and preservation policy. This is separate from material color blending below.

Legacy seat `standing` flags are retired only for `false` with explicit `animation = "sitting"`, or `true` with explicit `animation = "idle"`. The animation, seat transform and other authored seat fields remain. A supplied standing flag with a missing, conflicting or malformed animation blocks export; `seatMigrations` records each matching flag removed and its installed schema evidence.

Material properties must be declared by the selected installed material type; a standalone property file is insufficient evidence. Color blending uses the specific material's two/four-channel definition. Legacy scalar scales target the single source color channel; explicit source scales/colors are retained and empty/trailing channels use installed defaults. Every such change records its schema and policy. Editor backups keep an inert `.editor_backup` ending; normalization rejects empty, current and parent path segments before creating the destination.

Legacy material defaults in mesh descriptors are resolved directly. A missing default may use the explicit model material at the same submesh slot only when every model referrer has a complete verified material list and all agree on the target. The audit records this evidence; index/attribute values, embedded animations and binary blobs remain unchanged. LOD mesh variants may share a configuration only through explicit corresponding node names with identical full world transforms, never guessed filename suffixes. Empty/single literal URL wrappers are unwrapped with their source value recorded.

During version 0.9 validation, three installed Workshop packages were inspected through complete draft export attempts with source hashes unchanged. Those strict material checks stopped MAN SL202 at an undeclared `alpha_scale` property and Cessna172 at `color_blend` on a material type without that property. Cessna also had unsupported aircraft engine metadata later in the model path. Opel Insignia used computed/global metadata requiring migration. MAN's LOD references and three missing legacy mesh defaults received verified adapters, including a read-only check of the actual mesh and matching door animations. These historical attempts produced no successful complete export or gameplay claim; they are not version 0.10 conversion results.

## Exact installed TF2 category adaptation

Verified native resource roles and verified identical native files remain the preferred resolution. If neither provides a supported replacement, the exporter can read the exact requested resource from the detected or explicitly selected TF2 installation. Supported inputs include models, mesh/blob pairs, materials, animations, textures, sound sets and audio. Loose files and archive members use the installed mount selection; unrelated similar names are not substitutes.

`SourceGameResources` validates bounded shared mesh/animation schemas and supported texture/audio binary formats before importing source bytes. Model, material and sound descriptors still pass their category adapters and recursively resolve their own installed source dependencies. Geometry and binary inputs retain their checked bytes; unsupported descriptor behavior or binary formats block export. No source or installed Lua is executed.

Raw inputs are retained under `_port_originals`. `sourceGameDependencies` records source resource, installation, container/member, SHA-256, validation policy and exported target. `sourceGameResourceFingerprints` and `sourceGameInventoryFingerprint` track referenced bytes and mount selection. Fresh verification runs before completion and when a completed receipt is resumed; changed evidence invalidates that receipt. This produces a local draft with `nativeTest: not_run`, without a claim of rendering, audio or gameplay success.

`workshopAbsentDependencies` records scoped author/declared-dependency lookup failures used before the installed-source fallback. Fresh verification checks those resource absences and declaration metadata too. An exact resource added to that author or its declared dependencies invalidates the previous fallback receipt; unrelated providers do not alter this scoped evidence.

## Evidence and research

Primary format references are the [TF2 vehicle types](https://wiki.transportfever2.com/doku.php?id=modding:vehicletypes), [TF3 vehicle types](https://wiki.transportfever3.com/doku.php?id=modding:vehicles:types), [TF3 model metadata](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mdl), [cargo definitions](https://wiki.transportfever3.com/doku.php?id=modding:misc:cargo), [TF2 meshes](https://wiki.transportfever2.com/doku.php?id=modding:resourcetypes:msh), [TF3 meshes](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:msh), [resource structure](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes), [tracks/streets](https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:tracksstreets) and [bridges/tunnels](https://wiki.transportfever3.com/doku.php?id=modding:infrastructure:bridgestunnels). Installed definitions are checked when documentation and shipped fields differ.

External projects researched include [Tpf2 Mod Studio](https://github.com/CeberusOne/Tpf2-Mod-Studio) for static parsing, resource checks and dependency-aware inventories; [TpFMC](https://github.com/Enzojz/TpFMC) for historical model conversion; [modutram](https://github.com/eisfeuer/modutram) and [modular train stations](https://github.com/eisfeuer/tpf2-modular-train-station) for construction/module boundaries; and [Auto Line Namer Plus](https://github.com/AnujCtrl/tpf2-auto-line-namer-plus) for separating game API logic from testable data logic. These projects do not supply a universal TF3 exporter. No third-party implementation was copied into this MIT project.

Historical version 0.9 read-only checks of TF2's 374 native vehicle models validated the metadata adapter for 351 models: all 29 buses, 33 cars, 27 trams, 57 trucks, 64 wagons and 21 ships; 109 of 114 trains and 11 of 29 aircraft. Remaining failures were explicit emissions or missing/conflicting aircraft radii. These are **metadata adapter checks**, not version 0.10 completion results, full mod-package exports or in-game tests. Eight representative cargo layouts were checked against installed TF3 definitions. Automated package tests use authored fixtures for every vehicle family and selected resource configurations.

Read-only checks for the new catalog inspected 355 installed TF3 vehicle definitions. All 355 accepted the literal metadata-projection path; 341 provide supported donor profiles, while helicopter/zeppelin profiles are excluded. All 27 inspected ships declare payload values, with ratios of 150 or 300 kg per raw capacity unit. None of the 30 inspected aircraft declares that optional payload field. Completion integration checks on copied installed Aboag, Alco HH600 and Junkers F13 definitions selected their corresponding TF3 models, restored absent simulation fields and kept original source hashes unchanged. These observations establish installed format/data evidence, not gameplay support. Current test and package-build records are maintained in [VALIDATION.md](VALIDATION.md).

The report retains `nativeTest: not_run`. Rendering, audio, particle timing, cargo loading, motion, infrastructure use and save/reload still require native tests. Earlier SJ Class D runtime observations remain documented separately in [VALIDATION.md](VALIDATION.md).

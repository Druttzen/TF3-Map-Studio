# General conversion logic: TF2 → TF3

The target is a converter for complete mod packages, including every vehicle family and mixed content. The existing electric-locomotive profile is one narrow exporter, not the architecture for all mods.

## What version 0.5 implements

`analyze` inspects a resource directory without executing Lua or requiring valid root metadata. The same conversion plan is available in normal inspection, desktop preview and export reports. It identifies categories from model metadata, resource endings and known legacy config directories. It keeps unknown/computed models visible instead of guessing from a model name. Several categories can coexist in one package.

~~~console
trf3-mod-converter analyze "F:\TF2\mods\any_mod"
~~~

The plan describes required migrations and explicitly reports `exportSupport: not_claimed_by_analysis` and `nativeTest: not_run`. Analysis does not add export support merely by recognizing a category. The current exporters remain metadata/layout conversion and the strict electric-locomotive draft profile.

A shared mesh validator now checks descriptor ranges, attribute component counts, every separate index stream, triangle counts and non-finite values. This applies to meshes from any mod category. Invalid ranges/indices block export before replacing existing output. Non-finite values are reported without changing the original. Unsupported descriptors are marked unverified, never passed. Payloads such as textures and audio still need their own format/engine checks.

## Reusable conversion pipeline

1. Inventory every resource and dependency across the package. Keep base-game and external-mod namespaces distinct. Use one explicit old→new path map and detect collisions and unresolved references.
2. Parse source data statically. Preserve all fields and scripts, including data not understood by the current rules. Record computed references as unresolved work.
3. Normalize models into named nodes, hierarchy, LOD, materials, animations and typed metadata. Keep per-LOD identity maps. Numeric IDs for different domains must not be conflated.
4. Apply a migration rule for each resource kind. Shared geometry/material/reference logic should be reusable; physics, transport and callback rules remain type-specific. Every unit conversion must name the source field and target field. Never apply one global weight or power factor.
5. Validate the combined staged package, retaining originals and a report of each change. No unresolved component should be described as fully converted.
6. Validate rendering and behavior in TF3. Buying a vehicle alone does not prove motion, loading, sound or animation. Test save/reload and affected inter-mod dependencies too.

Steps 1–6 describe the complete intended pipeline. Version 0.5 implements category/requirement analysis, shared mesh checks, existing literal-reference checks and the previous exporters; a normalized model intermediate representation and the additional exporters still need implementation.

## Category-specific logic

| Content | Required adapter work |
|---|---|
| Road vehicles: buses, trucks, cars and horse vehicles | Land dynamics, wheels/steering, capacities, doors, lights and traffic/depot behavior. |
| Rail: steam/diesel/electric locomotives, wagons and railcars | Engines or no engine, per-LOD bogies, wheel animation, consist orientation, coupling and loads. |
| Trams and multiple units | Transport/depot modes and correctly ordered, oriented constituent models. |
| Ships | Propulsion units, waterline, rudder/propellers and pier compatibility. |
| Aircraft | Flight dynamics, control surfaces, landing gear, propellers and airport compatibility. |
| Repaints and model variants | Preserve referenced parent models, material/texture variants, namespaces and dependencies. |
| Stations, depots, assets, industries and town buildings | Construction type, parameters, callback split, networks/terminals, slots, terrain operations and production rules. |
| Modular constructions | Module types, slots and getModels/update callbacks, including captured parameters. |
| Streets, tracks, bridges, tunnels, crossings and signals | Distinct TF3 schemas, networks/styles/templates and relevant construction/update logic. |
| Terrain, climates, vegetation, people and animals | Appropriate model/generator metadata, distribution and behavior; shared model checks still apply. |
| Cargo and economies | Preserve relationships between cargo definitions, formats/classes, vehicles and production/consumption. |
| Sound, material and shader mods | Preserve events/texture channels and resolve the exact TF3 schemas or programs. |
| Gameplay/UI/mission scripts | Migrate API calls, imports, lifecycle, persistence and callbacks; behavior cannot be converted by extension renaming. |
| Localization and names | Retain keys and languages and update references consistently. |

This table is the development specification, not a claim that every adapter is implemented. The analysis registry deliberately groups several subtypes; unknown extensions/configurations remain explicit.

## Verified primary references

- [TF2 vehicle types](https://wiki.transportfever2.com/doku.php?id=modding:vehicletypes) and [TF3 vehicle types](https://wiki.transportfever3.com/doku.php?id=modding:vehicles:types): shared land dynamics versus type-specific vehicle logic; TF3 uses named nodes. Verify units field by field.
- [TF3 resource structure](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes): typed resource endings, namespaced references and static resources linked to script callbacks with capture parameters.
- [TF3 model metadata](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mdl) and [materials](https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:mtl): general model fields, visible loads and material definitions.
- [TF2 constructions](https://wiki.transportfever2.com/doku.php?id=modding:constructiontypes) and [TF3 modular constructions](https://wiki.transportfever3.com/doku.php?id=modding:constructions:modular): construction-specific output and modular callback interfaces.
- [TF3 script API](https://wiki.transportfever3.com/script-doc/): API-level verification for behavioral mods. Some wiki pages, including [modifiers/filters](https://wiki.transportfever3.com/doku.php?id=modding:scripting:modifiersfilters), explicitly warn that their content has not yet been adapted for TF3. Treat those as historical leads and verify against the installed game, not as conversion authority.

External TF2 tools are references for algorithms, not universal TF3 exporters. No third-party code was incorporated into this implementation. The newly written checks and registry retain this project's MIT license.

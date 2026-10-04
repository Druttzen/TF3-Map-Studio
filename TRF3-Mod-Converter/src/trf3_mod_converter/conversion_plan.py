"""Evidence-based conversion requirements for mixed TF2/TF3 mod packages.

This registry describes required migrations, not implemented export support.
Unknown/computed resources remain visible. Source Lua is never executed.
"""
from __future__ import annotations

from collections import Counter
import contextlib
import io
from pathlib import Path

from .filesystem import linked
from .lua_metadata import load_lua_table
from .mesh_audit import audit_mesh
from .resource_audit import parse_lua
from .lua_metadata import _value
from luaparser import astnodes as lua

WIKI = "https://wiki.transportfever3.com/doku.php?id=modding:"
COMMON_MODEL = ["Preserve geometry, hierarchy, transforms and LOD; assign stable node names.",
                "Resolve meshes, materials, textures and animations through an explicit path/namespace map.",
                "Migrate metadata field by field; preserve unknown fields for review."]
VEHICLE_COMMON = ["Map cargo/passenger compartments, capacity, seats and visible loads without losing entries.",
                  "Migrate sound, animation events, availability, cost, maintenance and emissions.",
                  "Select transport modes, depot filters and transformator from verified TF3 definitions."]
RULES = {
    "road_vehicle": ("vehicles:types", VEHICLE_COMMON + ["Move dynamics to landVehicle; check source units.", "Map axles, steering parts and wheels to node names; validate turning and lights."]),
    "rail_vehicle": ("vehicles:types", VEHICLE_COMMON + ["Move dynamics to landVehicle; check source units.", "Map axles and per-LOD bogies; validate coupling, reversal and wheel events.", "Handle HORSE, STEAM, DIESEL, ELECTRIC or unpowered vehicles separately."]),
    "tram": ("vehicles:types", VEHICLE_COMMON + ["Apply rail dynamics and tram transport modes; validate curves, blinkers and doors."]),
    "water_vehicle": ("vehicles:types", VEHICLE_COMMON + ["Migrate propulsion, mass, power units, waterline and pier compatibility.", "Validate rudder/propeller events and wake appearance."]),
    "air_vehicle": ("vehicles:types", VEHICLE_COMMON + ["Migrate flight dynamics and airport compatibility.", "Map wheels, landing gear, control surfaces and propeller/light events."]),
    "multiple_unit": ("vehicles:types", ["Migrate every referenced vehicle first; retain consist order and orientation.", "Generate .mu.lua with explicit references, availability, filters and variant grouping."]),
    "static_model": ("general:resourcetypes:mdl", ["Identify model metadata and migrate functional keys; keep decorative models separate from networks."]),
    "model_metadata": ("general:resourcetypes:mdl", ["Review non-vehicle model metadata (signals, vegetation, people, animals, networks and depots) against its TF3 schema."]),
    "construction": ("constructions:basics", ["Migrate to .con.lua and separate static configuration from .script.lua callbacks.", "Adapt callback arguments and output schema; preserve parameters and captureParams.", "Migrate networks, terminals, slots, terrain operations and cargo/stock rules for the construction type."]),
    "module": ("constructions:modular", ["Migrate to .module.lua; map slots, metadata and getModels/update callback references."]),
    "infrastructure": ("infrastructure:bridgestunnels", ["Distinguish street/track templates, styles, bridges, tunnels, crossings and traffic lights.", "Map to the matching TF3 resource type; adapt lanes, materials, networks and update callbacks."]),
    "environment": ("general:resourcetypes", ["Migrate climate, terrain generator/material, ground texture, grass or environment to its TF3 resource type.", "Adapt generator/distribution logic and resource dependencies; compare terrain output."]),
    "cargo": ("misc:cargo", ["Map cargo types, classes, formats, sets and cargo models; update vehicles and industries together."]),
    "sound": ("general:resourcetypes", ["Migrate sound definitions to .snd.lua; preserve events and resolve audio files."]),
    "script": ("general:syntax", ["Parse imports and lifecycle/game callbacks without executing the source.", "Migrate API calls and require/ug_require namespaces; split callback resources where needed.", "Test runtime state, save/load and inter-mod dependencies; do not infer API compatibility from syntax."]),
    "rendering": ("general:resourcetypes:mtl", ["Validate material/shader types against installed TF3 definitions; retain texture channels and transparency."]),
    "localization": ("general:syntax", ["Preserve translation keys and language variants; migrate legacy strings.lua to strings.json."]),
    "unknown": ("general:resourcetypes", ["Identify this resource before selecting a migration; copying is not evidence of compatibility."]),
}
NATIVE_ENDINGS = {
    "construction": (".con.lua",), "module": (".module.lua", ".module"),
    "infrastructure": (".street.lua", ".street_template.lua", ".bridge.lua", ".tunnel.lua", ".rcr.lua", ".trl.lua", ".edge.lua"),
    "environment": (".clima.lua", ".gen.lua", ".env.lua", ".tmat.lua", ".grass.lua", ".gtex.lua", ".agt.lua"),
    "cargo": (".cargo.lua", ".cmf.lua", ".cargoclass.lua"), "sound": (".snd.lua",),
    "multiple_unit": (".mu.lua",), "script": (".script.lua", ".script.tl", ".gs.lua", ".mission.lua", ".campaign.lua", ".eco.lua"),
    "rendering": (".mtl", ".mat.lua", ".prop.lua", ".fs", ".vs", ".glsl", ".tesc", ".tese", ".gs", ".tec", ".prog"),
    "localization": (".lang.lua", ".names.lua"),
}
LEGACY_CONFIGS = {
    "multiple_unit": ("multiple_unit/",), "module": ("module/",),
    "infrastructure": ("track/", "street/", "bridge/", "tunnel/", "railroad_crossing/", "traffic_light/"),
    "environment": ("climate/", "environment/", "terrain_generator/", "terrain_material/", "grass/", "ground_texture/", "auto_ground_tex/"),
    "cargo": ("cargo_types/",), "sound": ("sound_set/",), "script": ("game_script/",),
}


def _dict(value):
    return value if isinstance(value, dict) else {}


def _read_data(path):
    text = path.read_text(encoding="utf-8-sig")
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return load_lua_table(text)
    except ValueError:
        # Classification may inspect a literal return even when helper imports
        # or computations prevent the strict exporter from accepting the file.
        # It never resolves imports or treats this as export compatibility.
        try:
            tree = parse_lua(text)
        except Exception as error:
            raise ValueError("Cannot parse resource for static classification") from error
        definitions = [s for s in tree.body.body if isinstance(s, lua.Function)
                       and isinstance(s.name, lua.Name) and s.name.id == "data"]
        if len(definitions) != 1:
            raise ValueError("No unique data() function for static classification")
        definition_index = tree.body.body.index(definitions[0])
        for index, statement in enumerate(tree.body.body):
            if isinstance(statement, (lua.Assign, lua.LocalAssign)):
                if index > definition_index or any(isinstance(target, lua.Name) and target.id == "data" for target in statement.targets):
                    raise ValueError("Rebound data() function requires manual classification")
            elif not isinstance(statement, (lua.Function, lua.LocalFunction)):
                raise ValueError("Top-level control flow or calls require manual classification")
        body = definitions[0].body.body
        if any(isinstance(s, (lua.If, lua.While, lua.Repeat, lua.Fornum, lua.Forin, lua.Do)) for s in body):
            raise ValueError("Control flow in data() requires manual classification")
        returns = [s for s in body if isinstance(s, lua.Return)]
        if len(returns) != 1 or len(returns[0].values) != 1 or not isinstance(returns[0].values[0], lua.Table):
            raise ValueError("Computed data() return requires manual classification")
        value = _value(returns[0].values[0])
        if not isinstance(value, dict):
            raise ValueError("No literal resource fields for classification")
        return value


def _model(path: Path) -> tuple[str, dict]:
    data = _read_data(path)
    raw_metadata = data.get("metadata")
    if raw_metadata is not None and not isinstance(raw_metadata, dict) and raw_metadata != []:
        return "unknown", {"reason": "Computed or unsupported model metadata; category cannot be established."}
    m = _dict(data.get("metadata"))
    t = _dict(m.get("transportVehicle"))
    markers = [key for key in ("airVehicle", "waterVehicle", "railVehicle", "roadVehicle")
               if key in m and m[key] is not None]
    if any(not isinstance(m[key], dict) and m[key] != [] for key in markers):
        return "unknown", {"reason": "Non-literal or invalid vehicle metadata struct."}
    if len(markers) > 1:
        return "unknown", {"reason": "Conflicting vehicle metadata structs require manual classification."}
    modes = t.get("transportModes", [])
    is_tram = t.get("carrier") == "TRAM" or isinstance(modes, list) and any(mode in ("TRAM", "ELECTRIC_TRAM") for mode in modes)
    if "airVehicle" in markers: kind = "air_vehicle"
    elif "waterVehicle" in markers: kind = "water_vehicle"
    elif "railVehicle" in markers: kind = "tram" if is_tram else "rail_vehicle"
    elif "roadVehicle" in markers: kind = "road_vehicle"
    else: kind = "model_metadata" if m else "static_model"
    dynamics = _dict(m.get("landVehicle")) or _dict(m.get("railVehicle")) or _dict(m.get("roadVehicle"))
    engines = dynamics.get("engines")
    details = {"modelVersion": data.get("version") if type(data.get("version")) is int else None,
               "metadataKeys": sorted(str(k) for k in m), "carrier": t.get("carrier") if isinstance(t.get("carrier"), str) else None}
    if isinstance(engines, list):
        details["engineTypes"] = sorted({e["type"] for e in engines if isinstance(e, dict) and isinstance(e.get("type"), str)})
        details["unpowered"] = not engines
    return kind, details


def analyze_mod(source: str | Path) -> dict:
    root = Path(source).expanduser().absolute()
    if not root.is_dir(): raise ValueError("Select a mod directory for content analysis")
    if any(linked(p) for p in (root, *root.parents)): raise ValueError("Linked source path is not allowed")
    resources, geometry, problems = [], [], []
    bases = [p for p in (root / "res", root / "content") if p.exists()]
    if len(bases) > 1: problems.append("Both res and content exist; resolve layout before exporting.")
    if not bases: problems.append("No res or content directory; content migration cannot be assessed.")

    def visit(directory):
        for p in sorted(directory.iterdir()):
            if linked(p): problems.append(f"Linked source is not allowed: {p.relative_to(root).as_posix()}")
            elif p.is_dir() and p.name not in {".git", "__pycache__", ".pytest_cache"}: yield from visit(p)
            elif p.is_file(): yield p

    for base in bases:
        if linked(base):
            problems.append(f"Linked resource folder: {base.name}"); continue
        for path in visit(base):
            rel = path.relative_to(base).as_posix()
            category, details = "unknown", {}
            if path.suffix == ".msh":
                check = audit_mesh(path); check["file"] = path.relative_to(root).as_posix()
                geometry.append(check); continue
            if path.name.endswith((".msh.blob", ".dds", ".tga", ".hdr", ".wav", ".ogg", ".ani")):
                continue  # Payloads are dependencies, not independent mod profiles.
            try:
                if path.suffix == ".mdl": category, details = _model(path)
                elif path.suffix == ".con":
                    category = "construction"
                    data = _read_data(path)
                    details["constructionType"] = data.get("type") if isinstance(data.get("type"), str) else None
                else:
                    for key, endings in NATIVE_ENDINGS.items():
                        if path.name.endswith(endings): category = key; break
                    if category == "unknown" and rel.startswith("config/"):
                        for key, dirs in LEGACY_CONFIGS.items():
                            if rel[7:].startswith(dirs): category = key; break
                    if category == "unknown" and path.suffix in {".lua", ".tl"}: category = "script"
            except (ValueError, UnicodeError, OSError) as error:
                category = "unknown"; details["reason"] = str(error)
            chapter, requirements = RULES[category]
            resources.append({"file": path.relative_to(root).as_posix(), "category": category,
                              "evidence": details or {"classification": "resource ending or legacy config directory"},
                              "exportSupport": "not_claimed_by_analysis", "requirements": (COMMON_MODEL if path.suffix == ".mdl" else []) + requirements,
                              "source": WIKI + chapter})
    for path in (root / "mod.lua", root / "strings.lua", root / "strings.json"):
        if path.is_file() and not linked(path):
            key = "script" if path.name == "mod.lua" else "localization"
            chapter, steps = RULES[key]
            resources.append({"file": path.name, "category": key, "evidence": {"classification": "root resource"},
                              "exportSupport": "not_claimed_by_analysis", "requirements": steps, "source": WIKI + chapter})
    counts = dict(sorted(Counter(r["category"] for r in resources).items()))
    return {"source": str(root), "status": "needs_review" if problems or "unknown" in counts or any(g["status"] != "checked" for g in geometry) else "analyzed",
            "purpose": "Conversion requirements; does not claim automated export or TF3 compatibility.",
            "nativeTest": "not_run", "categories": counts, "resources": resources, "geometry": geometry,
            "problems": problems, "mixedMod": len(counts) > 1,
            "implementedExport": "Metadata/layout and verified literal road/rail/tram/water/air, cargo, render/config and constant-asset draft profiles. Dynamic/API behavior needs manual migration.",
            "sharedSteps": ["Build one dependency/path/ID map for the entire mod, including external mods and base resources.",
                            "Apply category migrations together; preserve originals and report each changed field.",
                            "Resolve shared resources and computed references; unknowns must remain explicit.",
                            "Validate the staged output, then test all affected behavior in TF3."]}

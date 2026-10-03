"""Offline reference checks. Source scripts are parsed, never executed.

This is deliberately a partial audit: computed references, Teal, external mods,
binary formats and game APIs still need engine testing.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from luaparser import ast, astnodes as nodes

from .lua_metadata import _value
from .filesystem import linked

TEXT_RESOURCES = {".lua", ".mdl", ".msh", ".mtl", ".ani", ".json"}
LUA_RESOURCE_ENDINGS = (
    ".trf", ".snd", ".clima", ".gen", ".eco", ".env", ".tmat", ".grass",
    ".script", ".gs", ".campaign", ".mission", ".con", ".module", ".gtex", ".agt",
    ".street_template", ".street", ".bridge", ".tunnel", ".rcr", ".trl", ".cargo",
    ".cmf", ".cargoclass", ".mu", ".css", ".plist", ".node", ".names", ".lang", ".res",
)
ASSET_ENDINGS = (
    ".mdl", ".msh", ".msh.blob", ".mtl", ".ani", ".dds", ".tga", ".hdr",
    ".wav", ".ogg",
) + LUA_RESOURCE_ENDINGS


def parse_lua(text: str):
    # luaparser's diagnostics are captured so CLI output remains valid JSON.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return ast.parse(text)


def callback_status(tree, key: str) -> str:
    """resolved/missing/unverified for a key returned by global data()."""
    definitions = [statement for statement in tree.body.body
                   if isinstance(statement, nodes.Function)
                   and isinstance(statement.name, nodes.Name) and statement.name.id == "data"]
    if not definitions:
        # A top-level return is not the TF3 resource data() interface.
        return "missing" if all(isinstance(s, (nodes.Return, nodes.LocalFunction))
                                for s in tree.body.body) else "unverified"
    if len(definitions) != 1:
        return "unverified"
    definition_index = tree.body.body.index(definitions[0])
    for index, statement in enumerate(tree.body.body):
        if isinstance(statement, (nodes.Assign, nodes.LocalAssign)):
            if index > definition_index or any(isinstance(target, nodes.Name) and target.id == "data" for target in statement.targets):
                return "unverified"
        elif not isinstance(statement, (nodes.Function, nodes.LocalFunction)):
            return "unverified"
    body = definitions[0].body.body
    if any(not isinstance(s, (nodes.Return, nodes.LocalFunction)) for s in body):
        return "unverified"
    returns = [s for s in body if isinstance(s, nodes.Return)]
    if len(returns) != 1 or len(returns[0].values) != 1 or not isinstance(returns[0].values[0], nodes.Table):
        return "unverified"
    bindings = {s.name.id for s in (*tree.body.body, *body)
                if isinstance(s, nodes.LocalFunction) and isinstance(s.name, nodes.Name)}
    # Only simple, stable local function bindings can be proved here.
    for s in ast.walk(tree):
        if isinstance(s, (nodes.Assign, nodes.LocalAssign)):
            bindings.difference_update(t.id for t in s.targets if isinstance(t, nodes.Name))
    value = returns[0].values[0]
    # TF3 function keys can traverse exported tables, e.g. bulk.updateFn.
    for part in key.split("."):
        if not part:
            return "missing"
        if not isinstance(value, nodes.Table):
            return "missing" if isinstance(value, (nodes.Nil, nodes.Number, nodes.String, nodes.TrueExpr, nodes.FalseExpr, nodes.AnonymousFunction)) else "unverified"
        matches = []
        for entry in value.fields:
            field_key = entry.key.id if isinstance(entry.key, nodes.Name) and not entry.between_brackets else _value(entry.key)
            if field_key == part:
                matches.append(entry.value)
            elif not isinstance(field_key, (str, int)):
                return "unverified"
        if not matches:
            return "missing"
        value = matches[-1]
    if isinstance(value, nodes.AnonymousFunction) or isinstance(value, nodes.Name) and value.id in bindings:
        return "resolved"
    if isinstance(value, (nodes.Nil, nodes.Number, nodes.String, nodes.Table, nodes.TrueExpr, nodes.FalseExpr)):
        return "missing"
    return "unverified"


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for entry in value.values():
            yield from _strings(entry)
    elif isinstance(value, list):
        for entry in value:
            yield from _strings(entry)


def audit_resources(root: Path, mod_id: str, *, source_id: str | None = None,
                    lifecycle: dict[str, str | None] | None = None,
                    metadata_extras: dict | None = None) -> dict:
    content = root / ("content" if (root / "content").is_dir() else "res")
    result: dict = {"filesScanned": 0, "references": [], "blockers": [],
                    "unverified": [], "nativeTest": "not_run", "coverage": "static literal references"}
    files: dict[str, Path] = {}
    trees: dict[str, Any] = {}
    strings: list[tuple[str, str, bool]] = []
    old_id = source_id or mod_id

    def issue(message: str) -> None:
        result["blockers"].append(message)

    def visit(directory: Path) -> None:
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(content).as_posix()
            if linked(path):
                issue(f"Linked resource is not allowed: content/{relative}.")
            elif path.is_dir():
                if path.name not in {".git", "__pycache__", ".pytest_cache"}:
                    visit(path)
            elif path.is_file():
                files[relative] = path

    if linked(content):
        issue("Linked resource folder is not allowed.")
    elif content.is_dir():
        visit(content)
    for relative, path in files.items():
        if not re.fullmatch(r"[a-z0-9_./@-]+", relative):
            issue(f"Resource path must use lowercase letters and no spaces: content/{relative}.")
        if path.suffix not in TEXT_RESOURCES:
            if path.suffix == ".tl":
                result["unverified"].append(f"content/{relative}: Teal requires engine validation.")
                if old_id != mod_id and old_id + "::" in path.read_text(encoding="utf-8-sig"):
                    issue(f"Cannot change modId: content/{relative} still references {old_id}::; migrate it explicitly.")
            continue
        result["filesScanned"] += 1
        text = ""
        try:
            text = path.read_text(encoding="utf-8")
            if text.startswith("\ufeff"):
                issue(f"content/{relative}: remove UTF-8 BOM before TF3 loading.")
                text = text.lstrip("\ufeff")
            if path.suffix == ".json":
                strings.extend((relative, s, False) for s in _strings(json.loads(text)))
            else:
                tree = parse_lua(text)
                trees[relative] = tree
                concat_children = {id(child) for n in ast.walk(tree) if isinstance(n, nodes.Concat)
                                   for child in ast.walk(n) if child is not n}
                strings.extend((relative, s, False) for n in ast.walk(tree)
                               if id(n) not in concat_children and isinstance(n, (nodes.String, nodes.Concat))
                               and isinstance(s := _value(n), str))
                for n in ast.walk(tree):
                    if isinstance(n, nodes.Call) and isinstance(n.func, nodes.Name) and n.func.id == "ug_require":
                        if n.args and isinstance(value := _value(n.args[0]), str):
                            strings.append((relative, value, True))
                        else:
                            result["unverified"].append(f"content/{relative}: computed ug_require reference.")
        except (ValueError, UnicodeError, SyntaxError) as error:
            issue(f"content/{relative}: cannot parse resource ({type(error).__name__}).")
        except Exception as error:
            # luaparser uses its own exception class for syntax errors.
            issue(f"content/{relative}: cannot parse Lua resource ({type(error).__name__}).")
        if old_id != mod_id and old_id + "::" in text:
            # Conservative even if it only appears in a comment; no hidden ID rewrite.
            issue(f"Cannot change modId: content/{relative} still references {old_id}::; migrate it explicitly.")
    result["unverified"].append("Computed references, external/base-game resources, binary formats and gameplay APIs require TF3 testing.")

    legacy_origins = set()
    if content.name == 'res':
        for origin, tree in trees.items():
            if not origin.startswith(('models/model/','models/material/')):
                continue
            native_material = any(isinstance(n,nodes.Field) and isinstance(n.key,nodes.Name)
                                  and n.key.id in {'fragmentSamplers','fragmentProperties','vertexProperties'}
                                  for n in ast.walk(tree))
            definitions = [n for n in tree.body.body if isinstance(n,nodes.Function)
                           and isinstance(n.name,nodes.Name) and n.name.id == 'data']
            returns = [n for n in definitions[0].body.body if isinstance(n,nodes.Return)] if len(definitions)==1 else []
            table = returns[0].values[0] if len(returns)==1 and len(returns[0].values)==1 else None
            version_one = isinstance(table,nodes.Table) and any(
                isinstance(f.key,nodes.Name) and not f.between_brackets and f.key.id=='version'
                and type(v := _value(f.value)) in (int,float) and v==1 for f in table.fields)
            if origin.endswith('.mdl') and version_one or origin.endswith('.mtl') and not native_material:
                legacy_origins.add(origin)

    def check(origin: str, reference: str, module: bool = False, force: bool = False) -> None:
        if not reference or not (force or module or "::" in reference or reference.split("@", 1)[0].endswith(ASSET_ENDINGS)):
            return
        # Ignore ordinary prose containing a filename, but explicit references are checked.
        if not force and not module and "::" not in reference and any(c.isspace() for c in reference):
            return
        callback = None
        ref = reference
        if "@" in ref and (force or ".script@" in ref):
            ref, callback = ref.rsplit("@", 1)
        namespace = mod_id
        if "::" in ref:
            namespace, ref = ref.split("::", 1)
        row = {"source": origin or "mod.json", "reference": reference}
        result["references"].append(row)
        legacy_root = None
        if origin.startswith('config/sound_set/') and reference.endswith(('.wav','.ogg')):
            legacy_root = 'audio/effects'
        elif origin in legacy_origins:
            legacy_root = next((prefix for ending,prefix in (
                ('.dds','textures'),('.tga','textures'),('.hdr','textures'),
                ('.msh','models/mesh'),('.mtl','models/material'),('.mdl','models/model'),
                ('.ani','models/animation'),('.wav','audio/effects'),('.ogg','audio/effects'))
                if reference.endswith(ending)),None)
        if legacy_root and '::' not in reference and not module:
            # TF2 uses resource-type roots with a base-game/mod fallback,
            # whereas TF3 references are relative to the containing resource.
            if '\\' in reference or reference.startswith('/') or '..' in PurePosixPath(reference).parts:
                row['status'] = 'invalid'
                issue(f"{origin}: unsafe TF2 resource reference {reference!r}.")
                return
            target = legacy_root+'/'+reference
            row['status'] = 'legacy_local' if target in files else 'legacy_base_or_missing'
            if target in files: row['target'] = content.name+'/'+target
            else: result['unverified'].append(f"{origin}: TF2 resource {reference!r} may come from the TF2 base game or another mod; its availability needs separate verification.")
            if origin.startswith('config/sound_set/'):
                issue(f"{origin}: TF2 sound set needs migration to a TF3 .snd resource and updateScript; use the supported vehicle port, not metadata-only conversion.")
            else:
                issue(f"{origin}: TF2 resource references need explicit TF3 migration; metadata-only conversion cannot rewrite their resource-type roots.")
            return
        if "\\" in ref or ".." in PurePosixPath(ref).parts or not re.fullmatch(r"/?[a-z0-9_./@-]+", ref):
            row["status"] = "invalid"
            issue(f"{row['source']}: invalid TF3 resource reference {reference!r}.")
            return
        if namespace not in {mod_id, old_id}:
            row["status"] = "external"
            return
        base = PurePosixPath(origin).parent if origin else PurePosixPath(".")
        target = str(PurePosixPath(ref.lstrip("/")) if ref.startswith("/") else base / ref)
        candidates = [target] if ref.endswith((".lua", ".tl")) else (
            [target + ".lua", target + ".tl"] if module or callback or not PurePosixPath(ref).suffix or ref.endswith(LUA_RESOURCE_ENDINGS) else [target])
        found = [c for c in candidates if c in files]
        if not found:
            row["status"] = "missing"
            issue(f"{row['source']}: missing local resource for {reference!r}.")
            return
        row["status"] = "resolved"
        row["target"] = "content/" + found[0]
        if callback:
            tree = trees.get(found[0])
            status = callback_status(tree, callback) if tree else "unverified"
            row["callbackStatus"] = status
            if status == "missing":
                issue(f"{row['source']}: {reference!r} does not expose callable {callback} through global data().")
            elif status == "unverified":
                result["unverified"].append(f"{reference}: data() callback could not be proved statically; test in TF3.")

    merged_strings: dict[tuple[str, str], bool] = {}
    for origin, reference, module in strings:
        merged_strings[origin, reference] = module or merged_strings.get((origin, reference), False)
    for (origin, reference), module in merged_strings.items():
        check(origin, reference, module)
    for key, reference in (lifecycle or {}).items():
        if reference:
            check("", reference, force=True)
    for reference in _strings(metadata_extras or {}):
        if old_id != mod_id and old_id + "::" in reference:
            issue(f"Cannot change modId: retained metadata still references {old_id}::; migrate it explicitly.")
    for relative in files:
        if relative.endswith(".msh") and relative + ".blob" not in files:
            issue(f"content/{relative}: missing companion mesh blob {relative}.blob.")
    result["blockers"] = list(dict.fromkeys(result["blockers"]))
    result["unverified"] = list(dict.fromkeys(result["unverified"]))
    result["status"] = "blocked" if result["blockers"] else "static_checks_passed"
    return result

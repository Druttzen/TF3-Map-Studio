from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .lua_metadata import UnsupportedValue, load_lua_table
from .filesystem import linked as _linked
from .resource_audit import audit_resources
from .conversion_plan import analyze_mod

_load_lua_table = load_lua_table
Progress = Callable[[str], None]
ALIASES = {
    "name": ("name", "displayName", "modName"),
    "modId": ("modId", "mod_id", "id"),
    "revision": ("revision", "version", "minorVersion", "majorVersion"),
    "summary": ("summary", "shortDescription"),
    "description": ("description", "details"),
    "authors": ("authors", "author"),
    "preRunScript": ("preRunScript", "preRunFn", "preScript"),
    "runScript": ("runScript", "runFn", "script"),
    "postRunScript": ("postRunScript", "postRunFn", "postScript"),
}


@dataclass
class ModDescriptor:
    name: str = "Unnamed Mod"
    summary: str = ""
    description: str = ""
    authors: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    url: str = ""
    mod_id: str = ""
    revision: int = 1
    dependencies: list | None = None
    incompatibilities: list | None = None
    params: list | None = None
    options: list | None = None
    severity_add: str = "None"
    severity_remove: str = "Warning"
    pre_run_script: str | None = None
    run_script: str | None = None
    post_run_script: str | None = None
    visible: bool = True
    cosmetic: bool = False
    localization: dict = field(default_factory=dict)
    modinfo_dependencies: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    metadata_files: list[str] = field(default_factory=list)
    script_configs: dict[str, dict] = field(default_factory=dict)
    native_mod_fields: dict = field(default_factory=dict)
    native_info_fields: dict = field(default_factory=dict)
    source_metadata: dict = field(default_factory=dict)
    source_id: str = ""
    resource_audit: dict = field(default_factory=dict)
    conversion_plan: dict = field(default_factory=dict)

    @property
    def target_mod_id(self) -> str:
        return self.mod_id or self._slugify_name(self.name)

    @staticmethod
    def _slugify_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "converted_mod"

    def as_mod_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {**deepcopy(self.native_mod_fields), **{
            "modId": self.target_mod_id,
            "revision": self.revision,
            "severityAdd": self.severity_add,
            "severityRemove": self.severity_remove,
            "visible": self.visible,
            "cosmetic": self.cosmetic,
        }}
        for key in ("dependencies", "incompatibilities", "params"):
            value = getattr(self, key)
            if value is not None or key in payload:
                payload[key] = deepcopy(value)
        for key, value in (("preRunScript", self.pre_run_script), ("runScript", self.run_script), ("postRunScript", self.post_run_script)):
            if value is not None:
                payload[key] = {**deepcopy(self.script_configs.get(key, {})), "fileName": value}
            elif key in payload:
                payload[key] = None
        return payload

    def as_modinfo_json(self) -> dict[str, Any]:
        payload = {**deepcopy(self.native_info_fields), **{
            "authors": deepcopy(self.authors),
            "description": self.description,
            "name": self.name,
            "summary": self.summary,
            "tags": self.tags,
            "url": self.url,
        }}
        if self.localization:
            payload["localization"] = deepcopy(self.localization)
        if self.modinfo_dependencies:
            payload["dependencies"] = deepcopy(self.modinfo_dependencies)
        return payload

    def as_inspection(self) -> dict[str, Any]:
        return {
            **self.as_modinfo_json(),
            "modId": self.target_mod_id,
            "revision": self.revision,
            "modJson": self.as_mod_json(),
            "metadataFiles": self.metadata_files,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "canConvert": not self.blockers,
            "sourceModId": self.source_id or self.target_mod_id,
            "resourceAudit": self.resource_audit,
            "conversionPlan": self.conversion_plan,
            "sourceMetadata": self.source_metadata,
        }


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        def reject_constant(value: str):
            raise ValueError(f"Non-finite JSON value {value}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError(f"Invalid JSON in {path.name}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file {path} must contain an object")
    return payload


def _canonicalize(raw: dict[str, Any]) -> dict[str, Any]:
    flattened = {}
    for key in ("data", "info"):
        nested = raw.get(key)
        if isinstance(nested, UnsupportedValue):
            raise ValueError(f"{key} contains {nested.reason}")
        if isinstance(nested, dict):
            flattened.update(nested)
    flattened.update({key: value for key, value in raw.items() if key not in {"data", "info"}})
    result = dict(flattened)
    for target, aliases in ALIASES.items():
        for alias in aliases:
            result.pop(alias, None)
        for alias in aliases:
            if alias in flattened:
                result[target] = flattened[alias]
                break
    return result


def _unsupported(value: Any) -> str | None:
    if isinstance(value, UnsupportedValue):
        return value.reason
    if isinstance(value, dict):
        for nested in value.values():
            if reason := _unsupported(nested):
                return reason
    if isinstance(value, list):
        for nested in value:
            if reason := _unsupported(nested):
                return reason
    return None


def _normalize_mod_descriptor(raw: dict[str, Any]) -> ModDescriptor:
    raw = _canonicalize(raw)
    descriptor = ModDescriptor()

    def read(key: str, default: Any) -> Any:
        value = raw.get(key, default)
        if key in {"preRunScript", "runScript", "postRunScript"} and isinstance(value, UnsupportedValue) and value.empty_callback:
            descriptor.warnings.append(f"{key}: empty inline callback has no behavior and is omitted from TF3 metadata; original metadata is retained.")
            return None
        if reason := _unsupported(value):
            descriptor.blockers.append(f"{key} contains {reason}.")
            return default
        return value

    def text(key: str, default: str = "") -> str:
        value = read(key, default)
        if value is None:
            return default
        if not isinstance(value, str):
            descriptor.blockers.append(f"{key} must be text.")
            return default
        return value

    descriptor.name = text("name", "Unnamed Mod") or "Unnamed Mod"
    descriptor.description = text("description")
    descriptor.summary = text("summary")
    if "summary" not in raw:
        descriptor.summary = " ".join(descriptor.description.split())[:100]
    descriptor.mod_id = text("modId").strip()
    descriptor.url = text("url")
    revision = read("revision", 1)
    if revision in (None, ""):
        revision = 1
    try:
        if isinstance(revision, bool) or (isinstance(revision, float) and not revision.is_integer()):
            raise ValueError
        descriptor.revision = int(revision)
        if descriptor.revision < 0:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        descriptor.blockers.append("revision must be a non-negative integer; set a revision override.")

    authors = read("authors", [])
    if isinstance(authors, (str, dict)):
        authors = [authors]
    if authors is None:
        authors = []
    if not isinstance(authors, list):
        descriptor.blockers.append("authors must be a list, an author object, or a name.")
        authors = []
    for entry in authors:
        if isinstance(entry, str):
            entry = {"name": entry, "role": "CREATOR"}
        if not isinstance(entry, dict) or not isinstance(entry.get("name") or entry.get("author"), str):
            descriptor.blockers.append("Each author needs a name.")
            continue
        author = deepcopy(entry)
        author["name"] = author.pop("author", None) or author["name"]
        author["role"] = author.get("role") or "CREATOR"
        descriptor.authors.append(author)

    tags = read("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        descriptor.blockers.append("tags must be a list of text values.")
    else:
        descriptor.tags = tags

    for key in ("dependencies", "incompatibilities", "params", "options"):
        value = read(key, None)
        if value is not None and (not isinstance(value, list) or any(not isinstance(entry, dict) for entry in value)):
            descriptor.blockers.append(f"{key} must be a list of objects; migrate legacy entries manually.")
        else:
            setattr(descriptor, key, deepcopy(value))
    if descriptor.options:
        descriptor.blockers.append("Legacy options require migration to TF3 params; they cannot be copied unchanged.")

    for source_key, attr, default in (("severityAdd", "severity_add", "None"), ("severityRemove", "severity_remove", "Warning")):
        value = text(source_key, default).capitalize()
        if value not in {"None", "Warning", "Critical"}:
            descriptor.blockers.append(f"{source_key} must be None, Warning, or Critical.")
        else:
            setattr(descriptor, attr, value)
    for key in ("visible", "cosmetic"):
        value = read(key, getattr(descriptor, key))
        if type(value) is not bool:
            descriptor.blockers.append(f"{key} must be true or false.")
        else:
            setattr(descriptor, key, value)
    for key, attr in (("preRunScript", "pre_run_script"), ("runScript", "run_script"), ("postRunScript", "post_run_script")):
        value = read(key, None)
        if isinstance(value, dict):
            descriptor.script_configs[key] = deepcopy(value)
            if "fileName" in value:
                value = value["fileName"]
            elif "filename" in value:
                value = value["filename"]
                descriptor.script_configs[key].pop("filename")
            else:
                descriptor.blockers.append(f"{key} needs a fileName, including an empty string for a disabled script.")
                value = None
            if not isinstance(value, str):
                descriptor.blockers.append(f"{key}.fileName must be text; an empty string disables the script.")
            if descriptor.script_configs[key].get("params"):
                descriptor.warnings.append(f"{key}.params is preserved, but TF3 mod lifecycle callbacks receive configDict/allModParams, not resource captureParams. Verify the script's argument contract in TF3.")
        if value is not None and not isinstance(value, str):
            descriptor.blockers.append(f"{key} must reference a TF3 script module.")
        else:
            setattr(descriptor, attr, value)
    localization = read("localization", {}) or {}
    if not isinstance(localization, dict):
        descriptor.blockers.append("localization must be an object of language entries.")
    else:
        descriptor.localization = localization
    descriptor.modinfo_dependencies = read("_modinfoDependencies", []) or []
    if not isinstance(descriptor.modinfo_dependencies, list) or any(not isinstance(entry, str) for entry in descriptor.modinfo_dependencies):
        descriptor.blockers.append("modinfo dependencies must be a list of mod.io id strings.")
    return descriptor


def _source_root(source: Path) -> Path:
    if source.is_dir():
        return source
    if source.parent.name == "_metadata" and source.name == "modinfo.json":
        return source.parent.parent
    return source.parent


def inspect_mod(source: str | Path) -> ModDescriptor:
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"Source does not exist: {source_path}")
    root = _source_root(source_path)
    filenames = ("modinfo.lua", "mod.lua", "modinfo.json", "info.json", "mod.json", "_metadata/modinfo.json")
    recognized = source_path.is_file() and source_path.relative_to(root).as_posix() in filenames
    if source_path.is_file() and not recognized:
        candidates = [source_path]
    else:
        candidates = [root / filename for filename in filenames]
    raw: dict[str, Any] = {}
    source_metadata: dict = {}
    native_mod_fields: dict = {}
    native_info_fields: dict = {}
    files = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() == ".json":
            original = _read_json_file(candidate)
            source_metadata[candidate.relative_to(root).as_posix()] = deepcopy(original)
            if candidate == root / "mod.json":
                native_mod_fields = deepcopy(original)
            elif candidate == root / "_metadata" / "modinfo.json":
                native_info_fields = deepcopy(original)
            layer = _canonicalize(original)
            if candidate.name == "modinfo.json" and "dependencies" in layer:
                layer["_modinfoDependencies"] = layer.pop("dependencies")
        elif candidate.suffix.lower() == ".lua":
            try:
                layer = _canonicalize(load_lua_table(candidate.read_text(encoding="utf-8-sig")))
            except (ValueError, UnicodeError) as error:
                raise ValueError(f"{candidate.name}: {error}") from error
            def archive(value):
                if isinstance(value, UnsupportedValue):
                    return {"unsupportedLuaValue": value.reason, **({"emptyCallback": True} if value.empty_callback else {})}
                if isinstance(value, dict):
                    if any(not isinstance(k,str) for k in value):
                        return {"luaTableEntries": [{"keyType": "string" if isinstance(k,str) else "number",
                                                     "key": k, "value": archive(v)} for k,v in value.items()]}
                    return {str(k): archive(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [archive(v) for v in value]
                return value
            source_metadata[candidate.relative_to(root).as_posix()] = archive(layer)
        else:
            raise ValueError("Select a mod folder or a .json/.lua metadata file")
        raw.update(layer)
        files.append(str(candidate))
    if not files:
        child_mods = 0
        for child in root.iterdir():
            if child.is_dir() and not _linked(child) and any((child / filename).is_file() for filename in filenames):
                child_mods += 1
                if child_mods == 2:
                    raise ValueError("This folder contains multiple mods. Batch conversion is not available; select one mod folder.")
        raise FileNotFoundError(f"No supported metadata found in {source_path}")
    descriptor = _normalize_mod_descriptor(raw)
    # Known aliases are normalized; native extension fields are preserved in place.
    aliases = {alias for entries in ALIASES.values() for alias in entries}
    technical_keys = {"modId", "revision", "severityAdd", "severityRemove", "visible", "cosmetic",
                      "dependencies", "incompatibilities", "params", "options",
                      "preRunScript", "runScript", "postRunScript"}
    browser_keys = {"name", "summary", "description", "authors", "tags", "url", "localization"}
    descriptor.native_mod_fields = {k: v for k, v in native_mod_fields.items()
                                    if k in technical_keys or k not in aliases | browser_keys | {"info", "data"}}
    descriptor.native_info_fields = {k: v for k, v in native_info_fields.items()
                                     if k in browser_keys | {"dependencies"} or k not in aliases | technical_keys | {"info", "data"}}
    descriptor.source_metadata = source_metadata
    unknown = set(raw) - technical_keys - browser_keys - {"_modinfoDependencies"}
    if unknown:
        descriptor.warnings.append("Additional metadata is archived in sourceMetadata; native extension fields are retained but not validated: " + ", ".join(sorted(str(k) for k in unknown)))
    if any(not isinstance(k,str) for k in raw):
        descriptor.blockers.append("Legacy metadata contains non-text keys; review the archived Lua table before conversion. No dependency is inferred from unnamed entries.")
    descriptor.metadata_files = files
    if not descriptor.authors:
        descriptor.warnings.append("No author was provided. Add the original creator before publishing.")
    if (root / "res").is_dir():
        descriptor.warnings.append("Legacy res files will move to content. Resource formats and game APIs still need testing in TF3.")
        if (root / "content").exists():
            descriptor.blockers.append("Both res and content folders exist. Resolve their resource layout before conversion.")
    if any(candidate.suffix.lower() == ".lua" for candidate in candidates if candidate.is_file()):
        descriptor.warnings.append("Localized Lua text is read as its literal key; translations are not executed.")
    return descriptor


def _validate(descriptor: ModDescriptor, root: Path) -> list[str]:
    errors = list(descriptor.blockers)
    if not re.fullmatch(r"[a-z0-9_]+", descriptor.target_mod_id):
        errors.append("modId must contain only lowercase letters, digits, and underscores.")
    if len(descriptor.name) > 32 or "\n" in descriptor.name or "\r" in descriptor.name:
        errors.append("Mod name must be at most 32 characters without line breaks.")
    if len(descriptor.summary) > 100 or "\n" in descriptor.summary or "\r" in descriptor.summary:
        errors.append("Summary must be at most 100 characters without line breaks.")
    for language, entry in descriptor.localization.items():
        if not isinstance(language, str) or not isinstance(entry, dict):
            errors.append("Each localization entry must be a language object.")
            continue
        for key, limit in (("name", 32), ("summary", 100), ("description", None)):
            if key in entry:
                value = entry[key]
                if not isinstance(value, str) or (limit is not None and (len(value) > limit or "\n" in value or "\r" in value)):
                    errors.append(f"localization.{language}.{key} must be text" + (f" of at most {limit} characters without line breaks." if limit else "."))
    for key, reference in (("preRunScript", descriptor.pre_run_script), ("runScript", descriptor.run_script), ("postRunScript", descriptor.post_run_script)):
        if not reference:
            continue
        match = re.fullmatch(r"([a-z0-9_]+)::/?([A-Za-z0-9_./-]+)@([A-Za-z_][A-Za-z0-9_]*)", reference)
        if not match or ".." in Path(match.group(2)).parts:
            errors.append(f"{key}: use a TF3 reference such as mod_id::mod.script@runFn; legacy file paths require manual migration.")
            continue
        mod_id, module, _ = match.groups()
        if mod_id != descriptor.target_mod_id:
            descriptor.warnings.append(f"{key} references external mod {mod_id}; its availability must be checked in game.")
            continue
        if module.endswith((".lua", ".tl")):
            errors.append(f"{key}: omit the .lua/.tl extension in the TF3 module reference.")
        elif not any((root / folder / (module + extension)).is_file() for folder in ("content", "res") for extension in (".lua", ".tl")):
            errors.append(f"{key}: missing content/{module}.lua or .tl script module.")
    for key in ("dependencies", "incompatibilities"):
        for entry in getattr(descriptor, key) or []:
            mod = entry.get("mod")
            if not isinstance(mod, dict) or not isinstance(mod.get("modId"), str) or not re.fullmatch(r"[a-z0-9_]+", mod["modId"]):
                errors.append(f"{key}: each entry needs mod.modId with a valid TF3 id.")
    for entry in descriptor.params or []:
        if not isinstance(entry.get("key"), str) or entry.get("uiType") not in {"Button", "Slider", "ComboBox", "IconButton", "CheckBox"}:
            errors.append("Each TF3 parameter requires a key and a supported uiType; migrate legacy params manually.")
        values = entry.get("values")
        if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
            errors.append("Each TF3 parameter needs a non-empty list of text values.")
        index = entry.get("defaultIndex", 0)
        if type(index) is not int or index < 0 or (isinstance(values, list) and index >= len(values)):
            errors.append("Parameter defaultIndex must be a valid zero-based index into values.")
        numbers = entry.get("numbers")
        if numbers is not None:
            try:
                if not isinstance(numbers, list) or not isinstance(values, list) or len(numbers) != len(values):
                    raise ValueError
                if any(type(number) not in {int, float} or not math.isfinite(float(number)) for number in numbers):
                    raise ValueError
                # Build 40408 rejects integer JSON tokens for this double array.
                entry["numbers"] = [float(number) for number in numbers]
                descriptor.warnings.append("Parameter numbers are preserved as TF3 doubles. Verify selected values in game: build 40408 Map Editor supplied an option index in the native smoke test, not the configured numbers value.")
            except (ValueError, OverflowError):
                errors.append("Parameter numbers must be finite numbers, one per value; export writes TF3 doubles.")
    return list(dict.fromkeys(errors))


def _audit(descriptor: ModDescriptor, root: Path) -> None:
    descriptor.conversion_plan = analyze_mod(root)
    for mesh in descriptor.conversion_plan["geometry"]:
        descriptor.blockers.extend(f"{mesh['file']}: {error}" for error in mesh["errors"])
        descriptor.warnings.extend(f"{mesh['file']}: {warning}" for warning in mesh["warnings"])
    extras = {k: v for k, v in descriptor.native_mod_fields.items()
              if k not in {"preRunScript", "runScript", "postRunScript"}}
    descriptor.resource_audit = audit_resources(root, descriptor.target_mod_id, source_id=descriptor.source_id,
        lifecycle={"preRunScript": descriptor.pre_run_script, "runScript": descriptor.run_script,
                   "postRunScript": descriptor.post_run_script}, metadata_extras={"mod": extras, "browser": descriptor.native_info_fields,
                       "scriptConfig": {k: {field: value for field, value in config.items() if field != "fileName"}
                                        for k, config in descriptor.script_configs.items()}})
    if descriptor.source_id != descriptor.target_mod_id:
        for entry in (descriptor.dependencies or []) + (descriptor.incompatibilities or []):
            if isinstance(entry.get("mod"), dict) and entry["mod"].get("modId") == descriptor.source_id:
                descriptor.resource_audit["blockers"].append("Cannot change modId: a technical dependency still names the original mod id; migrate it explicitly.")
                descriptor.resource_audit["status"] = "blocked"
    descriptor.blockers = list(dict.fromkeys([*descriptor.blockers, *descriptor.resource_audit["blockers"]]))
    descriptor.warnings = list(dict.fromkeys([*descriptor.warnings, *descriptor.resource_audit["unverified"]]))


def prepare_mod(source: str | Path, *, name: str | None = None, author: str | None = None,
                mod_id: str | None = None, revision: int | None = None,
                summary: str | None = None) -> ModDescriptor:
    descriptor = inspect_mod(source)
    original_id = descriptor.target_mod_id
    descriptor.source_id = original_id
    if name is not None:
        descriptor.name = name.strip()
        for entry in descriptor.localization.values():
            if isinstance(entry, dict) and "name" in entry:
                entry["name"] = descriptor.name
        descriptor.blockers = [error for error in descriptor.blockers if not error.startswith("name ")]
        if not descriptor.name:
            descriptor.blockers.append("Mod name cannot be blank.")
    if author:
        descriptor.authors = [{"name": author.strip(), "role": "CREATOR"}]
        descriptor.warnings = [warning for warning in descriptor.warnings if not warning.startswith("No author")]
        descriptor.blockers = [error for error in descriptor.blockers if not error.startswith(("authors ", "Each author"))]
    if summary is not None:
        descriptor.summary = summary
        descriptor.blockers = [error for error in descriptor.blockers if not error.startswith("summary ")]
    if mod_id is not None:
        descriptor.mod_id = mod_id.strip()
        descriptor.blockers = [error for error in descriptor.blockers if not error.startswith("modId ")]
    if revision is not None:
        if type(revision) is not int or revision < 0:
            raise ValueError("Revision override must be a non-negative integer")
        descriptor.revision = revision
        descriptor.blockers = [error for error in descriptor.blockers if not error.startswith("revision ")]
    for attr in ("pre_run_script", "run_script", "post_run_script"):
        reference = getattr(descriptor, attr)
        if reference and reference.startswith(original_id + "::"):
            setattr(descriptor, attr, descriptor.target_mod_id + reference[len(original_id):])
    descriptor.blockers = _validate(descriptor, _source_root(Path(source).expanduser()))
    _audit(descriptor, _source_root(Path(source).expanduser()))
    return descriptor


def _check_paths(source: Path, destination: Path, overwrite: bool) -> Path:
    root = _source_root(source).resolve()
    if destination == root or root.is_relative_to(destination):
        raise ValueError("Choose a separate output folder; the destination cannot contain or replace the source mod")
    if not re.fullmatch(r"[A-Za-z0-9_ ]+", destination.name):
        raise ValueError("Output folder name must use only letters, digits, underscores, and spaces for TF3")
    if any(_linked(path) for path in (source, destination, *destination.parents, *source.parents)):
        raise ValueError("Source and output paths cannot use symbolic links or directory junctions")
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("The output path is a file; choose a folder")
        if any(destination.iterdir()) and not overwrite:
            raise FileExistsError("Output folder is not empty. Choose a new folder or enable replacement with backup")
    return root


def _copy_files(root: Path, stage: Path, excluded: set[Path], progress: Progress) -> int:
    count = 0

    def visit(directory: Path, target: Path) -> None:
        nonlocal count
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(directory.iterdir()):
            if item.resolve() in excluded:
                continue
            if item.name in {".git", "__pycache__", ".pytest_cache"} and item.is_dir():
                continue
            if _linked(item):
                raise ValueError(f"Cannot copy linked file or folder: {item.relative_to(root)}")
            out = target / item.name
            if item.is_dir():
                visit(item, out)
            elif item.is_file():
                shutil.copy2(item, out)
                count += 1
                progress(f"Copied {item.relative_to(root)}")
    visit(root, stage)
    if (stage / "res").is_dir():
        if (stage / "content").exists():
            raise ValueError("Both res and content folders exist. Resolve their resource layout before conversion")
        (stage / "res").rename(stage / "content")
    (stage / "content").mkdir(exist_ok=True)
    return count


def _backup_parent(destination: Path) -> Path:
    return destination.parent.parent / "trf3_mod_backups" if destination.parent.name.lower() == "mods" else destination.parent


def convert_mod(source: str | Path, destination: str | Path, *, name: str | None = None,
                author: str | None = None, mod_id: str | None = None, revision: int | None = None,
                summary: str | None = None, overwrite: bool = False,
                progress: Progress | None = None,
                _report_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"Source does not exist: {source_path}")
    destination_input = Path(destination).expanduser()
    if any(_linked(path) for path in (destination_input, *destination_input.parents)):
        raise ValueError("Output path cannot use symbolic links or directory junctions")
    destination_path = destination_input.resolve()
    root = _check_paths(source_path, destination_path, overwrite)
    descriptor = prepare_mod(source_path, name=name, author=author, mod_id=mod_id, revision=revision, summary=summary)
    if descriptor.blockers:
        raise ValueError("Conversion needs manual changes:\n" + "\n".join(descriptor.blockers))
    notify = progress or (lambda message: None)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    report: dict[str, Any] = {
        "destination": str(destination_path), "modId": descriptor.target_mod_id,
        "name": descriptor.name, "revision": descriptor.revision,
        "warnings": list(dict.fromkeys(descriptor.warnings)),
        "sourceModId": descriptor.source_id,
        "sourceMetadata": descriptor.source_metadata,
        "idChange": {"changed": descriptor.source_id != descriptor.target_mod_id,
                     "policy": "Keep existing id by default; refuse changes with retained old namespace references."},
        "validation": "Metadata and static references checked; game compatibility requires testing in Transport Fever 3.",
    }
    if _report_fields:
        if set(_report_fields) & (set(report) - {'source'}):
            raise ValueError('Port report fields cannot replace conversion validation fields')
        report.update(_report_fields)
    with tempfile.TemporaryDirectory(prefix=".trf3-stage-", dir=destination_path.parent) as temporary:
        stage = Path(temporary) / "mod"
        excluded = {destination_path, Path(temporary).resolve()}
        # A nested output's previous backups must not be copied on the next run.
        for previous in _backup_parent(destination_path).glob(destination_path.name + ".backup-*"):
            previous_report = previous / "conversion-report.json"
            if previous.is_dir() and previous_report.is_file():
                try:
                    if _read_json_file(previous_report).get("destination") == str(destination_path):
                        excluded.add(previous.resolve())
                except (OSError, ValueError):
                    pass
        report["filesCopied"] = _copy_files(root, stage, excluded, notify)
        (stage / "_metadata").mkdir(parents=True, exist_ok=True)
        for path, payload in ((stage / "mod.json", descriptor.as_mod_json()),
                              (stage / "_metadata" / "modinfo.json", descriptor.as_modinfo_json())):
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=4, allow_nan=False) + "\n", encoding="utf-8")
        # Validate the actual staged resources before touching an existing output.
        _audit(descriptor, stage)
        if descriptor.blockers:
            raise ValueError("Staged conversion needs manual changes:\n" + "\n".join(descriptor.blockers))
        report["resourceAudit"] = descriptor.resource_audit
        report["conversionPlan"] = descriptor.conversion_plan
        report["conversionPlan"]["source"] = str(destination_path)
        report["warnings"] = descriptor.warnings
        _check_paths(source_path, destination_path, overwrite)
        if destination_path.exists():
            backup_name = destination_path.name + ".backup-" + uuid.uuid4().hex[:12]
            backup_parent = _backup_parent(destination_path)
            if backup_parent != destination_path.parent:
                # TF3 discovers sibling backups as duplicate installed mods.
                if any(_linked(path) for path in (backup_parent, *backup_parent.parents)):
                    raise ValueError("Backup path cannot use symbolic links or directory junctions")
                backup_parent.mkdir(exist_ok=True)
                backup = backup_parent / backup_name
            else:
                backup = destination_path.with_name(backup_name)
            report["backup"] = str(backup)
        (stage / "conversion-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        notify("Metadata validated. Finalizing output…")
        if backup:
            destination_path.rename(backup)
        try:
            stage.rename(destination_path)
        except OSError:
            if backup:
                backup.rename(destination_path)
            raise
    notify("Conversion complete")
    return report


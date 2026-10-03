"""Read-only mesh validation shared by every model/mod category.

Descriptors are parsed, never executed. TF mesh offsets/counts are byte ranges;
each attribute has its own uint32 index stream. No geometry is rewritten.
"""
from __future__ import annotations

import math
import mmap
import struct
import contextlib
import io
from pathlib import Path

from .lua_metadata import load_lua_table
from .filesystem import linked


def audit_mesh(path: Path) -> dict:
    result = {"file": path.name, "status": "unverified", "errors": [],
              "warnings": [], "attributes": {}, "subMeshes": []}
    blob_path = Path(str(path) + ".blob")
    if any(linked(p) for p in (path, blob_path, *path.parents)):
        result["errors"].append("Linked mesh paths are not allowed.")
    elif not blob_path.is_file():
        result["errors"].append("Missing companion mesh blob.")
    else:
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                data = load_lua_table(path.read_text(encoding="utf-8-sig"))
            attributes, subs = data.get("vertexAttr"), data.get("subMeshes")
            if not isinstance(attributes, dict) or not isinstance(subs, list) or "position" not in attributes:
                result["warnings"].append("No supported literal mesh descriptor; binary checks were not completed.")
                return result
            size = blob_path.stat().st_size
            result["blobBytes"] = size

            def bounds(value, components=False):
                if not isinstance(value, dict):
                    raise ValueError("Non-literal attribute/index descriptor")
                offset, count = value.get("offset"), value.get("count")
                comp = value.get("numComp") if components else 1
                if any(type(v) is not int for v in (offset, count, comp)) or offset < 0 or count < 0 or comp <= 0:
                    raise ValueError("Invalid offset, byte count or component count")
                if offset + count > size or count % (4 * comp):
                    raise ValueError("Buffer range or component alignment is invalid")
                return offset, count, comp

            if size == 0:
                raise ValueError("Empty mesh blob")
            with blob_path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as blob:
                for name, attr in attributes.items():
                    offset, count, comp = bounds(attr, True)
                    expected = {"position": 3, "normal": 3, "tangent": 4, "uv0": 2, "uv1": 2}.get(name)
                    if expected is not None and comp != expected:
                        raise ValueError(f"{name}: expected {expected} components per attribute item")
                    # Scan floats without retaining or duplicating the whole blob.
                    nonfinite = sum(not math.isfinite(struct.unpack_from("<f", blob, i)[0])
                                    for i in range(offset, offset + count, 4))
                    result["attributes"][name] = {"items": count // (4 * comp), "components": comp,
                                                   "nonfiniteComponents": nonfinite}
                    if nonfinite:
                        result["warnings"].append(f"{name}: {nonfinite} non-finite components; game impact requires testing.")
                for sub in subs:
                    if not isinstance(sub, dict) or not isinstance(sub.get("indices"), dict) or "position" not in sub["indices"]:
                        raise ValueError("Missing literal submesh position indices")
                    row = {"indexCounts": {}}
                    for name, stream in sub["indices"].items():
                        offset, count, _ = bounds(stream)
                        if name not in result["attributes"]:
                            raise ValueError(f"Index stream {name} has no matching attribute")
                        if count % 12:
                            raise ValueError(f"{name}: index stream does not contain complete triangles")
                        limit = result["attributes"][name]["items"]
                        if any(struct.unpack_from("<I", blob, i)[0] >= limit for i in range(offset, offset + count, 4)):
                            raise ValueError(f"{name}: index exceeds its own attribute buffer")
                        row["indexCounts"][name] = count // 4
                    if len(set(row["indexCounts"].values())) != 1:
                        raise ValueError("Submesh attribute index streams have different lengths")
                    result["subMeshes"].append(row)
                result["usesSeparateIndexStreams"] = any(len(s["indexCounts"]) > 1 for s in result["subMeshes"])
                if not any(s["indexCounts"].get("position") for s in result["subMeshes"]):
                    result["warnings"].append("Mesh has no indexed triangles; verify that this is intended.")
                result["separateAttributeIndices"] = len({a["items"] for a in result["attributes"].values()}) > 1
                result["status"] = "checked_with_warnings" if result["warnings"] else "checked"
        except (OSError, ValueError, UnicodeError) as error:
            result["errors"].append(str(error))
    if result["errors"]:
        result["status"] = "blocked"
    return result

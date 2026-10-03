"""Read-only vanilla resource inventory audit; no converter or copied game assets."""
import argparse
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "resource_manifest.json"


def canonical(name):
    return name[:-4] if name.endswith(".lua") else name


def inventory(game):
    base = Path(game) / "base" / "content"
    if not base.is_dir():
        raise ValueError("Expected a TF3 installation containing base/content")
    available = set()
    for archive in base.rglob("*.zip"):
        prefix = archive.parent.relative_to(base).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                if not name.endswith("/"):
                    available.add(canonical("::/" + prefix + name))
    for file in base.rglob("*"):
        if file.is_file() and file.suffix != ".zip":
            available.add(canonical("::/" + file.relative_to(base).as_posix()))
    return available


def check(game):
    available = inventory(game)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    required = manifest["resourceNames"]
    ui = manifest["uiModules"]
    definition = json.loads((ROOT / "mod" / "tf3_osm_importer_mod" / "mod.json").read_text(encoding="utf-8"))
    dependencies = definition.get("dependencies", [])
    if dependencies:
        raise ValueError("The standalone mod declares external mod dependencies")
    return {
        "checkedVanillaResources": len(required),
        "missing": sorted(name for name in required if canonical(name) not in available),
        "externalModDependencies": dependencies,
        "resourceNames": required,
        "checkedUiModules": len(ui),
        "uiMissing": sorted(name for name in ui if canonical(name) not in available),
        "uiModules": ui,
        "scope": "Inventory names in installed base/content files and ZIPs; no engine execution or assets copied",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = check(args.game)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"resourceNames", "uiModules"}}, indent=2))
    raise SystemExit(bool(result["missing"] or result["uiMissing"]))

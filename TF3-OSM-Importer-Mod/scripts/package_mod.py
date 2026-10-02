"""Package only the installable TF3 mod; needs Python's standard library."""
import argparse
from pathlib import Path
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "mod" / "druttzen_osm_vanilla"
DEFAULT_OUTPUT = ROOT / "dist" / "TF3-OSM-Importer-Mod-Preview.zip"


def package(output=DEFAULT_OUTPUT):
    output = Path(output).resolve()
    if output.is_relative_to(MOD.resolve()):
        raise ValueError("The archive output must be outside the installable mod folder")
    files = sorted(file for file in MOD.rglob("*") if file.is_file())
    required = [MOD / "mod.json", MOD / "LICENSE", MOD / "NOTICE.txt", MOD / "README.txt",
                MOD / "content" / "osm" / "dataset.lua"]
    if not all(file.is_file() for file in required):
        raise ValueError("Installable mod is incomplete")
    for file in files:
        if file.is_symlink() or (file.name != "LICENSE" and file.suffix not in {".lua", ".json", ".txt"}):
            raise ValueError(f"Unexpected file in installable mod: {file.relative_to(MOD)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, "druttzen_osm_vanilla/" + file.relative_to(MOD).as_posix())
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output, len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, count = package(args.output)
    print(f"Packaged {count} mod files: {output}")

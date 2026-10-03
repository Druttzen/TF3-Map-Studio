"""Build a portable Windows app and archive; run on Windows."""
from pathlib import Path
import subprocess
import sys
import zipfile


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Build the Windows executable on Windows.")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--windowed", "--name", "TRF3-Mod-Converter",
        "--paths", str(root / "src"),
        "--distpath", str(root / "dist"),
        "--workpath", str(root / "build" / "desktop"),
        "--specpath", str(root / "build"),
        "--collect-all", "luaparser",
        str(root / "desktop_launcher.py"),
    ], cwd=root, check=True)
    archive = root / "dist" / "TRF3-Mod-Converter-Windows.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(root / "dist" / "TRF3-Mod-Converter.exe", "TRF3-Mod-Converter.exe")
        bundle.write(root / "README.md", "README.md")
        bundle.write(root / "VALIDATION.md", "VALIDATION.md")
        bundle.write(root / "GENERAL_CONVERSION.md", "GENERAL_CONVERSION.md")
        bundle.write(root / "LICENSE", "LICENSE")
        for path in (root / "examples").rglob("*"):
            if path.is_file():
                bundle.write(path, str(path.relative_to(root)))
    print(f"Built {archive}")


if __name__ == "__main__":
    main()

"""Check the release ZIP's installation layout and bytes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_mod", ROOT / "scripts" / "package_mod.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class PackageTests(unittest.TestCase):
    def test_archive_contains_only_installable_files_with_identical_bytes(self):
        with TemporaryDirectory() as folder:
            output, count = packager.package(Path(folder) / "mod.zip")
            source = {"tf3_osm_importer_mod/" + file.relative_to(packager.MOD).as_posix(): file
                      for file in packager.MOD.rglob("*") if file.is_file()}
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(source))
                self.assertEqual(count, len(source))
                self.assertIn("tf3_osm_importer_mod/mod.json", archive.namelist())
                self.assertEqual(json.loads(archive.read('tf3_osm_importer_mod/mod.json'))['modId'],'druttzen_osm_vanilla')
                self.assertEqual(json.loads(archive.read('tf3_osm_importer_mod/_metadata/modinfo.json'))['name'],'TF3-OSM-Importer-Mod')
                for name, file in source.items():
                    self.assertEqual(archive.read(name), file.read_bytes(), name)
                self.assertTrue(all(Path(name).suffix not in {".py", ".exe", ".pyc"} for name in archive.namelist()))

    def test_command_is_independent_of_working_directory(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "result.zip"
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "package_mod.py"),
                                     "--output", str(output)], cwd=folder, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())

    def test_output_inside_mod_is_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            packager.package(packager.MOD / "accidental.zip")


if __name__ == "__main__":
    unittest.main()

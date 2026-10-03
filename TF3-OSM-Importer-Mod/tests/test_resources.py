"""Verify the standalone audit has no converter dependency and covers local references."""
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
import zipfile

from check_resources import ROOT, MANIFEST, canonical, inventory


class ResourceTests(unittest.TestCase):
    def test_manifest_covers_literal_vanilla_references(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        names = set(manifest["resourceNames"] + manifest["uiModules"])
        references = set()
        for file in (ROOT / "mod" / "druttzen_osm_vanilla" / "content").rglob("*"):
            if file.suffix not in {'.lua','.mdl','.msh'}: continue
            references.update(re.findall(r'(?<![\w])::/[^"\s]+\.(?:mdl|mtl|gtex|tmat|street_template|bridge|tunnel|lua|tl)', file.read_text(encoding="utf-8")))
        self.assertTrue(references)
        self.assertEqual(references - names, set())
        self.assertEqual(len(names), len(manifest["resourceNames"]) + len(manifest["uiModules"]))

    def test_loose_and_archived_resources_share_the_same_namespace(self):
        with TemporaryDirectory() as folder:
            base = Path(folder) / "base" / "content"
            (base / "gui").mkdir(parents=True)
            (base / "gui" / "helper.lua").write_text("return {}", encoding="utf-8")
            with zipfile.ZipFile(base / "gui" / "helpers.zip", "w") as archive:
                archive.writestr("main/react.lua", "return {}")
                archive.writestr("main/control.tl", "")
            self.assertEqual(inventory(folder), {"::/gui/helper", "::/gui/main/react", "::/gui/main/control.tl"})
            self.assertEqual(canonical("::/gui/main/react.lua"), "::/gui/main/react")

    def test_missing_installation_is_rejected(self):
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "base/content"):
                inventory(folder)


if __name__ == "__main__":
    unittest.main()

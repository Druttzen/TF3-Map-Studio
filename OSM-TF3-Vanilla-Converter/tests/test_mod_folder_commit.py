"""A scanner lock must not lose a new export or overwrite a competing folder."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from converter import _rename_new_mod
from job import Cancelled


def locked():
    error=PermissionError('Transient scanner lock');error.winerror=5
    return error


class ModFolderCommitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.stage=Path(self.temp.name)/'stage';self.stage.mkdir()
        (self.stage/'data.lua').write_bytes(b'complete export')
        self.target=Path(self.temp.name)/'tf3_osm_importer_mod'

    def test_transient_lock_preserves_complete_export_then_commits(self):
        original=Path.rename;attempts=[]
        def rename(path,target):
            attempts.append(path)
            if len(attempts)==1:raise locked()
            return original(path,target)
        with patch.object(Path,'rename',rename),patch('converter.time.sleep'):
            _rename_new_mod(self.stage,self.target)
        self.assertEqual(len(attempts),2)
        self.assertEqual((self.target/'data.lua').read_bytes(),b'complete export')
        self.assertFalse(self.stage.exists())

    def test_competing_folder_created_during_lock_is_not_replaced(self):
        def rename(path,target):
            target.mkdir();(target/'preserve.txt').write_bytes(b'another export')
            raise locked()
        with patch.object(Path,'rename',rename),patch('converter.time.sleep'),self.assertRaisesRegex(ValueError,'another process'):
            _rename_new_mod(self.stage,self.target)
        self.assertEqual((self.target/'preserve.txt').read_bytes(),b'another export')
        self.assertEqual((self.stage/'data.lua').read_bytes(),b'complete export')

    def test_permanent_lock_stops_with_source_intact(self):
        with patch.object(Path,'rename',side_effect=locked()) as rename,patch('converter.time.sleep'),self.assertRaises(PermissionError):
            _rename_new_mod(self.stage,self.target)
        self.assertEqual(rename.call_count,6)
        self.assertFalse(self.target.exists())
        self.assertEqual((self.stage/'data.lua').read_bytes(),b'complete export')

    def test_cancellation_during_lock_does_not_commit(self):
        event=threading.Event()
        def rename(path,target):event.set();raise locked()
        with patch.object(Path,'rename',rename),patch('converter.time.sleep'),self.assertRaises(Cancelled):
            _rename_new_mod(self.stage,self.target,event)
        self.assertFalse(self.target.exists())
        self.assertTrue((self.stage/'data.lua').is_file())

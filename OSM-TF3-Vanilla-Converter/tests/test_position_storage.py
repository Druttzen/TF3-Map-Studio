"""Compact accepted model evidence must retain exact XYZ and fail closed."""
import struct
import unittest

from lupa import LuaRuntime
import test_game_scripts as game


class PositionStorageTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.controls=self.lua.execute((game.CONTENT/'controls.lua').read_text())

    def test_hex_text_round_trips_double_bits_sparse_source_indices_and_signed_zero(self):
        points={1:(8123.456789012345,-7890.123456789012,-0.0),
                5000:(1e-300,-1e-300,169.00000000000003),
                900000:(-8191.99999999999,0.0,-21.000000000000004)}
        source=self.lua.table_from({i:self.lua.table_from(p) for i,p in points.items()})
        payload=self.controls.packPositions(source)
        payload.encode('ascii')
        record=self.lua.table_from({'modelJournalSchema':2,'modelPositions':payload,'first':1,'last':900000})
        decoded=self.controls.modelPositions(record)
        for index,point in points.items():
            for axis,expected in enumerate(point,1):
                self.assertEqual(struct.pack('<d',decoded[index][axis]),struct.pack('<d',expected))
        self.assertEqual(len(list(decoded.items())),3)

    def test_invalid_truncated_duplicate_and_out_of_range_evidence_is_rejected(self):
        for payload in ('1|0x1p0|0x2p0|0x3p0',
                        '1|nan|0|0\n', '1|inf|0|0\n',
                        '1|0|0|0\n1|0|0|0\n', '3|0|0|0\n',
                        '1|os.execute("ignored")|0|0\n', '\n'):
            with self.subTest(payload=payload):
                record=self.lua.table_from({'modelJournalSchema':2,'modelPositions':payload,'first':1,'last':2})
                with self.assertRaises(Exception): self.controls.modelPositions(record)

    def test_changed_payload_invalidates_decoding_cache(self):
        record=self.lua.table_from({'modelJournalSchema':2,'modelPositions':'1|0x1p0|0x2p0|0x3p0\n','first':1,'last':1})
        self.assertEqual(self.controls.modelPositions(record)[1][1],1)
        record.modelPositions='1|0x1p1|0x2p0|0x3p0\n'
        self.assertEqual(self.controls.modelPositions(record)[1][1],2)
        record.modelPositions='broken'
        with self.assertRaises(Exception): self.controls.modelPositions(record)

    def test_legacy_pending_accepted_record_is_compacted_without_rebuilding(self):
        h=game.GameScriptTests(); h.setUp()
        h.event('start'); h.lua.globals().failOwnershipNext=True; h.step()
        record=h.state.value.sceneryRecords[1]
        accepted=record.entities[1]
        points=game.model_positions(h.lua,record)
        before=(points[1][1],points[1][2],points[1][3])
        record.modelPositions=points; record.modelJournalSchema=1
        h.state.value.positionStorageRevision=None
        h.script=game.load_script(h.lua,game.CONTENT/'importer.script.lua')
        h.script.update(None,h.state,1)
        self.assertEqual(record.modelJournalSchema,2)
        after=game.model_positions(h.lua,record)
        self.assertEqual((after[1][1],after[1][2],after[1][3]),before)
        h.event('retry'); h.finish()
        self.assertEqual(h.state.value.phase,'finished',h.state.value.error)
        self.assertEqual(h.state.value.sceneryRecords[1].entities[1],accepted)
        self.assertEqual(h.state.value.builtScenery,117)

    def test_legacy_without_model_evidence_remains_explicitly_partial(self):
        record=self.lua.eval('{phase="scenery",first=1,last=1,entities={123}}')
        value=self.lua.table_from({'sceneryRecords':self.lua.table_from([record])})
        self.controls.compactModelPositions(value)
        self.assertIsNone(record.modelJournalSchema)
        self.assertIsNone(record.modelPositions)


if __name__=='__main__': unittest.main()

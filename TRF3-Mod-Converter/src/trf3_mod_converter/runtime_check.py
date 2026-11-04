"""Offline frozen-app smoke test using fictional metadata, never user mods."""
import json
from pathlib import Path
import tempfile


def check(output):
    result = {'ok': False}
    try:
        import tkinter
        from .batch import scan_mods, convert_queue, file_fingerprint, STATE_NAME
        assert tkinter.Tcl().call('info', 'patchlevel')
        with tempfile.TemporaryDirectory(prefix='trf3-runtime-') as folder:
            root = Path(folder); collection = root / 'source'
            for name in ('first', 'second'):
                mod = collection / name; mod.mkdir(parents=True)
                (mod / 'mod.json').write_text(json.dumps({'name': name, 'authors': ['Fictional test']}), encoding='utf-8')
            items = scan_mods(collection)['items']
            before = {item.source: file_fingerprint(Path(item.source)) for item in items}
            destination = root / 'exports'
            state = convert_queue(items, destination)
            assert state['counts'] == {'completed': 2, 'failed': 0, 'pending': 0}, state
            assert json.loads((destination / STATE_NAME).read_text(encoding='utf-8'))['counts'] == state['counts']
            repeated = convert_queue(scan_mods(collection)['items'], destination)
            assert repeated['counts'] == state['counts']
            assert all(file_fingerprint(Path(path)) == digest for path, digest in before.items())
            exported = {item.mod_id: file_fingerprint(destination / item.mod_id) for item in items}
            assert exported
        result = {'ok': True, 'networkUsed': False, 'tcl': 'loaded',
                  'batch': 'two fictional mods exported', 'recovery': 'saved receipts and repeated exports verified',
                  'sourcePreservation': 'source fingerprints unchanged'}
    except Exception as exc:
        result['error'] = str(exc)
    Path(output).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return 0 if result['ok'] else 1

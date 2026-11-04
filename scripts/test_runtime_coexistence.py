"""Exercise install, damaged-runtime repair and recoverable removal on fixtures.

Only new fixture apps under --output and backups under --backups are changed.
The two explicit runtime sources and all existing installations remain read-only.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent))
from private_runtime import provision, inventory, verify, file_sha, child_environment


def fingerprint(root):
    # Python may generate bytecode on first use; cache creation is not a
    # runtime/configuration change. Compare all persistent source/binary/data.
    return {p.relative_to(root).as_posix(): file_sha(p) for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-a', type=Path, required=True)
    parser.add_argument('--source-b', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backups', type=Path, required=True)
    args = parser.parse_args(); output = args.output.resolve(); backups = args.backups.resolve()
    output.mkdir(parents=True, exist_ok=False)
    a = output/'a/OSM-TF3-Vanilla-Converter'; b = output/'b/TF3-Heightmap-Studio'
    for root in (a, b):
        root.mkdir(parents=True); (root/'README.md').write_text('Fictional coexistence test app')
        (root/'project-data.json').write_text('{"preserve":"user project"}')
        (root/'settings.json').write_text('{"preserve":"private configuration"}')
    provision(a, args.source_a); provision(b, args.source_b)
    versions = [inventory(a)['version'], inventory(b)['version']]
    assert versions[0] != versions[1], 'Use two different interpreter versions.'
    # Prove independent storage even when provisioning from an existing private
    # copy: no mutation may reach the source or the other app.
    source_hash = file_sha(args.source_a/'python.exe')
    before_b = fingerprint(b); preserved_a = {name: (a/name).read_bytes() for name in ('project-data.json','settings.json')}
    (a/'.runtime/python.exe').write_bytes(b'damaged fictional test interpreter')
    try:
        verify(a)
    except ValueError:
        pass
    else:
        raise AssertionError('A damaged interpreter was accepted')
    assert file_sha(args.source_a/'python.exe') == source_hash
    provision(a, args.source_a, backup=backups/('repair-'+uuid.uuid4().hex))
    verify(a)
    assert fingerprint(b) == before_b
    assert all((a/name).read_bytes() == data for name, data in preserved_a.items())
    runner = Path(__file__).with_name('private_runtime.py')
    # Use B's private interpreter so A can be moved safely on Windows.
    subprocess.run([str(b/'.runtime/python.exe'), '-I', '-B', str(runner), 'uninstall',
                    '--tool', str(a), '--backup', str(backups/('uninstall-'+uuid.uuid4().hex))],
                   env=child_environment(b), check=True)
    assert not (a/'.runtime').exists()
    assert fingerprint(b) == before_b
    assert all((a/name).read_bytes() == data for name, data in preserved_a.items())
    verify(b)
    check = subprocess.check_output([str(b/'.runtime/python.exe'), '-I', '-c',
             'import hashlib,json,tkinter; print(json.dumps({"sha256":hashlib.sha256(b"test").hexdigest(),"tcl":tkinter.Tcl().call("info","patchlevel")}))'],
             env=child_environment(b), text=True)
    result = {'ok': True, 'pythonVersions': versions, 'independentCopies': True,
              'damagedInterpreterRejected': True, 'repairPassed': True,
              'recoverableUninstallPassed': True, 'otherAppFilesUnchanged': True,
              'projectDataAndSettingsPreserved': True, 'survivingAppCheck': json.loads(check)}
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()

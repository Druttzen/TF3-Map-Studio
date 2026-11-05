"""Provision and run independent, app-owned Windows development runtimes.

The explicit source is copied, never linked. No ambient interpreter or package
directory satisfies a tool's runtime requirement. All writes stay in the tool
or the explicitly selected backup directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import uuid
import zipfile

TOOLS = {'OSM-TF3-Vanilla-Converter', 'TF3-Heightmap-Studio', 'TF3-OSM-Importer-Mod'}


def tool_root(path):
    root = Path(path).resolve()
    if root.name not in TOOLS or not (root / 'README.md').is_file():
        raise ValueError('Select one of this repository\'s tool folders.')
    return root


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def prepare_tk_archives(runtime):
    """Expose Tcl/Tk 9 zipfs script data as private directories for freezing.

    Retain the original archives too. Select the script-library root by its
    initialization file, rather than assuming the archive's internal prefix.
    """
    base = Path(runtime)/'tcl'
    for pattern, marker in [('libtcl*.zip','init.tcl'),('libtk*.zip','tk.tcl')]:
        for archive in base.glob(pattern):
            with zipfile.ZipFile(archive) as bundle:
                entries = [(item,PurePosixPath(item.filename)) for item in bundle.infolist()]
                for item,path in entries:
                    if path.is_absolute() or '..' in path.parts or '\\' in item.filename or (item.external_attr>>16)&0o170000==0o120000:
                        raise ValueError('Unsafe Tcl/Tk library archive: ' + str(archive))
                roots = [path.parent for item,path in entries if not item.is_dir() and path.name==marker]
                if len(roots)!=1:raise ValueError('Missing or ambiguous library root in '+str(archive))
                prefix=roots[0];destination=base/archive.stem.removeprefix('lib')
                for item,path in entries:
                    if item.is_dir() or not path.is_relative_to(prefix):continue
                    target=destination.joinpath(*path.relative_to(prefix).parts)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(bundle.read(item))


def child_environment(root, runtime=None):
    root = tool_root(root)
    runtime = Path(runtime or root / '.runtime').resolve()
    tcl = list(runtime.glob('tcl/tcl*/init.tcl'))
    tk = list(runtime.glob('tcl/tk*/tk.tcl'))
    if len(tcl) != 1 or len(tk) != 1:
        available = sorted(p.name for p in (runtime/'tcl').iterdir()) if (runtime/'tcl').is_dir() else []
        raise ValueError(f'Private Tcl/Tk libraries are missing or ambiguous: {runtime}; available: {available}')
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('PYTHON', 'PIP_', 'CONDA', 'VIRTUAL_ENV'))
           and k.upper() not in {'TCL_LIBRARY', 'TK_LIBRARY'}}
    state = root / '.runtime-state'
    for name in ('tmp', 'cache', 'config', 'pip-cache', 'pyinstaller'):
        (state / name).mkdir(parents=True, exist_ok=True)
    env.update(PYTHONNOUSERSITE='1', PIP_CONFIG_FILE=os.devnull,
               PIP_CACHE_DIR=str(state / 'pip-cache'),
               PYINSTALLER_CONFIG_DIR=str(state / 'pyinstaller'),
               TEMP=str(state / 'tmp'), TMP=str(state / 'tmp'),
               LOCALAPPDATA=str(state / 'cache'), APPDATA=str(state / 'config'),
               TCL_LIBRARY=str(tcl[0].parent), TK_LIBRARY=str(tk[0].parent))
    env['PATH'] = os.pathsep.join(map(str, [runtime, runtime / 'Scripts', runtime / 'DLLs',
                                          Path(env.get('SystemRoot', 'C:/Windows')) / 'System32']))
    return env


def inventory(root, runtime=None):
    runtime = Path(runtime or root / '.runtime').resolve()
    script = ('import importlib.metadata as m,json,site,sys;'
              'print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,'
              'basePrefix=sys.base_prefix,version=sys.version,paths=sys.path,'
              'userSite=site.ENABLE_USER_SITE,'
              'packages={d.metadata["Name"]:d.version for d in m.distributions()})))')
    data = json.loads(subprocess.check_output([str(runtime / 'python.exe'), '-I', '-c', script],
                     env=child_environment(root, runtime), text=True))
    if Path(data['prefix']).resolve() != runtime or Path(data['basePrefix']).resolve() != runtime:
        raise ValueError('The private runtime still depends on an external interpreter.')
    if data['userSite'] or any(not Path(p).resolve().is_relative_to(runtime) and not Path(p).resolve().is_relative_to(root) for p in data['paths']):
        raise ValueError('The private runtime imports from outside its owned directory.')
    return data


def verify(root):
    root = tool_root(root)
    runtime = root / '.runtime'
    manifest = json.loads((runtime / 'ownership.json').read_text(encoding='utf-8'))
    if manifest['owner'] != str(root) or manifest['runtime'] != str(runtime):
        raise ValueError('Runtime ownership differs; provision this tool\'s own runtime.')
    for name, digest in manifest['runtimeHashes'].items():
        if file_sha(runtime / name) != digest:
            raise ValueError('Private interpreter changed: ' + name)
    current = inventory(root)
    if current['packages'] != manifest['inventory']['packages']:
        raise ValueError('Private packages changed; record them with refresh after an intentional update.')
    return current


def record(root, runtime, source):
    data = inventory(root, runtime)
    hashes = {p.name: file_sha(p) for p in runtime.iterdir()
              if p.is_file() and p.suffix.lower() in {'.exe', '.dll'}}
    manifest = {'owner': str(root), 'runtime': str(root / '.runtime'),
                'source': source, 'copyMode': 'independent copies; no links',
                'runtimeHashes': hashes, 'inventory': data}
    (runtime / 'ownership.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


def executable_manifest(root, executable, report):
    """Record only packages whose import modules occur in the frozen archive."""
    import importlib.metadata as metadata
    from PyInstaller.archive.readers import CArchiveReader
    root = tool_root(root); executable = Path(executable).resolve(); report = Path(report).resolve()
    if not executable.is_relative_to(root) or not report.is_relative_to(root):
        raise ValueError('Manifest and executable must belong to this app.')
    current = verify(root); reader = CArchiveReader(str(executable))
    pyz = reader.open_embedded_archive(next(name for name in reader.toc if name.endswith('.pyz')))
    top_levels = {name.split('.')[0] for name in pyz.toc}
    distributions = metadata.packages_distributions(); packages = {}
    for name in top_levels:
        for distribution in distributions.get(name, []):
            packages[distribution] = metadata.version(distribution)
    result = {'application': root.name, 'ownership': 'Bundled private interpreter and packages; no external Python required',
              'executableSha256': file_sha(executable), 'python': current['version'],
              'pythonLibraries': sorted(name for name in reader.toc if Path(name).name.startswith('python') and name.endswith('.dll')),
              'packagedDistributions': dict(sorted(packages.items())),
              'packageSource': 'Declared per-tool requirements; resolved versions recorded here',
              'buildInterpreterHashes': json.loads((root/'.runtime/ownership.json').read_text())['runtimeHashes']}
    report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def provision(root, source, seed=None, backup=None):
    root = tool_root(root); source = Path(source).resolve()
    if not (source / 'python.exe').is_file() or not (source / 'Lib/encodings').is_dir() or (source / 'pyvenv.cfg').exists():
        raise ValueError('Source must be a complete Windows CPython installation, not a venv.')
    if any(p.is_symlink() or p.is_junction() for p in [source] if hasattr(p, 'is_junction')):
        raise ValueError('Runtime source must be a real directory.')
    target = root / '.runtime'
    if target.exists():
        owned = json.loads((target / 'ownership.json').read_text(encoding='utf-8'))
        if owned['owner'] != str(root) or owned['runtime'] != str(target):
            raise ValueError('Refusing to replace a runtime owned by another app.')
        if not backup:
            raise ValueError('Runtime exists. Supply an explicit backup directory to replace only this app\'s copy.')
        backup = Path(backup).resolve()
        if backup.exists() or backup.is_relative_to(root) or root.is_relative_to(backup):
            raise ValueError('Select a new, separate backup directory for this app\'s runtime.')
    stage = root / ('.runtime-stage-' + uuid.uuid4().hex)
    stage.mkdir()
    # Exclude source packages, startup hooks and compiled caches, even when
    # bootstrapping from a machine-wide CPython distribution.
    ignore = shutil.ignore_patterns('site-packages', '__pycache__', '*.pth', '*._pth')
    for part in ('Lib', 'DLLs', 'tcl'):
        if (source / part).is_dir():
            shutil.copytree(source / part, stage / part, ignore=ignore)
    for path in source.iterdir():
        if path.is_file() and path.suffix.lower() in {'.exe', '.dll', '.txt'}:
            shutil.copy2(path, stage / path.name)
    if seed:
        seed = Path(seed).resolve()
        shutil.copytree(seed, stage / 'Lib/site-packages',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pth'))
    prepare_tk_archives(stage)
    inventory(root, stage)
    if target.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(backup))
    try:
        stage.rename(target)
        manifest = record(root, target, {'interpreter': str(source), 'packages': str(seed) if seed else 'ensurepip / declared requirements'})
    except BaseException:
        if backup and not target.exists() and backup.exists():
            shutil.move(str(backup), str(target))
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['provision', 'install', 'verify', 'refresh', 'run', 'check-executable', 'uninstall', 'manifest'])
    parser.add_argument('--tool', required=True, type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--seed-packages', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--report', type=Path)
    args, command = parser.parse_known_args()
    if command[:1] == ['--']: command = command[1:]
    root = tool_root(args.tool); runtime = root / '.runtime'; python = runtime / 'python.exe'
    if args.action == 'provision':
        if not args.source: parser.error('--source is required; no global fallback is used')
        print(json.dumps(provision(root, args.source, args.seed_packages, args.backup), indent=2)); return
    if args.action == 'refresh':
        previous = json.loads((runtime / 'ownership.json').read_text(encoding='utf-8'))
        if previous['owner'] != str(root): raise ValueError('Runtime belongs to another app.')
        print(json.dumps(record(root, runtime, previous['source']), indent=2)); return
    if args.action == 'uninstall':
        if not args.backup: parser.error('--backup is required for recoverable private-runtime removal')
        owned = json.loads((runtime / 'ownership.json').read_text(encoding='utf-8'))
        if owned['owner'] != str(root) or owned['runtime'] != str(runtime):
            raise ValueError('Refusing to remove a runtime belonging to another app.')
        backup = args.backup.resolve()
        if backup.exists() or backup.is_relative_to(root) or root.is_relative_to(backup):
            raise ValueError('Select a new, separate backup path.')
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(runtime), str(backup))
        print('Private runtime removed; recoverable backup: ' + str(backup)); return
    verify(root); env = child_environment(root)
    if args.action == 'verify': print(json.dumps(verify(root), indent=2)); return
    if args.action == 'manifest':
        if not args.executable or not args.report: parser.error('--executable and --report are required')
        print(json.dumps(executable_manifest(root, args.executable, args.report), indent=2)); return
    if args.action == 'install':
        subprocess.run([str(python), '-I', '-m', 'ensurepip', '--upgrade'], env=env, check=True)
        subprocess.run([str(python), '-I', '-m', 'pip', 'install', '-r',
                        str(root / 'requirements-dev.txt'), 'pytest'], env=env, check=True)
        record(root, runtime, json.loads((runtime / 'ownership.json').read_text())['source']); return
    if args.action == 'check-executable':
        if not args.executable or not args.report: parser.error('--executable and --report are required')
        executable = args.executable.resolve(); report = args.report.resolve()
        if not executable.is_relative_to(root) or not report.is_relative_to(root):
            raise ValueError('Executable and report must belong to this tool.')
        report.parent.mkdir(parents=True, exist_ok=True)
        if report.exists(): report.unlink()
        subprocess.run([str(executable), '--self-check', str(report)], env=env, check=True, timeout=120,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        result = json.loads(report.read_text(encoding='utf-8'))
        if result.get('ok') is not True: raise ValueError('Packaged runtime check failed: ' + str(result))
        print(json.dumps(result, indent=2)); return
    if not command: parser.error('Supply the private Python command after --')
    if command[0].endswith('.py'):
        # -I removes the script directory. Restore only the app-owned entry
        # point's directory, without restoring ambient PYTHONPATH.
        script = Path(command[0]).resolve()
        if not script.is_relative_to(root): raise ValueError('Source entry point must belong to this tool.')
        command = ['-c', 'import pathlib,runpy,sys; p=sys.argv[1]; sys.path.insert(0,str(pathlib.Path(p).parent)); sys.argv=sys.argv[1:]; runpy.run_path(p,run_name="__main__")', str(script), *command[1:]]
    raise SystemExit(subprocess.call([str(python), '-I', *command], env=env))


if __name__ == '__main__':
    main()

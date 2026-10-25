"""Package a successful main CI artifact and publish its exact draft release.

Only --publish mutates GitHub. Source comes from the reviewed run SHA, not the
newer checkout containing this helper. No local work/output directories enter ZIPs.
"""
import argparse
import hashlib
import json
import marshal
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import zipfile


ARTIFACT = 'TF3-Map-Studio-Windows'
TOOLS = ('TF3-Heightmap-Studio', 'OSM-TF3-Vanilla-Converter',
         'TRF3-Mod-Converter', 'TF3-OSM-Importer-Mod')


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def api(repository, endpoint):
    return json.loads(command('gh', 'api', f'repos/{repository}/{endpoint}'))


def validate_metadata(run, release, repository):
    assert run['repository']['full_name'] == repository, 'Run belongs to another repository'
    assert run['head_repository']['full_name'] == repository, 'Fork artifacts are not eligible'
    assert run['event'] == 'push' and run['head_branch'] == 'main', 'Expected a main push run'
    assert run['status'] == 'completed' and run['conclusion'] == 'success', 'CI has not passed'
    assert run['path'] == '.github/workflows/ci.yml', 'Unexpected build workflow'
    sha = run['head_sha']
    assert re.fullmatch(r'[0-9a-f]{40}', sha), 'Invalid reviewed commit'
    assert release['draft'] is True, 'Only an existing draft can be replaced'
    assert release['target_commitish'] == sha, 'Draft target must be the exact reviewed SHA'
    return sha


def extract_zip(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, f'ZIP integrity failure: {archive}'
        for item in bundle.infolist():
            path = PurePosixPath(item.filename)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in item.filename
            assert item.external_attr >> 16 & 0o170000 != 0o120000, 'Symlinks are not packaged'
            target = destination.joinpath(*path.parts)
            assert target.resolve().is_relative_to(destination.resolve())
        bundle.extractall(destination)


def verify_executable(executable, source, tool):
    from PyInstaller.archive.readers import CArchiveReader
    reader = CArchiveReader(str(executable))
    pyz = reader.open_embedded_archive(next(name for name in reader.toc if name.endswith('.pyz')))
    checked = []
    if tool == 'TRF3-Mod-Converter':
        files = [(('trf3_mod_converter' + ('' if p.stem == '__init__' else '.' + p.stem)), p)
                 for p in (source/'src/trf3_mod_converter').glob('*.py')]
        launcher = source/'desktop_launcher.py'
        entry = 'desktop_launcher'
        expected_count = 32
    else:
        files = [(p.stem, p) for p in (source/'tools').glob('*.py')]
        if tool == 'TF3-Heightmap-Studio':
            files += [(p.stem, p) for p in (source/'vendor').glob('*.py')]
        launcher = source/'tools/gui.py'
        entry = 'gui'
        expected_count = 16 if tool == 'TF3-Heightmap-Studio' else 10
    for name, path in files:
        if name in pyz.toc:
            code = pyz.extract(name)
        elif name == entry:
            code = marshal.loads(reader.extract(entry))
        else:
            continue
        assert code == compile(path.read_text(encoding='utf-8-sig'), code.co_filename,
                               'exec', dont_inherit=True), f'Embedded code differs: {tool}/{path.name}'
        checked.append(name)
    code = marshal.loads(reader.extract(entry))
    assert code == compile(launcher.read_text(encoding='utf-8-sig'), code.co_filename,
                           'exec', dont_inherit=True), f'Launcher differs: {tool}'
    assert len(checked) == expected_count, f'Unexpected module coverage: {tool}: {checked}'
    if tool == 'OSM-TF3-Vanilla-Converter':
        names = {name.replace('\\', '/'): name for name in reader.toc}
        for path in (source/'mod/tf3_osm_importer_mod').rglob('*'):
            if path.is_file():
                name = 'mod_template/' + path.relative_to(source/'mod/tf3_osm_importer_mod').as_posix()
                assert reader.extract(names[name]) == path.read_bytes(), f'Embedded mod differs: {name}'
    return len(checked)


def zip_files(target, entries):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name, source in sorted(entries.items()):
            bundle.write(source, name)
    with zipfile.ZipFile(target) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == set(entries)
        for name, source in entries.items():
            assert bundle.read(name) == source.read_bytes(), name


def docs(source):
    result = {}
    for path in source.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if len(rel.parts) == 1 and (path.suffix in ('.md', '.txt', '.json') or path.name == 'LICENSE'):
            result[rel.as_posix()] = path
        elif rel.parts[0] in ('examples', 'third-party', 'mod'):
            result[rel.as_posix()] = path
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    repository = os.environ['REVIEW_REPOSITORY']
    run_id = os.environ['REVIEW_RUN_ID']
    tag = os.environ['REVIEW_RELEASE_TAG']
    assert re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
    assert re.fullmatch(r'[1-9][0-9]*', run_id), 'Invalid run ID'
    assert re.fullmatch(r'map-studio-review-[0-9]{4}-[0-9]{2}-[0-9]{2}', tag), 'Unexpected release tag'
    date = tag.removeprefix('map-studio-review-')
    run = api(repository, f'actions/runs/{run_id}')
    releases = api(repository, 'releases?per_page=100')
    drafts = [item for item in releases if item['tag_name'] == tag]
    assert len(drafts) == 1, 'Expected one existing release with the requested tag'
    release = drafts[0]
    release_id = release['id']
    def current_release():
        current = api(repository, f'releases/{release_id}')
        assert current['tag_name'] == tag and current['id'] == release_id, 'Draft identity changed'
        return current
    sha = validate_metadata(run, release, repository)
    artifacts = api(repository, f'actions/runs/{run_id}/artifacts?per_page=100')['artifacts']
    matches = [a for a in artifacts if a['name'] == ARTIFACT and not a['expired']]
    assert len(matches) == 1, 'Expected one non-expired reviewed Windows artifact'
    assert matches[0].get('workflow_run', {}).get('head_sha', sha) == sha
    # A pre-existing tag must also resolve to this commit; draft target alone
    # cannot override a tag that somebody previously created at another commit.
    existing = command('git', 'ls-remote', 'origin', f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}')
    if existing:
        refs = dict((line.split()[1], line.split()[0]) for line in existing.splitlines())
        assert refs.get(f'refs/tags/{tag}^{{}}', refs.get(f'refs/tags/{tag}')) == sha, 'Existing tag points elsewhere'
    subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', sha], check=True)
    with tempfile.TemporaryDirectory(prefix='reviewed-release-') as directory:
        work = Path(directory)
        source_zip = work/f'TF3-Map-Studio-source-{date}.zip'
        subprocess.run(['git', 'archive', '--format=zip', '--prefix=TF3-Map-Studio/',
                        f'--output={source_zip}', sha], check=True)
        extract_zip(source_zip, work/'source')
        source = work/'source/TF3-Map-Studio'
        incoming = work/'artifact'
        subprocess.run(['gh', 'run', 'download', run_id, '--repo', repository,
                        '--name', ARTIFACT, '--dir', str(incoming)], check=True)
        heightmap = incoming/'TF3-Heightmap-Studio/dist/TF3-Heightmap-Studio.exe'
        osm = incoming/'OSM-TF3-Vanilla-Converter/dist/OSM-TF3-Vanilla-Converter.exe'
        vehicle_zip = incoming/'TRF3-Mod-Converter/dist/TRF3-Mod-Converter-Windows.zip'
        for path in (heightmap, osm, vehicle_zip):
            assert path.is_file(), f'Missing reviewed app: {path}'
        extract_zip(vehicle_zip, work/'vehicle')
        vehicle = work/'vehicle/TRF3-Mod-Converter.exe'
        coverage = {tool: verify_executable(exe, source/tool, tool) for tool, exe in (
            ('TF3-Heightmap-Studio', heightmap), ('OSM-TF3-Vanilla-Converter', osm),
            ('TRF3-Mod-Converter', vehicle))}
        for path in (source/'OSM-TF3-Vanilla-Converter/mod/tf3_osm_importer_mod').rglob('*'):
            if path.is_file():
                relative = path.relative_to(source/'OSM-TF3-Vanilla-Converter/mod/tf3_osm_importer_mod')
                assert path.read_bytes() == (source/'TF3-OSM-Importer-Mod/mod/tf3_osm_importer_mod'/relative).read_bytes()
        manifest = work/'build-manifest.json'
        manifest.write_text(json.dumps({
            'reviewedSourceCommit': sha, 'successfulWorkflowRunId': run_id,
            'artifactId': matches[0]['id'], 'nativeGameTestByThisWorkflow': 'not_run',
            'validationNote': 'Source validation.json records may describe earlier local builds. This manifest identifies the CI binaries in this package; source archive is unchanged.',
            'executables': {tool: {'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
                                   'embeddedModulesVerified': coverage[tool]}
                            for tool, exe in (('TF3-Heightmap-Studio', heightmap),
                                              ('OSM-TF3-Vanilla-Converter', osm),
                                              ('TRF3-Mod-Converter', vehicle))},
        }, indent=2) + '\n', encoding='utf-8')
        assets = [source_zip]
        all_entries = {'TF3-Map-Studio/README.md': source/'README.md',
                       'TF3-Map-Studio/CODE-REVIEW-2026-10-25.md': source/'CODE-REVIEW-2026-10-25.md',
                       'TF3-Map-Studio/build-manifest.json': manifest}
        versions = {'TF3-Heightmap-Studio': '0.10', 'OSM-TF3-Vanilla-Converter': '0.16'}
        for tool, exe in (('TF3-Heightmap-Studio', heightmap), ('OSM-TF3-Vanilla-Converter', osm), ('TRF3-Mod-Converter', vehicle)):
            entries = docs(source/tool)
            entries[f'dist/{tool}.exe'] = exe
            entries['build-manifest.json'] = manifest
            all_entries.update({f'TF3-Map-Studio/{tool}/{name}': path for name, path in entries.items()})
            if tool in versions:
                asset = work/f'{tool}-{versions[tool]}-Windows.zip'
                zip_files(asset, {f'{tool}/{name}': path for name, path in entries.items()})
                assets.append(asset)
        mod = source/'TF3-OSM-Importer-Mod/mod/tf3_osm_importer_mod'
        mod_entries = {f'tf3_osm_importer_mod/{path.relative_to(mod).as_posix()}': path
                       for path in mod.rglob('*') if path.is_file()}
        assert json.loads((mod/'mod.json').read_text())['revision'] == 9
        mod_zip = work/'TF3-OSM-Importer-Mod-Revision-9.zip'
        zip_files(mod_zip, mod_entries)
        assets.append(mod_zip)
        all_entries.update({f'TF3-Map-Studio/TF3-OSM-Importer-Mod/mod/{name}': path for name, path in mod_entries.items()})
        windows_zip = work/f'TF3-Map-Studio-Windows-{date}.zip'
        zip_files(windows_zip, all_entries)
        assets.append(windows_zip)
        digests = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in assets}
        checksums = work/f'TF3-Map-Studio-{date}-SHA256.txt'
        checksums.write_text(''.join(f'{digest}  {name}\n' for name, digest in sorted(digests.items())), encoding='utf-8')
        assets.append(checksums)
        print(json.dumps({'reviewedCommit': sha, 'runId': run_id, 'moduleCoverage': coverage, 'sha256': digests}, indent=2))
        if not args.publish:
            print('Validation passed. --publish was not supplied; GitHub was not changed.')
            return
        validate_metadata(api(repository, f'actions/runs/{run_id}'), current_release(), repository)
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', repository, '--clobber', *map(str, assets)], check=True)
        current = current_release()
        validate_metadata(run, current, repository)
        uploaded = {a['name']: a for a in current['assets']}
        for path in assets:
            remote = uploaded[path.name]
            assert remote['state'] == 'uploaded' and remote['size'] == path.stat().st_size
            assert remote['digest'] == 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(), path.name
        subprocess.run(['gh', 'release', 'edit', tag, '--repo', repository, '--draft=false'], check=True)
        print(current['html_url'])


if __name__ == '__main__':
    main()

"""Release verification must follow source modules, never a stale numeric count."""
import importlib.util
import marshal
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

spec = importlib.util.spec_from_file_location('publish_reviewed', Path(__file__).resolve().parents[1]/'scripts/publish_reviewed.py')
publish = importlib.util.module_from_spec(spec); spec.loader.exec_module(publish)


def archive(tmp_path, missing=False, changed=False):
    source = tmp_path/'source'; (source/'tools').mkdir(parents=True); (source/'vendor').mkdir()
    for name in ('gui', 'terrain_quality', 'local_sources', 'data_access'):
        (source/'tools'/f'{name}.py').write_text(f'value = {name!r}\n')
    (source/'tools/cli.py').write_text('raise SystemExit()')
    (source/'tools/build_check.py').write_text('raise SystemExit()')
    codes = {p.stem: compile(p.read_text(), str(p), 'exec') for p in (source/'tools').glob('*.py')}
    launcher = codes.pop('gui')
    if missing: codes.pop('terrain_quality')
    if changed: codes['terrain_quality'] = compile('value = "obsolete"', 'terrain_quality.py', 'exec')
    class PYZ:
        toc = codes
        def extract(self, name): return codes[name]
    class Reader:
        toc = {'PYZ.pyz': None, 'gui': None}
        def __init__(self, path): pass
        def open_embedded_archive(self, name): return PYZ()
        def extract(self, name): return marshal.dumps(launcher)
    return source, Reader


def test_new_runtime_modules_are_verified_without_updating_a_numeric_count(tmp_path):
    source, reader = archive(tmp_path)
    with patch('PyInstaller.archive.readers.CArchiveReader', reader):
        assert publish.verify_executable(tmp_path/'app.exe', source, 'TF3-Heightmap-Studio') == 4


@pytest.mark.parametrize('missing,changed,message', [(True, False, 'Required runtime module is missing'), (False, True, 'Embedded code differs')])
def test_missing_or_outdated_runtime_module_blocks_publication(tmp_path, missing, changed, message):
    source, reader = archive(tmp_path, missing, changed)
    with patch('PyInstaller.archive.readers.CArchiveReader', reader), pytest.raises(AssertionError, match=message):
        publish.verify_executable(tmp_path/'app.exe', source, 'TF3-Heightmap-Studio')

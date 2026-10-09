import errno
import os
from pathlib import Path

import pytest

from trf3_mod_converter import filesystem


def windows_permission(code):
    error = PermissionError(errno.EACCES, 'simulated Windows lock')
    error.winerror = code
    return error


@pytest.mark.parametrize('code',[5,32,33])
def test_batch_report_transient_lock_preserves_previous_until_atomic_save(tmp_path,monkeypatch,code):
    import json
    from trf3_mod_converter import batch
    target=tmp_path/batch.STATE_NAME
    target.write_text(json.dumps({'previous':True}))
    replace=os.replace;calls=[];sleeps=[]
    def locked(source,destination):
        calls.append(1)
        assert json.loads(target.read_text())=={'previous':True}
        if len(calls)<3:raise windows_permission(code)
        return replace(source,destination)
    monkeypatch.setattr(filesystem.os,'replace',locked)
    monkeypatch.setattr(filesystem.time,'sleep',sleeps.append)
    batch._save_state(tmp_path,{'completed':True})
    assert json.loads(target.read_text())=={'completed':True}
    assert len(calls)==3 and sleeps==[0.05,0.10]
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('code',[5,32,33,None])
def test_batch_report_permanent_denial_keeps_prior_report_and_original_error(tmp_path,monkeypatch,code):
    import json
    from trf3_mod_converter import batch
    target=tmp_path/batch.STATE_NAME;target.write_text(json.dumps({'previous':True}))
    errors=[];sleeps=[]
    def locked(*args):
        error=windows_permission(code);errors.append(error);raise error
    monkeypatch.setattr(filesystem.os,'replace',locked)
    monkeypatch.setattr(filesystem.time,'sleep',sleeps.append)
    with pytest.raises(PermissionError) as failure:batch._save_state(tmp_path,{'completed':True})
    assert failure.value is errors[-1]
    assert len(errors)==(1 if code is None else 6)
    assert json.loads(target.read_text())=={'previous':True}
    assert sum(sleeps)<2 and not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('code', [5, 32, 33])
@pytest.mark.parametrize('directory', [False, True])
def test_transient_locks_eventually_publish_unchanged_source(tmp_path, monkeypatch, code, directory):
    source, destination = tmp_path/'stage', tmp_path/'published'
    if directory:
        source.mkdir()
        (source/'payload').write_bytes(b'original bytes')
    else:
        source.write_bytes(b'original bytes')
    rename = Path.rename
    attempts, sleeps = [], []

    def transient(path, target):
        attempts.append((path, Path(target)))
        if len(attempts) < 3:
            raise windows_permission(code)
        return rename(path, target)

    monkeypatch.setattr(Path, 'rename', transient)
    monkeypatch.setattr(filesystem.time, 'sleep', sleeps.append)
    assert filesystem.rename_with_retry(source, destination) == destination
    assert len(attempts) == 3 and sleeps == [0.05, 0.10]
    assert not source.exists()
    assert (destination/'payload' if directory else destination).read_bytes() == b'original bytes'


@pytest.mark.parametrize('code', [5, 32, 33])
def test_exhausted_locks_leave_source_and_raise_original_last_error(tmp_path, monkeypatch, code):
    source, destination = tmp_path/'source', tmp_path/'destination'
    source.write_bytes(b'keep source')
    errors, sleeps = [], []

    def locked(path, target):
        error = windows_permission(code)
        errors.append(error)
        raise error

    monkeypatch.setattr(Path, 'rename', locked)
    monkeypatch.setattr(filesystem.time, 'sleep', sleeps.append)
    with pytest.raises(PermissionError) as failure:
        filesystem.rename_with_retry(source, destination)
    assert failure.value is errors[-1]
    assert len(errors) == 6 and sleeps == [0.05, 0.10, 0.20, 0.40, 0.80]
    assert sum(sleeps) < 2
    assert source.read_bytes() == b'keep source' and not destination.exists()


@pytest.mark.parametrize('error', [
    PermissionError(errno.EACCES, 'POSIX denied'),
    windows_permission(2), windows_permission(3), windows_permission(80), windows_permission(183),
    FileNotFoundError(errno.ENOENT, 'missing'),
    OSError(errno.EIO, 'I/O failure'),
])
def test_other_errors_fail_immediately_without_changes(tmp_path, monkeypatch, error):
    source, destination = tmp_path/'source', tmp_path/'destination'
    source.write_bytes(b'source')
    attempts, sleeps = [], []

    def failing(path, target):
        attempts.append((path, target))
        raise error

    monkeypatch.setattr(Path, 'rename', failing)
    monkeypatch.setattr(filesystem.time, 'sleep', sleeps.append)
    with pytest.raises(type(error)) as failure:
        filesystem.rename_with_retry(source, destination)
    assert failure.value is error
    assert len(attempts) == 1 and not sleeps
    assert source.read_bytes() == b'source' and not destination.exists()


@pytest.mark.parametrize('directory', [False, True])
def test_existing_destination_is_not_overwritten(tmp_path, monkeypatch, directory):
    source, destination = tmp_path/'source', tmp_path/'destination'
    source.write_bytes(b'source')
    if directory:
        destination.mkdir()
        (destination/'payload').write_bytes(b'destination')
    else:
        destination.write_bytes(b'destination')

    def forbidden(*args):
        pytest.fail('Existing destination must be rejected before rename or sleep')

    monkeypatch.setattr(Path, 'rename', forbidden)
    monkeypatch.setattr(filesystem.time, 'sleep', forbidden)
    with pytest.raises(FileExistsError):
        filesystem.rename_with_retry(source, destination)
    assert source.read_bytes() == b'source'
    assert (destination/'payload' if directory else destination).read_bytes() == b'destination'


def test_destination_created_during_backoff_is_not_overwritten(tmp_path, monkeypatch):
    source, destination = tmp_path/'source', tmp_path/'destination'
    source.write_bytes(b'source')
    attempts = []

    def locked(path, target):
        attempts.append((path, target))
        raise windows_permission(32)

    def destination_appears(delay):
        destination.write_bytes(b'new unrelated destination')

    monkeypatch.setattr(Path, 'rename', locked)
    monkeypatch.setattr(filesystem.time, 'sleep', destination_appears)
    with pytest.raises(FileExistsError):
        filesystem.rename_with_retry(source, destination)
    assert len(attempts) == 1
    assert source.read_bytes() == b'source' and destination.read_bytes() == b'new unrelated destination'


def test_missing_source_fails_without_creating_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(filesystem.time, 'sleep', lambda delay: pytest.fail('Missing source must not retry'))
    with pytest.raises(FileNotFoundError):
        filesystem.rename_with_retry(tmp_path/'missing', tmp_path/'destination')
    assert not (tmp_path/'destination').exists()


def test_same_path_is_a_safe_no_op(tmp_path, monkeypatch):
    source = tmp_path/'source'
    source.write_bytes(b'source')
    monkeypatch.setattr(Path, 'rename', lambda *args: pytest.fail('Same path must not rename'))
    assert filesystem.rename_with_retry(source, source) == source
    assert source.read_bytes() == b'source'


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-insensitive path semantics')
@pytest.mark.parametrize('directory', [False, True])
def test_windows_case_only_rename_preserves_payload(tmp_path, directory):
    source, destination = tmp_path/'Staged', tmp_path/'staged'
    if directory:
        source.mkdir()
        (source/'payload').write_bytes(b'unchanged')
    else:
        source.write_bytes(b'unchanged')
    assert filesystem.rename_with_retry(source, destination) == destination
    assert [path.name for path in tmp_path.iterdir()] == ['staged']
    assert (destination/'payload' if directory else destination).read_bytes() == b'unchanged'

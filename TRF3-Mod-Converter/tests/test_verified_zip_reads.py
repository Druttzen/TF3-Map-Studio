import os
import zipfile

import pytest

from trf3_mod_converter.base_resources import VerifiedReadZipFile


@pytest.fixture
def archive(tmp_path):
    VerifiedReadZipFile._catalogs.clear()
    path=tmp_path/'inputs.zip'
    with zipfile.ZipFile(path,'w') as handle:
        handle.writestr('input.txt',b'first')
    return path


def test_repeated_current_directory_reuses_parsing_and_returns_isolated_info(archive,monkeypatch):
    calls=[]
    original=zipfile.ZipFile._RealGetContents
    def parse(handle):
        calls.append(1)
        return original(handle)
    monkeypatch.setattr(zipfile.ZipFile,'_RealGetContents',parse)
    for _ in range(3):
        with VerifiedReadZipFile(archive) as handle:
            assert handle.read('input.txt')==b'first'
            handle.getinfo('input.txt').CRC=0
            handle.infolist()[0].external_attr=0
    assert len(calls)==1


def test_changed_catalog_is_detected_even_when_size_and_timestamp_are_restored(archive):
    before=archive.stat()
    with VerifiedReadZipFile(archive) as handle:assert handle.read('input.txt')==b'first'
    with zipfile.ZipFile(archive,'w') as handle:handle.writestr('input.txt',b'other')
    assert archive.stat().st_size==before.st_size
    os.utime(archive,ns=(before.st_atime_ns,before.st_mtime_ns))
    with VerifiedReadZipFile(archive) as handle:assert handle.read('input.txt')==b'other'


def test_payload_is_read_again_when_catalog_bytes_do_not_change(archive):
    with VerifiedReadZipFile(archive) as handle:
        info=handle.getinfo('input.txt')
        assert handle.read('input.txt')==b'first'
    with archive.open('r+b') as stream:
        stream.seek(info.header_offset+30+len(info.filename.encode()))
        stream.write(b'other')
    with VerifiedReadZipFile(archive) as handle:
        with pytest.raises(zipfile.BadZipFile,match='CRC'):
            handle.read('input.txt')


def test_new_duplicate_member_selects_current_last_entry(archive):
    with VerifiedReadZipFile(archive) as handle:assert handle.read('input.txt')==b'first'
    with pytest.warns(UserWarning,match='Duplicate name'):
        with zipfile.ZipFile(archive,'a') as handle:handle.writestr('input.txt',b'latest')
    with VerifiedReadZipFile(archive) as handle:
        assert handle.read('input.txt')==b'latest'
        assert len(handle.infolist())==2


def test_changed_symlink_attributes_are_not_hidden_by_cache(archive):
    with VerifiedReadZipFile(archive) as handle:assert handle.getinfo('input.txt').external_attr>>16 & 0o170000 != 0o120000
    info=zipfile.ZipInfo('input.txt');info.create_system=3;info.external_attr=0o120777<<16
    with zipfile.ZipFile(archive,'w') as handle:handle.writestr(info,b'first')
    with VerifiedReadZipFile(archive) as handle:assert handle.getinfo('input.txt').external_attr>>16 & 0o170000 == 0o120000


def test_missing_private_runtime_helper_uses_standard_reader(archive,monkeypatch):
    # Simulate an older runtime without changing the standard reader itself.
    monkeypatch.setattr(VerifiedReadZipFile,'_directory_signature',lambda self:None)
    with VerifiedReadZipFile(archive) as handle:assert handle.read('input.txt')==b'first'
    assert not VerifiedReadZipFile._catalogs


def test_invalid_archive_and_write_attempt_are_rejected(archive):
    archive.write_bytes(b'invalid')
    with pytest.raises(zipfile.BadZipFile):VerifiedReadZipFile(archive)
    with pytest.raises(ValueError,match='read-only'):VerifiedReadZipFile(archive,'w')

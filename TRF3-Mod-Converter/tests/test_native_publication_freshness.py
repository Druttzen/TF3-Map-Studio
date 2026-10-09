import hashlib
import json
import zipfile

import pytest

from trf3_mod_converter import batch
from trf3_mod_converter.tf2_vehicle_port import NativeInventory, port_tf2_mod, snapshot
from test_tf2_vehicle_port import fixture_mod


@pytest.mark.parametrize('change', ['loose_addition', 'archive_addition', 'loose_shadow'])
def test_mount_change_during_export_prevents_publication(fixture_mod, monkeypatch, change):
    source, game, output = fixture_mod
    before = snapshot(source)
    actual = NativeInventory.material
    changed = False
    def mutate(self, data, resolve, **kwargs):
        nonlocal changed
        result = actual(self, data, resolve, **kwargs)
        if not changed:
            changed = True
            if change == 'archive_addition':
                with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as z:
                    z.writestr('vehicle/plane/new.mdl', 'return {version=2}')
            else:
                relative = ('vehicle/plane/new.mdl' if change == 'loose_addition' else
                    'vehicle/train/shared/sound/train_electric_old.snd.lua')
                path = game/'base/content'/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('return {version=2}')
        return result
    monkeypatch.setattr(NativeInventory, 'material', mutate)
    with pytest.raises(ValueError, match='TF3 resource.*changed'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft')
    assert snapshot(source) == before
    assert not output.exists()


def test_cached_inventory_cannot_publish_after_new_plane_appears(fixture_mod):
    source, game, output = fixture_mod
    inventory = NativeInventory(game)
    path = game/'base/content/vehicle/plane/new.mdl'
    path.parent.mkdir(parents=True)
    path.write_text('return {version=2}')
    with pytest.raises(ValueError, match='TF3 resources or mounts changed'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft',
                     _native_inventory=inventory)
    assert not output.exists()


@pytest.mark.parametrize('phase', ['final_copy', 'finalizing_notification'])
@pytest.mark.parametrize('overwrite', [False, True])
def test_last_copy_phase_guard_preserves_existing_output(fixture_mod, monkeypatch, phase, overwrite):
    from trf3_mod_converter import converter
    source, game, output = fixture_mod
    before = snapshot(source)
    if overwrite:
        output.mkdir()
        (output/'sentinel.txt').write_bytes(b'preserve existing draft')
    def change():
        path = game/'base/content/vehicle/plane/late.mdl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('return {version=2}')
    actual = converter._copy_files
    def late_copy(*args, **kwargs):
        value = actual(*args, **kwargs)
        change()
        return value
    if phase == 'final_copy':
        monkeypatch.setattr(converter, '_copy_files', late_copy)
    def notify(message):
        if phase == 'finalizing_notification' and 'Finalizing output' in message:
            change()
    with pytest.raises(ValueError, match='TF3 resources or mounts changed'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Draft',
                     overwrite=overwrite, progress=notify)
    assert snapshot(source) == before
    if overwrite:
        assert snapshot(output) == {'sentinel.txt':hashlib.sha256(b'preserve existing draft').hexdigest()}
    else:
        assert not output.exists()


def test_a_second_read_cannot_replace_an_attested_native_digest(fixture_mod):
    _, game, _ = fixture_mod
    path = game/'base/content/attested.mdl'
    path.write_bytes(b'parsed old definition')
    inventory = NativeInventory(game)
    assert inventory.read('attested.mdl') == b'parsed old definition'
    path.write_bytes(b'changed definition')
    with pytest.raises(ValueError, match='TF3 resource changed'):
        inventory.read('attested.mdl')
    assert inventory.dependencies['attested.mdl'] == hashlib.sha256(b'parsed old definition').hexdigest()


def test_conflicting_catalog_digest_cannot_replace_a_native_read(fixture_mod):
    _, game, _ = fixture_mod
    inventory = NativeInventory(game)
    inventory.read('rendering/physical.mat.lua')
    before = dict(inventory.dependencies)
    with pytest.raises(ValueError, match='after their data was parsed'):
        inventory.track_dependencies({'rendering/physical.mat.lua':'0'*64})
    assert inventory.dependencies == before


def test_queue_rechecks_mounts_after_export_before_green_receipt(fixture_mod, monkeypatch):
    source, game, output = fixture_mod
    items = batch.scan_mods(source)['items']
    actual = batch._export
    def mutate(*args, **kwargs):
        report = actual(*args, **kwargs)
        path = game/'base/content/vehicle/plane/new.mdl'
        path.parent.mkdir(parents=True)
        path.write_text('return {version=2}')
        return report
    monkeypatch.setattr(batch, '_export', mutate)
    state = batch.convert_queue(items, output, tf3_game=game)
    assert items[0].status == 'failed'
    assert 'TF3 resources changed' in items[0].message
    assert not state['receipts']


def test_queue_resume_with_shared_inventory_rejects_added_mount(fixture_mod, monkeypatch):
    source, game, output = fixture_mod
    first = batch.scan_mods(source)['items']
    state = batch.convert_queue(first, output, tf3_game=game)
    assert state['counts']['completed'] == 1
    inventory = NativeInventory(game)
    path = game/'base/content/vehicle/plane/new.mdl'
    path.parent.mkdir(parents=True)
    path.write_text('return {version=2}')
    monkeypatch.setattr(batch, 'NativeInventory', lambda _game: inventory)
    state = batch.convert_queue(batch.scan_mods(source)['items'], output, tf3_game=game)
    assert state['counts']['failed'] == 1
    assert 'not overwritten' in state['items'][0]['message']

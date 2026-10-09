import hashlib
import zipfile

import pytest

from trf3_mod_converter.base_resources import BASE_MATERIALS, BaseResourceResolver, TF2Inventory, find_tf2_game
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot
from test_tf2_vehicle_port import fixture_mod


class Installed:
    def __init__(self, files):
        self.files = files
        self.references = set()

    def read(self, path):
        return self.files[path]

    def reference(self, path):
        target = path + '.lua' if path.endswith('.snd') else path
        if target not in self.files:
            raise ValueError('Installed resource missing')
        self.references.add(path)
        return '::/' + path


def tf2_inventory(tmp_path, files):
    game = tmp_path / 'tf2'
    for name, value in files.items():
        path = game / 'res' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    return TF2Inventory(game)


@pytest.mark.parametrize('reference,target', [
    ('models/vehicle/dirt_albedo.dds', 'vehicle/shared/mat/tex/dirt_albedo.dds'),
    ('default_normal_map.tga', 'placeholders/mat/tex/default_normal_map.dds'),
    ('particle_smoke.dds', 'base/tex/particle_smoke.dds'),
    ('unknown_texture.tga', 'placeholders/mat/tex/unknown_texture.dds'),
    ('unknown_albedo_1k.tga', 'placeholders/mat/tex/unknown_albedo_1k.dds'),
])
def test_known_roles_use_installed_tf3_asset_even_when_its_bytes_changed(tmp_path, reference, target):
    legacy = tf2_inventory(tmp_path, {'textures/' + reference: b'TF2 authored placeholder'})
    native = Installed({target: b'updated TF3 authored placeholder'})
    resolver = BaseResourceResolver(native, legacy)
    assert resolver.resolve('texture', reference) == '::/' + target
    assert resolver.replacements[0]['matchMethod'] == 'verified_role_mapping'
    assert resolver.replacements[0]['sourceOrigin'] == 'tf2_base'
    assert native.read(target) != legacy.read('textures/' + reference)


def test_standard_emissive_material_role_requires_installed_target_and_does_not_match_custom_names(tmp_path):
    reference='vehicle/car/emissive/car_brake_lights.mtl'
    target=BASE_MATERIALS[reference]
    legacy=tf2_inventory(tmp_path, {'models/material/'+reference:b'authored TF2 material placeholder'})
    native=Installed({target:b'updated TF3 light material placeholder'})
    resolver=BaseResourceResolver(native,legacy)
    assert resolver.resolve('material',reference)=='::/'+target
    assert resolver.replacements[0]['matchMethod']=='verified_role_mapping'
    with pytest.raises(ValueError,match='No verified TF3 equivalent'):
        BaseResourceResolver(Installed({}),legacy).resolve('material',reference)
    with pytest.raises(ValueError,match='No verified TF3 equivalent'):
        resolver.resolve('material','vehicle/custom/emissive/car_brake_lights.mtl')


@pytest.mark.parametrize('name,family', [
    ('bus_modern', 'bus'), ('car_old', 'car'), ('truck_modern', 'truck'),
    ('train_electric_old', 'train'), ('cabcar_modern', 'train'),
    ('tram_old', 'tram'), ('waggon_modern', 'waggon'),
    ('aircraft_jet_modern', 'plane'), ('ship_diesel_modern', 'ship'),
])
def test_vehicle_sound_sets_keep_their_native_vehicle_family(name, family):
    target = f'vehicle/{family}/shared/sound/{name}.snd'
    resolver = BaseResourceResolver(Installed({target + '.lua': b'authored native fixture'}))
    assert resolver.resolve('sound_set', name) == '::/' + target


def test_ambiguous_vehicle_audio_needs_context_or_identical_binary_proof(tmp_path):
    train = 'vehicle/train/shared/sound/common/drive.wav'
    bus = 'vehicle/bus/shared/sound/common/drive.wav'
    native = Installed({train: b'train TF3', bus: b'bus TF3'})
    reference = 'vehicle/common/drive.wav'
    with pytest.raises(ValueError, match='No verified TF3 equivalent'):
        BaseResourceResolver(native).resolve('audio', reference)
    assert BaseResourceResolver(native, family='bus').resolve('audio', reference) == '::/' + bus
    legacy = tf2_inventory(tmp_path, {'audio/effects/' + reference: b'bus TF3'})
    resolver = BaseResourceResolver(native, legacy)
    assert resolver.resolve('audio', reference) == '::/' + bus
    assert resolver.replacements[0]['matchMethod'] == 'byte_identical'


def test_matching_basename_without_matching_bytes_is_not_an_equivalent(tmp_path):
    legacy = tf2_inventory(tmp_path, {'textures/custom/shared.dds': b'original image'})
    resolver = BaseResourceResolver(Installed({'assets/tex/shared.dds': b'different image'}), legacy)
    with pytest.raises(ValueError, match='No verified TF3 equivalent'):
        resolver.resolve('texture', 'custom/shared.dds')
    assert not resolver.replacements


def test_relocated_binary_requires_hash_proof_and_allows_identical_copies(tmp_path):
    original = b'authored identical texture fixture'
    legacy = tf2_inventory(tmp_path, {'textures/custom/shared.dds': original})
    native = Installed({'assets/tex/shared.dds': original, 'placeholders/tex/shared.dds': original})
    resolver = BaseResourceResolver(native, legacy)
    assert resolver.resolve('texture', 'custom/shared.dds') == '::/assets/tex/shared.dds'
    assert resolver.replacements[0]['sha256'] == hashlib.sha256(original).hexdigest()
    assert resolver.replacements[0]['matchMethod'] == 'byte_identical'


@pytest.mark.parametrize('reference', ['../outside.wav', '/absolute.wav', 'vehicle\\clip.wav',
                                        'other_mod::/clip.wav', 'vehicle//../clip.wav'])
def test_unsafe_resource_references_are_rejected(reference):
    with pytest.raises(ValueError, match='Unsafe TF2 resource reference'):
        BaseResourceResolver(Installed({})).resolve('audio', reference)


def test_tf2_inventory_mounts_zip_members_and_preserves_loose_override(tmp_path):
    game = tmp_path / 'tf2'
    textures = game / 'res/textures'
    textures.mkdir(parents=True)
    with zipfile.ZipFile(textures / 'misc.zip', 'w') as archive:
        archive.writestr('particle_smoke.dds', b'packaged fixture')
        archive.writestr('nested/shared.dds', b'nested fixture')
    (textures / 'particle_smoke.dds').write_bytes(b'loose fixture')
    inventory = TF2Inventory(game)
    assert inventory.read('textures/particle_smoke.dds') == b'loose fixture'
    assert inventory.read('textures/nested/shared.dds') == b'nested fixture'


def test_tf2_inventory_rejects_unsafe_archive_members(tmp_path):
    game = tmp_path / 'tf2'
    (game / 'res').mkdir(parents=True)
    with zipfile.ZipFile(game / 'res/unsafe.zip', 'w') as archive:
        archive.writestr('../outside.dds', b'fixture')
    with pytest.raises(ValueError, match='Unsafe TF2 resource reference'):
        TF2Inventory(game)


def test_detect_tf2_from_workshop_steam_library(tmp_path):
    game = tmp_path / 'steamapps/common/Transport Fever 2'
    (game / 'res').mkdir(parents=True)
    source = tmp_path / 'steamapps/workshop/content/1066780/123'
    assert find_tf2_game(source, tmp_path / 'other_library/Transport Fever 3') == game


def test_complete_port_references_tf3_and_omits_bundled_tf2_game_data(fixture_mod, tmp_path):
    source, game, output = fixture_mod
    texture_ref = 'models/vehicle/dirt_albedo.dds'
    audio_ref = 'vehicle/train/wheels_ringing1.wav'
    texture_target = 'vehicle/shared/mat/tex/dirt_albedo.dds'
    audio_target = 'vehicle/train/shared/sound/train/wheels_ringing1.wav'
    files = {'textures/' + texture_ref: b'borrowed TF2 texture fixture',
             'audio/effects/' + audio_ref: b'borrowed TF2 clip fixture',
             'config/sound_set/train_electric_old.lua': b'error("must never execute base Lua")'}
    legacy = tf2_inventory(tmp_path, files)
    for relative, value in files.items():
        target = source / 'res' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value)
    for relative in ('models/material/body.mtl', 'models/material/light.mtl'):
        material = source / 'res' / relative
        data = load_lua_table(material.read_text())
        data['params']['map_albedo']['fileName'] = texture_ref
        material.write_text(emit(data))
    model = source / 'res/models/model/vehicle/train/test.mdl'
    data = load_lua_table(model.read_text())
    data['metadata']['railVehicle']['soundSet']['horn'] = audio_ref
    model.write_text(emit(data))
    for relative in (texture_target, audio_target):
        target = game / 'base/content' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'updated TF3 fixture')
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=legacy.content.parent,
                          mod_id='fixture_test', name='Native Resources')
    assert snapshot(source) == before
    assert report['omittedBorrowedResources'] == sorted(files)
    assert not set(files) & report['pathMapping'].keys()
    assert len(report['baseResourceReplacements']) == 3
    assert all(row['sourceOrigin'] == 'bundled_tf2_base' for row in report['baseResourceReplacements'])
    assert all(not (output / 'content' / relative).exists() for relative in files)
    assert not (output / 'content/config/sound_set/train_electric_old.snd.lua').exists()
    converted = load_lua_table((output / 'content/models/model/vehicle/train/test.mdl').read_text())
    assert converted['metadata']['soundConfig']['effects']['horn'] == ['::/' + audio_target]
    material = load_lua_table((output / 'content/models/material/body.mtl').read_text())
    assert material['params']['map_albedo']['fragmentSamplers']['albedoTex']['fileName'] == '::/' + texture_target
    assert (output / 'content/textures/body.dds').read_bytes() == b'fixture texture'
    assert report['nativeTest'] == 'not_run'


def test_authored_texture_with_standard_name_is_retained(fixture_mod, tmp_path):
    source, game, output = fixture_mod
    reference = 'models/vehicle/dirt_albedo.dds'
    legacy = tf2_inventory(tmp_path, {'textures/' + reference: b'original TF2 fixture'})
    own = source / 'res/textures' / reference
    own.parent.mkdir(parents=True)
    own.write_bytes(b'custom mod texture fixture')
    for relative in ('models/material/body.mtl', 'models/material/light.mtl'):
        material = source / 'res' / relative
        data = load_lua_table(material.read_text())
        data['params']['map_albedo']['fileName'] = reference
        material.write_text(emit(data))
    report = port_tf2_mod(source, output, tf3_game=game, tf2_game=legacy.content.parent,
                          mod_id='fixture_test', name='Custom Paint')
    assert not report['omittedBorrowedResources']
    assert (output / 'content/textures' / reference).read_bytes() == b'custom mod texture fixture'
    assert not any(r['kind'] == 'texture' for r in report['baseResourceReplacements'])


def test_missing_native_equivalent_blocks_before_output_changes(fixture_mod):
    source, game, output = fixture_mod
    material = source / 'res/models/material/body.mtl'
    data = load_lua_table(material.read_text())
    data['params']['map_albedo']['fileName'] = 'particle_smoke.dds'
    material.write_text(emit(data))
    before = snapshot(source)
    output.mkdir()
    (output / 'sentinel.txt').write_text('keep existing output')
    with pytest.raises(ValueError, match='No verified TF3 equivalent'):
        port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_test', name='Missing', overwrite=True)
    assert snapshot(source) == before
    assert (output / 'sentinel.txt').read_text() == 'keep existing output'

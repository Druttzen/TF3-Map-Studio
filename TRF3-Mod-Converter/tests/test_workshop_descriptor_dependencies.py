import hashlib
from pathlib import Path

import pytest

from trf3_mod_converter.workshop_resources import WorkshopResources, verify_workshop_dependencies
import trf3_mod_converter.workshop_resources as resources


@pytest.fixture
def collection(tmp_path):
    root = tmp_path / '1066780'
    source = root / '123'
    source.mkdir(parents=True)
    return root, source


def file(root, package, resource, data=b'authored resource'):
    path = root / package / 'res' / resource
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def metadata(root, package, mod_id='dependency', version=0):
    path = root / package / 'mod.lua'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('function data() return { info = { modid = "' + mod_id
                    + '", steamId = ' + package + ', minorVersion = ' + str(version) + ' } } end')
    return path


def declare(source, package='456', mod_id='dependency', minimum=0):
    (source / 'mod.lua').write_text('function data() return { info = { requiredMods = { { steamId = '
                                  + package + ', modId = "' + mod_id + '", minMinorVersion = '
                                  + str(minimum) + ' } } } } end')


def receipt(match):
    row = {key: value for key, value in match.items() if key not in ('data', 'fingerprints')}
    return [row], match['fingerprints']


def test_declared_scope_does_not_scan_unrelated_linked_resources(collection, monkeypatch):
    root, source = collection
    declare(source)
    metadata(root, '456')
    selected = file(root, '456', 'config/sound_set/shared.lua', b'intended sound')
    other = file(root, '789', 'config/sound_set/shared.lua', b'unrelated sound')
    real_linked = resources.linked
    monkeypatch.setattr(resources, 'linked', lambda p: p == other.parent or real_linked(p))
    match = WorkshopResources(source).resolve('shared', 'sound_set')
    assert match['providers'] == [str(selected)]
    assert verify_workshop_dependencies(source, *receipt(match))
    declare(source, '789')
    metadata(root, '789')
    with pytest.raises(ValueError, match='Linked'):
        WorkshopResources(source).resolve('shared', 'sound_set')


def test_literal_dependency_helper_keeps_full_metadata_hash_proof(collection):
    root, source = collection
    declare(source)
    header = metadata(root, '456')
    original = header.read_text()
    header.write_text('local hidden = {"x"}\nlocal function filter(items) return items end\n' + original)
    selected = file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    assert match['providers'] == [str(selected)]
    assert verify_workshop_dependencies(source, *receipt(match))
    header.write_text(header.read_text().replace('"x"', '"y"'))
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_conflicting_literal_dependency_identity_is_not_last_wins(collection):
    root, source = collection
    declare(source)
    header = metadata(root, '456')
    header.write_text(header.read_text().replace('modid = "dependency"',
        'modid = "wrong", modid = "dependency"'))
    file(root, '456', 'models/material/shared.mtl')
    with pytest.raises(ValueError, match='[Dd]uplicate|conflict'):
        WorkshopResources(source).resolve('shared.mtl', 'material')


@pytest.mark.parametrize('kind,reference,resource', [
    ('material', 'vehicle/plane/additional.mtl', 'models/material/vehicle/plane/additional.mtl'),
    ('model', 'asset/container.mdl', 'models/model/asset/container.mdl'),
    ('mesh', 'asset/container.msh', 'models/mesh/asset/container.msh'),
    ('mesh_blob', 'asset/container.msh.blob', 'models/mesh/asset/container.msh.blob'),
    ('audio', 'vehicle/horn.wav', 'audio/effects/vehicle/horn.wav'),
    ('animation', 'asset/doors.ani', 'models/animation/asset/doors.ani'),
    ('sound_set', 'gw_neu', 'config/sound_set/gw_neu.lua'),
    ('terrain_material', 'shared/grass.lua', 'config/terrain_material/shared/grass.lua'),
    ('ground_texture', 'ground', 'config/ground_texture/ground.lua'),
    ('grass', 'grass', 'config/grass/grass.lua'),
    ('multiple_unit', 'train/group', 'config/multiple_unit/train/group.lua'),
])
def test_exact_nontexture_dependency_records_verified_provider_without_transforming(collection, kind, reference, resource):
    root, source = collection
    provider = file(root, '456', resource)
    match = WorkshopResources(source).resolve(reference, kind)
    assert match['data'] == b'authored resource'
    assert match['providers'] == [str(provider)]
    assert match['sourceResource'] == resource
    assert match['providerSelection'] == 'all_exact_providers'
    assert match['declarationFingerprints'] == {}
    assert verify_workshop_dependencies(source, *receipt(match))
    provider.write_bytes(b'changed resource')
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_declared_steam_dependency_disambiguates_exact_conflicts_with_matching_identity(collection):
    root, source = collection
    declare(source)
    meta = metadata(root, '456')
    selected = file(root, '456', 'config/sound_set/gw_neu.lua', b'intended custom sound')
    file(root, '789', 'config/sound_set/gw_neu.lua', b'different sound')
    match = WorkshopResources(source).resolve('gw_neu', 'sound_set')
    assert match['providers'] == [str(selected)]
    assert match['providerSelection'] == 'declared_requiredMods'
    assert match['declarationFingerprints'] == {str(meta): hashlib.sha256(meta.read_bytes()).hexdigest()}
    assert verify_workshop_dependencies(source, *receipt(match))
    # A fresh receipt verifies identity evidence even if resource bytes are unchanged.
    meta.write_text(meta.read_text().replace('minorVersion = 0', 'minorVersion = 1'))
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_declared_scope_ignores_unrelated_linked_resource_tree_but_checks_selected_paths(collection, monkeypatch):
    root, source = collection
    declare(source)
    metadata(root, '456')
    selected = file(root, '456', 'config/sound_set/gw_neu.lua', b'intended sound')
    unrelated = file(root, '789', 'config/sound_set/gw_neu.lua', b'other sound').parent
    actual_linked = resources.linked
    monkeypatch.setattr(resources, 'linked', lambda path: path == unrelated or actual_linked(path))
    match = WorkshopResources(source).resolve('gw_neu', 'sound_set')
    assert match['providers'] == [str(selected)]
    assert verify_workshop_dependencies(source, *receipt(match))
    # Changing the declaration to that linked resource does not bypass checks.
    metadata(root, '789')
    declare(source, '789')
    with pytest.raises(ValueError, match='Linked'):
        WorkshopResources(source).resolve('gw_neu', 'sound_set')


def test_literal_dependency_header_with_independent_local_helper_keeps_hash_proof(collection):
    root, source = collection
    declare(source)
    meta = metadata(root, '456')
    meta.write_text('local hidden = { "unused.mdl" }\n'
                    'local function filter(name) return name ~= hidden[1] end\n' + meta.read_text())
    file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    assert verify_workshop_dependencies(source, *receipt(match))
    meta.write_text(meta.read_text().replace('unused.mdl', 'changed.mdl'))
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_source_declaration_changes_invalidate_selected_provider_scope(collection):
    root, source = collection
    declare(source)
    metadata(root, '456')
    metadata(root, '789')
    file(root, '456', 'models/material/shared.mtl', b'one material')
    file(root, '789', 'models/material/shared.mtl', b'another material')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    declare(source, '789')
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_missing_declared_package_does_not_choose_between_other_providers(collection):
    root, source = collection
    declare(source, '999')
    file(root, '456', 'models/material/shared.mtl', b'one material')
    file(root, '789', 'models/material/shared.mtl', b'another material')
    with pytest.raises(ValueError, match='Ambiguous.*declared packages are not installed: 999'):
        WorkshopResources(source).resolve('shared.mtl', 'material')


@pytest.mark.parametrize('installed_id,installed_version,message', [
    ('wrong', 0, 'modId does not match'),
    ('dependency', 0, 'does not satisfy minMinorVersion'),
])
def test_declared_provider_identity_and_minimum_version_are_checked(collection, installed_id, installed_version, message):
    root, source = collection
    declare(source, minimum=1)
    metadata(root, '456', installed_id, installed_version)
    file(root, '456', 'models/model/asset/container.mdl')
    with pytest.raises(ValueError, match=message):
        WorkshopResources(source).resolve('asset/container.mdl', 'model')


def test_declared_provider_requires_its_literal_metadata(collection):
    root, source = collection
    declare(source)
    file(root, '456', 'models/material/shared.mtl')
    with pytest.raises(ValueError, match='provider is missing'):
        WorkshopResources(source).resolve('shared.mtl', 'material')


def test_multiple_declared_providers_with_different_content_remain_ambiguous(collection):
    root, source = collection
    (source/'mod.lua').write_text('function data() return { info = { requiredMods = {'
                               '{steamId=456,modId="dependency"},{steamId=789,modId="dependency"}'
                               '} } } end')
    metadata(root, '456')
    metadata(root, '789')
    file(root, '456', 'models/material/shared.mtl', b'one material')
    file(root, '789', 'models/material/shared.mtl', b'another material')
    with pytest.raises(ValueError, match='Ambiguous.*different bytes'):
        WorkshopResources(source).resolve('shared.mtl', 'material')


def test_unrelated_declaration_does_not_hide_unambiguous_implicit_dependency(collection):
    root, source = collection
    declare(source, '999')
    provider = file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    assert match['providers'] == [str(provider)]
    assert match['providerSelection'] == 'all_exact_providers'


def test_declared_only_ignores_ambiguous_unrelated_exact_providers_and_cache_scope(collection):
    root, source = collection
    file(root, '456', 'models/material/shared.mtl', b'one material')
    file(root, '789', 'models/material/shared.mtl', b'another material')
    lookup = WorkshopResources(source)
    assert lookup.resolve('shared.mtl', 'material', allow_global=False) is None
    with pytest.raises(ValueError, match='Ambiguous'):
        lookup.resolve('shared.mtl', 'material')


def test_declared_only_custom_provider_wins_and_fresh_receipt_preserves_scope(collection):
    root, source = collection
    declare(source)
    meta = metadata(root, '456')
    selected = file(root, '456', 'models/material/shared.mtl', b'declared custom material')
    file(root, '789', 'models/material/shared.mtl', b'different global material')
    match = WorkshopResources(source).resolve('shared.mtl', 'material', allow_global=False)
    assert match['providers'] == [str(selected)]
    assert match['lookupPolicy'] == 'declared_only'
    assert match['providerSelection'] == 'declared_requiredMods'
    dependencies, fingerprints = receipt(match)
    assert verify_workshop_dependencies(source, dependencies, fingerprints)
    file(root, '999', 'models/material/shared.mtl', b'yet another unrelated material')
    assert verify_workshop_dependencies(source, dependencies, fingerprints)
    meta.write_text(meta.read_text() + '\n-- changed declared identity proof')
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)


def test_prefer_owner_declared_only_selects_exact_owner_and_rechecks_missing_owner(collection):
    root, source = collection
    declare(source)
    metadata(root, '456')
    local = file(root, source.name, 'models/material/shared.mtl', b'owner material')
    file(root, '456', 'models/material/shared.mtl', b'declared different material')
    file(root, '789', 'models/material/shared.mtl', b'global different material')
    match = WorkshopResources(source).resolve('shared.mtl', 'material', prefer_local=True, allow_global=False)
    assert match['providers'] == [str(local)]
    assert match['lookupPolicy'] == 'prefer_local_declared_only'
    assert verify_workshop_dependencies(source, *receipt(match))
    local.unlink()
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_declared_only_rejects_nonboolean_policy(collection):
    _,source = collection
    with pytest.raises(ValueError, match='allow_global must be a boolean'):
        WorkshopResources(source).resolve('shared.mtl','material',allow_global=1)


@pytest.mark.parametrize('kind,reference', [
    ('material', '../shared.mtl'), ('model', '/asset/model.mdl'),
    ('audio', 'C:/horn.wav'), ('sound_set', 'x/../gw_neu'),
    ('script', 'helper.lua'), ('material', 'plugin.dll'),
    ('mesh_blob', 'mesh.blob'), ('model', 'looks_like_texture.dds'),
])
def test_generalized_lookup_rejects_traversal_wrong_suffix_and_executable_categories(collection, kind, reference):
    _, source = collection
    with pytest.raises(ValueError):
        WorkshopResources(source).resolve(reference, kind)


def test_no_basename_guessing_for_descriptors(collection):
    root, source = collection
    file(root, '456', 'models/material/elsewhere/shared.mtl')
    assert WorkshopResources(source).resolve('vehicle/shared.mtl', 'material') is None


def test_new_conflicting_provider_and_missing_provider_invalidate_receipt(collection):
    root, source = collection
    provider = file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    conflicting = file(root, '789', 'models/material/shared.mtl', b'other')
    with pytest.raises(ValueError, match='Ambiguous'):
        verify_workshop_dependencies(source, *receipt(match))
    conflicting.unlink()
    provider.unlink()
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_linked_descriptor_and_declared_metadata_are_blocked_before_read(collection, monkeypatch):
    root, source = collection
    declare(source)
    meta = metadata(root, '456')
    provider = file(root, '456', 'models/material/shared.mtl')
    real_linked = resources.linked
    monkeypatch.setattr(resources, 'linked', lambda p: p == meta or real_linked(p))
    with pytest.raises(ValueError, match='Linked'):
        WorkshopResources(source).resolve('shared.mtl', 'material')
    monkeypatch.setattr(resources, 'linked', lambda p: p == provider or real_linked(p))
    with pytest.raises(ValueError, match='Linked'):
        WorkshopResources(source).resolve('shared.mtl', 'material')


def test_generalized_receipt_rejects_wrong_kind_and_forged_metadata_paths(collection):
    root, source = collection
    file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    dependencies, fingerprints = receipt(match)
    dependencies[0]['kind'] = 'script'
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)
    dependencies, fingerprints = receipt(match)
    arbitrary = str(root/'456/res/scripts/execute.lua')
    digest = 'f'*64
    dependencies[0]['declarationFingerprints'] = {arbitrary:digest}
    fingerprints[arbitrary] = digest
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)


def test_owner_local_resource_overrides_unrelated_conflicting_packages(collection):
    root, source = collection
    own = file(root, '123', 'models/material/shared.mtl', b'owner material')
    file(root, '456', 'models/material/shared.mtl', b'other material')
    lookup = WorkshopResources(source)
    with pytest.raises(ValueError, match='Ambiguous'):
        lookup.resolve('shared.mtl', 'material')
    match = lookup.resolve('shared.mtl', 'material', prefer_local=True)
    assert match['providers'] == [str(own)]
    assert match['providerSelection'] == 'owner_exact_resource'
    assert match['lookupPolicy'] == 'prefer_local'
    assert verify_workshop_dependencies(source, *receipt(match))
    file(root, '789', 'models/material/shared.mtl', b'new unrelated conflict')
    assert verify_workshop_dependencies(source, *receipt(match))


def test_transitive_context_uses_provider_declarations_and_invalidates_owner_metadata(collection):
    root, source = collection
    owner = root / '456'
    owner.mkdir()
    declare(owner, '789')
    metadata(root, '789')
    selected = file(root, '789', 'models/material/shared.mtl', b'intended material')
    file(root, '999', 'models/material/shared.mtl', b'other material')
    match = WorkshopResources(owner).resolve('shared.mtl', 'material', prefer_local=True)
    assert match['providers'] == [str(selected)]
    assert match['lookupSource'] == str(owner)
    assert match['originFingerprints'] == {
        str(owner/'mod.lua'): hashlib.sha256((owner/'mod.lua').read_bytes()).hexdigest()}
    assert verify_workshop_dependencies(source, *receipt(match))
    # Source123 is unrelated to the selected descriptor's lookup scope.
    metadata(root, '123', 'unrelated-root')
    assert verify_workshop_dependencies(source, *receipt(match))
    (owner/'mod.lua').write_text((owner/'mod.lua').read_text() + '\n-- metadata edited')
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_new_owner_resource_invalidates_prior_context_fallback(collection):
    root, source = collection
    file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material', prefer_local=True)
    assert verify_workshop_dependencies(source, *receipt(match))
    file(root, '123', 'models/material/shared.mtl')
    assert not verify_workshop_dependencies(source, *receipt(match))


@pytest.mark.parametrize('context', ['ordinary-package', '456/nested', '../elsewhere/456'])
def test_receipt_lookup_context_must_be_a_numeric_sibling(collection, context, monkeypatch):
    root, source = collection
    file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    dependencies, fingerprints = receipt(match)
    dependencies[0]['lookupSource'] = str(root / context)
    monkeypatch.setattr(resources, 'WorkshopResources', lambda *_: pytest.fail('Invalid context triggered a lookup'))
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)


def test_receipt_cannot_drop_or_forge_owner_metadata_evidence(collection):
    root, source = collection
    metadata(root, '123')
    file(root, '456', 'models/material/shared.mtl')
    match = WorkshopResources(source).resolve('shared.mtl', 'material')
    dependencies, fingerprints = receipt(match)
    del dependencies[0]['originFingerprints']
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)
    dependencies, fingerprints = receipt(match)
    dependencies[0]['originFingerprints'] = {}
    fingerprints.pop(str(source/'mod.lua'))
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)


@pytest.mark.parametrize('kind,reference,relative', [
    ('localization', 'strings.lua', 'strings.lua'),
    ('helper', 'bbs2util', 'res/scripts/bbs2util.lua'),
    ('helper', 'nested/soundeffectsutil2.lua', 'res/scripts/nested/soundeffectsutil2.lua'),
])
def test_owner_evidence_never_falls_back_to_another_package(collection, kind, reference, relative):
    root, source = collection
    other = root / '456' / relative
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(b'other owner definition')
    assert WorkshopResources(source).resolve(reference, kind) is None
    own = source / relative
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_bytes(b'authored owner definition')
    match = WorkshopResources(source).resolve(reference, kind)
    assert match['data'] == b'authored owner definition'
    assert match['providers'] == [str(own)]
    assert match['lookupPolicy'] == 'prefer_local'
    assert verify_workshop_dependencies(source, *receipt(match))
    own.write_bytes(b'changed owner definition')
    assert not verify_workshop_dependencies(source, *receipt(match))


def test_localization_requires_exact_owner_strings_and_linked_evidence_is_blocked(collection, monkeypatch):
    root, source = collection
    with pytest.raises(ValueError, match='exact owner strings.lua'):
        WorkshopResources(source).resolve('elsewhere/strings.lua', 'localization')
    own = source / 'strings.lua'
    own.write_bytes(b'authored translations')
    real_linked = resources.linked
    monkeypatch.setattr(resources, 'linked', lambda p: p == own or real_linked(p))
    with pytest.raises(ValueError, match='Linked'):
        WorkshopResources(source).resolve('strings.lua', 'localization')


def test_legacy_texture_receipts_remain_valid_when_source_has_metadata(collection):
    from trf3_mod_converter.workshop_resources import WorkshopTextures
    root, source = collection
    metadata(root, '123')
    file(root, '456', 'textures/shared.dds')
    match = WorkshopTextures(source).resolve('shared.dds')
    dependencies = [{k: value for k, value in match.items() if k != 'data'}]
    fingerprints = {p: match['sha256'] for p in match['providers']}
    assert verify_workshop_dependencies(source, dependencies, fingerprints)

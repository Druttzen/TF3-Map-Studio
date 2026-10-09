import hashlib
import pytest

from trf3_mod_converter.workshop_resources import WorkshopTextures, workshop_fingerprints, verify_workshop_dependencies
import trf3_mod_converter.workshop_resources as resources


@pytest.fixture
def collection(tmp_path):
    root = tmp_path / '1066780'
    source = root / '123'
    source.mkdir(parents=True)
    return root, source


def texture(root, mod, reference, data=b'authored texture'):
    provider = root / mod / 'res/textures' / reference
    provider.parent.mkdir(parents=True, exist_ok=True)
    provider.write_bytes(data)
    return provider


def test_exact_shared_texture_records_all_identical_providers_and_fresh_fingerprints(collection):
    root, source = collection
    a = texture(root, '456', 'models/paint.dds')
    b = texture(root, '789', 'models/paint.dds')
    lookup = WorkshopTextures(source)
    match = lookup.resolve('models/paint.dds')
    digest = hashlib.sha256(b'authored texture').hexdigest()
    assert match == {'data':b'authored texture', 'providers':[str(a),str(b)], 'sha256':digest, 'sourceReference':'models/paint.dds'}
    assert lookup.fingerprints(match['providers']) == {str(a):digest,str(b):digest}
    # Cached dependency bytes stay stable, while receipts detect later edits.
    b.write_bytes(b'changed texture')
    match['providers'].clear()
    assert lookup.resolve('models/paint.dds')['providers'] == [str(a),str(b)]
    assert lookup.resolve('models/paint.dds')['data'] == b'authored texture'
    assert lookup.fingerprints([b])[str(b)] != digest


def test_shared_lookup_rejects_exact_path_conflicts(collection):
    root, source = collection
    texture(root,'456','paint.tga',b'a')
    texture(root,'789','paint.tga',b'b')
    with pytest.raises(ValueError, match='Ambiguous.*different bytes'):
        WorkshopTextures(source).resolve('paint.tga')


def test_lookup_does_not_guess_basename_or_search_nonnumeric_packages(collection):
    root, source = collection
    texture(root,'456','other/paint.dds')
    texture(root,'ordinary_folder','models/paint.dds')
    assert WorkshopTextures(source).resolve('models/paint.dds') is None


def test_collection_cache_can_supply_initial_source_texture_to_another_package(collection):
    root, source = collection
    provider = texture(root, '123', 'models/paint.dds')
    assert WorkshopTextures(source).resolve('models/paint.dds')['providers'] == [str(provider)]


def test_empty_dependency_receipts_do_not_require_a_workshop_source(tmp_path):
    assert workshop_fingerprints({}, tmp_path/'ordinary-mod') == {}


@pytest.mark.parametrize('reference',['../paint.dds','models/../paint.dds','/paint.dds','C:/paint.dds','models\\paint.dds','paint.lua'])
def test_unsafe_or_nonbinary_references_are_blocked(collection,reference):
    _,source=collection
    with pytest.raises(ValueError):
        WorkshopTextures(source).resolve(reference)


def test_fingerprints_reject_receipt_paths_outside_collection_or_texture_directory(collection,tmp_path):
    root,source=collection
    outside=texture(tmp_path/'elsewhere'/'1066780','456','paint.dds')
    with pytest.raises(ValueError,match='outside'):
        workshop_fingerprints([outside],root)
    script=root/'456/res/scripts/script.dds'
    script.parent.mkdir(parents=True)
    script.write_bytes(b'not a texture resource')
    with pytest.raises(ValueError,match='Invalid'):
        workshop_fingerprints([script],root)
    with pytest.raises(ValueError,match='absolute'):
        workshop_fingerprints(['paint.dds'],root)


def test_linked_texture_and_linked_parent_are_rejected_before_read(collection,tmp_path):
    root,source=collection
    outside=tmp_path/'external.dds'
    outside.write_bytes(b'external')
    provider=root/'456/res/textures/paint.dds'
    provider.parent.mkdir(parents=True)
    try:
        provider.symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation is unavailable on this Windows account')
    with pytest.raises(ValueError,match='Linked'):
        WorkshopTextures(source).resolve('paint.dds')
    with pytest.raises(ValueError,match='Linked'):
        workshop_fingerprints([provider],root)
    parent=root/'789/res/textures'
    parent.parent.mkdir(parents=True)
    parent.symlink_to(provider.parent, target_is_directory=True)
    with pytest.raises(ValueError,match='Linked'):
        workshop_fingerprints([parent/'paint.dds'],root)


def test_link_detection_precedes_provider_read_even_without_symlink_permission(collection, monkeypatch):
    root, source = collection
    provider = texture(root, '456', 'models/paint.dds')
    real_linked = resources.linked
    monkeypatch.setattr(resources, 'linked', lambda path: path == provider.parent or real_linked(path))
    monkeypatch.setattr(resources, '_read', lambda path: pytest.fail('Linked provider was read'))
    with pytest.raises(ValueError, match='Linked'):
        WorkshopTextures(source).resolve('models/paint.dds')
    with pytest.raises(ValueError, match='Linked'):
        workshop_fingerprints([provider], root)


def test_source_must_be_numeric_and_inside_the_collection(tmp_path):
    source=tmp_path/'123'
    source.mkdir()
    with pytest.raises(ValueError,match='1066780'):
        WorkshopTextures(source)


def dependency_receipt(source, reference):
    match = WorkshopTextures(source).resolve(reference)
    row = {key: match[key] for key in ('sourceReference', 'providers', 'sha256')}
    fingerprints = {path: match['sha256'] for path in match['providers']}
    return [row], fingerprints


def test_verification_rejects_new_provider_ambiguity_despite_unchanged_cached_bytes(collection):
    root, source = collection
    texture(root, '456', 'models/paint.dds', b'original')
    cached = WorkshopTextures(source)
    cached_match = cached.resolve('models/paint.dds')
    dependencies, fingerprints = dependency_receipt(source, 'models/paint.dds')
    assert verify_workshop_dependencies(source, dependencies, fingerprints)
    texture(root, '789', 'models/paint.dds', b'conflicting')
    assert cached.resolve('models/paint.dds') == cached_match
    assert workshop_fingerprints(fingerprints, root) == fingerprints
    with pytest.raises(ValueError, match='Ambiguous'):
        verify_workshop_dependencies(source, dependencies, fingerprints)


def test_verification_rejects_new_identical_provider_set_and_updated_provider_bytes(collection):
    root, source = collection
    provider = texture(root, '456', 'models/paint.dds', b'original')
    dependencies, fingerprints = dependency_receipt(source, 'models/paint.dds')
    assert verify_workshop_dependencies(source, dependencies, fingerprints)
    extra = texture(root, '789', 'models/paint.dds', b'original')
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)
    extra.unlink()
    provider.write_bytes(b'updated')
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)


def test_empty_dependency_verification_accepts_non_workshop_sources(tmp_path):
    assert verify_workshop_dependencies(tmp_path/'ordinary', [], {})


@pytest.mark.parametrize('dependencies,fingerprints', [
    ({}, {}), ([], []), ([], {'wrong': 'digest'}), ([{}], {}),
    ([None], {'wrong': 'digest'}), ([{'sourceReference': 42}], {'wrong': 'digest'}),
])
def test_verification_rejects_malformed_shapes_without_reading(collection, dependencies, fingerprints, monkeypatch):
    _, source = collection
    monkeypatch.setattr(resources, 'WorkshopTextures', lambda *_: pytest.fail('Malformed receipt triggered a lookup'))
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)


def test_verification_requires_all_expected_provider_fingerprints_and_complete_rows(collection):
    root, source = collection
    first = texture(root, '456', 'models/paint.dds')
    second = texture(root, '789', 'models/paint.dds')
    dependencies, fingerprints = dependency_receipt(source, 'models/paint.dds')
    assert verify_workshop_dependencies(source, dependencies, fingerprints)
    incomplete = [{**dependencies[0], 'providers': [str(first)]}]
    assert not verify_workshop_dependencies(source, incomplete, fingerprints)
    assert not verify_workshop_dependencies(source, dependencies, {str(first): fingerprints[str(first)]})
    incomplete[0]['providers'] = [str(first), str(first)]
    assert not verify_workshop_dependencies(source, incomplete, fingerprints)
    invalid = [{**dependencies[0], 'sourceReference': '../paint.dds'}]
    assert not verify_workshop_dependencies(source, invalid, fingerprints)
    second.unlink()
    assert not verify_workshop_dependencies(source, dependencies, fingerprints)

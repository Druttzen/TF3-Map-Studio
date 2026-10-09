from dataclasses import dataclass

import pytest

from trf3_mod_converter.dependency_context import DependencyContext
from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.resource_profiles import TranslatedConcat, resolve_translation_concatenations
from trf3_mod_converter.tf2_vehicle_port import emit
from trf3_mod_converter.workshop_resources import WorkshopResources, verify_workshop_dependencies


@pytest.fixture
def context(tmp_path):
    collection = tmp_path/'1066780'
    source = collection/'123'
    source.mkdir(parents=True)
    translations = {'en': {'label':'Root author label'}, 'sv': {'label':'Root author Swedish label'}}
    audit, fingerprints = {}, {}
    return DependencyContext(source, WorkshopResources(source), translations, audit, fingerprints)


def owner(context, name, locales=None, required=None):
    package = context.source.parent/name
    package.mkdir(exist_ok=True)
    info = {'name': name, 'modid':'package_'+name, 'steamId':int(name), 'minorVersion':0}
    if required is not None:
        info['requiredMods'] = [{'steamId':int(required), 'modId':'package_'+required}]
    (package/'mod.lua').write_text(emit({'info':info}))
    if locales is not None:
        (package/'strings.lua').write_text(emit(locales))
    return package


def material(package, data=b'authored material'):
    path = package/'res/models/material/shared.mtl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_recursive_lookup_keeps_provider_required_mod_scope_and_records_fresh_evidence(context):
    author = owner(context, '456', required='789')
    intended = owner(context, '789')
    alternative = owner(context, '999')
    selected = material(intended)
    material(alternative, b'conflicting unrelated material')
    context.owners = [author]
    matches = context.lookup('shared.mtl', 'material')
    assert context.provider_owners(matches) == [intended]
    assert matches[0]['providers'] == [str(selected)]
    context.record(matches, 'target::/models/material/shared.mtl', 'port_exact_workshop_resource_dependency')
    rows = context.audit['workshopDependencies']
    assert verify_workshop_dependencies(context.source, rows, context.fingerprints)
    (author/'mod.lua').write_text((author/'mod.lua').read_text() + '\n-- changed dependency metadata')
    assert not verify_workshop_dependencies(context.source, rows, context.fingerprints)


def test_declared_only_author_context_ignores_global_conflicts_then_keeps_owner_intent(context):
    author = owner(context, '456', required='789')
    declared = owner(context, '789')
    global_provider = owner(context, '999')
    selected = material(declared, b'declared custom material')
    material(global_provider, b'global unrelated material')
    matches = context.lookup('shared.mtl', 'material', owners=[author], allow_global=False)
    assert matches[0]['providers'] == [str(selected)]
    assert matches[0]['lookupPolicy'] == 'prefer_local_declared_only'
    context.record(matches, 'target::/models/material/shared.mtl', 'port_declared_author_resource')
    assert verify_workshop_dependencies(context.source, context.audit['workshopDependencies'], context.fingerprints)
    local = material(author, b'owner overrides declared material')
    fresh = DependencyContext(context.source, WorkshopResources(context.source), {}, {}, {})
    owner_matches = fresh.lookup('shared.mtl', 'material', owners=[author], allow_global=False)
    assert owner_matches[0]['providers'] == [str(local)]
    assert not verify_workshop_dependencies(context.source, context.audit['workshopDependencies'], context.fingerprints)


def test_declared_only_root_context_returns_no_unrelated_global_match(context):
    material(owner(context, '456'), b'global material')
    material(owner(context, '789'), b'different global material')
    assert context.lookup('shared.mtl', 'material', allow_global=False) == []


def test_same_reference_with_conflicting_author_contents_is_blocked(context):
    first = owner(context, '456')
    second = owner(context, '789')
    material(first, b'first authored material')
    material(second, b'second authored material')
    with pytest.raises(ValueError, match='Conflicting resource contents in dependency author contexts'):
        context.lookup('shared.mtl', 'material', owners=[first, second])


@dataclass(frozen=True)
class CallbackMetadata:
    title: str


def test_provider_localization_is_namespaced_and_preserves_language_variants(context):
    author = owner(context, '456', {
        'en': {'label':'Provider label'}, 'sv': {'label':'Provider Swedish label'}})
    data = {
        'description': {'name':TranslatedString('label')},
        'callback': CallbackMetadata(TranslatedString('label')),
        'joined': TranslatedConcat(((True,'label'),(False,'!')))}
    result = context.localize(data, [author])
    localized = result['description']['name']
    assert isinstance(localized, TranslatedString) and localized != 'label'
    assert result['callback'].title == localized
    assert result['joined'].parts == ((True, str(localized)), (False,'!'))
    assert context.translations['en'][localized] == 'Provider label'
    assert context.translations['sv'][localized] == 'Provider Swedish label'
    assert context.translations['en']['label'] == 'Root author label'
    joined = resolve_translation_concatenations(result, context.translations)['joined']
    assert context.translations['en'][joined] == 'Provider label!'
    assert context.translations['sv'][joined] == 'Provider Swedish label!'
    assert context.archive['_dependencies/456/strings.lua'] == (author/'strings.lua').read_bytes()
    rows = context.audit['workshopDependencies']
    assert rows[0]['kind'] == 'localization'
    assert 'targetReference' not in rows[0]
    assert verify_workshop_dependencies(context.source, rows, context.fingerprints)
    (author/'strings.lua').write_text(emit({'en': {'label':'Changed provider label'}}))
    assert not verify_workshop_dependencies(context.source, rows, context.fingerprints)


def test_localized_descriptor_needs_its_own_verified_strings_file(context):
    author = owner(context, '456')
    owner(context, '789', {'en': {'label':'Unrelated sibling label'}})
    with pytest.raises(ValueError, match='no verifiable author strings.lua'):
        context.localize({'name':TranslatedString('label')}, [author])


def test_identical_descriptors_with_conflicting_author_locales_remain_blocked(context):
    first = owner(context, '456', {'en': {'label':'First label'}})
    second = owner(context, '789', {'en': {'label':'Second label'}})
    with pytest.raises(ValueError, match='different author localization'):
        context.localize({'name':TranslatedString('label')}, [first, second])


def test_helper_provenance_is_owner_only_and_detects_change(context):
    author = owner(context, '456')
    unrelated = owner(context, '789')
    for package, content in ((author,b'known helper'),(unrelated,b'other helper')):
        path = package/'res/scripts/bbs2util.lua'
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    matches = context.lookup('bbs2util', 'helper', owners=[author])
    assert matches[0]['data'] == b'known helper'
    context.record(matches, None, 'interpret_exact_legacy_sound_helper',
                   original_file='_port_originals/_dependencies/456/scripts/bbs2util.lua')
    rows = context.audit['workshopDependencies']
    assert verify_workshop_dependencies(context.source, rows, context.fingerprints)
    (author/'res/scripts/bbs2util.lua').write_bytes(b'edited helper')
    assert not verify_workshop_dependencies(context.source, rows, context.fingerprints)


def test_record_refuses_to_combine_different_bytes_of_the_same_provider(context):
    author = owner(context, '456')
    path = material(author)
    matches = context.lookup('shared.mtl', 'material', owners=[author])
    context.record(matches, 'target::/material.mtl', 'verified_owner_resource')
    path.write_bytes(b'changed during adaptation')
    fresh = WorkshopResources(author).resolve('shared.mtl', 'material', prefer_local=True)
    with pytest.raises(ValueError, match='changed during adaptation'):
        context.record([fresh], 'target::/material.mtl', 'verified_owner_resource')


def test_empty_provider_locale_keeps_literal_key_fallback(context):
    author = owner(context, '456', {'en': {'label':'Provider label'}, 'sv': {}})
    result = context.localize({'name':TranslatedString('label')}, [author])
    key = result['name']
    assert context.translations['en'][key] == 'Provider label'
    assert context.translations['sv'][key] == 'label'
    assert verify_workshop_dependencies(context.source, context.audit['workshopDependencies'], context.fingerprints)


def test_unattached_numeric_provider_translation_is_archived_and_audited(context):
    author = owner(context, '456', {'en': {'label':'Provider label', 1:'Unattached author text'}})
    result = context.localize({'name':TranslatedString('label')}, [author])
    assert context.translations['en'][result['name']] == 'Provider label'
    assert 'Unattached author text' not in context.translations['en'].values()
    row = context.audit['translationMigrations'][0]
    assert row['policy'] == 'archive_unattached_numeric_translation_entry'
    assert row['sourceKey'] == 1 and row['sourceValue'] == 'Unattached author text'
    assert row['originalFile'] == '_port_originals/_dependencies/456/strings.lua'
    assert context.archive['_dependencies/456/strings.lua'] == (author/'strings.lua').read_bytes()

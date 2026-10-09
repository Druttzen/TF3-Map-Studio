"""Exact dependencies from sibling TF2 Workshop packages.

This lookup never searches by basename or reads the installed game inventory.
Every provider uses the requested resource path. Conflicting bytes remain a
blocker unless literal requiredMods Steam IDs identify the intended providers.
Descriptors still require their category adapter: this module never runs Lua,
converts a schema, copies files, or establishes equivalence with game assets.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import zipfile

from .base_resources import ROOTS, TF2Inventory, find_tf2_game, normalize_reference, source_resource
from .filesystem import linked
from .lua_metadata import load_lua_table


TEXTURE_SUFFIXES = {'.dds', '.tga', '.hdr'}
RESOURCE_SUFFIXES = {
    'texture': TEXTURE_SUFFIXES, 'material': {'.mtl'}, 'model': {'.mdl'},
    'mesh': {'.msh'}, 'mesh_blob': {'.msh.blob'}, 'animation': {'.ani'},
    'audio': {'.wav', '.ogg'}, 'sound_set': {'.lua'}, 'ground_texture': {'.lua'},
    'terrain_material': {'.lua'}, 'grass': {'.lua'}, 'multiple_unit': {'.lua'},
}


def _resource(kind: str, reference: str) -> str:
    if kind == 'localization':
        if normalize_reference(reference) != 'strings.lua':
            raise ValueError('Workshop localization must use the exact owner strings.lua')
        return 'strings.lua'
    if kind == 'helper':
        reference = normalize_reference(reference)
        return 'scripts/' + reference + ('' if reference.endswith('.lua') else '.lua')
    if kind not in RESOURCE_SUFFIXES:
        raise ValueError(f'Unsupported Workshop dependency kind: {kind}')
    reference = normalize_reference(reference)
    resource = (ROOTS['mesh'] + '/' + reference if kind == 'mesh_blob'
                else source_resource(kind, reference))
    if not any(resource.lower().endswith(suffix) for suffix in RESOURCE_SUFFIXES[kind]):
        raise ValueError(f'Invalid Workshop {kind} resource reference: {reference}')
    return resource


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(Path(path).expanduser()))


def _unlinked(path: Path) -> None:
    if any(linked(part) for part in (path, *path.parents)):
        raise ValueError(f'Linked Workshop dependency is not supported: {path}')


def _collection(path: str | Path) -> Path:
    root = _absolute(path)
    _unlinked(root)
    if root.name != '1066780' or not root.is_dir():
        raise ValueError('Expected a TF2 Workshop collection folder named 1066780')
    return root


def _provider(path: str | Path, root: Path | None = None) -> Path:
    supplied = Path(path)
    if not supplied.is_absolute() or '..' in supplied.parts:
        raise ValueError('Workshop provider filenames must be absolute')
    provider = _absolute(supplied)
    _unlinked(provider)
    if root is None:
        root = next((parent for parent in provider.parents if parent.name == '1066780'), None)
        if root is None:
            raise ValueError('Workshop provider is outside a TF2 Workshop collection')
        root = _collection(root)
    if not provider.is_relative_to(root):
        raise ValueError(f'Workshop provider is outside the selected Workshop collection: {provider}')
    parts = provider.relative_to(root).parts
    valid = False
    if parts and re.fullmatch(r'[0-9]+', parts[0]):
        if len(parts) == 2 and parts[1] in ('mod.lua', 'strings.lua'):
            valid = True  # Identity/localization evidence owned by a package.
        elif len(parts) >= 4 and parts[1] == 'res':
            resource = PurePosixPath(*parts[2:]).as_posix()
            if resource.startswith('scripts/') and resource.endswith('.lua'):
                valid = True  # Audited owner helper evidence; never exported as executable source.
            for kind, suffixes in RESOURCE_SUFFIXES.items():
                resource_root = ROOTS['mesh' if kind == 'mesh_blob' else kind]
                if (resource.startswith(resource_root + '/')
                        and any(resource.lower().endswith(suffix) for suffix in suffixes)):
                    valid = True
                    break
    if not valid:
        raise ValueError(f'Invalid Workshop provider path: {provider}')
    if not provider.is_file():
        raise ValueError(f'Workshop provider is missing: {provider}')
    return provider


def _read(provider: Path) -> bytes:
    _unlinked(provider)
    before = provider.stat()
    data = provider.read_bytes()
    _unlinked(provider)
    after = provider.stat()
    if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError(f'Workshop provider changed while being read: {provider}')
    return data


def workshop_fingerprints(paths, collection_root: str | Path | None = None) -> dict[str, str]:
    """Re-read untrusted receipt paths within the selected Workshop collection."""
    paths = tuple(paths)
    if not paths:
        return {}
    root = _collection(collection_root) if collection_root is not None else None
    result = {}
    for path in paths:
        provider = _provider(path, root)
        result[str(provider)] = hashlib.sha256(_read(provider)).hexdigest()
    return result


def verify_workshop_dependencies(source: Path, dependencies: list,
                                 expected_fingerprints: dict) -> bool:
    """Verify fresh exact-path provider sets as well as their current bytes.

    A cached match cannot see a newly added conflicting provider. Rebuilding
    the lookup here makes both commit checks and resumed receipts cover that
    change without copying cached data or trusting receipt paths outside the
    source's Workshop collection.
    """
    if not isinstance(dependencies, list) or not isinstance(expected_fingerprints, dict):
        return False
    if not dependencies or not expected_fingerprints:
        return not dependencies and not expected_fingerprints
    def digest_valid(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None
    if any(not isinstance(path, str) or not Path(path).is_absolute()
           or '..' in Path(path).parts or not digest_valid(digest)
           for path, digest in expected_fingerprints.items()):
        return False
    providers = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            return False
        reference = dependency.get('sourceReference')
        paths = dependency.get('providers')
        digest = dependency.get('sha256')
        if (not isinstance(reference, str) or not reference
                or not isinstance(paths, list) or not paths or not digest_valid(digest)
                or any(not isinstance(path, str) or not Path(path).is_absolute()
                       or '..' in Path(path).parts for path in paths)
                or len(set(paths)) != len(paths)
                or any(expected_fingerprints.get(path) != digest for path in paths)):
            return False
        kind = dependency.get('kind', 'texture')
        try:
            resource = _resource(kind, reference)
        except (TypeError, ValueError):
            return False
        if 'sourceResource' in dependency and dependency['sourceResource'] != resource:
            return False
        for evidence_key in ('declarationFingerprints', 'originFingerprints'):
            declarations = dependency.get(evidence_key, {})
            if not isinstance(declarations, dict):
                return False
            for path, declared_digest in declarations.items():
                if (not isinstance(path, str) or not Path(path).is_absolute()
                        or '..' in Path(path).parts or Path(path).name != 'mod.lua'
                        or not digest_valid(declared_digest)
                        or expected_fingerprints.get(path) != declared_digest):
                    return False
            providers.update(declarations)
        lookup_source = dependency.get('lookupSource')
        lookup_policy = dependency.get('lookupPolicy', 'declared_or_global')
        if lookup_policy not in ('prefer_local', 'declared_or_global',
                                 'declared_only', 'prefer_local_declared_only'):
            return False
        if lookup_source is not None:
            if (not isinstance(lookup_source, str) or not Path(lookup_source).is_absolute()
                    or '..' in Path(lookup_source).parts or 'originFingerprints' not in dependency):
                return False
            original = _absolute(source)
            context = _absolute(lookup_source)
            if (context.parent != original.parent or re.fullmatch(r'[0-9]+', context.name) is None):
                return False
        providers.update(paths)
    if providers != set(expected_fingerprints):
        return False
    lookups = {}
    for dependency in dependencies:
        context = _absolute(dependency.get('lookupSource', source))
        if context not in lookups:
            lookups[context] = WorkshopResources(context)
        lookup = lookups[context]
        policy = dependency.get('lookupPolicy', 'declared_or_global')
        match = lookup.resolve(dependency['sourceReference'], dependency.get('kind', 'texture'),
                               prefer_local=policy in ('prefer_local', 'prefer_local_declared_only'),
                               allow_global=policy not in ('declared_only', 'prefer_local_declared_only'))
        if (match is None or match['sha256'] != dependency['sha256']
                or match['providers'] != dependency['providers']
                or match['declarationFingerprints'] != dependency.get('declarationFingerprints', {})
                or ('originFingerprints' in dependency
                    and match['originFingerprints'] != dependency['originFingerprints'])
                or ('lookupSource' in dependency and match['lookupSource'] != dependency['lookupSource'])
                or ('lookupPolicy' in dependency and match['lookupPolicy'] != dependency['lookupPolicy'])
                or ('providerSelection' in dependency
                    and match['providerSelection'] != dependency['providerSelection'])):
            return False
    return workshop_fingerprints(expected_fingerprints, _absolute(source).parent) == expected_fingerprints


def verify_workshop_absences(source: Path, rows: list) -> bool:
    """Verify that exact author/declared inputs remain absent before TF2 fallback.

    Metadata hashes stay inside these rows because no provider was selected.
    This deliberately ignores unrelated global providers: only the recorded
    owner and its declared dependency packages may invalidate the fallback.
    """
    if not isinstance(rows, list):
        return False
    if not rows:
        return True
    try:
        original = _absolute(source)
        _unlinked(original)
        if re.fullmatch('[0-9]+', original.name) is None:
            return False
        collection = _collection(original.parent)
        lookups = {}
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                    'kind', 'sourceReference', 'lookupSource', 'lookupPolicy', 'originFingerprints'}:
                return False
            kind, reference = row['kind'], row['sourceReference']
            context_path, policy = row['lookupSource'], row['lookupPolicy']
            if (not isinstance(context_path, str) or not Path(context_path).is_absolute()
                    or '..' in Path(context_path).parts
                    or policy not in ('declared_only', 'prefer_local_declared_only')):
                return False
            context = _absolute(context_path)
            if (context.parent != collection or re.fullmatch('[0-9]+', context.name) is None
                    or str(context) != context_path):
                return False
            _resource(kind, reference)
            if normalize_reference(reference) != reference:
                return False
            key = (context_path, kind, reference, policy)
            if key in seen:
                return False
            seen.add(key)
            origins = row['originFingerprints']
            if (not isinstance(origins, dict) or any(path != str(context/'mod.lua')
                    or not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None
                    for path, digest in origins.items())):
                return False
            if context not in lookups:
                lookups[context] = WorkshopResources(context)
            fresh = lookups[context].absence(reference, kind,
                prefer_local=policy == 'prefer_local_declared_only')
            if fresh != row:
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return False


def verify_native_stock_selections(source: Path, tf3_game: Path | None,
                                   workshop_rows: list, *, tf2_game: Path | None = None) -> bool:
    """Revalidate TF2 stock identity used to choose a native resource mapping.

    Workshop provider hashes and declared scope are verified separately. This
    check proves their bytes still match the exact installed TF2 input that
    allowed the native mapping. Receipt paths never select a TF2 installation;
    only a port's explicit input may supply an override.
    """
    if not isinstance(workshop_rows, list) or any(not isinstance(row, dict) for row in workshop_rows):
        return False
    selections = [row for row in workshop_rows
                  if row.get('policy') == 'verify_stock_provider_selection_for_native_mapping']
    if not selections:
        return True
    try:
        if tf2_game is None:
            if tf3_game is None:
                return False
            tf2_game = find_tf2_game(Path(source), Path(tf3_game))
        if tf2_game is None:
            return False
        game = _absolute(tf2_game)
        _unlinked(game)
        inventory = TF2Inventory(game)
        for row in selections:
            kind, reference, digest = row.get('kind', 'texture'), row.get('sourceReference'), row.get('sha256')
            if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
                return False
            resource = _resource(kind, reference)
            if kind in ('helper', 'localization') or normalize_reference(reference) != reference:
                return False
            if 'sourceResource' in row and row['sourceResource'] != resource:
                return False
            if resource not in inventory.files:
                return False
            container, _ = inventory.files[resource]
            _unlinked(container)
            before = container.stat()
            data = inventory.read(resource)
            _unlinked(container)
            after = container.stat()
            if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or hashlib.sha256(data).hexdigest() != digest):
                return False
        return True
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, zipfile.BadZipFile):
        return False


def verify_base_resource_identities(source: Path, tf3_game: Path | None,
                                    replacements: list, *, tf2_game: Path | None = None) -> bool:
    """Recheck TF2 byte identity that selected a native base-game resource.

    Missing local inputs use the SHA recorded by byte-identical mappings.
    Bundled inputs also require their exact source file to remain identical to
    current TF2 stock, including descriptor mappings chosen by a verified role.
    """
    if not isinstance(replacements, list) or any(not isinstance(row, dict) for row in replacements):
        return False
    try:
        selections = []
        for row in replacements:
            origin, method = row.get('sourceOrigin'), row.get('matchMethod')
            if origin != 'bundled_tf2_base' and not (origin == 'tf2_base' and method == 'byte_identical'):
                continue
            kind, reference = row.get('kind'), row.get('sourceReference')
            resource = _resource(kind, reference)
            if (kind in ('helper', 'localization') or normalize_reference(reference) != reference
                    or row.get('sourceResource') != 'res/'+resource
                    or method not in ('byte_identical', 'verified_role_mapping')):
                return False
            digest = row.get('sha256')
            if origin == 'bundled_tf2_base':
                bundled = _absolute(source)/'res'/resource
                _unlinked(bundled)
                if not bundled.is_file():
                    return False
                source_digest = hashlib.sha256(_read(bundled)).hexdigest()
                if method == 'byte_identical' and digest != source_digest:
                    return False
                digest = source_digest
            selections.append({'kind':kind, 'sourceReference':reference,
                'sourceResource':resource, 'sha256':digest,
                'policy':'verify_stock_provider_selection_for_native_mapping'})
        return verify_native_stock_selections(source, tf3_game, selections, tf2_game=tf2_game)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return False


def _steam_id(value) -> str | None:
    if value is None or value == '' or type(value) is int and value == 0:
        return None
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value):
        return value
    raise ValueError('requiredMods.steamId must be a positive literal Steam Workshop ID')


def _mod_info(path: Path) -> tuple[dict, str]:
    data = _read(path)
    text = data.decode('utf-8-sig')
    # Inspect only sealed literal identity fields. Unrelated local helpers are
    # never run, and conflicting identities cannot silently become last-wins.
    from .shared_metadata_literals import load_literal_dependency_info
    info = load_literal_dependency_info(text)
    return info, hashlib.sha256(data).hexdigest()


class WorkshopResources:
    def __init__(self, source: Path):
        self.source = _absolute(source)
        _unlinked(self.source)
        if re.fullmatch(r'[0-9]+', self.source.name) is None or not self.source.is_dir():
            raise ValueError('Expected a numeric TF2 Workshop mod folder')
        self.root = _collection(self.source.parent)
        self._cache = {}
        self._declarations = {}
        self._origin_fingerprints = {}
        metadata = self.source / 'mod.lua'
        _unlinked(metadata)
        if metadata.is_file():
            info, digest = _mod_info(metadata)
            self._origin_fingerprints[str(metadata)] = digest
            declarations = info.get('requiredMods', [])
            if not isinstance(declarations, list):
                raise ValueError('mod.lua.info.requiredMods must be a literal list')
            for declaration in declarations:
                if not isinstance(declaration, dict):
                    raise ValueError('mod.lua.info.requiredMods entries must be literal named tables')
                package_id = _steam_id(declaration.get('steamId'))
                if package_id is None:
                    continue  # No installed Steam package identity was declared.
                mod_id = declaration.get('modId')
                if mod_id is not None and (not isinstance(mod_id, str) or not mod_id):
                    raise ValueError('requiredMods.modId must be non-empty literal text')
                minimum = declaration.get('minMinorVersion')
                if minimum is not None and (type(minimum) is not int or minimum < 0):
                    raise ValueError('requiredMods.minMinorVersion must be a nonnegative literal integer')
                prior = self._declarations.get(package_id)
                if prior is not None and prior != declaration:
                    raise ValueError(f'Conflicting requiredMods declarations for Workshop package {package_id}')
                self._declarations[package_id] = dict(declaration)
        self._packages = []
        for package in sorted(self.root.iterdir()):
            if re.fullmatch(r'[0-9]+', package.name) is None:
                continue
            # Never traverse linked sibling packages while looking for a match.
            if linked(package):
                continue
            if package.is_dir():
                self._packages.append(package)

    def _declared_metadata(self, package: Path) -> tuple[str, str]:
        declaration = self._declarations[package.name]
        metadata = _provider(package / 'mod.lua', self.root)
        info, digest = _mod_info(metadata)
        declared_id = declaration.get('modId')
        actual_id = info.get('modid', info.get('modId'))
        if declared_id is not None and actual_id != declared_id:
            raise ValueError(f'Declared Workshop dependency {package.name} modId does not match its installed mod.lua')
        if 'steamId' in info and _steam_id(info['steamId']) not in (None, package.name):
            raise ValueError(f'Declared Workshop dependency {package.name} steamId does not match its installed mod.lua')
        minimum = declaration.get('minMinorVersion')
        if minimum is not None and (type(info.get('minorVersion')) is not int or info['minorVersion'] < minimum):
            raise ValueError(f'Declared Workshop dependency {package.name} does not satisfy minMinorVersion {minimum}')
        return str(metadata), digest

    def resolve(self, reference: str, kind: str = 'texture', prefer_local: bool = False,
                allow_global: bool = True) -> dict | None:
        if type(prefer_local) is not bool:
            raise ValueError('Workshop lookup prefer_local must be a boolean')
        if type(allow_global) is not bool:
            raise ValueError('Workshop lookup allow_global must be a boolean')
        reference = normalize_reference(reference)
        resource = _resource(kind, reference)
        if kind in ('localization', 'helper'):
            prefer_local = True
        key = (kind, reference, prefer_local, allow_global)
        if key not in self._cache:
            candidates = []
            local = self.source / resource if kind == 'localization' else self.source / 'res' / resource
            _unlinked(local)
            if prefer_local and local.is_file():
                candidates = [(self.source, _provider(local, self.root))]
            elif kind not in ('localization', 'helper'):
                def exact_candidates(packages):
                    result = []
                    for package in packages:
                        candidate = package / 'res' / resource
                        _unlinked(candidate)
                        if candidate.is_file():
                            result.append((package, _provider(candidate, self.root)))
                    return result

                # Declared providers already take precedence over every global
                # match. Resolve that scope first, avoiding unrelated resource
                # trees when the exact declared input is present. Each selected
                # provider and declaration is still freshly read and hashed;
                # commit/resume verification rebuilds this lookup as before.
                candidates = exact_candidates(package for package in self._packages
                                              if package.name in self._declarations)
                if not candidates and allow_global:
                    candidates = exact_candidates(self._packages)
            declared = [(package, candidate) for package, candidate in candidates
                        if package.name in self._declarations]
            declarations = {}
            local_selected = len(candidates) == 1 and candidates[0][0] == self.source and prefer_local
            selection = 'owner_exact_resource' if local_selected else 'all_exact_providers'
            if declared and not local_selected:
                for package, _ in declared:
                    path, digest = self._declared_metadata(package)
                    declarations[path] = digest
                candidates = declared
                selection = 'declared_requiredMods'
            providers, first_data, first_hash = [], None, None
            for _, provider in candidates:
                data = _read(provider)
                digest = hashlib.sha256(data).hexdigest()
                if first_hash is not None and digest != first_hash:
                    unavailable = []
                    for package_id in self._declarations:
                        package = self.root / package_id
                        _unlinked(package)
                        if not package.is_dir():
                            unavailable.append(package_id)
                    detail = ('; declared packages are not installed: ' + ', '.join(sorted(unavailable))) if unavailable else ''
                    raise ValueError(f'Ambiguous Workshop {kind} dependency: {reference}; exact-path providers have different bytes{detail}')
                first_data, first_hash = data, digest
                providers.append(str(provider))
            self._cache[key] = (first_data, tuple(providers), first_hash,
                                tuple(sorted(declarations.items())), selection) if providers else None
        match = self._cache[key]
        if match is None:
            return None
        data, providers, digest, declarations, selection = match
        fingerprints = {path: digest for path in providers}
        fingerprints.update(declarations)
        fingerprints.update(self._origin_fingerprints)
        policy = ('prefer_local' if prefer_local else 'declared_or_global') if allow_global else (
                 'prefer_local_declared_only' if prefer_local else 'declared_only')
        return {'data': data, 'providers': list(providers), 'sha256': digest,
                'sourceReference': reference, 'sourceResource': resource, 'kind': kind,
                'declarationFingerprints': dict(declarations), 'providerSelection': selection,
                'lookupSource': str(self.source), 'lookupPolicy': policy,
                'originFingerprints': dict(self._origin_fingerprints),
                'fingerprints': fingerprints}

    def fingerprints(self, paths) -> dict[str, str]:
        return workshop_fingerprints(paths, self.root)

    def absence(self, reference: str, kind: str, prefer_local: bool = False) -> dict:
        """Record a scoped no-provider result without mixing it with asset hashes."""
        reference = normalize_reference(reference)
        for package_id in self._declarations:
            _unlinked(self.root/package_id)
        if self.resolve(reference, kind, prefer_local=prefer_local, allow_global=False) is not None:
            raise ValueError(f'Declared/owner Workshop resource is no longer absent: {kind} {reference}')
        if kind in ('localization', 'helper'):
            prefer_local = True
        return {'kind': kind, 'sourceReference': reference, 'lookupSource': str(self.source),
                'lookupPolicy': 'prefer_local_declared_only' if prefer_local else 'declared_only',
                'originFingerprints': dict(self._origin_fingerprints)}


class WorkshopTextures(WorkshopResources):
    """Compatibility interface for texture-only consumers and old receipts."""
    def resolve(self, reference: str) -> dict | None:
        if PurePosixPath(normalize_reference(reference)).suffix.lower() not in TEXTURE_SUFFIXES:
            raise ValueError('Workshop dependencies support only DDS, TGA and HDR textures')
        match = super().resolve(reference, 'texture')
        return None if match is None else {key: match[key] for key in ('data', 'providers', 'sha256', 'sourceReference')}

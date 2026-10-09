"""Resolve borrowed TF2 assets to installed TF3 assets, without copying game data.

Known resource-role mappings may use updated TF3 bytes. Other binary assets need
an identical hash; names alone never establish equivalence. Format/behavior
migration remains the responsibility of the calling category adapter.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from copy import copy
from pathlib import Path, PurePosixPath
import threading
import zipfile

from .filesystem import linked


class VerifiedReadZipFile(zipfile.ZipFile):
    """Reuse parsed ZIP metadata only after hashing the current directory bytes.

    Each instance opens the current file and reads its current member bytes.
    Neither timestamps nor previously open file handles establish freshness.
    Unsupported Python internals use the ordinary standard-library reader.
    """
    _catalogs = OrderedDict()
    _catalog_lock = threading.RLock()

    def __init__(self, file, mode='r', **kwargs):
        if mode != 'r':
            raise ValueError('Verified ZIP inputs are read-only')
        super().__init__(file, mode=mode, **kwargs)

    def _directory_signature(self):
        helper = getattr(zipfile, '_handle_prepended_data', None)
        if helper is None:
            return None
        end = zipfile._EndRecData(self.fp)
        if not end:
            return None
        offset, concat = helper(end, 0)
        start, size = offset+concat, end[zipfile._ECD_SIZE]
        if start < 0 or not 0 <= size <= 64*1024*1024:
            return None
        self.fp.seek(start)
        raw = self.fp.read(size)
        if len(raw) != size:
            return None
        return (self.filename, self.metadata_encoding, tuple(end), start,
                hashlib.sha256(raw).digest())

    def _RealGetContents(self):
        signature = self._directory_signature()
        with self._catalog_lock:
            cached = self._catalogs.get(signature) if signature is not None else None
            if cached is not None:
                self._catalogs.move_to_end(signature)
                entries, self.start_dir, self._comment = cached
                self.filelist = list(entries)
                self.NameToInfo = {entry.filename:entry for entry in entries}
                return
        super()._RealGetContents()
        # Do not label a catalog with bytes read before a concurrent change.
        if signature is not None and signature == self._directory_signature():
            entries = tuple(copy(entry) for entry in self.filelist)
            with self._catalog_lock:
                self._catalogs[signature] = (entries, self.start_dir, self._comment)
                self._catalogs.move_to_end(signature)
                while len(self._catalogs) > 8:
                    self._catalogs.popitem(last=False)

    def getinfo(self, name):
        return copy(super().getinfo(name))

    def infolist(self):
        return [copy(entry) for entry in super().infolist()]


ROOTS = {'model': 'models/model', 'mesh': 'models/mesh', 'material': 'models/material',
         'animation': 'models/animation', 'texture': 'textures', 'audio': 'audio/effects',
         'sound_set': 'config/sound_set', 'ground_texture': 'config/ground_texture',
         'terrain_material': 'config/terrain_material', 'grass': 'config/grass',
         'multiple_unit': 'config/multiple_unit'}
BASE_TEXTURES = {
    'models/vehicle/dirt_albedo.tga': 'vehicle/shared/mat/tex/dirt_albedo.dds',
    'models/vehicle/dirt_albedo.dds': 'vehicle/shared/mat/tex/dirt_albedo.dds',
    'models/vehicle/dirt_normal.dds': 'vehicle/shared/mat/tex/dirt_normal.dds',
    'models/vehicle/rust_albedo.dds': 'vehicle/shared/mat/tex/rust_albedo.dds',
    'models/vehicle/rust_normal.dds': 'vehicle/shared/mat/tex/rust_normal.dds',
    'models/vehicle/train/emissive/train_all_lights.dds': 'vehicle/train/emissive/tex/train_all_lights.dds',
    'default_metal_gloss_ao.tga': 'vehicle/shared/mat/tex/default_metal_gloss_ao.dds',
    'default_metal_gloss_ao.dds': 'vehicle/shared/mat/tex/default_metal_gloss_ao.dds',
    'default_normal_map.tga': 'placeholders/mat/tex/default_normal_map.dds',
    'default_normal_map.dds': 'placeholders/mat/tex/default_normal_map.dds',
    # Both installations ship these explicit missing-texture placeholders.
    # Reference the native role rather than copying the old game texture.
    'unknown_texture.tga': 'placeholders/mat/tex/unknown_texture.dds',
    'unknown_texture.dds': 'placeholders/mat/tex/unknown_texture.dds',
    'unknown_albedo_1k.tga': 'placeholders/mat/tex/unknown_albedo_1k.dds',
    'unknown_albedo_1k.dds': 'placeholders/mat/tex/unknown_albedo_1k.dds',
    **{name + '.dds': 'base/tex/' + name + '.dds' for name in
       ('particle_noise0', 'particle_noise1', 'particle_smoke', 'particle_smoke_normal')},
}
SOUND_FAMILIES = {'train': 'train', 'cabcar': 'train', 'tram': 'tram', 'waggon': 'waggon',
                  'bus': 'bus', 'car': 'car', 'truck': 'truck', 'aircraft': 'plane', 'plane':'plane', 'ship': 'ship'}
# Verified semantic role and installed location, rather than generic filename matching.
BASE_MODELS = {f'characters/{name}.mdl': f'characters/{name}/{name}.mdl'
               for name in ('era_a_driver_rail','era_a_driver_road','era_a_driver_water',
                            'era_b_driver_air_indoor','era_b_driver_air_outdoor','era_b_driver_rail',
                            'era_b_driver_road','era_b_driver_water','era_c_driver_air',
                            'era_c_driver_rail','era_c_driver_road','era_c_driver_water')}
BASE_MODELS.update({
    'railroad/tracks/single_rail.mdl':'infrastructure/track/shared/single_rail.mdl',
    'railroad/tracks/single_sleeper_base.mdl':'infrastructure/track/standard/single_sleeper_standard.mdl',
    'railroad/tracks/single_sleeper_high_speed.mdl':'infrastructure/track/high_speed/single_sleeper_high_speed.mdl',
    **{f'railroad/tracks/{size}m_base.mdl':f'infrastructure/track/standard/{size}m_standard.mdl' for size in (2,4,8,16)},
    **{f'railroad/tracks/{size}m_high_speed.mdl':f'infrastructure/track/high_speed/{size}m_high_speed.mdl' for size in (2,4,8,16)},
})
BASE_MATERIALS = {'track/ballast.mtl':'infrastructure/track/shared/mat/ballast.mtl',
                  'track/rail.mtl':'infrastructure/track/shared/mat/rail_tileable.mtl',
                  'track/catenary.mtl':'infrastructure/shared/mat/catenary.mtl',
                  'track/sleeper.mtl':'infrastructure/track/standard/mat/sleeper_standard_tileable.mtl',
                  'track/sleeper_concrete.mtl':'infrastructure/track/high_speed/mat/sleeper_high_speed_tileable.mtl'}
# Shipped TF2/TF3 light materials retain these specific roles and filenames.
# TF3 supplies its own light-mask and emissive values; no game material is copied.
BASE_MATERIALS.update({f'vehicle/{family}/emissive/{family}_{role}.mtl':
                      f'vehicle/{family}/emissive/{family}_{role}.mtl'
                      for family, roles in {
                          'bus': ('add_lights','all_lights','blink_lights','brake_lights'),
                          'car': ('all_lights','blink_lights','brake_lights'),
                          'plane': ('all_lights','strobe_light'),
                          'ship': ('add_lights','all_lights'),
                          'train': ('all_lights','red_lights'),
                          'tram': ('add_lights','all_lights','blink_lights','brake_lights'),
                          'truck': ('all_lights','blink_lights','brake_lights'),
                      }.items() for role in roles})
BINARY_ENDINGS = {'texture': {'.dds', '.tga', '.hdr'}, 'audio': {'.wav', '.ogg'}, 'animation': {'.ani'}}


def validate_reference(reference: str) -> None:
    if (not isinstance(reference, str) or not reference or '\\' in reference or ':' in reference
            or reference.startswith('/') or any(p in ('', '.', '..') for p in reference.split('/'))):
        raise ValueError(f'Unsafe TF2 resource reference: {reference!r}')


def normalize_reference(reference: str) -> str:
    """Canonicalize repeated interior separators without admitting traversal."""
    if not isinstance(reference, str) or reference.startswith('/') or reference.endswith('/'):
        validate_reference(reference)
    normalized = '/'.join(part for part in reference.split('/') if part)
    validate_reference(normalized)
    return normalized


def source_resource(kind: str, reference: str) -> str:
    reference = normalize_reference(reference)
    if kind not in ROOTS:
        raise ValueError(f'No verified source resource root for {kind}')
    ending = '.lua' if kind in ('sound_set','ground_texture','terrain_material','grass','multiple_unit') and not reference.endswith('.lua') else ''
    return ROOTS[kind] + '/' + reference + ending


class TF2Inventory:
    """TF2 res/ mounts loose files and zip members at each archive's parent."""
    def __init__(self, game: Path):
        self.content = game / 'res'
        if not self.content.is_dir() or linked(self.content):
            raise ValueError('Choose the TF2 installation folder (with res)')
        self.files = {}
        for path in sorted(self.content.rglob('*')):
            if linked(path):
                raise ValueError(f'Linked TF2 base resource is not supported: {path}')
            if not path.is_file():
                continue
            if path.suffix == '.zip':
                with zipfile.ZipFile(path) as archive:
                    for entry in archive.infolist():
                        if entry.is_dir():
                            continue
                        validate_reference(entry.filename)
                        relative = (path.parent.relative_to(self.content) / entry.filename).as_posix()
                        # Loose files have precedence over packaged base resources.
                        self.files.setdefault(relative, (path, entry.filename))
            else:
                self.files[path.relative_to(self.content).as_posix()] = (path, None)

    def read(self, resource: str) -> bytes:
        path, member = self.files[resource]
        if member is None:
            return path.read_bytes()
        with VerifiedReadZipFile(path) as archive:
            return archive.read(member)


def find_tf2_game(source: Path, tf3_game: Path) -> Path | None:
    candidates = [parent / 'common/Transport Fever 2' for parent in source.parents
                  if parent.name.lower() == 'steamapps']
    candidates.append(tf3_game.parent / 'Transport Fever 2')
    return next((p for p in candidates if (p / 'res').is_dir()), None)


class BaseResourceResolver:
    """Shared by vehicle/mod adapters; uncertain equivalents remain blockers."""
    def __init__(self, native, tf2: TF2Inventory | None = None, *, family: str | None = None):
        self.native, self.tf2, self.family = native, tf2, family
        self.replacements: list[dict] = []
        self._hashes = {}
        self._tf2_hashes = {}
        self._by_name = {}
        self._audio_references = {}
        binary_suffixes = set().union(*BINARY_ENDINGS.values())
        for path in native.files:
            if PurePosixPath(path).suffix in binary_suffixes:
                self._by_name.setdefault(PurePosixPath(path).name, []).append(path)
            if path.startswith('vehicle/') and '/shared/sound/' in path and path.endswith(('.wav', '.ogg')):
                reference = 'vehicle/' + path.split('/shared/sound/', 1)[1]
                self._audio_references.setdefault(reference, []).append(path)

    def is_borrowed(self, kind: str, reference: str, local: Path) -> bool:
        known_descriptor = kind == 'model' and reference in BASE_MODELS or kind == 'material' and reference in BASE_MATERIALS
        if kind not in BINARY_ENDINGS and kind != 'sound_set' and not known_descriptor:
            return False  # Resource descriptors need their own schema adapter.
        old = source_resource(kind, reference)
        return bool(self.tf2 and old in self.tf2.files
                    and hashlib.sha256(local.read_bytes()).hexdigest() == self._tf2_hash(old))

    def _tf2_hash(self, path: str) -> str:
        if path not in self._tf2_hashes:
            self._tf2_hashes[path] = hashlib.sha256(self.tf2.read(path)).hexdigest()
        return self._tf2_hashes[path]

    def _native_hash(self, path: str) -> str:
        if path not in self._hashes:
            self._hashes[path] = hashlib.sha256(self.native.read(path)).hexdigest()
        return self._hashes[path]

    def resolve(self, kind: str, reference: str, *, bundled: bool = False) -> str:
        reference = normalize_reference(reference)
        old = source_resource(kind, reference)
        target, method, digest = None, 'verified_role_mapping', None
        if kind == 'texture':
            target = BASE_TEXTURES.get(reference)
        elif kind == 'model':
            target = BASE_MODELS.get(reference)
        elif kind == 'material':
            target = BASE_MATERIALS.get(reference)
        elif kind == 'sound_set':
            family = SOUND_FAMILIES.get(reference.split('_', 1)[0])
            if family:
                target = f'vehicle/{family}/shared/sound/{reference}.snd'
            elif reference in ('airport_1920', 'airport_1980'):
                target = f'stations/air/sound/{reference}.snd'
            elif reference in ('harbor_cargo', 'town_building'):
                target = {'harbor_cargo': 'stations/water/sound/harbor_cargo.snd',
                          'town_building': 'buildings/shared/sound/town_building.snd'}[reference]
            elif '/' not in reference:
                target = f'industries/{reference}/sound/{reference}.snd'
        elif kind == 'audio' and reference.startswith('vehicle/'):
            matches = sorted(self._audio_references.get(reference, []))
            preferred = [p for p in matches if self.family and p.startswith(f'vehicle/{self.family}/')]
            if len(preferred) == 1:
                matches = preferred
            if len(matches) == 1:
                target = matches[0]
        if target:
            try:
                resolved = self.native.reference(target)
            except ValueError:
                target = None
        if not target and kind in BINARY_ENDINGS and self.tf2 and old in self.tf2.files:
            digest = self._tf2_hash(old)
            matches = sorted(p for p in self._by_name.get(PurePosixPath(reference).name, [])
                             if PurePosixPath(p).suffix in BINARY_ENDINGS[kind]
                             and self._native_hash(p) == digest)
            if matches:
                # Multiple copies of identical binary content are equivalent.
                target = next((p for p in matches if self.family and p.startswith(f'vehicle/{self.family}/')), matches[0])
                resolved = self.native.reference(target)
                method = 'byte_identical'
        if not target:
            raise ValueError(f'No verified TF3 equivalent for TF2 {kind} reference: {reference}. '
                             'Keep this item for manual migration; no resource was guessed.')
        row = {'kind': kind, 'sourceReference': reference, 'sourceResource': 'res/' + old,
               'tf3Resource': target, 'targetReference': resolved, 'matchMethod': method,
               'sourceOrigin': 'bundled_tf2_base' if bundled else
               ('tf2_base' if self.tf2 and old in self.tf2.files else 'legacy_base_reference')}
        if method == 'byte_identical':
            row['sha256'] = digest
        if row not in self.replacements:
            self.replacements.append(row)
        return resolved

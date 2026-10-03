"""Resolve borrowed TF2 assets to installed TF3 assets, without copying game data.

Known resource-role mappings may use updated TF3 bytes. Other binary assets need
an identical hash; names alone never establish equivalence. Format/behavior
migration remains the responsibility of the calling category adapter.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import zipfile

from .filesystem import linked


ROOTS = {'model': 'models/model', 'mesh': 'models/mesh', 'material': 'models/material',
         'animation': 'models/animation', 'texture': 'textures', 'audio': 'audio/effects',
         'sound_set': 'config/sound_set'}
BASE_TEXTURES = {
    'models/vehicle/dirt_albedo.dds': 'vehicle/shared/mat/tex/dirt_albedo.dds',
    'models/vehicle/dirt_normal.dds': 'vehicle/shared/mat/tex/dirt_normal.dds',
    'models/vehicle/rust_albedo.dds': 'vehicle/shared/mat/tex/rust_albedo.dds',
    'models/vehicle/rust_normal.dds': 'vehicle/shared/mat/tex/rust_normal.dds',
    'models/vehicle/train/emissive/train_all_lights.dds': 'vehicle/train/emissive/tex/train_all_lights.dds',
    'default_metal_gloss_ao.tga': 'vehicle/shared/mat/tex/default_metal_gloss_ao.dds',
    'default_metal_gloss_ao.dds': 'vehicle/shared/mat/tex/default_metal_gloss_ao.dds',
    'default_normal_map.tga': 'placeholders/mat/tex/default_normal_map.dds',
    'default_normal_map.dds': 'placeholders/mat/tex/default_normal_map.dds',
    **{name + '.dds': 'base/tex/' + name + '.dds' for name in
       ('particle_noise0', 'particle_noise1', 'particle_smoke', 'particle_smoke_normal')},
}
SOUND_FAMILIES = {'train': 'train', 'cabcar': 'train', 'tram': 'tram', 'waggon': 'waggon',
                  'bus': 'bus', 'car': 'car', 'truck': 'truck', 'aircraft': 'plane', 'ship': 'ship'}
BINARY_ENDINGS = {'texture': {'.dds', '.tga', '.hdr'}, 'audio': {'.wav', '.ogg'}, 'animation': {'.ani'}}


def validate_reference(reference: str) -> None:
    if (not isinstance(reference, str) or not reference or '\\' in reference or ':' in reference
            or reference.startswith('/') or any(p in ('', '.', '..') for p in reference.split('/'))):
        raise ValueError(f'Unsafe TF2 resource reference: {reference!r}')


def source_resource(kind: str, reference: str) -> str:
    validate_reference(reference)
    return ROOTS[kind] + '/' + reference + ('.lua' if kind == 'sound_set' else '')


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
        with zipfile.ZipFile(path) as archive:
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
        if kind not in BINARY_ENDINGS and kind != 'sound_set':
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
        old = source_resource(kind, reference)
        target, method, digest = None, 'verified_role_mapping', None
        if kind == 'texture':
            target = BASE_TEXTURES.get(reference)
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

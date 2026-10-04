"""Preserve mesh geometry while resolving literal legacy material defaults.

TF3 assigns one material per submesh in the model's mesh node. A legacy default
whose resource is absent can therefore be linked to that explicit assignment
only when every known model referrer supplies complete, matching evidence.
No material is selected by filename, directory proximity or referrer order.
"""
from __future__ import annotations

from copy import deepcopy

from .base_resources import validate_reference
from .lua_metadata import TranslatedString


SCHEMA_SOURCES = (
    'https://wiki.transportfever2.com/doku.php?id=modding:resourcetypes:msh',
    'https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:msh',
)


def _reference(value, where):
    if isinstance(value, TranslatedString):
        raise ValueError(f'{where}: localized material reference requires manual migration')
    validate_reference(value)
    return value


def _resolved(value, resolve, where):
    reference = _reference(value, where)
    result = resolve(reference, 'material')
    if not isinstance(result, str) or not result:
        raise ValueError(f'{where}: resolver returned no verified material reference')
    return result


def _slot_evidence(referrers, slot, submesh_count, resolve, mesh_path):
    if not referrers:
        raise ValueError(f'{mesh_path}: missing mesh material has no explicit model referrers')
    evidence, target = [], None
    for referrer in referrers:
        if not isinstance(referrer, dict):
            raise ValueError(f'{mesh_path}: expected named model referrer evidence')
        model, node = referrer.get('modelPath'), referrer.get('nodePath')
        if not isinstance(model, str) or not model or not isinstance(node, str) or not node:
            raise ValueError(f'{mesh_path}: referrer requires explicit modelPath and nodePath')
        materials = referrer.get('materials')
        if not isinstance(materials, list) or len(materials) != submesh_count:
            raise ValueError(f'{mesh_path}: incomplete model materials at {model}/{node}; '
                             f'expected {submesh_count} explicit submesh slots')
        # An apparently complete list with unresolved slots is not evidence of
        # a valid explicit model assignment, even if this slot alone resolves.
        resolved = [_resolved(reference, resolve, f'{model}/{node}/materials/{index}')
                    for index, reference in enumerate(materials)]
        if target is not None and resolved[slot] != target:
            raise ValueError(f'{mesh_path}: conflicting model materials for submesh slot {slot}; '
                             'no default was chosen')
        target = resolved[slot]
        row = {'modelPath': model, 'nodePath': node, 'sourceReference': materials[slot]}
        if row not in evidence:
            evidence.append(row)
    return target, evidence


def port_mesh_descriptor(data: dict, resolve, referrers: list[dict], report: dict | None = None,
                         mesh_path: str = '') -> dict:
    """Resolve submesh material defaults without changing geometry or animation.

    ``resolve(source_reference, 'material')`` must verify its returned reference.
    Referrers contain ``modelPath``, ``nodePath`` and the original TF2 node
    ``materials`` list. Missing defaults require complete lists on every known
    referrer and a single resolved material for the corresponding submesh slot.
    Existing defaults resolve directly and need no inferred model binding.

    All literal fields, index/attribute values and material-list order remain
    intact. The caller handles the unchanged blob and archives changed source
    text. Audit rows never assert native TF3 runtime validation.
    """
    from .resource_profiles import _checked

    _checked(data, 'mesh descriptor')
    _checked(referrers, 'mesh referrers')
    if not isinstance(data, dict) or not isinstance(referrers, list):
        raise ValueError('Expected a literal mesh descriptor and referrer list')
    result = deepcopy(data)
    submeshes = result.get('subMeshes')
    if not isinstance(submeshes, list):
        raise ValueError(f'{mesh_path}: expected a literal subMeshes list')
    migrations = []
    verified_slots = {}
    for slot, submesh in enumerate(submeshes):
        if not isinstance(submesh, dict):
            raise ValueError(f'{mesh_path}: expected named submesh {slot}')
        if 'materials' not in submesh:
            continue
        materials = submesh['materials']
        if not isinstance(materials, list):
            raise ValueError(f'{mesh_path}: submesh materials must be a literal list')
        for variant, source in enumerate(materials):
            where = f'{mesh_path}/subMeshes/{slot}/materials/{variant}'
            # Unsafe/localized input is always a blocker, never a reason to use
            # otherwise-valid model evidence as a replacement.
            _reference(source, where)
            evidence, method = [], 'direct_verified_reference'
            try:
                target = _resolved(source, resolve, where)
            except ValueError as missing:
                if slot not in verified_slots:
                    try:
                        verified_slots[slot] = _slot_evidence(referrers, slot, len(submeshes), resolve, mesh_path)
                    except ValueError as uncertain:
                        raise ValueError(f'{where}: {uncertain}; original default unresolved: {missing}') from uncertain
                target, evidence = verified_slots[slot]
                method = 'unanimous_explicit_model_material_slot'
            materials[variant] = target
            migrations.append({'mesh': mesh_path, 'submeshSlot': slot, 'materialVariant': variant,
                               'sourceReference': source, 'targetReference': target,
                               'method': method, 'referrers': deepcopy(evidence), 'nativeTest': 'not_run'})
    if report is not None and migrations:
        report.setdefault('meshMigrations', []).extend(migrations)
    return result

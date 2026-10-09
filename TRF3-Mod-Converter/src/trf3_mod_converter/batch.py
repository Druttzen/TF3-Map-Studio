"""Recursive discovery and sequential exports with durable, verified receipts."""
from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import traceback
import uuid
from luaparser import ast, astnodes as lua

from .converter import convert_mod, inspect_mod, _is_legacy_tf2_package, _legacy_tf2_savegame_blocker
from .filesystem import linked, replace_with_retry
from .lua_metadata import load_lua_table, _value, UnsupportedValue
from .resource_audit import parse_lua
from .base_resources import TF2Inventory, find_tf2_game
from .workshop_resources import (verify_workshop_dependencies, verify_workshop_absences,
                                 verify_native_stock_selections, verify_base_resource_identities)
from .source_game_resources import verify_source_game_dependencies
from .tf2_vehicle_port import NativeInventory, port_tf2_mod, snapshot, literal
from .resource_profiles import classify_resource, load_resource_table
from .vehicle_profiles import classify_model
from . import __version__
from .conversion_choices import conversion_choices

METADATA = ('mod.lua', 'modinfo.lua', 'modinfo.json', 'info.json', 'mod.json', '_metadata/modinfo.json')
SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv', '_port_originals'}
STATE_NAME = '.tf3-batch-report.json'
FORMAT = 'tf3-converter-batch-v1'


@dataclass
class QueueItem:
    source: str
    display_name: str
    mod_id: str
    metadata_signature: str
    scan_error: str = ''
    status: str = 'pending'
    message: str = ''
    destination: str = ''
    emissions_policy: str = 'strict'
    vehicle_policy: str = 'strict'

    @property
    def key(self):
        return os.path.normcase(self.source)


def metadata_signature(root: Path) -> str:
    values = {}
    for name in (*METADATA, 'strings.lua', 'strings.json'):
        path = root / name
        if any(linked(p) for p in (path, *path.parents)):
            raise ValueError(f'Linked metadata is not supported: {path}')
        if path.is_file():
            values[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return fingerprint(values)


def fingerprint(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_fingerprint(root: Path) -> str:
    for path in root.rglob('*'):
        if linked(path):
            raise ValueError(f'Linked package resource is not supported: {path}')
    return fingerprint(snapshot(root))


def display_name(root: Path, descriptor) -> str:
    name = descriptor.name
    try:
        text = (root / 'strings.lua').read_text(encoding='utf-8-sig') if (root / 'strings.lua').is_file() else ''
        try:
            translations = load_lua_table(text) if text else {}
        except Exception:
            translated = _literal_translation_name(text, name)
            if translated:
                return translated
            translations = {}
        for locale in ('en', 'sv', 'se', 'de'):
            table = translations.get(locale, {}) if isinstance(translations, dict) else {}
            value = table.get(name) if isinstance(table, dict) else None
            if isinstance(value, str) and value:
                return value
        for locale in ('en', 'sv', 'se', 'de'):
            value = descriptor.localization.get(locale, {}).get('name')
            if isinstance(value, str) and value:
                return value
    except (OSError, ValueError, UnicodeError):
        pass
    return name


def _literal_translation_name(text: str, key: str) -> str | None:
    """Read only a proven literal name when unrelated descriptions use locals."""
    try:
        tree = parse_lua(text)
        top = tree.body.body
        if len(top) != 1 or not isinstance(top[0], lua.Function) or not isinstance(top[0].name, lua.Name) or top[0].name.id != 'data':
            return None
        body = top[0].body.body
        for statement in body[:-1]:
            if not isinstance(statement, lua.LocalAssign) or any(isinstance(_value(v), UnsupportedValue) or type(_value(v)) not in (str, int, float, bool, type(None)) for v in statement.values):
                return None
        returned = body[-1]
        if not isinstance(returned, lua.Return) or len(returned.values) != 1 or not isinstance(returned.values[0], lua.Table):
            return None
        if any(isinstance(node, (lua.Call, lua.Invoke, lua.AnonymousFunction)) for node in ast.walk(returned)):
            return None
        def field(table, name):
            if not isinstance(table, lua.Table):
                return None
            found = None
            for entry in table.fields:
                if entry.key is None:
                    continue  # Unnamed numeric entries cannot replace a named key.
                k = entry.key.id if isinstance(entry.key, lua.Name) and not entry.between_brackets else _value(entry.key)
                if isinstance(k, UnsupportedValue):
                    raise ValueError('Computed translation key')
                if k == name:
                    found = entry.value
            return found
        for locale in ('en', 'sv', 'se', 'de'):
            value = field(field(returned.values[0], locale), key)
            if value is not None and isinstance(name := _value(value), str) and name:
                return name
    except Exception:
        pass
    return None


def stable_id(root: Path, descriptor) -> str:
    workshop = root.name.isdecimal() and root.parent.name == '1066780'
    # TF2-generated map IDs may contain '?', spaces and uppercase characters.
    # A numeric Workshop identity is already proven by the package location;
    # use it only for an invalid legacy ID, preserving native/valid authored IDs.
    invalid_legacy_workshop_id = (workshop and _is_legacy_tf2_package(root)
                                  and not re.fullmatch('[a-z0-9_]+', descriptor.mod_id or ''))
    if descriptor.mod_id and not invalid_legacy_workshop_id:
        return descriptor.mod_id
    if workshop:
        return 'tf2_workshop_' + root.name
    slug = re.sub('[^a-z0-9]+', '_', root.name.lower()).strip('_')[:20] or 'mod'
    digest = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:12]
    return f'tf2_{slug}_{digest}'


def scan_mods(source: str | Path, *, exclude: str | Path | None = None,
              stop: threading.Event | None = None, progress=None, vehicles_only=False) -> dict:
    if not str(source).strip():
        raise ValueError('Choose a mod folder first.')
    root = Path(source).expanduser().absolute()
    if any(linked(p) for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError('Choose an existing folder without symbolic links or junctions.')
    root = root.resolve()
    excluded = Path(exclude).expanduser().resolve() if exclude else None
    items, warnings = [], []
    stack = [root]
    while stack:
        if stop and stop.is_set():
            break
        directory = stack.pop()
        if directory == excluded or directory.name in SKIP_DIRS:
            continue
        try:
            if linked(directory):
                warnings.append(f'Skipped linked folder: {directory}')
                continue
            if any((directory / name).is_file() for name in METADATA):
                if vehicles_only:
                    from .vehicle_mode import vehicle_package
                    if not vehicle_package(directory):
                        warnings.append(f'Skipped non-vehicle package: {directory}')
                        continue
                # A package boundary prevents helper-library metadata becoming another mod.
                signature, error, name, mod_id = '', '', directory.name, ''
                try:
                    signature = metadata_signature(directory)
                    descriptor = inspect_mod(directory)
                    name, mod_id = display_name(directory, descriptor), stable_id(directory, descriptor)
                except Exception as exc:
                    error = str(exc)
                    mod_id = stable_id(directory, type('Unnamed', (), {'mod_id': ''})())
                items.append(QueueItem(str(directory), name, mod_id, signature, error))
                if progress:
                    progress(f'{len(items)} mods found')
                continue
            children = sorted(directory.iterdir(), key=lambda p: p.name.casefold(), reverse=True)
            for child in children:
                if linked(child):
                    if child.is_dir():
                        warnings.append(f'Skipped linked folder: {child}')
                elif child.is_dir():
                    stack.append(child)
        except OSError as exc:
            warnings.append(f'Could not scan {directory}: {exc}')
    return {'source': str(root), 'items': items, 'warnings': warnings,
            'cancelled': bool(stop and stop.is_set())}


def find_tf3_game(source: str | Path) -> str:
    libraries = [parent.parent for parent in Path(source).absolute().parents if parent.name.lower() == 'steamapps']
    if sys.platform == 'win32':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                libraries.append(Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
        except OSError:
            pass
    for library in list(libraries):
        file = library / 'steamapps/libraryfolders.vdf'
        if file.is_file():
            try:
                libraries.extend(Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', file.read_text(encoding='utf-8')))
            except (OSError, UnicodeError):
                pass
    for library in libraries:
        game = library / 'steamapps/common/Transport Fever 3'
        if (game / 'base/content').is_dir():
            return str(game)
    return ''


@contextmanager
def output_lock(output: Path):
    """OS locks are automatically released after a crash; keep the lock inode."""
    path = output / '.tf3-batch.lock'
    if linked(path):
        raise ValueError('Linked batch lock is not allowed.')
    handle, locked = path.open('a+b'), False
    try:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise ValueError('Another conversion owns this output folder. Use another folder or wait.') from None
        yield
    finally:
        if locked:
            handle.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _save_state(output: Path, state: dict) -> None:
    target = output / STATE_NAME
    if linked(target):
        raise ValueError('Linked batch report is not allowed.')
    temporary = output / (STATE_NAME + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _export(item, target, tf3_game, native_cache, tf2_cache, progress):
    root = Path(item.source)
    content = root / 'res'
    if content.is_dir() and any(p.is_file() for p in content.rglob('*')):
        game = Path(tf3_game) if tf3_game else None
        if game is None:
            raise ValueError('Choose the installed TF3 folder before converting TF2 content.')
        key = str(game.resolve())
        if key not in native_cache:
            native_cache[key] = NativeInventory(game)
        tf2_game = find_tf2_game(root, game)
        tf2 = None
        if tf2_game is not None:
            tf2_key = str(tf2_game.resolve())
            if tf2_key not in tf2_cache:
                tf2_cache[tf2_key] = TF2Inventory(tf2_game)
            tf2 = tf2_cache[tf2_key]
        return port_tf2_mod(root, target, tf3_game=game, mod_id=item.mod_id, name=item.display_name,
                            progress=progress, _native_inventory=native_cache[key], _tf2_inventory=tf2,
                            emissions_policy=item.emissions_policy, vehicle_policy=item.vehicle_policy)
    # Metadata-only/native packages retain the original static validation path.
    return convert_mod(root, target, mod_id=item.mod_id, name=item.display_name, progress=progress,
                       _report_fields={'conversionChoices': conversion_choices(item.emissions_policy, item.vehicle_policy)})


def _tf3_data_added(report) -> bool:
    """Expose recorded completions without treating every migration as a repair."""
    if not isinstance(report, dict):
        return False
    audit = report.get('migrationAudit')
    if not isinstance(audit, dict):
        return False
    return any(isinstance(audit.get(key), list) and any(isinstance(row, dict) and row for row in audit[key])
               for key in ('dataCompletions', 'donorCompletions'))


def _source_game_valid(root: Path, tf3_game, evidence: dict) -> bool:
    """Derive the permitted TF2 installation independently of the saved report."""
    rows = evidence.get('sourceGameDependencies', [])
    resources = evidence.get('sourceGameResourceFingerprints', {})
    inventory = evidence.get('sourceGameInventoryFingerprint')
    installation = evidence.get('sourceGameInstallation')
    if (rows and 'workshopAbsentDependencies' not in evidence
            or not verify_workshop_absences(root, evidence.get('workshopAbsentDependencies', []))):
        return False
    if not isinstance(rows, list) or not isinstance(resources, dict):
        return False
    if not rows and not resources and inventory is None and installation is None:
        return True  # Older exports without adapted stock inputs remain compatible.
    if (not rows or not resources or not isinstance(inventory, str)
            or not re.fullmatch('[a-f0-9]{64}', inventory) or tf3_game is None):
        return False
    selected = find_tf2_game(root, Path(tf3_game))
    if selected is None or installation != str(selected.resolve()):
        return False
    return verify_source_game_dependencies(selected, rows, resources, inventory)


def _receipt_base_replacements(receipt: dict, target: Path):
    """Recover old receipt evidence only from its already fingerprinted output."""
    if 'baseResourceReplacements' in receipt:
        return receipt['baseResourceReplacements']
    report = target/'conversion-report.json'
    try:
        if any(linked(path) for path in (report, *report.parents)) or not report.is_file():
            return None
        if report.resolve().parent != target.resolve():
            return None
        before = report.stat()
        data = json.loads(report.read_text(encoding='utf-8'))
        after = report.stat()
        if (any(linked(path) for path in (report, *report.parents))
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or not isinstance(data, dict)):
            return None
        return data.get('baseResourceReplacements', [])
    except (OSError, ValueError, TypeError, UnicodeError):
        return None


def _preflight_profile(root: Path) -> None:
    """Reject known unsupported packages before hashing gigabytes of assets."""
    if blocker := _legacy_tf2_savegame_blocker(root):
        raise ValueError(blocker)
    content = root / 'res'
    if not content.is_dir():
        return
    from .verified_helpers import verified_legacy_helpers
    helper_paths = set(verified_legacy_helpers(root).values())
    models = []
    for path in content.rglob('*'):
        if linked(path):
            raise ValueError(f'Linked resource is not supported: {path}')
        if path.is_file():
            relative = path.relative_to(content).as_posix()
            if path.suffix.lower() in ('.zip','.7z','.rar','.pak','.dll','.exe','.bat','.cmd','.ps1','.sh'):
                raise ValueError(f'Opaque resource archive/native executable requires unpacking or manual migration: {relative}')
            kind = classify_resource(relative)
            if path in helper_paths:
                continue  # An exact audited native adapter replaces this helper.
            if kind in ('script', 'module', 'tunnel') or path.suffix.lower() in ('.trf', '.snd'):
                raise ValueError(f'Custom behavior resource needs a manual port: {relative}')
            if path.suffix.lower() == '.mdl':
                models.append(path)
    for path in sorted(models):
        data = literal(load_resource_table(path.read_text(encoding='utf-8-sig')))
        if data.get('version') != 1:
            raise ValueError(f'{path.name}: expected TF2 model version 1')
        from .missing_data import classify_missing_model
        classify_missing_model(data, path.relative_to(content).as_posix())


def convert_queue(items: list[QueueItem], destination: str | Path, *, tf3_game: str | Path | None = None,
                  stop: threading.Event | None = None, event=None) -> dict:
    if not str(destination).strip():
        raise ValueError('Choose a separate export folder.')
    output = Path(destination).expanduser().absolute()
    if any(linked(p) for p in (output, *output.parents)):
        raise ValueError('Output cannot use symbolic links or junctions.')
    output = output.resolve()
    for item in items:
        source = Path(item.source).resolve()
        if source.is_relative_to(output) or output.is_relative_to(source):
            raise ValueError('Choose an output folder separate from every source mod.')
    output.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        state_path = output / STATE_NAME
        if linked(state_path):
            raise ValueError('Linked batch report is not allowed.')
        previous = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'format': FORMAT, 'receipts': {}}
        if not isinstance(previous, dict) or previous.get('format') != FORMAT or not isinstance(previous.get('receipts'), dict):
            raise ValueError('Existing batch report is not recognized; choose another output folder.')
        state = {'format': FORMAT, 'destination': str(output), 'receipts': previous['receipts'], 'items': [],
                 'nativeTest': 'not_run', 'cancelled': False, 'diagnostics': {}}
        collisions = {key for key, count in Counter(i.mod_id for i in items).items() if count > 1}
        native_cache, tf2_cache = {}, {}
        for item in items:
            if item.vehicle_policy == 'tf2_complete' and item.emissions_policy == 'strict':
                item.emissions_policy = 'class_average'
            item.status, item.message, item.destination = 'pending', '', str(output / item.mod_id)
        state['items'] = [asdict(i) for i in items]
        _save_state(output, state)
        for index, item in enumerate(items):
            if stop and stop.is_set():
                state['cancelled'] = True
                break
            target = output / item.mod_id
            item.destination, item.status, item.message = str(target), 'running', 'Converting…'
            if event:
                event('item', {'key': item.key, 'status': item.status, 'message': item.message, 'index': index, 'total': len(items), 'destination': str(target)})
            try:
                choices = conversion_choices(item.emissions_policy, item.vehicle_policy)
                if not re.fullmatch('[a-z0-9_]+', item.mod_id):
                    raise ValueError('Invalid mod ID; no export was created.')
                if item.mod_id in collisions:
                    raise ValueError('Another listed mod uses the same ID. Remove one or repair its metadata.')
                root = Path(item.source)
                if any(linked(p) for p in (root, *root.parents)):
                    raise ValueError('Source became a linked folder. Scan again.')
                if item.scan_error and not (item.vehicle_policy == 'tf2_complete' and _is_legacy_tf2_package(root)):
                    raise ValueError(item.scan_error)
                if metadata_signature(root) != item.metadata_signature:
                    raise ValueError('Metadata changed after scanning. Scan the folder again.')
                if item.vehicle_policy == 'strict':
                    _preflight_profile(root)
                else:
                    from .vehicle_mode import vehicle_package
                    if not vehicle_package(root):
                        raise ValueError('Vehicle mode skips packages without vehicle content')
                before = file_fingerprint(root)
                receipt = state['receipts'].get(item.key, {})
                native=None
                if tf3_game and (root/'res').is_dir() and any(p.is_file() for p in (root/'res').rglob('*')):
                    game_key=str(Path(tf3_game).resolve())
                    if game_key not in native_cache:native_cache[game_key]=NativeInventory(Path(tf3_game))
                    native=native_cache[game_key]
                native_valid=(native is None and receipt.get('nativeResources')=={} or native is not None
                              and isinstance(receipt.get('nativeResources'),dict)
                              and native.verify_current(receipt.get('nativeInventory'), receipt['nativeResources'])) if target.exists() else False
                if target.exists():
                    output_valid = not linked(target) and receipt.get('outputFingerprint') == file_fingerprint(target)
                    base_identity_valid = output_valid and verify_base_resource_identities(root, tf3_game,
                        _receipt_base_replacements(receipt, target))
                    workshop_resources = receipt.get('workshopResources', {})
                    workshop_valid = verify_workshop_dependencies(root, receipt.get('workshopDependencies', []), workshop_resources)
                    native_selection_valid = verify_native_stock_selections(root, tf3_game,
                        receipt.get('workshopDependencies', []))
                    source_game_valid = _source_game_valid(root, tf3_game, receipt)
                    if (receipt.get('status') == 'completed' and receipt.get('modId') == item.mod_id
                            and receipt.get('sourceFingerprint') == before and not linked(target)
                            and receipt.get('converterVersion') == __version__
                            and receipt.get('conversionChoices', conversion_choices()) == choices
                            and receipt.get('tf3Game') == (str(Path(tf3_game).resolve()) if tf3_game else None)
                            and native_valid and workshop_valid and native_selection_valid and source_game_valid
                            and base_identity_valid and output_valid):
                        item.message = ('Previous export verified · TF3 data added'
                                        if receipt.get('tf3DataAdded') is True else 'Previous export verified')
                        if receipt.get('vehicleWarnings'):
                            item.message += f" · {len(receipt['vehicleWarnings'])} warnings"
                    else:
                        raise ValueError('Output already exists or has changed. It was not overwritten; choose another output folder.')
                else:
                    progress = (lambda message: event('progress', {'key': item.key, 'message': message})) if event else None
                    report = _export(item, target, tf3_game, native_cache, tf2_cache, progress)
                    report = report if isinstance(report, dict) else {}
                    if report.get('conversionChoices', conversion_choices()) != choices:
                        raise ValueError('The exporter did not preserve the selected conversion choices.')
                    migration_audit = report.get('migrationAudit')
                    migration_audit = migration_audit if isinstance(migration_audit, dict) else {}
                    if not verify_workshop_dependencies(root, migration_audit.get('workshopDependencies', []), report.get('workshopResourceFingerprints', {})):
                        raise ValueError('Workshop dependencies changed during conversion. Export needs review.')
                    if not verify_native_stock_selections(root, tf3_game, migration_audit.get('workshopDependencies', [])):
                        raise ValueError('TF2 stock resources used to select native mappings changed during conversion. Export needs review.')
                    if not verify_base_resource_identities(root, tf3_game, report.get('baseResourceReplacements', [])):
                        raise ValueError('TF2 base resources used to select native mappings changed during conversion. Export needs review.')
                    if native and not native.verify_current(
                            report.get('nativeInventoryFingerprint', native.inventory_fingerprint()),
                            report.get('nativeResourceFingerprints',{})):
                        raise ValueError('TF3 resources changed during conversion. Export needs review.')
                    if not _source_game_valid(root, tf3_game, report):
                        raise ValueError('Referenced TF2 installation or resources changed during conversion. Export needs review.')
                    if file_fingerprint(root) != before:
                        raise ValueError('Source changed during conversion. Export needs review.')
                    data_added = _tf3_data_added(report)
                    state['receipts'][item.key] = {'status': 'completed', 'modId': item.mod_id,
                                                  'sourceFingerprint': before, 'outputFingerprint': file_fingerprint(target),
                                                  'converterVersion': __version__, 'tf3Game': str(Path(tf3_game).resolve()) if tf3_game else None,
                                                  'conversionChoices': choices,
                                                  'nativeInventory': native.inventory_fingerprint() if native else None,
                                                  'nativeResources': report.get('nativeResourceFingerprints',{}) if native else {},
                                                  'workshopResources': report.get('workshopResourceFingerprints', {}),
                                                  'workshopDependencies': migration_audit.get('workshopDependencies', []),
                                                  'baseResourceReplacements': report.get('baseResourceReplacements', []),
                                                  'sourceGameDependencies': report.get('sourceGameDependencies', []),
                                                  'sourceGameResourceFingerprints': report.get('sourceGameResourceFingerprints', {}),
                                                  'sourceGameInventoryFingerprint': report.get('sourceGameInventoryFingerprint'),
                                                  'sourceGameInstallation': report.get('sourceGameInstallation'),
                                                  'workshopAbsentDependencies': report.get('workshopAbsentDependencies', []),
                                                  'tf3DataAdded': data_added}
                    vehicle_warnings = migration_audit.get('vehicleWarnings', [])
                    state['receipts'][item.key]['vehicleWarnings'] = vehicle_warnings
                    item.message = (f'Export saved · {len(vehicle_warnings)} warnings' if vehicle_warnings else
                                    'Export saved · TF3 data added' if data_added else 'Export saved')
                item.status = 'completed'
            except Exception as exc:
                item.status, item.message = 'failed', str(exc)
                state['diagnostics'][item.key] = {'exceptionType':type(exc).__name__,
                    'message':str(exc), 'traceback':traceback.format_exc()}
            state['items'] = [asdict(i) for i in items]
            _save_state(output, state)  # A durable receipt precedes the green checkmark.
            if event:
                event('item', {'key': item.key, 'status': item.status, 'message': item.message, 'index': index + 1, 'total': len(items), 'destination': str(target)})
        state['items'] = [asdict(i) for i in items]
        state['counts'] = {s: sum(i.status == s for i in items) for s in ('completed', 'failed', 'pending')}
        _save_state(output, state)
        return state

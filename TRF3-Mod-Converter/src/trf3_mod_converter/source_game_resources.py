"""Exact installed TF2 inputs for the existing category adapters.

This module does not export files, execute Lua, or assert native equivalence.
Descriptors must still pass the caller's TF3 category adapter. Binary mesh and
animation structure is checked before source bytes can enter a draft export.
"""
from __future__ import annotations

from copy import deepcopy
from collections import OrderedDict
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import threading
import wave
import zipfile

from luaparser import ast, astnodes as lua

from .base_resources import TF2Inventory, VerifiedReadZipFile, normalize_reference, source_resource
from .filesystem import linked
from .lua_metadata import UnsupportedValue, TranslatedString


_format_proofs = OrderedDict()
_format_proof_lock = threading.RLock()


def _format_proof(key, validate):
    # Callers freshly read and hash every input before asking for a proof.
    # The validator identity prevents reuse after a validator is replaced.
    with _format_proof_lock:
        if key not in _format_proofs:
            _format_proofs[key] = validate()
        _format_proofs.move_to_end(key)
        while len(_format_proofs) > 2048:
            _format_proofs.popitem(last=False)
        return deepcopy(_format_proofs[key])
from .resource_profiles import load_resource_table, TranslatedConcat


ENDINGS = {'texture': ('.dds', '.tga', '.hdr'), 'material': ('.mtl',),
           'mesh': ('.msh',), 'mesh_blob': ('.msh.blob',),
           'animation': ('.ani',), 'audio': ('.wav', '.ogg'),
           'sound_set': ('.lua',), 'model': ('.mdl',)}
ATTRIBUTES = {'attrOffsetLOD', 'normal', 'position', 'positionAmbient', 'offset',
              'tangent', 'jointWeights', 'uv0', 'uv1'}
SCHEMA_SOURCES = (
    'https://www.wiki.transportfever2.com/doku.php?id=modding:resourcetypes:msh',
    'https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes:msh',
    'https://www.wiki.transportfever2.com/doku.php?id=modding:resourcetypes',
    'https://wiki.transportfever3.com/doku.php?id=modding:general:resourcetypes',
)


def _resource(reference, kind):
    reference = normalize_reference(reference)
    if kind not in ENDINGS:
        raise ValueError(f'Unsupported installed TF2 adaptation category: {kind}')
    if kind == 'sound_set' and reference.endswith('.lua'):
        reference = reference[:-4]
    resource = (source_resource('mesh', reference) if kind == 'mesh_blob'
                else source_resource(kind, reference))
    if not resource.endswith(ENDINGS[kind]):
        raise ValueError(f'Wrong installed TF2 {kind} resource suffix: {reference}')
    return reference, resource


def _literal(value, where):
    if isinstance(value, (UnsupportedValue, TranslatedString, TranslatedConcat)):
        raise ValueError(f'{where}: dynamic or translated installed TF2 descriptor needs a separate adapter')
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError(f'{where}: non-finite descriptor number')
    elif value is None or type(value) in (str, bool):
        pass
    elif isinstance(value, dict):
        for key, item in value.items():
            _literal(key, where+'/key'); _literal(item, where+'/'+str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _literal(item, where+'/'+str(index))
    else:
        raise ValueError(f'{where}: unsupported installed TF2 descriptor value')


def _source_text(data, resource):
    try:
        text = data.decode('utf-8-sig')
        tree = ast.parse(text)
    except (UnicodeError, SyntaxError, ValueError, ast.SyntaxException) as error:
        raise ValueError(f'{resource}: invalid installed TF2 Lua descriptor') from error
    for node in ast.walk(tree):
        if isinstance(node, lua.Call) and isinstance(node.func, lua.Name) and node.func.id == '_':
            raise ValueError(f'{resource}: installed TF2 localization keys need a verified game locale adapter')
    return text


def _table(data, resource):
    table = load_resource_table(_source_text(data, resource))
    _literal(table, resource)
    if not isinstance(table, dict):
        raise ValueError(f'{resource}: expected a literal named resource table')
    return table


def _span(value, limit, where, components=1):
    if (not isinstance(value, dict) or set(value) != {'offset', 'count'}
            or any(type(value.get(key)) is not int for key in ('offset', 'count'))):
        raise ValueError(f'{where}: expected integer offset/count byte span')
    offset, count = value['offset'], value['count']
    if offset < 0 or count <= 0 or offset % 4 or count % (4*components) or offset+count > limit:
        raise ValueError(f'{where}: invalid or truncated byte span')
    return offset, offset+count


def validate_mesh_pair(descriptor: bytes, blob: bytes, resource: str = '') -> dict:
    """Validate the installed byte-count/index convention without modifying it."""
    data = _table(descriptor, resource)
    if set(data) != {'subMeshes', 'vertexAttr'} or not isinstance(data['vertexAttr'], dict):
        raise ValueError(f'{resource}: unsupported installed TF2 mesh schema')
    attributes = data['vertexAttr']
    if not attributes or set(attributes)-ATTRIBUTES or 'position' not in attributes:
        raise ValueError(f'{resource}: unsupported mesh vertex attributes')
    spans, capacities, proof = [], {}, []
    for name, value in attributes.items():
        if (not isinstance(value, dict) or set(value) != {'offset', 'count', 'numComp'}
                or type(value['numComp']) is not int or not 1 <= value['numComp'] <= 16):
            raise ValueError(f'{resource}/{name}: unsupported mesh attribute layout')
        components = value['numComp']
        start, end = _span({k: value[k] for k in ('offset', 'count')}, len(blob), resource+'/'+name, components)
        if not all(math.isfinite(number[0]) for number in struct.iter_unpack('<f', blob[start:end])):
            raise ValueError(f'{resource}/{name}: non-finite mesh attribute')
        capacities[name] = value['count']//(4*components)
        spans.append((start, end))
        proof.append({'attribute': name, 'offset': start, 'bytes': end-start,
                      'items': capacities[name], 'components': components})
    submeshes = data['subMeshes']
    if not isinstance(submeshes, list) or not submeshes:
        raise ValueError(f'{resource}: expected nonempty mesh subMeshes')
    index_proof = []
    for slot, part in enumerate(submeshes):
        if (not isinstance(part, dict) or set(part)-{'indices', 'materials'}
                or not isinstance(part.get('indices'), dict)
                or set(part['indices']) != set(attributes)):
            raise ValueError(f'{resource}/{slot}: unsupported mesh index layout')
        if 'materials' in part and (not isinstance(part['materials'], list)
                                   or not all(type(value) is str for value in part['materials'])):
            raise ValueError(f'{resource}/{slot}: expected literal legacy default materials')
        count = None
        for name, value in part['indices'].items():
            start, end = _span(value, len(blob), f'{resource}/{slot}/{name}')
            indices = [value[0] for value in struct.iter_unpack('<I', blob[start:end])]
            if len(indices) % 3 or any(value >= capacities[name] for value in indices):
                raise ValueError(f'{resource}/{slot}/{name}: index outside attribute or incomplete triangles')
            if count is not None and count != len(indices):
                raise ValueError(f'{resource}/{slot}: mesh attributes have different index counts')
            count = len(indices)
            spans.append((start, end))
            index_proof.append({'submesh': slot, 'attribute': name, 'offset': start,
                                'bytes': end-start, 'indices': len(indices), 'maxIndex': max(indices)})
    ordered = sorted(spans)
    if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
        raise ValueError(f'{resource}: overlapping mesh data spans are outside the verified profile')
    return {'policy': 'shared_mesh_schema_unchanged_geometry', 'submeshCount': len(submeshes),
            'blobBytes': len(blob), 'attributes': proof, 'indices': index_proof,
            'nativeTest': 'not_run', 'schemaSources': list(SCHEMA_SOURCES[:2])}


def validate_animation(data: bytes, resource: str = '') -> dict:
    table = _table(data, resource)
    times, transfs = table.get('times'), table.get('transfs')
    numeric = lambda value: type(value) in (int, float) and math.isfinite(value)
    if (set(table) != {'times', 'transfs'} or not isinstance(times, list) or not times
            or not all(numeric(value) for value in times) or times[0] != 0
            or any(left > right for left, right in zip(times, times[1:]))
            or not isinstance(transfs, list) or len(times) != len(transfs)
            or any(not isinstance(value, list) or len(value) != 16 or not all(numeric(v) for v in value)
                   for value in transfs)):
        raise ValueError(f'{resource}: unsupported installed TF2 animation schema')
    return {'policy': 'shared_literal_animation_schema', 'keyframes': len(times),
            'durationMs': times[-1], 'nativeTest': 'not_run', 'schemaSources': list(SCHEMA_SOURCES[2:])}


def _texture(data, suffix, resource):
    if suffix == '.dds':
        if len(data) < 128 or data[:4] != b'DDS ' or struct.unpack_from('<I', data, 4)[0] != 124:
            raise ValueError(f'{resource}: malformed DDS header')
        height, width = struct.unpack_from('<II', data, 12)
        mipmaps = struct.unpack_from('<I', data, 28)[0] or 1
        fourcc = data[84:88]
        blocks = {b'DXT1': 8, b'DXT3': 16, b'DXT5': 16, b'ATI1': 8, b'ATI2': 16,
                  b'BC4U': 8, b'BC4S': 8, b'BC5U': 16, b'BC5S': 16}
        if (width <= 0 or height <= 0 or struct.unpack_from('<I', data, 76)[0] != 32
                or fourcc not in blocks or mipmaps > max(width, height).bit_length()
                or struct.unpack_from('<I', data, 112)[0] != 0):
            raise ValueError(f'{resource}: DDS layout is outside the verified 2D legacy block-compressed profile')
        payload = sum(max(1, (max(1, width>>level)+3)//4)*max(1, (max(1, height>>level)+3)//4)
                      * blocks[fourcc] for level in range(mipmaps))
        if len(data) != 128+payload:
            raise ValueError(f'{resource}: truncated or unrecognized DDS payload')
        return {'policy': 'unchanged_legacy_dds', 'width': width, 'height': height,
                'mipmaps': mipmaps, 'fourCC': fourcc.decode('ascii')}
    if suffix == '.hdr':
        marker = re.search(rb'\r?\n\r?\n(-Y|\+Y) (\d+) ([+-]X) (\d+)\r?\n', data)
        if (not data.startswith((b'#?RADIANCE\n', b'#?RGBE\n')) or marker is None
                or b'FORMAT=32-bit_rle_rgbe' not in data[:marker.start()]):
            raise ValueError(f'{resource}: unrecognized Radiance HDR header')
        height, width = int(marker.group(2)), int(marker.group(4))
        if not width or not height:
            raise ValueError(f'{resource}: invalid HDR dimensions')
        cursor = marker.end()
        for _ in range(height):
            if cursor+4 > len(data):
                raise ValueError(f'{resource}: truncated HDR scanline')
            header = data[cursor:cursor+4]
            if not (8 <= width <= 32767 and header[:2] == b'\x02\x02' and not header[2]&128):
                # Old flat RGBE is safe only when the entire image is present
                # and has no old run-length marker requiring a different decoder.
                remaining = data[cursor:]
                if len(remaining) != (height-_)*width*4 or any(
                        remaining[index:index+3] == b'\x01\x01\x01' for index in range(0,len(remaining),4)):
                    raise ValueError(f'{resource}: unsupported or truncated old HDR encoding')
                cursor = len(data); break
            if int.from_bytes(header[2:], 'big') != width:
                raise ValueError(f'{resource}: HDR scanline width changed')
            cursor += 4
            for _channel in range(4):
                pixels = 0
                while pixels < width:
                    if cursor >= len(data): raise ValueError(f'{resource}: truncated HDR run')
                    run = data[cursor]; cursor += 1
                    count = run-128 if run > 128 else run
                    consumed = 1 if run > 128 else count
                    if not count or pixels+count > width or cursor+consumed > len(data):
                        raise ValueError(f'{resource}: invalid HDR run')
                    cursor += consumed; pixels += count
        if cursor != len(data): raise ValueError(f'{resource}: unexpected HDR trailing bytes')
        return {'policy': 'unchanged_radiance_hdr', 'width': width, 'height': height}
    if suffix == '.tga':
        if len(data) < 18:
            raise ValueError(f'{resource}: truncated TGA header')
        image_id, color_map, image_type = data[:3]
        width, height = struct.unpack_from('<HH', data, 12)
        depth = data[16]
        allowed_depths = (8, 16) if image_type in (3, 11) else (16, 24, 32)
        if color_map != 0 or image_type not in (2, 3, 10, 11) or not width or not height or depth not in allowed_depths:
            raise ValueError(f'{resource}: TGA layout is outside the verified profile')
        cursor, pixels, pixel_bytes = 18+image_id, 0, depth//8
        if image_type in (2,3):
            cursor += width*height*pixel_bytes
        else:
            while pixels < width*height:
                if cursor >= len(data): raise ValueError(f'{resource}: truncated TGA run')
                packet = data[cursor]; cursor += 1
                count = (packet&127)+1
                cursor += pixel_bytes*(1 if packet&128 else count); pixels += count
                if pixels > width*height: raise ValueError(f'{resource}: oversized TGA run')
        if cursor > len(data): raise ValueError(f'{resource}: truncated TGA payload')
        return {'policy': 'unchanged_legacy_tga', 'width': width, 'height': height, 'bits': depth}
    raise ValueError(f'{resource}: unsupported texture format')


def _audio(data, suffix, resource):
    if suffix == '.wav':
        if len(data)<12 or data[:4]!=b'RIFF' or data[8:12]!=b'WAVE' or struct.unpack_from('<I',data,4)[0]+8!=len(data):
            raise ValueError(f'{resource}: malformed WAV container')
        try:
            with wave.open(io.BytesIO(data)) as stream:
                frames = stream.getnframes()
                expected = frames*stream.getnchannels()*stream.getsampwidth()
                if frames <= 0 or len(stream.readframes(frames)) != expected:
                    raise ValueError(f'{resource}: truncated WAV sample data')
                return {'policy': 'unchanged_pcm_wav', 'channels': stream.getnchannels(),
                        'sampleRate': stream.getframerate(), 'frames': frames}
        except (wave.Error, EOFError) as error:
            raise ValueError(f'{resource}: WAV encoding is outside the verified PCM profile') from error
    if suffix == '.ogg':
        # Pages are bounded; identification must be a Vorbis stream. No codec
        # decoding or source code execution occurs here.
        cursor, pages = 0, 0
        while cursor < len(data):
            if cursor+27>len(data) or data[cursor:cursor+5]!=b'OggS\x00':
                raise ValueError(f'{resource}: malformed Ogg page')
            segments=data[cursor+26]
            end=cursor+27+segments
            if end>len(data): raise ValueError(f'{resource}: truncated Ogg segments')
            size=sum(data[cursor+27:end]); payload=data[end:end+size]
            if len(payload)!=size or (pages==0 and not payload.startswith(b'\x01vorbis')):
                raise ValueError(f'{resource}: unsupported or truncated Ogg stream')
            cursor=end+size;pages+=1
        if not pages: raise ValueError(f'{resource}: empty Ogg stream')
        return {'policy': 'unchanged_vorbis_ogg', 'pages': pages}
    raise ValueError(f'{resource}: unsupported audio format')


class SourceGameResources:
    """Per-export exact base input reader with selected mount and SHA provenance."""
    def __init__(self, inventory: TF2Inventory):
        if not isinstance(inventory, TF2Inventory):
            raise ValueError('Installed TF2 adaptation requires a TF2Inventory')
        self.inventory = inventory
        self.game = inventory.content.parent.resolve()
        self._rows = {}
        self._fingerprints = {}
        self._animation_validation = {}

    def _read(self, resource, reference, kind):
        if resource not in self.inventory.files:
            return None
        container, member = self.inventory.files[resource]
        container = Path(container)
        if linked(container) or any(linked(parent) for parent in container.parents if parent != self.game.parent):
            raise ValueError(f'Linked installed TF2 input is not supported: {container}')
        try:
            relative = container.resolve().relative_to(self.inventory.content.resolve()).as_posix()
        except ValueError as error:
            raise ValueError(f'Installed TF2 input escapes its resource root: {container}') from error
        if member is not None:
            normalize_reference(member)
            with VerifiedReadZipFile(container) as archive:
                entry=archive.getinfo(member)
                if (entry.external_attr >> 16)&0o170000 == 0o120000:
                    raise ValueError(f'Linked installed TF2 zip member is not supported: {member}')
        data=self.inventory.read(resource)
        row={'kind':kind,'sourceReference':reference,'sourceResource':'res/'+resource,
             'sourceGame':str(self.game),'sourceContainer':'res/'+relative,
             'sourceMember':member,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
             'sourceOrigin':'installed_tf2_base','nativeTest':'not_run'}
        return {'data':data,**row}

    def _remember(self, match):
        row={key:deepcopy(value) for key,value in match.items() if key!='data'}
        key=(row['kind'],row['sourceResource'])
        previous=self._rows.get(key)
        if previous is not None and previous != row:
            raise ValueError(f'Installed TF2 resource changed during adaptation: {row["sourceResource"]}')
        self._rows[key]=row
        self._fingerprints[row['sourceResource']]=row['sha256']

    def resolve(self, reference: str, kind: str):
        reference, resource = _resource(reference,kind)
        match=self._read(resource,reference,kind)
        if match is None: return None
        data=match['data']
        if kind in ('mesh','mesh_blob'):
            mesh_ref=reference[:-5] if kind=='mesh_blob' else reference
            mesh_resource=resource[:-5] if kind=='mesh_blob' else resource
            descriptor=self._read(mesh_resource,mesh_ref,'mesh')
            blob=self._read(mesh_resource+'.blob',mesh_ref+'.blob','mesh_blob')
            if descriptor is None or blob is None:
                raise ValueError(f'{mesh_resource}: exact installed TF2 mesh/blob pair is incomplete')
            proof=_format_proof((validate_mesh_pair,mesh_resource,descriptor['sha256'],blob['sha256']),
                                lambda:validate_mesh_pair(descriptor['data'],blob['data'],mesh_resource))
            descriptor['validation']=proof
            blob['validation']={**proof,'descriptorSha256':descriptor['sha256']}
            self._remember(descriptor);self._remember(blob)
            return descriptor if kind=='mesh' else blob
        if kind=='animation':
            key=(resource,match['sha256'])
            if key not in self._animation_validation:
                self._animation_validation[key]=_format_proof((validate_animation,resource,match['sha256']),
                                                            lambda:validate_animation(data,resource))
            match['validation']=deepcopy(self._animation_validation[key])
        elif kind=='texture':
            match['validation']=_texture(data,PurePosixPath(resource).suffix,resource)
        elif kind=='audio':
            match['validation']=_audio(data,PurePosixPath(resource).suffix,resource)
        elif kind=='sound_set':
            _source_text(data,resource)
            match['validation']={'policy':'requires_verified_sound_category_adapter','nativeTest':'not_run'}
        else:
            _table(data,resource)
            match['validation']={'policy':'requires_verified_category_adapter','nativeTest':'not_run'}
        self._remember(match)
        return match

    @property
    def rows(self):
        return [deepcopy(row) for _,row in sorted(self._rows.items())]

    @property
    def fingerprints(self):
        return dict(self._fingerprints)

    def inventory_fingerprint(self):
        """Catalog/mount selection and metadata; referenced bytes use SHA separately."""
        rows=[]; archives={}
        for resource,(container,member) in sorted(self.inventory.files.items()):
            container=Path(container)
            relative=container.relative_to(self.inventory.content).as_posix()
            if member is None:
                stat=container.stat();metadata=[stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
            else:
                if container not in archives:
                    with zipfile.ZipFile(container) as archive:
                        archives[container]={entry.filename:[entry.CRC,entry.file_size,entry.external_attr]
                                             for entry in archive.infolist()}
                metadata=archives[container][member]
            rows.append([resource,relative,member,metadata])
        return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def verify_source_game_dependencies(game, rows, fingerprints, inventory_fingerprint=None):
    """Freshly verify mount selection and actual bytes; empty old receipts are valid."""
    if not rows and not fingerprints and inventory_fingerprint is None: return True
    if not isinstance(rows,list) or not isinstance(fingerprints,dict): return False
    try:
        resolver=SourceGameResources(TF2Inventory(Path(game)))
        if inventory_fingerprint is not None and resolver.inventory_fingerprint()!=inventory_fingerprint:
            return False
        seen=set()
        for row in rows:
            if not isinstance(row,dict): return False
            reference,kind=row.get('sourceReference'),row.get('kind')
            current=resolver.resolve(reference,kind)
            if current is None: return False
            key=(kind,current['sourceResource'])
            if key in seen: return False
            seen.add(key)
            # Category adapters may append their audited target/archival policy.
            # All input evidence remains mandatory and must match freshly.
            if any(row.get(key) != value for key,value in current.items() if key!='data'):
                return False
        expected={(row['kind'],row['sourceResource']) for row in resolver.rows}
        return expected==seen and resolver.fingerprints==fingerprints
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,struct.error):
        return False

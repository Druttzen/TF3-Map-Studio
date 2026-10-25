"""Find local elevation candidates from file metadata, without reading samples.

Search extents are conservative header bounding boxes, not proof of valid ground
coverage. Actual import still validates raster cells, classified points and units.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import warnings

import laspy
from pyproj import CRS, Transformer
import rasterio

from alignment import osm
from job import Job

MAX_FILES = 10000
MAX_DIRECTORIES = 10000
MAX_RESULTS = 1000
MAX_WARNINGS = 100
CACHE_VERSION = 2
SUFFIXES = {'.tif', '.tiff', '.asc', '.hgt', '.las', '.laz'}


def _identity(path):
    stat = path.stat()
    result = [str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    # GeoTIFF/ASCII metadata may live in a PRJ, auxiliary XML or world file.
    if path.suffix.lower() not in {'.las', '.laz'}:
        sidecars = {Path(str(path) + '.aux.xml'), path.with_suffix('.prj'),
                    path.with_suffix('.tfw'), path.with_suffix('.tifw'),
                    path.with_suffix('.wld')}
        for companion in sorted(sidecars):
            try:
                info = companion.stat()
                result.append([str(companion), info.st_size,
                               info.st_mtime_ns, info.st_ctime_ns])
            except FileNotFoundError:
                result.append([str(companion), None])
    return result


def _horizontal(crs):
    crs = CRS.from_user_input(crs)
    if crs.is_compound:
        crs = next((part for part in crs.sub_crs_list
                    if part.is_projected or part.is_geographic), None)
        if crs is None:
            raise ValueError('No horizontal coordinate system is recorded.')
    return crs.to_2d()


def _geographic_bbox(crs, box):
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError('The file header has invalid bounds.')
    if box[0] > box[2] or box[1] > box[3]:
        raise ValueError('The file header has reversed bounds.')
    box = list(Transformer.from_crs(_horizontal(crs), 'EPSG:4326',
                                   always_xy=True).transform_bounds(
                                       *box, densify_pts=21, errcheck=True))
    if not all(math.isfinite(v) for v in box):
        raise ValueError('File bounds cannot be projected into map coordinates.')
    if box[0] > box[2] or box[0] < -180 or box[2] > 180 or box[1] < -90 or box[3] > 90:
        raise ValueError('File bounds cross the date line or need manual review.')
    return box


def _vertical_name(crs):
    if crs.is_compound:
        vertical = next((part for part in crs.sub_crs_list if part.is_vertical), None)
        if vertical is not None:
            return vertical.name
    return 'Unknown / unchanged'


def _read_metadata(path):
    """Read GDAL/LAS header metadata only. Never call read/chunk_iterator."""
    if path.suffix.lower() == '.hgt' or path.name.lower().endswith('.hgt.gz'):
        # HGT has no coordinate header; GDAL derives its tile location from
        # the filename. Do not advertise that as a verified location. Opening
        # compressed HGT can also decompress the whole source for dimensions.
        return {'kind': 'raster', 'crs': '', 'bbox': None,
                'resolution': 'Headerless HGT; inspect after adding',
                'verticalDatum': 'Unknown / unchanged',
                'surface': 'HGT location depends on its filename; review it manually. Discovery did not read raster samples or decompress the file.',
                'needsReview': True}
    if path.suffix.lower() in {'.las', '.laz'}:
        with laspy.open(path, read_evlrs=False) as source:
            header = source.header
            crs = header.parse_crs()
            count = int(header.point_count)
            if count == 0:
                raise ValueError('The point-cloud header records no points.')
            box = [float(header.mins[0]), float(header.mins[1]),
                   float(header.maxs[0]), float(header.maxs[1])]
            metadata = {'kind': 'pointcloud', 'crs': '', 'bbox': None,
                        'pointCount': count,
                        'resolution': f'{count:,} points; ground density not inspected',
                        'verticalDatum': 'Unknown / unchanged',
                        'surface': 'LAS/LAZ/COPC header only; import uses classified ground (class 2). Verify vertical units before import.',
                        'needsReview': crs is None}
            if crs is not None:
                crs = CRS.from_user_input(crs)
                metadata.update(crs=crs.to_string(), bbox=_geographic_bbox(crs, box),
                                verticalDatum=_vertical_name(crs))
            return metadata
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always', rasterio.errors.NotGeoreferencedWarning)
        source = rasterio.open(path)
    with source:
        if source.width < 1 or source.height < 1 or source.count < 1:
            raise ValueError('The raster header has no usable grid.')
        colours = {value.name.lower() for value in source.colorinterp}
        # A photograph with RGB bands is not a measured elevation model.
        imagery = {'red', 'green', 'blue'}.issubset(colours)
        tags = source.tags()
        crs = CRS.from_user_input(source.crs) if source.crs else None
        missing_geotransform = any(isinstance(note.message, rasterio.errors.NotGeoreferencedWarning)
                                   for note in notices)
        has_gcps = bool(source.gcps[0])
        has_rpcs = source.rpcs is not None
        affine = source.transform
        valid_affine = (all(math.isfinite(float(v)) for v in affine)
                        and affine.a * affine.e - affine.b * affine.d != 0)
        verified_affine = not (missing_geotransform or has_gcps or has_rpcs) and valid_affine
        extent = source.bounds
        # South-up and explicitly recorded identity transforms are legitimate;
        # their named bottom/top bounds may be numerically reversed.
        box = [min(extent.left, extent.right), min(extent.bottom, extent.top),
               max(extent.left, extent.right), max(extent.bottom, extent.top)]
        spacing = [abs(float(v)) for v in source.res]
        unit = (_horizontal(crs).axis_info[0].unit_name
                if crs and _horizontal(crs).axis_info else 'unknown units')
        metadata = {'kind': 'raster', 'crs': crs.to_string() if crs else '',
                    'bbox': _geographic_bbox(crs, box) if crs and verified_affine else None,
                    'resolution': f'{spacing[0]:g} × {spacing[1]:g} {unit} cells',
                    'verticalDatum': tags.get('VERTICAL_DATUM') or (_vertical_name(crs) if crs else 'Unknown / unchanged'),
                    'surface': 'Georeferenced raster header; verify that it records measured ground elevation.',
                    'needsReview': crs is None or not verified_affine or source.count != 1,
                    'imagery': imagery, 'bands': int(source.count)}
        if has_gcps or has_rpcs:
            metadata['surface'] = 'Raster uses ground-control points or RPC georeferencing; review and resample it before importing. An affine map footprint was not assumed.'
        elif not verified_affine:
            metadata['surface'] = 'No valid recorded affine geotransform was found. Pixel indices were not treated as map coordinates.'
        return metadata


def _overlaps(box, bounds):
    south, west, north, east = bounds
    # Boundary tiles may supply interpolation at a map corner; retain touches.
    return box[0] <= east and box[2] >= west and box[1] <= north and box[3] >= south


def _load_cache(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('version') == CACHE_VERSION and isinstance(value.get('files'), dict):
            return value['files']
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def _valid_cached_metadata(value):
    if not isinstance(value, dict) or value.get('kind') not in {'raster', 'pointcloud'}:
        return False
    if not all(isinstance(value.get(key), str)
               for key in ('crs', 'resolution', 'verticalDatum', 'surface')):
        return False
    box = value.get('bbox')
    if box is not None and (not isinstance(box, list) or len(box) != 4
                            or not all(type(v) in {int, float} and math.isfinite(v) for v in box)):
        return False
    return type(value.get('needsReview')) is bool


def _save_cache(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.local-index-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump({'version': CACHE_VERSION, 'files': entries}, output, allow_nan=False)
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def discover_local(folder, bounds, cache, job=None):
    """Find header-overlapping local files, preserving unknown-CRS candidates.

    ``paths`` contains known-overlap candidates suitable for adding to the
    Elevation file list; import still verifies their actual samples and units.
    Symlinks are deliberately not followed. Limits and failures are explicit.
    """
    job = job or Job()
    job.check()
    osm.validate_bounds(bounds, [1, 1])
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError('Choose an existing local LiDAR/elevation folder.')
    cache = Path(cache)
    cache_file = cache / ('local-index-' + hashlib.sha256(str(folder).encode()).hexdigest()[:20] + '.json')
    old = _load_cache(cache_file)
    entries = {}
    rows = []
    warnings = []
    scanned = cached = outside = unknown = directories = skipped_links = ignored = found = 0
    incomplete = False

    def warn(message):
        nonlocal incomplete
        incomplete = True
        if len(warnings) < MAX_WARNINGS and message not in warnings:
            warnings.append(message)

    pending = [folder]
    stopped = False
    while pending and not stopped:
        job.check()
        directory = pending.pop()
        directories += 1
        if directories > MAX_DIRECTORIES:
            warn(f'Folder search reached {MAX_DIRECTORIES:,} directories. Choose a narrower folder for the remaining data.')
            break
        try:
            with os.scandir(directory) as listing:
                for item in listing:
                    job.check()
                    if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                        skipped_links += 1
                        continue
                    if item.is_dir(follow_symlinks=False):
                        if len(pending) + directories >= MAX_DIRECTORIES:
                            warn(f'Folder search reached {MAX_DIRECTORIES:,} directories. Choose a narrower folder for the remaining data.')
                        else:
                            pending.append(Path(item.path))
                        continue
                    path = Path(item.path)
                    if not item.is_file(follow_symlinks=False) or (path.suffix.lower() not in SUFFIXES and not path.name.lower().endswith('.hgt.gz')):
                        continue
                    if scanned >= MAX_FILES:
                        warn(f'Folder search reached {MAX_FILES:,} elevation files. Choose a narrower folder for the remaining data.')
                        stopped = True
                        break
                    scanned += 1
                    job.update(min(90, 5 + scanned / MAX_FILES * 80),
                               'Searching local elevation files', f'{scanned:,} checked · {found:,} match map · {path.name}')
                    key = str(path.resolve())
                    try:
                        identity = _identity(path)
                        previous = old.get(key, {})
                        if (isinstance(previous, dict) and previous.get('identity') == identity
                                and _valid_cached_metadata(previous.get('metadata'))):
                            metadata = previous['metadata']
                            cached += 1
                        else:
                            metadata = _read_metadata(path)
                            if _identity(path) != identity:
                                raise ValueError('The file changed while its header was being inspected.')
                        entries[key] = {'identity': identity, 'metadata': metadata}
                    except Exception as exc:
                        # Failed files are not cached, so repairing them permits
                        # discovery on the next search even without a cache reset.
                        warn(f'{path.name}: could not inspect metadata ({str(exc)[:250]}). Add manually only after checking the file.')
                        metadata = {'kind': 'pointcloud' if path.suffix.lower() in {'.las', '.laz'} else 'raster',
                                    'crs': '', 'bbox': None, 'resolution': 'Header unavailable',
                                    'verticalDatum': 'Unknown / unchanged',
                                    'surface': 'Metadata could not be read; manual review required.',
                                    'needsReview': True}
                    if metadata.get('imagery'):
                        ignored += 1
                        warn(f'{path.name}: RGB imagery was excluded; photographs are not ground elevation.')
                        continue
                    box = metadata.get('bbox')
                    if box is not None and not _overlaps(box, bounds):
                        outside += 1
                        continue
                    coverage = 'overlap' if box is not None else 'unknown'
                    if coverage == 'unknown':
                        unknown += 1
                    else:
                        found += 1
                    if len(rows) >= MAX_RESULTS:
                        warn(f'Result list limited to {MAX_RESULTS:,} files. Choose a narrower folder to inspect additional matches.')
                        # Unknown-location files must not crowd a verified map
                        # match out of the bounded result list.
                        replace = next((index for index, row in enumerate(rows)
                                        if row['coverage'] == 'unknown'), None) if coverage == 'overlap' else None
                        if replace is None:
                            continue
                        rows.pop(replace)
                    rows.append({**metadata, 'id': 'local-' + hashlib.sha256(key.encode()).hexdigest()[:20],
                                 'path': key, 'name': path.name, 'provider': 'Local files',
                                 'access': 'local', 'assets': [], 'site': '',
                                 'coverage': coverage})
        except OSError as exc:
            warn(f'Could not search {directory.name}: {str(exc)[:250]}')
    if skipped_links:
        warn(f'{skipped_links:,} symbolic links were skipped; linked folders were not searched.')
    if unknown:
        warn(f'{unknown:,} files have no verified map extent. They remain listed for manual review; their location was not guessed from filenames.')
    job.check()
    try:
        _save_cache(cache_file, entries)
    except OSError:
        warn('Local metadata cache could not be saved. Search results are still available.')
    rows.sort(key=lambda row: (row['coverage'] != 'overlap', row['name'].casefold(), row['path'].casefold()))
    job.update(100, 'Local folder search complete', f'{found:,} match map · {unknown:,} need review', force=True)
    return {'rows': rows, 'warnings': warnings, 'complete': not incomplete,
            'scanned': scanned, 'cached': cached, 'outside': outside,
            'unknown': unknown, 'directories': directories,
            'skippedSymlinks': skipped_links, 'ignoredImagery': ignored,
            'matched': found, 'folder': str(folder), 'bounds': list(bounds),
            'paths': [row['path'] for row in rows
                      if row['coverage'] == 'overlap' and not row.get('needsReview')]}

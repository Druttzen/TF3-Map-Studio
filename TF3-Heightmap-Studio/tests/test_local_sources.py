"""Metadata-only local elevation discovery, map overlap and cache integrity."""
import gzip
import json
from pathlib import Path
import sys
import threading
import warnings
from unittest.mock import patch

import laspy
import numpy as np
from pyproj import CRS
import pytest
import rasterio
from rasterio.transform import from_bounds
from rasterio import Affine
from rasterio.control import GroundControlPoint

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import local_sources as local
from job import Cancelled, Job

BOUNDS = [0, 0, .01, .01]


def raster(path, box=(0, 0, 1000, 1000), crs='EPSG:3857', driver='GTiff', rgb=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, 'w', driver=driver, width=8, height=8,
                       count=3 if rgb else 1, dtype='uint8' if rgb else 'float32',
                       crs=crs, transform=from_bounds(*box, 8, 8)) as target:
        target.write(np.ones((3 if rgb else 1, 8, 8), dtype='uint8' if rgb else 'float32'))
    return path


def pointcloud(path, crs=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = laspy.LasHeader(point_format=6, version='1.4')
    if crs:
        header.add_crs(CRS.from_epsg(3857))
    data = laspy.LasData(header)
    data.x = [200, 300, 400]
    data.y = [200, 300, 400]
    data.z = [10, 11, 12]
    data.classification = np.array([2, 2, 2], dtype='uint8')
    data.write(path)
    return path


def test_recursive_header_search_matches_map_and_excludes_outside(tmp_path):
    folder = tmp_path/'data'
    inside = raster(folder/'nested/inside.tif')
    raster(folder/'outside.tiff', box=(50000, 50000, 51000, 51000))
    (folder/'not-elevation.txt').write_text('untouched')
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['scanned'] == 2 and result['outside'] == 1
    assert result['complete'] and result['matched'] == 1
    assert result['paths'] == [str(inside.resolve())]
    row = result['rows'][0]
    assert row['coverage'] == 'overlap' and row['crs'] == 'EPSG:3857'
    assert row['provider'] == 'Local files' and row['access'] == 'local'
    assert row['bbox'][2] == pytest.approx(.00898315284)


@pytest.mark.parametrize('suffix', ['.las', '.laz', '.copc.laz'])
def test_lidar_header_only_does_not_read_point_records(tmp_path, suffix):
    folder = tmp_path/'data'
    path = pointcloud(folder/('ground'+suffix))
    with (patch.object(laspy.LasReader, 'read', side_effect=AssertionError('No point reads')),
          patch.object(laspy.LasReader, 'chunk_iterator', side_effect=AssertionError('No point iteration'))):
        result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['paths'] == [str(path.resolve())]
    assert result['rows'][0]['kind'] == 'pointcloud'
    assert result['rows'][0]['pointCount'] == 3
    assert 'ground density not inspected' in result['rows'][0]['resolution']


def test_missing_crs_remains_candidate_without_guessing_its_location(tmp_path):
    folder = tmp_path/'data'
    pointcloud(folder/'looks-like-SWEREF99.las', crs=False)
    raster(folder/'unknown.asc', crs=None, driver='AAIGrid')
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['unknown'] == 2 and not result['complete']
    assert result['paths'] == []
    assert all(row['coverage'] == 'unknown' and row['needsReview'] for row in result['rows'])
    assert all(row['bbox'] is None for row in result['rows'])


def test_cache_reuses_header_and_invalidates_changed_file(tmp_path):
    folder = tmp_path/'data'; path = raster(folder/'ground.tif')
    with patch.object(local, '_read_metadata', wraps=local._read_metadata) as inspect:
        first = local.discover_local(folder, BOUNDS, tmp_path/'cache')
        second = local.discover_local(folder, BOUNDS, tmp_path/'cache')
        assert first['cached'] == 0 and second['cached'] == 1
        assert inspect.call_count == 1
        raster(path, box=(50000, 50000, 51000, 51000))
        third = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert third['cached'] == 0 and third['outside'] == 1
    assert inspect.call_count == 2


def test_new_prj_invalidates_unknown_crs_cache(tmp_path):
    folder = tmp_path/'data'; path = raster(folder/'ground.asc', crs=None, driver='AAIGrid')
    first = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert first['unknown'] == 1
    path.with_suffix('.prj').write_text(CRS.from_epsg(3857).to_wkt(version='WKT1_ESRI'))
    second = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert second['cached'] == 0 and second['matched'] == 1
    assert second['unknown'] == 0


def test_corrupt_header_is_not_cached_as_a_permanent_failure(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'broken.tif'
    path.write_bytes(b'broken raster')
    first = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert first['unknown'] == 1 and first['warnings']
    index = next((tmp_path/'cache').glob('local-index-*.json'))
    assert str(path.resolve()) not in json.loads(index.read_text())['files']
    raster(path)
    second = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert second['matched'] == 1 and second['cached'] == 0


def test_invalid_cached_metadata_is_reinspected(tmp_path):
    folder = tmp_path/'data'; path = raster(folder/'ground.tif')
    local.discover_local(folder, BOUNDS, tmp_path/'cache')
    index = next((tmp_path/'cache').glob('local-index-*.json'))
    value = json.loads(index.read_text()); value['files'][str(path.resolve())]['metadata']['bbox'] = 'broken'
    index.write_text(json.dumps(value))
    second = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert second['matched'] == 1 and second['cached'] == 0


def test_compressed_hgt_stays_manual_without_decompression(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'N57E012.hgt.gz'
    path.write_bytes(gzip.compress(b'not inspected during discovery'))
    before = path.read_bytes()
    with patch.object(local.rasterio, 'open', side_effect=AssertionError('No decompression')):
        result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['unknown'] == 1 and result['rows'][0]['needsReview']
    assert path.read_bytes() == before


def test_hgt_filename_does_not_prove_geographic_location(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'N00E000.hgt'
    path.write_bytes(b'not parsed as coordinates')
    with patch.object(local.rasterio, 'open', side_effect=AssertionError('No filename georeferencing')):
        result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['unknown'] == 1 and result['paths'] == []
    assert 'filename' in result['rows'][0]['surface']


def test_rgb_orthophoto_is_not_advertised_as_ground_elevation(tmp_path):
    folder = tmp_path/'data'; raster(folder/'photo.tif', rgb=True)
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['ignoredImagery'] == 1 and result['rows'] == []
    assert any('photographs are not ground elevation' in warning for warning in result['warnings'])


def test_non_rgb_multiband_raster_requires_review_before_automatic_add(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'multiple-bands.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=8, height=8, count=2,
                       dtype='float32', crs='EPSG:3857',
                       transform=from_bounds(0, 0, 1000, 1000, 8, 8)) as target:
        target.write(np.ones((2, 8, 8), dtype='float32'))
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['matched'] == 1 and result['rows'][0]['coverage'] == 'overlap'
    assert result['rows'][0]['needsReview'] and result['paths'] == []


def test_crs_without_geotransform_does_not_locate_pixels_on_map(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'unplaced.tif'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path, 'w', driver='GTiff', width=8, height=8, count=1,
                           dtype='float32', crs='EPSG:4326') as target:
            target.write(np.ones((1, 8, 8), dtype='float32'))
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['unknown'] == 1 and result['paths'] == []
    assert 'Pixel indices were not treated as map coordinates' in result['rows'][0]['surface']


def test_explicit_identity_geotransform_is_not_rejected_blindly(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'explicit-identity.tif'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path, 'w', driver='GTiff', width=8, height=8, count=1,
                           dtype='float32', crs='EPSG:4326', transform=Affine.identity()) as target:
            target.write(np.ones((1, 8, 8), dtype='float32'))
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['matched'] == 1 and result['paths'] == [str(path.resolve())]
    assert result['rows'][0]['bbox'] == [0, 0, 8, 8]


def test_rotated_affine_extent_is_read_without_raster_samples(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'rotated.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=8, height=8, count=1,
                       dtype='float32', crs='EPSG:3857',
                       transform=Affine(20, 5, 100, 4, -20, 500)) as target:
        target.write(np.ones((1, 8, 8), dtype='float32'))
    original_open = rasterio.open
    class HeaderOnly:
        def __init__(self, source):self.source = source
        def __enter__(self):return self
        def __exit__(self, *args):self.source.close()
        def __getattr__(self, name):
            if name in ('read', 'read_masks', 'sample'):
                raise AssertionError('Discovery must not read raster samples')
            return getattr(self.source, name)
    with patch.object(local.rasterio, 'open', side_effect=lambda *a, **k: HeaderOnly(original_open(*a, **k))):
        result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['matched'] == 1 and result['paths'] == [str(path.resolve())]


def test_gcp_georeferencing_is_not_mistaken_for_default_affine_bounds(tmp_path):
    folder = tmp_path/'data'; folder.mkdir(); path = folder/'control-points.tif'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(path, 'w', driver='GTiff', width=8, height=8, count=1,
                           dtype='float32') as target:
            target.write(np.ones((1, 8, 8), dtype='float32'))
            target.gcps = ([GroundControlPoint(0, 0, 0, 1000),
                            GroundControlPoint(0, 8, 1000, 1000),
                            GroundControlPoint(8, 0, 0, 0)], rasterio.crs.CRS.from_epsg(3857))
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['unknown'] == 1 and result['paths'] == []
    assert 'ground-control points' in result['rows'][0]['surface']


def test_search_and_result_limits_are_reported(tmp_path, monkeypatch):
    folder = tmp_path/'data'; raster(folder/'a.tif'); raster(folder/'b.tif')
    monkeypatch.setattr(local, 'MAX_FILES', 1)
    first = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert first['scanned'] == 1 and not first['complete']
    assert any('reached 1 elevation files' in warning for warning in first['warnings'])
    monkeypatch.setattr(local, 'MAX_FILES', 100)
    monkeypatch.setattr(local, 'MAX_RESULTS', 1)
    second = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert second['matched'] == 2 and len(second['rows']) == 1
    assert not second['complete'] and any('Result list limited' in warning for warning in second['warnings'])


def test_known_overlap_is_prioritized_over_unknown_locations_at_result_limit(tmp_path, monkeypatch):
    folder = tmp_path/'data'
    raster(folder/'unknown.asc', crs=None, driver='AAIGrid')
    known = raster(folder/'known.tif')
    monkeypatch.setattr(local, 'MAX_RESULTS', 1)
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert len(result['rows']) == 1 and result['rows'][0]['coverage'] == 'overlap'
    assert result['paths'] == [str(known.resolve())]


def test_cancellation_does_not_replace_existing_index(tmp_path):
    folder = tmp_path/'data'; raster(folder/'a.tif'); raster(folder/'b.tif')
    local.discover_local(folder, BOUNDS, tmp_path/'cache')
    index = next((tmp_path/'cache').glob('local-index-*.json')); previous = index.read_bytes()
    event = threading.Event()
    def progress(*args):
        event.set()
    with pytest.raises(Cancelled):
        local.discover_local(folder, BOUNDS, tmp_path/'cache', Job(progress=progress, cancel=event))
    assert index.read_bytes() == previous


def test_symbolic_link_directories_are_not_followed(tmp_path):
    folder = tmp_path/'data'; raster(folder/'a.tif')
    try:
        (folder/'loop').symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip('Host does not permit symlink creation')
    result = local.discover_local(folder, BOUNDS, tmp_path/'cache')
    assert result['scanned'] == 1 and result['skippedSymlinks'] == 1
    assert any('symbolic links were skipped' in warning for warning in result['warnings'])

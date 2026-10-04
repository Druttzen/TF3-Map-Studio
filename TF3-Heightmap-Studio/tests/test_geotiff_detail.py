"""Map-aligned GeoTIFF enhancement over a coarser elevation background."""
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio import Affine
from rasterio.enums import ColorInterp

from test_terrain import source
from elevation import sample_sources
from height_settings import normalize
from terrain import prepare, export, load_project


def detail_tile(source, tmp_path):
    original = source['affine']
    # Twice the source resolution; the same corner vertices as the OSM map.
    fine = Affine(original.a / 2, 0, original.c + original.a / 4,
                  0, original.e / 2, original.f + original.e / 4)
    values = np.full((129, 129), -9999.)
    values[24:105, 24:105] = 200
    values[64, 64] = 247  # A small feature must survive the final vertex sampling.
    values[80, 80] = -9999  # A true data void must use the background DEM.
    path = tmp_path / 'detailed-ground.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=129, height=129,
                       count=1, dtype='float64', crs='EPSG:3857',
                       transform=fine, nodata=-9999) as dst:
        dst.write(values, 1)
        dst.set_band_unit(1, 'm')
    return path


@pytest.mark.parametrize('resampling', ['Nearest', 'Bilinear'])
def test_fine_geotiff_overrides_coarse_overlap_and_fills_real_voids(source, tmp_path, resampling):
    detail = detail_tile(source, tmp_path)
    result, affine, metadata = sample_sources(
        [source['dem'], detail], source['bounds'], (65, 65),
        normalize({'resampling': resampling}))
    assert result[32, 32] == pytest.approx(247)
    assert result[20, 20] == pytest.approx(200)
    assert result[40, 40] == pytest.approx(source['z'][40, 40])
    assert result[0, 0] == pytest.approx(source['z'][0, 0])
    assert result[-1, -1] == pytest.approx(source['z'][-1, -1])
    assert affine == source['affine']
    assert metadata[0]['file'] == str(detail.resolve())
    assert metadata[0]['fileListPosition'] == 2
    assert sum(item['contributedSamples'] for item in metadata) == result.size
    assert sum(item['coveragePercent'] for item in metadata) == pytest.approx(100)
    assert metadata[0]['sourceResolutionMetres'][0] * 2 == pytest.approx(
        metadata[1]['sourceResolutionMetres'][0], rel=1e-5)


def test_manual_overlap_priority_remains_available(source, tmp_path):
    result, _, metadata = sample_sources(
        [source['dem'], detail_tile(source, tmp_path)], source['bounds'], (65, 65),
        normalize({'source_priority': 'File list order'}))
    np.testing.assert_allclose(result, source['z'], atol=1e-9)
    assert metadata[1]['contributedSamples'] == 0
    assert metadata[1]['availableSamples'] > 0


def test_download_and_local_detail_survive_export_and_project_replay(source, tmp_path):
    detail = detail_tile(source, tmp_path)
    options = {'source_mode': 'Download Copernicus GLO-30'}
    credits = [{'provider': 'Test background DEM', 'attribution': 'Fictional fixture', 'site': ''}]
    with patch('terrain.acquire', return_value=([source['dem']], {'mapBounds': source['bounds']}, credits)):
        result = prepare(source['report'], source['xml'], [detail], options)
        assert result['terrain'][32, 32] == pytest.approx(247)
        assert result['terrain'][0, 0] == pytest.approx(100)
        report = export(result, tmp_path / 'enhanced.png')
        project = load_project(report['files']['project'])
        assert project['elevationFiles'] == [str(detail.resolve())]
        replay = prepare(project['converterReport'], project['osmFile'], project['elevationFiles'], project['options'])
    np.testing.assert_array_equal(replay['terrain'], result['terrain'])
    assert report['sourceDetail']['bounds'] == source['bounds']
    assert report['sourceDetail']['geotiffSamples'] == 65 * 65
    assert not report['settings']['roads'] and not report['settings']['railways']
    assert report['clippedPngSamples'] == 0
    with rasterio.open(report['files']['dem']) as dst:
        np.testing.assert_array_equal(dst.read(1), result['terrain'])
    from PIL import Image
    with Image.open(report['files']['png']) as dst:
        heights = np.asarray(dst).astype(float) * report['pngEncodingStepMetres'] + report['importMinimumMetres']
    np.testing.assert_allclose(heights, result['terrain'], atol=report['pngEncodingStepMetres'] / 2 + 1e-10)
    attribution = Path(report['files']['attribution']).read_text(encoding='utf-8')
    assert 'Test background DEM' in attribution and 'Local elevation provider' in attribution


def test_old_project_preserves_file_order(source, tmp_path):
    result = prepare(source['report'], source['xml'], [source['dem']])
    report = export(result, tmp_path / 'old.png')
    path = Path(report['files']['project'])
    project = json.loads(path.read_text(encoding='utf-8'))
    del project['options']['source_priority']
    path.write_text(json.dumps(project), encoding='utf-8')
    assert load_project(path)['options']['source_priority'] == 'File list order'


def test_rgb_geotiff_is_not_interpreted_as_heights(source, tmp_path):
    path = tmp_path / 'aerial-photo.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=65, height=65,
                       count=3, dtype='uint8', crs='EPSG:3857', transform=source['affine']) as dst:
        dst.write(np.full((3, 65, 65), 155, dtype='uint8'))
        dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
    with pytest.raises(ValueError, match='not a DEM height band'):
        sample_sources([path], source['bounds'], (65, 65), normalize())


@pytest.mark.parametrize('unit,factor', [('ft', .3048), ('US survey foot', 1200/3937)])
def test_geotiff_scale_offset_and_vertical_units_are_applied_once(source, tmp_path, unit, factor):
    path = tmp_path / 'scaled.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=65, height=65,
                       count=1, dtype='int16', crs='EPSG:3857', transform=source['affine']) as dst:
        dst.write(np.full((65, 65), 200, dtype='int16'), 1)
        dst.scales = [.5]
        dst.offsets = [10]
        dst.set_band_unit(1, unit)
    result, _, _ = sample_sources([path], source['bounds'], (65, 65), normalize())
    np.testing.assert_allclose(result, 110 * factor, atol=1e-9)


def test_compound_crs_preserves_original_heights_and_vertical_reference(source, tmp_path):
    path = tmp_path / 'compound.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=65, height=65,
                       count=1, dtype='float64', crs='EPSG:3857+5773', transform=source['affine']) as dst:
        dst.write(source['z'], 1)
        dst.set_band_unit(1, 'm')
    result, _, metadata = sample_sources([path], source['bounds'], (65, 65), normalize())
    np.testing.assert_allclose(result, source['z'], atol=1e-9)
    assert metadata[0]['horizontalCrs'] == 'EPSG:3857'
    assert 'EGM96' in metadata[0]['verticalDatum']


def test_unrecognized_geotiff_units_are_not_guessed(source):
    with rasterio.open(source['dem'], 'r+') as dst:
        dst.set_band_unit(1, 'furlong')
    with pytest.raises(ValueError, match='Unsupported elevation unit'):
        prepare(source['report'], source['xml'], [source['dem']])


def test_different_contributing_vertical_references_are_reported(source, tmp_path):
    detail = detail_tile(source, tmp_path)
    with rasterio.open(detail, 'r+') as dst:
        dst.update_tags(VERTICAL_DATUM='RH2000')
    with rasterio.open(source['dem'], 'r+') as dst:
        dst.update_tags(VERTICAL_DATUM='EGM96')
    result = prepare(source['report'], source['xml'], [source['dem'], detail])
    assert any('different vertical references' in item for item in result['warnings'])
    assert result['terrain'][32, 32] == pytest.approx(247)


def test_resolution_measured_at_osm_latitude_instead_of_remote_raster_centre(tmp_path):
    bounds = [59, 12, 60, 13]
    path = tmp_path / 'wide-geographic.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=360, height=180,
                       count=1, dtype='float64', crs='EPSG:4326',
                       transform=Affine(1, 0, -180, 0, -1, 90)) as dst:
        dst.write(np.full((180, 360), 100.), 1)
    _, _, metadata = sample_sources([path], bounds, (33, 33), normalize())
    assert 55000 < metadata[0]['sourceResolutionMetres'][0] < 58000
    assert 110000 < metadata[0]['sourceResolutionMetres'][1] < 112000


def test_outside_detail_tile_does_not_change_osm_extent_or_claim_contribution(source, tmp_path):
    detail = detail_tile(source, tmp_path)
    with rasterio.open(detail, 'r+') as dst:
        dst.transform = dst.transform @ Affine.translation(10000, 0)
    result = prepare(source['report'], source['xml'], [source['dem'], detail])
    np.testing.assert_allclose(result['terrain'], source['z'], atol=1e-9)
    assert result['context']['bounds'] == source['bounds']
    assert result['sources'][0]['contributedSamples'] == 0
    assert any('no valid elevations' in item for item in result['warnings'])

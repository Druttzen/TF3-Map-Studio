"""Report actual contributing detail and distinguish ground from game scale."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from terrain_quality import summarize


def source(spacing, count, **extra):
    return {'sourceResolutionMetres': spacing, 'contributedSamples': count, **extra}


def test_actual_huge_export_reports_coarse_measured_sources_not_png_pixels():
    sources = [source([16.50173581825, 30.88752228759], 2109852),
               source([16.50173581836, 30.88752228759], 24114789)]
    quality = summarize((5121, 5121), [20480, 20480], sources,
                        {'resampling': 'Bilinear'}, output_cell_ground_metres=[4, 4])
    assert quality['outputGridSpacingGameMetres'] == [4, 4]
    assert quality['nativeGridSpacingGameMetres'] == 4
    assert quality['coarserThanNativeSamples'] == 5121 ** 2
    assert quality['coarserThanNativePercent'] == 100
    assert quality['finestSourceCellGroundMetres'] == sources[0]['sourceResolutionMetres']
    assert quality['coarsestSourceCellGroundMetres'] == sources[1]['sourceResolutionMetres']
    assert any('cannot add measured terrain detail' in message for message in quality['warnings'])


def test_fine_priority_and_coarse_fallback_use_actual_nonoverlapping_contributions():
    sources = [source([1, 1], 4000), source([30, 30], 200),
               source([90, 90], 0, availableSamples=4225)]
    quality = summarize((65, 65), [256, 256], sources,
                        output_cell_ground_metres=[4, 4])
    assert quality['contributingSources'] == 2
    assert quality['contributingSamples'] == 4200
    assert quality['coarserThanNativeSamples'] == 200
    assert quality['coarserThanNativePercent'] == pytest.approx(200 / 4225 * 100)
    assert quality['coarsestSourceCellGroundMetres'] == [30, 30]


def test_scaled_map_compares_ground_cells_with_native_game_spacing():
    # Each game metre represents ten ground metres. A 30 m DEM is finer than
    # the 40 m ground spacing represented by TF3's native 4 m game grid.
    quality = summarize((65, 65), [256, 256], [source([30, 30], 4225)],
                        output_cell_ground_metres=[40, 40])
    assert quality['nativeGridCellGroundMetres'] == [40, 40]
    assert quality['coarserThanNativeSamples'] == 0
    assert not quality['warnings']


def test_finer_export_does_not_change_native_measured_resolution_claim():
    quality = summarize((257, 257), [256, 256], [source([5, 5], 257 ** 2)],
                        output_cell_ground_metres=[1, 1])
    assert quality['outputGridSpacingGameMetres'] == [1, 1]
    assert quality['nativeGridCellGroundMetres'] == [4, 4]
    assert quality['coarserThanNativeSamples'] == 257 ** 2
    assert quality['finestSourceCellGroundMetres'] == [5, 5]


def test_anisotropic_sources_do_not_invent_a_finer_combined_source():
    quality = summarize((33, 33), [128, 128],
                        [source([1, 10], 500), source([10, 1], 589)],
                        output_cell_ground_metres=[4, 4])
    assert quality['finestSourceCellGroundMetres'] in ([1, 10], [10, 1])
    assert quality['coarsestSourceCellGroundMetres'] in ([1, 10], [10, 1])
    assert quality['sourceCellGroundMetresRange'] == {'x': [1, 10], 'y': [1, 10]}
    assert quality['coarserThanNativeSamples'] == 1089


def test_resampling_is_inferred_from_contributors_or_left_unknown():
    values = [source([1, 1], 1089, resampling='Cubic'),
              source([30, 30], 0, resampling='Nearest')]
    quality = summarize((33, 33), [128, 128], values)
    assert quality['resampling'] == 'Cubic'
    assert not quality['warnings']
    assert summarize((33, 33), [128, 128], [])['resampling'] == 'Unknown'


def test_unknown_scale_does_not_invent_a_source_native_comparison():
    quality = summarize((65, 65), [256, 256], [source([30, 30], 4225)])
    assert quality['finestSourceCellGroundMetres'] == [30, 30]
    assert quality['nativeGridCellGroundMetres'] is None
    assert quality['coarserThanNativeSamples'] is None
    assert quality['coarserThanNativePercent'] is None


def test_unknown_resolution_samples_are_not_described_as_fine():
    quality = summarize((65, 65), [256, 256],
                        [source([1, 1], 4000), source(None, 225)],
                        output_cell_ground_metres=[4, 4])
    assert quality['unknownResolutionSamples'] == 225
    assert quality['coarserThanNativeSamples'] == 0
    assert any('cannot be confirmed' in message for message in quality['warnings'])


def test_nearest_and_coarse_output_grid_have_explicit_independent_warnings():
    quality = summarize((33, 33), [256, 256], [source([1, 1], 33 ** 2)],
                        {'resampling': 'Nearest'}, output_cell_ground_metres=[8, 8])
    assert quality['resampling'] == 'Nearest'
    assert any('rectangular steps' in message for message in quality['warnings'])
    assert any('output grid is 8 x 8 game metres' in message for message in quality['warnings'])
    assert quality['coarserThanNativeSamples'] == 0


def test_no_contributions_does_not_claim_available_source_resolution():
    quality = summarize((33, 33), [128, 128],
                        [source([1, 1], 0, availableSamples=1089)],
                        output_cell_ground_metres=[4, 4])
    assert quality['contributingSources'] == 0
    assert quality['finestSourceCellGroundMetres'] is None
    assert quality['coarsestSourceCellGroundMetres'] is None
    assert quality['contributingSamples'] == 0


def test_inputs_are_not_mutated_and_invalid_resolution_is_unknown():
    sources = [source([float('nan'), 2], 100), source([1, 1], 989)]
    options = {'resampling': 'Cubic'}
    old_sources, old_options = copy.deepcopy(sources), dict(options)
    quality = summarize((33, 33), [128, 128], sources, options,
                        output_cell_ground_metres=[4, 4])
    assert quality['unknownResolutionSamples'] == 100
    assert sources[0]['sourceResolutionMetres'][1] == old_sources[0]['sourceResolutionMetres'][1]
    assert sources[1] == old_sources[1]
    assert options == old_options


@pytest.mark.parametrize('shape,size', [((1, 33), [128, 128]),
                                       ((33.5, 33), [128, 128]),
                                       ((33, 33), [0, 128]),
                                       ((33, 33), [128, float('inf')])])
def test_invalid_grid_metadata_is_rejected(shape, size):
    with pytest.raises(ValueError):
        summarize(shape, size, [])

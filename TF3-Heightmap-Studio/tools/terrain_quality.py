"""Describe measured elevation spacing without inventing detail. GPL-3.0."""
import math
from numbers import Real


NATIVE_GRID_METRES = 4.0


def _positive_pair(values):
    if not isinstance(values, (list, tuple)) or len(values) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, Real)
           or not math.isfinite(v) or v <= 0 for v in values):
        return None
    return [float(v) for v in values]


def summarize(shape, size, sources, options=None, *, output_cell_ground_metres=None):
    """Return compact source-resolution and interpolation information.

    ``shape`` is (rows, columns); ``size`` is game (width, height). Source
    ``sourceResolutionMetres`` values describe approximate ground spacing near
    the map, not survey accuracy. Only ``contributedSamples > 0`` participates.

    Ground and game metres need not have the same scale. Pass the existing
    sourceDetail.outputGridCellGroundMetres measurement to compare source
    spacing with TF3's native grid. Without it, comparison counts are unknown.
    The input metadata and height arrays are never changed.
    """
    if not isinstance(shape, (list, tuple)) or len(shape) != 2:
        raise ValueError('Terrain quality needs a (rows, columns) grid shape.')
    if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v)
           or v < 2 or v != int(v) for v in shape):
        raise ValueError('Terrain quality grid dimensions must be whole numbers of at least two.')
    game_size = _positive_pair(size)
    if game_size is None:
        raise ValueError('Terrain quality needs positive finite map width and height.')
    ny, nx = map(int, shape)
    output_spacing = [game_size[0] / (nx - 1), game_size[1] / (ny - 1)]
    output_ground = _positive_pair(output_cell_ground_metres)
    native_ground = ([output_ground[i] * NATIVE_GRID_METRES / output_spacing[i]
                      for i in range(2)] if output_ground else None)
    resolutions = []
    source_modes = set()
    contributing_sources = contributing_samples = unknown_samples = coarse_samples = 0
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        count = source.get('contributedSamples', 0)
        if (isinstance(count, bool) or not isinstance(count, Real)
                or not math.isfinite(count) or count <= 0 or count != int(count)):
            continue
        count = int(count)
        contributing_sources += 1
        contributing_samples += count
        if isinstance(source.get('resampling'), str):
            source_modes.add(source['resampling'])
        spacing = _positive_pair(source.get('sourceResolutionMetres'))
        if spacing is None:
            unknown_samples += count
            continue
        resolutions.append(spacing)
        if native_ground and any(spacing[i] > native_ground[i] * (1 + 1e-6)
                                 for i in range(2)):
            coarse_samples += count

    selected_mode = (options or {}).get('resampling')
    resampling = (selected_mode if isinstance(selected_mode, str)
                  else next(iter(source_modes)) if len(source_modes) == 1
                  else 'Mixed' if source_modes else 'Unknown')
    # Preserve actual source pairs: independent X/Y minima can describe a
    # fictional 1 x 1 m source when the real files are 1 x 10 and 10 x 1 m.
    resolution_order = lambda value: (max(value), value[0] * value[1], value[0], value[1])
    total = nx * ny
    warnings = []
    if native_ground and coarse_samples:
        warnings.append(
            f'{coarse_samples:,} output samples ({100 * coarse_samples / total:.1f}%) '
            "come from source cells coarser than TF3's 4 m terrain grid at this map scale. "
            'Interpolation can smooth transitions, but cannot add measured terrain detail. '
            'Use finer ground DEM or LiDAR data for more real detail.')
    if resampling == 'Nearest':
        warnings.append(
            'Nearest-neighbour elevation sampling can produce rectangular steps. '
            'Use smooth interpolation for a continuous terrain surface.')
    if any(spacing > NATIVE_GRID_METRES * (1 + 1e-6) for spacing in output_spacing):
        warnings.append(
            f'The output grid is {output_spacing[0]:g} x {output_spacing[1]:g} game metres, '
            "coarser than TF3's native 4 m grid. Export at the native grid to avoid discarding terrain detail.")
    if unknown_samples:
        warnings.append(
            f'Source cell spacing is unknown for {unknown_samples:,} contributing samples; '
            'their measured resolution cannot be confirmed.')

    return {
        'nativeGridSpacingGameMetres': NATIVE_GRID_METRES,
        'outputGridSpacingGameMetres': output_spacing,
        'outputGridCellGroundMetres': output_ground,
        'nativeGridCellGroundMetres': native_ground,
        'outputSamples': total,
        'contributingSources': contributing_sources,
        'contributingSamples': contributing_samples,
        'finestSourceCellGroundMetres': (min(resolutions, key=resolution_order)
                                         if resolutions else None),
        'coarsestSourceCellGroundMetres': (max(resolutions, key=resolution_order)
                                           if resolutions else None),
        'sourceCellGroundMetresRange': ({axis: [min(v[i] for v in resolutions),
                                               max(v[i] for v in resolutions)]
                                        for i, axis in enumerate(('x', 'y'))}
                                       if resolutions else None),
        'unknownResolutionSamples': unknown_samples,
        'coarserThanNativeSamples': coarse_samples if native_ground else None,
        'coarserThanNativePercent': 100 * coarse_samples / total if native_ground else None,
        'resampling': resampling,
        'resolutionMeaning': 'Approximate contributing source cell spacing near the map; not survey accuracy.',
        'warnings': warnings,
    }

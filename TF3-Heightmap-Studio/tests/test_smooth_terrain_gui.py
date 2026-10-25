"""The smooth preset keeps height calibration and saved projects explicit."""
from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from gui import App, quality_text
from height_settings import normalize
from terrain_quality import summarize
from terrain import preview_image


class Var:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


def test_smooth_preset_changes_sampling_without_resetting_height_calibration():
    options = normalize({'resampling': 'Nearest', 'grid': 'Custom pixels',
                         'source_priority': 'File list order', 'vertical_scale': 2,
                         'height_offset': -40, 'range_mode': 'Manual range'})
    app = SimpleNamespace(busy=False, values={k: Var(v) for k, v in options.items()},
                          changed=Mock(), status=Var(''))
    App.smooth_terrain_settings(app)
    assert app.values['resampling'].get() == 'Cubic'
    assert app.values['grid'].get() == 'Match TF3 (4 m)'
    assert app.values['source_priority'].get() == 'Finest elevation first'
    assert app.values['vertical_scale'].get() == 2
    assert app.values['height_offset'].get() == -40
    assert app.values['range_mode'].get() == 'Manual range'
    app.changed.assert_called_once()


def test_smooth_preset_does_not_change_a_running_build():
    app = SimpleNamespace(busy=True, values={}, changed=Mock())
    App.smooth_terrain_settings(app)
    app.changed.assert_not_called()


def test_new_projects_use_smooth_sampling_and_existing_explicit_choices_remain():
    assert normalize()['resampling'] == 'Cubic'
    assert normalize({'resampling': 'Bilinear'})['resampling'] == 'Bilinear'
    assert normalize({'resampling': 'Nearest'})['resampling'] == 'Nearest'


def test_quality_display_identifies_upsampled_terrain_and_single_image():
    info = summarize((65, 65), [256, 256], [
        {'contributedSamples': 65 * 65, 'sourceResolutionMetres': [16.5, 30.9]}],
        {'resampling': 'Cubic'}, output_cell_ground_metres=[4, 4])
    text = quality_text({'terrain': np.zeros((65, 65)), 'terrainQuality': info})
    assert 'continuous 16-bit heightmap' in text
    assert '16.5' in text and '30.9' in text
    assert '100.0% uses coarser source data' in text
    assert 'adds real detail' in text


def test_quality_display_does_not_guess_missing_source_spacing():
    info = summarize((65, 65), [256, 256], [], {'resampling': 'Cubic'})
    text = quality_text({'terrain': np.zeros((65, 65)), 'terrainQuality': info})
    assert 'spacing is unknown' in text
    assert '100.0%' not in text


def test_preview_interpolates_a_continuous_plane_instead_of_repeating_source_pixels():
    plane=np.repeat((100+np.arange(5)*50.)[None,:],5,axis=0)
    result={'terrain':plane,'context':{'size':[256,256],'lines':[]},'options':{'water_level':0}}
    preview=np.asarray(preview_image(result,(65,65),overlay=False))
    assert len(np.unique(preview[32],axis=0))>32

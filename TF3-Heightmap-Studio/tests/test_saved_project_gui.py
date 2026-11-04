"""The GUI's Save project path must retain legacy OSM identity."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from test_terrain import source
from test_discovery_gui import Var
from gui import App
from terrain import prepare, load_project
from height_settings import normalize


def gui_app(source, result=None):
    return SimpleNamespace(report_path=Var(str(source['report'])),
        check_brush_alignment=Mock(), osm_path=Var(str(source['xml'])),
        lua_path=Var(''), lua_sha=None, sources=[str(source['dem'])],
        options=normalize, strokes=[], biome_strokes=[], result=result,
        dirty=False, output_path=Var(''), local_folder=Var(''),
        auto_lidar=Var(False), lidar_provider=Var(''))


def legacy(source):
    report = json.loads(source['report'].read_text()); report.pop('sourceSha256')
    source['report'].write_text(json.dumps(report))


@pytest.mark.parametrize('built', [False, True])
def test_gui_save_binds_legacy_osm_and_reload_rejects_replaced_bytes(source, tmp_path, built):
    legacy(source)
    app = gui_app(source, prepare(source['report'], source['xml'], [source['dem']]) if built else None)
    project = App.form_project(app)
    assert project['osmSha256'] == hashlib.sha256(source['xml'].read_bytes()).hexdigest()
    saved = tmp_path/'saved.json'; saved.write_text(json.dumps(project))
    assert load_project(saved)['osmSha256'] == project['osmSha256']
    source['xml'].write_text(source['xml'].read_text().replace('0.002', '0.003'))
    with pytest.raises(ValueError, match='OSM checksum differs'):
        load_project(saved)


def test_gui_cannot_resave_changed_osm_over_built_identity(source):
    legacy(source)
    app = gui_app(source, prepare(source['report'], source['xml'], [source['dem']]))
    source['xml'].write_text(source['xml'].read_text().replace('0.002', '0.003'))
    with pytest.raises(ValueError, match='OSM checksum differs'):
        App.form_project(app)


def test_loaded_legacy_identity_is_checked_at_rebuild_and_resave(source):
    legacy(source); app = gui_app(source)
    app.osm_sha = App.form_project(app)['osmSha256']
    source['xml'].write_text(source['xml'].read_text().replace('0.002', '0.003'))
    with pytest.raises(ValueError, match='OSM checksum differs'):
        App.form_project(app)
    with pytest.raises(ValueError, match='OSM checksum differs'):
        prepare(source['report'], source['xml'], [source['dem']], osm_sha=app.osm_sha)

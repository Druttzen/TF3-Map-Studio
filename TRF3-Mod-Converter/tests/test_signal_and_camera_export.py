from copy import deepcopy
import zipfile

import pytest

from test_tf2_vehicle_port import fixture_mod, model
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.model_common import port_common_metadata
from trf3_mod_converter.resource_audit import callback_status, parse_lua
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod, snapshot


@pytest.mark.parametrize('kind', ['PATH_SIGNAL','WAYPOINT','ONE_WAY_PATH_SIGNAL'])
@pytest.mark.parametrize('soundevent', ['', 'horn'])
def test_signal_export_preserves_geometry_type_price_and_localized_description(fixture_mod, kind, soundevent):
    source, game, output = fixture_mod
    data = model()
    data['metadata'] = {'signal':{'type':kind,'soundevent':soundevent}, 'cost':{'price':3000},
                        'description':{'name':'key'}, 'availability':{'yearFrom':1970},
                        'category':{'categories':['swedish_signals']}}
    path = source/'res/models/model/vehicle/train/test.mdl'
    path.write_text(emit(data))
    with zipfile.ZipFile(game/'base/content/resources.zip', 'a') as archive:
        for relative in ('infrastructure/signal/signal_path_c.con.lua',
                         'infrastructure/signal/signal_path_c.script.lua'):
            archive.writestr(relative, 'function data() return {} end')
    before = snapshot(source)
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='signals', name='Signals')
    assert snapshot(source) == before and report['nativeTest'] == 'not_run'
    target = load_lua_table((output/'content/models/model/vehicle/train/test.mdl').read_text())
    assert target['version'] == 2 and 'signal' not in target['metadata']
    assert target['lods'][0]['node']['children'][0]['children'][0]['mesh'] == 'signals::/models/mesh/body.msh'
    construction = output/'content/construction/_tf3_signals/vehicle/train/test.con.lua'
    con = load_lua_table(construction.read_text())
    assert con['edgeObject'] == {'snapToTrack':True}
    assert con['description']['name'] == 'key'
    script = construction.with_name('test.script.lua')
    assert callback_status(parse_lua(script.read_text()), 'updateFn') == 'resolved'
    assert 'type = "'+kind+'"' in script.read_text()
    assert 'soundevent = "'+soundevent+'"' in script.read_text()
    assert 'cost = 3000' in script.read_text()
    assert report['migrationAudit']['signalMigrations'][0]['signalType'] == kind


def test_false_camera_flag_preserves_transform_and_records_migration():
    data = {'cameraConfig':{'positions':[{'group':0,'noTransf':False,'transf':[1]*16,'fov':60}]}}
    before = deepcopy(data)
    audit = {}
    result = port_common_metadata(data, [{'name':'root'}], lambda r,k:r, report=audit)
    assert data == before
    assert result['cameraConfig']['positions'] == [{'group':'root','transf':[1]*16,'fov':60}]
    assert audit['cameraMigrations'][0]['sourceValue'] is False


@pytest.mark.parametrize('value', [True, 0, 'false'])
def test_active_or_invalid_camera_flag_is_not_discarded(value):
    with pytest.raises(ValueError, match='noTransf'):
        port_common_metadata({'cameraConfig':{'positions':[{'group':0,'noTransf':value}]}},
                             [{'name':'root'}], lambda r,k:r)

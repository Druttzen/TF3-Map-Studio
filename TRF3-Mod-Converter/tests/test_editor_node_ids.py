from copy import deepcopy

import pytest

from trf3_mod_converter.tf2_vehicle_port import port_model
from trf3_mod_converter.vehicle_profiles import derive_lod_nodes
from test_tf2_vehicle_port import Native, model


def test_editor_ids_do_not_change_geometry_order_or_metadata_references():
    source = model()
    node = source['lods'][0]['node']['children'][1]
    node.update(_meshId=14, _origMeshId=7)
    before = deepcopy(source)
    expected = model()
    log = {}
    result = port_model(source, lambda ref, kind: 'fixture::/' + ref, Native(), report=log, model_path='body.mdl')
    assert result == port_model(expected, lambda ref, kind: 'fixture::/' + ref, Native())
    assert source == before
    assert log['modelNodeMigrations'] == [{
        'model': 'body.mdl', 'lod': 0, 'nodeIndex': 3, 'nodeName': 'wheel',
        'sourceFields': {'_meshId': 14, '_origMeshId': 7},
        'policy': 'omit_editor_mesh_ids_preserve_node_order',
        'reason': 'TF2 editor IDs are outside the runtime node schema; TF3 node references use unique names.',
        'nativeTest': 'not_run',
    }]


@pytest.mark.parametrize('value', [-1, True, '14', 1.5])
def test_unverified_editor_id_shape_is_blocked(value):
    lods = [{'node': {'_meshId': value}}]
    with pytest.raises(ValueError, match='editor ID'):
        derive_lod_nodes(lods)


def test_unknown_private_fields_still_block():
    with pytest.raises(ValueError, match='Unsupported node fields'):
        derive_lod_nodes([{'node': {'_customBehavior': 1}}])

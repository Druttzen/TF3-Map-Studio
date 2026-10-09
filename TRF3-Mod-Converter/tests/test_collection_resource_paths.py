import pytest

from trf3_mod_converter.base_resources import normalize_reference, source_resource, BaseResourceResolver
from test_base_resources import Installed
from trf3_mod_converter.tf2_vehicle_port import flatten


def test_repeated_interior_slashes_resolve_the_existing_resource():
    assert normalize_reference('vehicle/train//bogie.msh') == 'vehicle/train/bogie.msh'
    assert source_resource('mesh', 'vehicle/train//bogie.msh') == 'models/mesh/vehicle/train/bogie.msh'
    native = Installed({'vehicle/shared/mat/tex/dirt_albedo.dds': b'installed dirt texture'})
    resolver = BaseResourceResolver(native)
    assert resolver.resolve('texture', 'models//vehicle/dirt_albedo.tga') == '::/vehicle/shared/mat/tex/dirt_albedo.dds'


@pytest.mark.parametrize('reference', [None, '', '//outside.dds', '/outside.dds',
                                      'vehicle//../outside.dds', 'vehicle/./texture.dds',
                                      'vehicle\\texture.dds', 'other::/texture.dds', 'vehicle//'])
def test_normalization_preserves_path_safety(reference):
    with pytest.raises(ValueError, match='Unsafe TF2 resource reference'):
        normalize_reference(reference)


def test_malformed_model_children_report_a_schema_error_instead_of_crashing():
    with pytest.raises(ValueError, match='contiguous literal list'):
        list(flatten({'children':{1:{'mesh':'one.msh'}, 3:{'mesh':'three.msh'}}}))
    assert list(flatten({'children':{}})) == [{'children':{}}]

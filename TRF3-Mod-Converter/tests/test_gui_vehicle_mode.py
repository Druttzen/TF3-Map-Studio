from test_gui import app, wait_for_work
from trf3_mod_converter.tf2_vehicle_port import emit


def test_vehicle_scan_selects_scope_and_class_average_without_confirmation(app, tmp_path):
    app.vehicle_mode = True
    for name, resource in [('skin', 'textures/models/vehicle/car/skin.dds'),
                           ('map', 'textures/terrain/ground.dds')]:
        folder = tmp_path/name
        file = folder/'res'/resource
        file.parent.mkdir(parents=True)
        file.write_bytes(b'image')
        (folder/'mod.lua').write_text(emit({'info': {'name':name, 'authors':[{'name':'Author'}]}}))
    app._set_source(str(tmp_path))
    wait_for_work(app)
    assert [item.display_name for item in app.items] == ['skin']
    item = app.items[0]
    assert item.vehicle_policy == 'tf2_complete' and item.emissions_policy == 'class_average'
    app.show_item(item)
    assert app.emissions_choice.get() == 'Average of the same vehicle class'

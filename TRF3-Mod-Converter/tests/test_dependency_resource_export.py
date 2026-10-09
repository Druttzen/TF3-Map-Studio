"""Preserve localization intent when adapting externally authored config files."""
import json

from test_tf2_vehicle_port import fixture_mod
from trf3_mod_converter.lua_metadata import TranslatedString, load_lua_table
from trf3_mod_converter.tf2_vehicle_port import emit, port_tf2_mod


def test_plain_external_display_text_matching_root_key_stays_literal(fixture_mod, tmp_path):
    original, game, output = fixture_mod
    source = tmp_path/'1066780/123'
    source.parent.mkdir()
    original.rename(source)
    provider = source.parent/'456'
    provider.mkdir()
    (provider/'mod.lua').write_text(emit({'info':{'name':'Terrain author'}}))
    terrain = provider/'res/config/terrain_material/shared.lua'
    terrain.parent.mkdir(parents=True)
    terrain.write_text(emit({'name':'key'}))  # An authored literal, not _('key').
    ground = source/'res/config/ground_texture/local.lua'
    ground.parent.mkdir(parents=True)
    ground.write_text(emit({'texture':{'fileName':'body.dds'},'materialIndexMap':{1:'shared'}}))
    report = port_tf2_mod(source, output, tf3_game=game, mod_id='fixture_owner_terrain', name='Terrain fixture')
    converted = load_lua_table((output/'content/config/terrain_material/shared.tmat.lua').read_text())
    assert converted['description']['name'] == 'key'
    assert not isinstance(converted['description']['name'], TranslatedString)
    assert json.loads((output/'strings.json').read_text()) == {'en':{'key':'Original description'}}
    assert not any(row['kind'] == 'localization' for row in report['migrationAudit']['workshopDependencies'])

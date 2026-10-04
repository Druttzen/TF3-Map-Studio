from copy import deepcopy
import json
import math

import pytest

from trf3_mod_converter.cargo_port import CargoCatalog, CargoType, port_compartments
from trf3_mod_converter.lua_metadata import UnsupportedValue


class NativeCargo:
    def __init__(self):
        self.files, self.references, self.reads = {}, set(), []
        for tag in ('UNIVERSAL', 'BULK', 'GOODS', 'LIQUID', 'FLATBED', 'PASSENGERS'):
            self.files[f'cargos/classes/{tag.lower()}.cargoclass.lua'] = f'return {{tag="{tag}"}}'.encode()
        for tag in ('SMALL', 'BIG', 'MEDIUM4x1', 'MEDIUM2x1'):
            self.files[f'cargos/formats/{tag.lower()}.cmf.lua'] = f'return {{tag="{tag}"}}'.encode()
        groups = {
            'BULK': ('coal', 'iron_ore', 'grain', 'sand', 'stone', 'clay', 'cement'),
            'GOODS': ('tools', 'books', 'tinned_food', 'vegetables', 'fish', 'meat', 'bricks'),
            'LIQUID': ('fuel', 'crude_oil', 'chemicals', 'dyes', 'rubber'),
            'FLATBED': ('logs', 'planks', 'steel', 'machines'),
            'PASSENGERS': ('passengers',),
        }
        for tag, keys in groups.items():
            for key in keys:
                classes = ('PASSENGERS',) if tag == 'PASSENGERS' else ('UNIVERSAL', tag)
                tags = ','.join(f'"{t}"' for t in classes)
                self.files[f'cargos/{key}/{key}.cargo.lua'] = f'function data() return {{cargoClasses={{{tags}}},weightFactor=1.0}} end'.encode()

    def read(self, path):
        self.reads.append(path)
        return self.files[path]


@pytest.fixture
def native():
    return NativeCargo()


@pytest.fixture
def catalog(native):
    return CargoCatalog.from_native(native)


@pytest.fixture
def nodes():
    return [{'name': 'root'}, {'name': 'body', 'mesh': 'vehicle/body.msh'},
            {'name': 'cover', 'mesh': 'vehicle/cover.msh'}]


def transport(*entries, carrier='RAIL'):
    return {'carrier': carrier, 'loadSpeed': 2, 'compartmentsList': [
        {'loadConfigs': [{'cargoEntries': [entry], 'toHide': []} for entry in entries]}]}


def entry(cargo='COAL', capacity=80, **fields):
    return {'type': cargo, 'capacity': capacity, **fields}


def cargo_keys(loads):
    return {token.rsplit('/', 1)[-1].removesuffix('.cargo') for load in loads
            for token in load['cargoEntry']['cargoTypeSet']['cargoTypesIncluded']}


@pytest.mark.parametrize('carrier', ['RAIL', 'ROAD', 'TRAM', 'WATER', 'AIR'])
def test_same_class_expansion_all_carriers_preserves_original(native, catalog, carrier):
    source = transport(entry('COAL', 80), entry('IRON_ORE', 60), carrier=carrier)
    original = deepcopy(source)
    target, extras, audit = port_compartments(source, catalog=catalog)
    assert source == original
    assert target['carrier'] == carrier and target['loadSpeed'] == 2
    assert 'compartmentsList' not in target and extras == {}
    loads = target['compartments'][0]['loadConfigs']
    assert [load['cargoEntry']['capacity'] for load in loads[:2]] == [80, 60]
    assert cargo_keys(loads) == catalog.class_types('BULK')
    assert not cargo_keys(loads) & catalog.class_types('LIQUID')
    assert not cargo_keys(loads) & {'passengers'}
    assert audit['maxCapacity'] == 80
    assert len(audit['additions']) == 5
    for addition in audit['additions']:
        assert addition['capacity'] == 80 and addition['cargoClass'] == 'BULK'
        assert addition['evidence'] in native.files
        assert addition['inferredFrom'] == ['coal']
    assert native.references >= {'cargos/coal/coal.cargo', 'cargos/clay/clay.cargo'}


def test_passenger_capacity_seats_and_mixed_compartments_preserved(catalog):
    source = transport(entry('PASSENGERS', 44, seats=[0, 2]))
    source['compartmentsList'].append(transport(entry('FUEL', 60))['compartmentsList'][0])
    target, _, audit = port_compartments(source, catalog=catalog, seat_count=3)
    passengers = target['compartments'][0]['loadConfigs']
    assert len(passengers) == 1
    assert passengers[0]['cargoEntry']['seats'] == [0, 2]
    assert cargo_keys(passengers) == {'passengers'}
    assert cargo_keys(target['compartments'][1]['loadConfigs']) == catalog.class_types('LIQUID')
    assert audit['maxCapacity'] == 104
    assert all(row['cargoType'] != 'passengers' for row in audit['additions'])


def test_preserve_policy_disables_expansion(catalog):
    target, _, audit = port_compartments(transport(entry('COAL', 37)), catalog=catalog, expand_classes=False)
    assert cargo_keys(target['compartments'][0]['loadConfigs']) == {'coal'}
    assert audit['policy'] == 'preserve_types' and audit['additions'] == []


@pytest.mark.parametrize('schema', ['compartmentsList', 'compartments', 'capacities'])
def test_all_tf2_capacity_schemas(catalog, schema):
    original = transport(entry('LOGS', 88), entry('PLANKS', 64))
    if schema == 'compartments':
        original['compartments'] = [[[entry('LOGS', 88)], [entry('PLANKS', 64)]]]
        del original['compartmentsList']
    if schema == 'capacities':
        original['capacities'] = [entry('LOGS', 88), entry('PLANKS', 64)]
        original['compartments'] = []
        del original['compartmentsList']
    target, _, audit = port_compartments(original, catalog=catalog)
    assert audit['sourceSchema'] == schema
    loads = target['compartments'][0]['loadConfigs']
    assert [load['cargoEntry']['capacity'] for load in loads[:2]] == [88, 64]
    assert cargo_keys(loads) == catalog.class_types('FLATBED')


def test_empty_locomotive_requires_no_cargo_catalog():
    source = {'carrier': 'RAIL', 'compartments': [[[]]]}
    target, extras, audit = port_compartments(source)
    assert target['compartments'][0]['loadConfigs'][0]['cargoEntry']['capacity'] == 0
    assert extras == {} and audit['maxCapacity'] == 0 and audit['cargoTypes'] == []


def test_conflicting_nonempty_schemas_block_without_mutating_source(catalog):
    source = transport(entry())
    source['capacities'] = [entry('PASSENGERS', 1)]
    original = deepcopy(source)
    with pytest.raises(ValueError, match='Conflicting'):
        port_compartments(source, catalog=catalog)
    assert source == original


@pytest.mark.parametrize('cargo, expected', [
    ('CRUDE', {'crude_oil'}),
    ('FOOD', {'fish', 'meat', 'tinned_food', 'vegetables'}),
    ('CONSTRUCTION_MATERIALS', {'bricks'}),
    ('GOODS', {'tools', 'books', 'tinned_food', 'vegetables', 'fish', 'meat', 'bricks'}),
    ('OIL', {'fuel', 'crude_oil', 'chemicals', 'dyes', 'rubber'}),
])
def test_legacy_categories_record_semantic_mapping(catalog, cargo, expected):
    target, _, audit = port_compartments(transport(entry(cargo)), catalog=catalog, expand_classes=False)
    assert cargo_keys(target['compartments'][0]['loadConfigs']) == expected
    assert audit['entries'][0]['mapping'].startswith('legacy category')


@pytest.mark.parametrize('cargo', ['FOO_CUSTOM', 'oil_2', '', None])
def test_unknown_custom_or_missing_type_never_guessed(catalog, cargo):
    with pytest.raises(ValueError, match='cargo|Cargo'):
        port_compartments(transport(entry(cargo)), catalog=catalog)


def test_custom_alias_only_accepts_verified_explicit_mapping(native):
    catalog = CargoCatalog.from_native(native, aliases={'CUSTOM_COAL': ['coal']})
    target, _, audit = port_compartments(transport(entry('CUSTOM_COAL')), catalog=catalog, expand_classes=False)
    assert cargo_keys(target['compartments'][0]['loadConfigs']) == {'coal'}
    assert audit['entries'][0]['mapping'] == 'explicit custom cargo mapping'
    with pytest.raises(ValueError, match='verified'):
        CargoCatalog.from_native(native, aliases={'UNKNOWN': ['not_installed']})


def test_cargo_set_exclusions_preserved_on_added_alternatives(catalog):
    source_entry = {'capacity': 40, 'cargoTypeSet': {
        'cargoClassesIncluded': [], 'cargoClassesExcluded': [],
        'cargoTypesIncluded': ['coal.cargo'], 'cargoTypesExcluded': ['sand.cargo'],
    }}
    target, _, audit = port_compartments(transport(source_entry), catalog=catalog)
    loads = target['compartments'][0]['loadConfigs']
    assert cargo_keys(loads) == catalog.class_types('BULK') - {'sand'}
    assert all(load['cargoEntry']['cargoTypeSet']['cargoTypesExcluded'] == ['::/cargos/sand/sand.cargo'] for load in loads)
    assert all(row['cargoType'] != 'sand' for row in audit['additions'])


def test_cargo_set_class_exclusion_blocks_expansion(catalog):
    source_entry = {'capacity': 40, 'cargoTypeSet': {
        'cargoClassesIncluded': [], 'cargoClassesExcluded': ['BULK'],
        'cargoTypesIncluded': ['coal.cargo'], 'cargoTypesExcluded': [],
    }}
    target, _, audit = port_compartments(transport(source_entry), catalog=catalog)
    assert cargo_keys(target['compartments'][0]['loadConfigs']) == {'coal'}
    assert target['compartments'][0]['loadConfigs'][0]['cargoEntry']['cargoTypeSet']['cargoClassesExcluded'] == ['BULK']
    assert audit['additions'] == []


def test_universal_class_exclusion_cannot_be_bypassed_by_expansion(catalog):
    source_entry = {'capacity': 40, 'cargoTypeSet': {
        'cargoClassesIncluded': [], 'cargoClassesExcluded': ['UNIVERSAL'],
        'cargoTypesIncluded': ['coal.cargo'], 'cargoTypesExcluded': [],
    }}
    target, _, audit = port_compartments(transport(source_entry), catalog=catalog)
    assert cargo_keys(target['compartments'][0]['loadConfigs']) == {'coal'}
    assert audit['additions'] == []


def test_bay_moves_to_native_indicator_and_maps_nodes(catalog, nodes):
    bay = {'bbMin': [-2, -1, 1], 'bbMax': [2, 1, 2], 'cargoFormat': 'MEDIUM4x1',
           'childId': 1, 'type': 'LEVEL', 'sizePolicy': 'STRETCH', 'gridSize': [1, 1]}
    source = transport(entry('COAL', cargoBay=bay))
    source['compartmentsList'][0]['loadConfigs'][0]['toHide'] = [2, 'vehicle/body.msh']
    original = deepcopy(source)
    target, extras, audit = port_compartments(source, catalog=catalog, nodes=nodes)
    first = target['compartments'][0]['loadConfigs'][0]
    assert first['toHide'] == ['cover', 'body']
    migrated = extras['loadIndicator']['configs'][first['cargoEntry']['loadIndicator']]['cargoBay']
    assert migrated['cargoFormats'] == ['MEDIUM4x1'] and migrated['childId'] == 'body'
    assert 'cargoFormat' not in migrated and 'cargoBay' not in first['cargoEntry']
    assert source == original and audit['maxCapacity'] == 80


def test_slot_indices_randomization_and_fixed_models_preserved(catalog, nodes):
    source = transport(entry('LOGS', customCargoModels={'configurations': [{'slotLevels': [[], [0], [0, 1]]}]}))
    provider = {'slots': [
        {'group': 1, 'models': ['#BIG'], 'randomId': 2, 'transf': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        {'group': 'body', 'models': ['authored/load.mdl'], 'randomId': 3, 'transf': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 2, 1]},
    ]}
    target, extras, _ = port_compartments(source, catalog=catalog, nodes=nodes, cargo_slot_provider=provider,
                                         resolve=lambda path, kind: 'test::/' + path, expand_classes=False)
    indicator = extras['loadIndicator']
    assert indicator['slots'][0]['group'] == 'body' and indicator['slots'][0]['randomId'] == 2
    assert indicator['slots'][1]['models'] == ['test::/authored/load.mdl']
    name = target['compartments'][0]['loadConfigs'][0]['cargoEntry']['loadIndicator']
    assert indicator['configs'][name]['cargoSlots']['configurations'] == [[[], [0], [0, 1]]]


def test_fixed_authored_slot_models_block_unverified_new_cargo_visuals(catalog, nodes):
    source = transport(entry('LOGS', customCargoModels={'configurations': [{'slotLevels': [[], [0]]}]}))
    provider = {'slots': [{'group': 1, 'models': ['authored/logs.mdl'], 'transf': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]}
    with pytest.raises(ValueError, match='fixed source cargo models'):
        port_compartments(source, catalog=catalog, nodes=nodes, cargo_slot_provider=provider,
                          resolve=lambda path, kind: 'test::/' + path)


def test_dynamic_cargo_slots_support_class_expansion(catalog, nodes):
    source = transport(entry('LOGS', customCargoModels={'configurations': [{'slotLevels': [[], [0]]}]}))
    provider = {'slots': [{'group': 1, 'models': ['#BIG'], 'transf': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]}
    target, _, audit = port_compartments(source, catalog=catalog, nodes=nodes, cargo_slot_provider=provider)
    assert cargo_keys(target['compartments'][0]['loadConfigs']) == catalog.class_types('FLATBED')
    assert len(audit['additions']) == 3


def test_combined_old_visual_systems_block_instead_of_silently_disappearing(catalog, nodes):
    bay = {'bbMin': [-1, -1, 0], 'bbMax': [1, 1, 1], 'cargoFormat': 'BIG', 'childId': 1}
    source = transport(entry('LOGS', cargoBay=bay, customCargoModels={'configurations': [{'slotLevels': [[]]}]}))
    with pytest.raises(ValueError, match='neither visual system was discarded'):
        port_compartments(source, catalog=catalog, nodes=nodes, expand_classes=False)


def test_fixed_single_mixed_load_preserves_simultaneous_capacities(catalog):
    source = {'carrier': 'WATER', 'compartmentsList': [{'loadConfigs': [{'cargoEntries': [
        entry('PASSENGERS', 40, seats=[0]), entry('COAL', 20)], 'toHide': []}]}]}
    target, _, audit = port_compartments(source, catalog=catalog)
    assert len(target['compartments']) == 2
    assert [c['loadConfigs'][0]['cargoEntry']['capacity'] for c in target['compartments']] == [40, 20]
    assert audit['maxCapacity'] == 60 and audit['additions'] == [] and audit['warnings']


def test_coupled_mixed_alternatives_are_blocked(catalog):
    source = {'compartmentsList': [{'loadConfigs': [
        {'cargoEntries': [entry('COAL', 40), entry('IRON_ORE', 20)]},
        {'cargoEntries': [entry('COAL', 80)]},
    ]}]}
    with pytest.raises(ValueError, match='Coupled mixed-cargo'):
        port_compartments(source, catalog=catalog)


@pytest.mark.parametrize('capacity', [-1, float('nan'), float('inf'), True, '40'])
def test_invalid_capacity_blocked(catalog, capacity):
    with pytest.raises(ValueError, match='capacity'):
        port_compartments(transport(entry(capacity=capacity)), catalog=catalog)


def test_dynamic_lua_values_are_never_executed(catalog):
    source = transport(entry('COAL', UnsupportedValue('dynamic Lua')))
    with pytest.raises(ValueError, match='dynamic Lua'):
        port_compartments(source, catalog=catalog)


def test_catalog_requires_valid_installed_definitions(native):
    native.files['cargos/coal/coal.cargo.lua'] = b'return {cargoClasses={"NOT_INSTALLED"}}'
    with pytest.raises(ValueError, match='classes'):
        CargoCatalog.from_native(native)


def test_native_catalog_build_is_lazy(native):
    port_compartments({'compartments': [[[]]]}, native=native)
    assert native.reads == []
    target, _, _ = port_compartments(transport(entry('COAL')), native=native)
    assert native.reads and cargo_keys(target['compartments'][0]['loadConfigs']) == {'coal', 'iron_ore', 'grain', 'sand', 'stone', 'clay', 'cement'}


def test_audit_is_json_serializable(catalog):
    _, _, audit = port_compartments(transport(entry('COAL', 80)), catalog=catalog)
    assert json.loads(json.dumps(audit)) == audit

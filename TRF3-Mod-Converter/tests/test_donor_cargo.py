from copy import deepcopy
from types import SimpleNamespace

import pytest

from trf3_mod_converter.cargo_port import CargoCatalog, CargoType, port_compartments
from trf3_mod_converter.donor_cargo import (complete_missing_cargo, missing_cargo_requirements,
    has_payload_declaration, validate_source_cargo_identifiers)
from trf3_mod_converter.lua_metadata import TranslatedString


@pytest.fixture
def catalog():
    types = {}
    for tag, keys in {'BULK': ('coal', 'iron_ore', 'sand'), 'LIQUID': ('fuel', 'water'),
                      'GOODS': ('tools', 'books'), 'PASSENGERS': ('passengers',)}.items():
        for key in keys:
            classes = frozenset({tag} if tag == 'PASSENGERS' else {tag, 'UNIVERSAL'})
            types[key] = CargoType(key, f'cargos/{key}/{key}.cargo', classes)
    return CargoCatalog(types, classes={tag: f'cargos/classes/{tag.lower()}.cargoclass'
                                       for tag in ('BULK', 'GOODS', 'LIQUID', 'PASSENGERS', 'UNIVERSAL')}, formats={})


def source(*slots, schema='compartmentsList'):
    transport = {'carrier': 'RAIL', 'loadSpeed': 2}
    if schema == 'capacities':
        assert len(slots) == 1
        transport[schema] = slots[0]
    elif schema == 'compartments':
        transport[schema] = [[[entry] for entry in slot] for slot in slots]
    else:
        transport[schema] = [{'loadConfigs': [{'cargoEntries': [entry], 'toHide': [2]} for entry in slot]}
                             for slot in slots]
    return {'metadata': {'transportVehicle': transport}, 'version': 1, 'lods': [{'keep': True}]}


def cargo(kind='COAL', **fields):
    return {'type': kind, **fields}


def native_entry(kind='coal', capacity=80, *, classes=None, excluded=None):
    return {'capacity': capacity, 'cargoTypeSet': {'cargoClassesIncluded': classes or [],
            'cargoClassesExcluded': [], 'cargoTypesIncluded': [] if classes else [f'::/cargos/{kind}/{kind}.cargo'],
            'cargoTypesExcluded': excluded or []}, 'seats': [], 'loadIndicator': 'native_visuals'}


def donor(*slots):
    metadata = {'transportVehicle': {'compartments': [
        {'loadConfigs': [{'cargoEntry': entry, 'toHide': ['native_mesh']} for entry in slot]} for slot in slots]}}
    return SimpleNamespace(model={'metadata': metadata}, resource='vehicle/waggon/native/native.mdl',
                           evidence={'family': 'waggon', 'installedResource': True}, score=0.94)


@pytest.mark.parametrize('schema', ['capacities', 'compartments', 'compartmentsList'])
@pytest.mark.parametrize('missing', [None, 'absent'])
def test_three_tf2_schemas_complete_absent_capacity_and_preserve_everything(catalog, schema, missing):
    entry = cargo(seats=[1], cargoBay={'childId': 2, 'bbMin': [0, 0, 0], 'bbMax': [1, 1, 1]},
                  customCargoModels={'configurations': [{'slotLevels': [[0]]}]}, loadIndicator='authored')
    if missing != 'absent':
        entry['capacity'] = None
    original = source([entry], schema=schema)
    before = deepcopy(original)
    report = {}
    completed = complete_missing_cargo(original, donor([native_entry(capacity=72)]), catalog=catalog,
                                        model_path='vehicle/my_model.mdl', report=report)
    assert original == before
    restored = deepcopy(completed)
    transport = restored['metadata']['transportVehicle']
    target_entry = (transport[schema][0] if schema == 'capacities' else
                    transport[schema][0][0][0] if schema == 'compartments' else
                    transport[schema][0]['loadConfigs'][0]['cargoEntries'][0])
    assert target_entry.pop('capacity') == 72
    if missing is None:
        target_entry['capacity'] = None
    assert restored == original
    row = report['donorCompletions'][0]
    assert row['sourcePath'].endswith('/capacity')
    assert row['targetValue'] == row['donorValue'] == 72
    assert row['inferredFromSimilar'] and row['nativeTest'] == 'not_run'
    assert row['donorResource'].endswith('native.mdl') and row['matchScore'] == 0.94


def test_requirement_is_canonical_and_empty_locomotive_needs_no_donor():
    assert missing_cargo_requirements(source([cargo()])) == ('nativeCargoCapacityPolicy',)
    assert missing_cargo_requirements(source([cargo(capacity=0)])) == ()
    assert missing_cargo_requirements(source([{}])) == ()
    original = source([{}])
    assert complete_missing_cargo(original, None) == original
    assert missing_cargo_requirements({'metadata': []}) == ()
    assert missing_cargo_requirements({'metadata': {'transportVehicle': []}}) == ()


@pytest.mark.parametrize('schema', ['capacities', 'compartments', 'compartmentsList'])
@pytest.mark.parametrize('capacity,expected', [(None, True), (40, True), (0, False)])
def test_payload_declaration_follows_only_known_cargo_entries(schema, capacity, expected):
    assert has_payload_declaration(source([cargo(capacity=capacity)], schema=schema)) is expected


@pytest.mark.parametrize('entry', [{}, {'capacity': 0},
    {'capacity': 4, 'cargoTypeSet': {}},
    {'capacity': 4, 'cargoTypeSet': {'cargoClassesIncluded': [], 'cargoTypesIncluded': []}},
    {'capacity': None, 'cargoTypeSet': {'cargoClassesIncluded': [], 'cargoTypesIncluded': []}}])
def test_inactive_cargo_placeholders_do_not_require_payload_donor(entry):
    assert not has_payload_declaration(source([entry]))


def test_visual_type_fields_are_not_cargo_declarations():
    entry = {'capacity': 0, 'cargoBay': {'type': 'LEVEL'},
             'customCargoModels': {'configurations': [{'type': 'COAL'}]}}
    assert not has_payload_declaration(source([entry]))
    assert not has_payload_declaration(source([cargo(capacity=0, cargoBay={'type': 'LEVEL'})]))


@pytest.mark.parametrize('entry', [{'cargoType': 'COAL', 'capacity': 40},
    {'cargoTypeSet': {'cargoClassesIncluded': ['BULK']}, 'capacity': 40},
    {'cargoTypeSet': {'cargoTypesIncluded': ['COAL']}}, cargo()])
def test_explicit_type_or_type_set_activates_missing_or_positive_payload(entry):
    assert has_payload_declaration(source([entry]))


@pytest.mark.parametrize('entry', [cargo(TranslatedString('COAL'), capacity=0),
    {'cargoType': TranslatedString('COAL'), 'capacity': 0},
    {'cargoTypeSet': {'cargoClassesIncluded': [TranslatedString('BULK')]}, 'capacity': 0},
    {'cargoTypeSet': {'cargoClassesExcluded': [TranslatedString('BULK')]}, 'capacity': 0},
    {'cargoTypeSet': {'cargoTypesIncluded': [TranslatedString('COAL')]}, 'capacity': 0},
    {'cargoTypeSet': {'cargoTypesExcluded': [TranslatedString('COAL')]}, 'capacity': 0}])
def test_localized_id_guard_applies_even_to_complete_zero_capacity_entries(entry):
    with pytest.raises(ValueError, match='localized cargo identifiers'):
        validate_source_cargo_identifiers(source([entry]))


def test_localized_display_names_and_visual_metadata_are_not_cargo_identifiers():
    original = source([cargo(capacity=0, cargoBay={'type': TranslatedString('Decorative label')})])
    original['metadata']['description'] = {'name': TranslatedString('COAL')}
    validate_source_cargo_identifiers(original)
    assert original['metadata']['description']['name'] == 'COAL'


def test_preserves_supplied_capacities_and_only_donates_missing_alternative(catalog):
    original = source([cargo(capacity=20), cargo('IRON_ORE')])
    completed = complete_missing_cargo(original, donor([native_entry(capacity=80), native_entry('iron_ore', 60)]), catalog=catalog)
    loads = completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs']
    assert [load['cargoEntries'][0]['capacity'] for load in loads] == [20, 60]


def test_same_verified_class_donates_without_replacing_source_cargo(catalog):
    original = source([cargo('SAND')])
    report = {}
    completed = complete_missing_cargo(original, donor([native_entry('coal', 44), native_entry('iron_ore', 44)]),
                                        catalog=catalog, report=report)
    target = completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    assert target == {'type': 'SAND', 'capacity': 44}
    assert report['donorCompletions'][0]['matchingMethod'] == ['same_verified_cargo_class']


def test_exact_type_wins_over_other_same_class_capacities(catalog):
    completed = complete_missing_cargo(source([cargo()]),
                                      donor([native_entry('coal', 44), native_entry('iron_ore', 60)]), catalog=catalog)
    assert completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['capacity'] == 44


def test_exact_type_wins_over_native_class_wide_alternative(catalog):
    completed = complete_missing_cargo(source([cargo()]), donor([native_entry(capacity=44), native_entry(capacity=80, classes=['BULK'])]), catalog=catalog)
    assert completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['capacity'] == 44


def test_exact_cargo_identity_proves_reordered_independent_compartment_mapping(catalog):
    completed = complete_missing_cargo(source([cargo('IRON_ORE')], [cargo()]),
                                      donor([native_entry('coal', 20)], [native_entry('iron_ore', 30)]), catalog=catalog)
    compartments = completed['metadata']['transportVehicle']['compartmentsList']
    assert [compartment['loadConfigs'][0]['cargoEntries'][0]['capacity'] for compartment in compartments] == [30, 20]


def test_passenger_and_freight_reorder_matches_without_changing_source_seats(catalog):
    completed = complete_missing_cargo(source([cargo()], [cargo('PASSENGERS', seats=[0, 2])]),
                                      donor([native_entry('passengers', 24)], [native_entry('coal', 60)]), catalog=catalog)
    entries = [slot['loadConfigs'][0]['cargoEntries'][0] for slot in completed['metadata']['transportVehicle']['compartmentsList']]
    assert entries == [{'type': 'COAL', 'capacity': 60}, {'type': 'PASSENGERS', 'seats': [0, 2], 'capacity': 24}]


@pytest.mark.parametrize('source_cargo,native_slots', [
    ('SAND', [[native_entry('coal', 44), native_entry('iron_ore', 60)]]),
    ('COAL', [[native_entry('coal', 44), native_entry('coal', 60)]]),
    ('OIL', [[native_entry('fuel', 30), native_entry('water', 40)]]),
    ('GOODS', [[native_entry('tools', 30), native_entry('books', 40)]]),
    ('PASSENGERS', [[native_entry('coal', 44)]]),
])
def test_conflicting_native_alternatives_and_different_classes_block_atomically(catalog, source_cargo, native_slots):
    original = source([cargo(source_cargo)])
    before, report = deepcopy(original), {'donorCompletions': [{'previous': True}]}
    with pytest.raises(ValueError, match='layout|alternatives'):
        complete_missing_cargo(original, donor(*native_slots), catalog=catalog, report=report)
    assert original == before and report == {'donorCompletions': [{'previous': True}]}


def test_same_class_duplicate_compartments_with_different_capacities_are_ambiguous(catalog):
    report = {}
    with pytest.raises(ValueError, match='ambiguous capacities'):
        complete_missing_cargo(source([cargo()], [cargo()]),
                               donor([native_entry(capacity=20)], [native_entry(capacity=30)]), catalog=catalog, report=report)
    assert report == {}


def test_duplicate_compartments_with_identical_capacities_have_unambiguous_values(catalog):
    completed = complete_missing_cargo(source([cargo()], [cargo()]),
                                      donor([native_entry(capacity=20)], [native_entry(capacity=20)]), catalog=catalog)
    assert all(slot['loadConfigs'][0]['cargoEntries'][0]['capacity'] == 20
               for slot in completed['metadata']['transportVehicle']['compartmentsList'])


def test_count_mismatch_blocks(catalog):
    with pytest.raises(ValueError, match='compartment counts'):
        complete_missing_cargo(source([cargo()]), donor([native_entry()], [native_entry()]), catalog=catalog)


@pytest.mark.parametrize('bad', [-1, True, '32', float('nan'), float('inf')])
def test_invalid_supplied_capacity_is_preserved_and_blocks_instead_of_replaced(catalog, bad):
    original = source([cargo(capacity=bad), cargo('IRON_ORE')])
    with pytest.raises(ValueError, match='invalid supplied data'):
        complete_missing_cargo(original, donor([native_entry(), native_entry('iron_ore')]), catalog=catalog)
    assert original['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['capacity'] is bad


@pytest.mark.parametrize('kind', ['UNKNOWN_MOD_CARGO', None, ''])
def test_unknown_cargo_identity_is_never_inferred_from_donor(catalog, kind):
    with pytest.raises(ValueError, match='cargo|Cargo'):
        complete_missing_cargo(source([cargo(kind)]), donor([native_entry()]), catalog=catalog)


@pytest.mark.parametrize('entry', [cargo(TranslatedString('COAL')),
    {'cargoTypeSet': {'cargoTypesIncluded': [TranslatedString('COAL')]}},
    {'cargoTypeSet': {'cargoClassesIncluded': [TranslatedString('BULK')]}}])
def test_localized_cargo_identifiers_cannot_establish_donor_class(catalog, entry):
    with pytest.raises(ValueError, match='localized|literal cargo identifiers'):
        complete_missing_cargo(source([entry]), donor([native_entry()]), catalog=catalog)


def test_explicit_catalog_alias_is_respected(catalog):
    alias_catalog = CargoCatalog(catalog.types, classes=catalog.classes, formats=catalog.formats,
                                 aliases={'MY_COAL': ['coal']})
    completed = complete_missing_cargo(source([cargo('MY_COAL')]), donor([native_entry(capacity=70)]), catalog=alias_catalog)
    assert completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0] == {'type': 'MY_COAL', 'capacity': 70}


def test_existing_cargo_set_exclusions_determine_donor_identity(catalog):
    entry = {'cargoTypeSet': {'cargoClassesIncluded': ['BULK'], 'cargoTypesExcluded': ['SAND', 'IRON_ORE']}}
    completed = complete_missing_cargo(source([entry]), donor([native_entry(capacity=32), native_entry('sand', 99)]), catalog=catalog)
    assert completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0] == {**entry, 'capacity': 32}


def test_literal_single_fixed_mixed_load_preserves_source_layout(catalog):
    original = source([cargo()])
    load = original['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    load['cargoEntries'].append(cargo('PASSENGERS', capacity=24, seats=[0]))
    completed = complete_missing_cargo(original, donor([native_entry(capacity=80)], [native_entry('passengers', 30)]), catalog=catalog)
    target = completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    assert target['toHide'] == [2] and target['cargoEntries'] == [{'type': 'COAL', 'capacity': 80},
                                                                {'type': 'PASSENGERS', 'capacity': 24, 'seats': [0]}]


def test_completed_capacity_is_accepted_by_existing_cargo_export(catalog):
    completed = complete_missing_cargo(source([cargo('SAND')]), donor([native_entry(capacity=36)]), catalog=catalog)
    # This test targets donated schema compatibility without model hide nodes.
    completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['toHide'] = []
    converted, _, audit = port_compartments(completed['metadata']['transportVehicle'], catalog=catalog)
    assert converted['compartments'][0]['loadConfigs'][0]['cargoEntry']['capacity'] == 36
    assert audit['maxCapacity'] == 36


def test_missing_capacity_requires_installed_catalog():
    with pytest.raises(ValueError, match='selected TF3 cargo catalog'):
        complete_missing_cargo(source([cargo()]), donor([native_entry()]))


def test_metadata_only_donor_does_not_require_or_evaluate_lod_helpers(catalog):
    selected = donor([native_entry(capacity=40)])

    class MetadataMatch:
        metadata = selected.model['metadata']
        resource = selected.resource
        evidence = selected.evidence
        score = selected.score

        @property
        def model(self):
            raise AssertionError('Cargo capacities do not require parsing donor LOD helpers')

    completed = complete_missing_cargo(source([cargo()]), MetadataMatch(), catalog=catalog)
    assert completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['capacity'] == 40


def test_protects_against_large_layout_matching(catalog):
    with pytest.raises(ValueError, match='32 independent compartments'):
        complete_missing_cargo(source(*[[cargo()] for _ in range(33)]),
                               donor(*[[native_entry()] for _ in range(33)]), catalog=catalog)

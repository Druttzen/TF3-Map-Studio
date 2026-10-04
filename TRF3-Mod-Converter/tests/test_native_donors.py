from copy import deepcopy

import pytest

from trf3_mod_converter.native_donors import NativeDonorCatalog
from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.tf2_vehicle_port import emit


class Native:
    def __init__(self, models):
        self.files = {resource: emit(data).encode() for resource, data in models.items()}
        self.references = set()
        self._cache_owner = self
        for tag in ('PASSENGERS', 'BULK', 'LIQUID', 'GOODS', 'FLATBED', 'UNIVERSAL'):
            self.files[f'cargos/classes/{tag.lower()}.cargoclass.lua'] = emit({'tag': tag}).encode()
        for name, classes in {'passengers': ['PASSENGERS'], 'coal': ['BULK', 'UNIVERSAL'],
                              'oil': ['LIQUID', 'UNIVERSAL'], 'goods': ['GOODS', 'UNIVERSAL'],
                              'wood': ['FLATBED', 'UNIVERSAL']}.items():
            self.files[f'cargos/{name}/{name}.cargo.lua'] = emit({'cargoClasses': classes}).encode()
        self.reads = []

    def read(self, path):
        self.reads.append(path)
        return self.files[path]

    def reference(self, path):
        assert path in self.files
        self.references.add(path)
        return '::/' + path

    def fork(self):
        result = object.__new__(type(self))
        result.files, result.reads, result.references = self.files, self.reads, set()
        result._cache_owner = self._cache_owner
        return result


def bounds(length=10, width=2, height=3):
    return {'bbMin': [-length / 2, -width / 2, 0], 'bbMax': [length / 2, width / 2, height]}


def source(cargo='PASSENGERS', carrier='RAIL', engine='DIESEL', size='SMALL'):
    model = {'version': 1, 'boundingInfo': bounds(), 'lods': [], 'metadata': {}}
    m = model['metadata']
    if cargo:
        compartments = [{'loadConfigs': [{'cargoEntries': [{'type': cargo, 'capacity': 40}]}]}]
    else:
        compartments = []
    m['transportVehicle'] = {'carrier': carrier, 'compartmentsList': compartments}
    physical = {'topSpeed': 20, 'weight': 15}
    if carrier in ('RAIL', 'TRAM'):
        physical['engines'] = [] if engine is None else [{'type': engine, 'power': 200, 'tractiveEffort': 40}]
        m['railVehicle'] = physical
    elif carrier == 'ROAD':
        physical['engine'] = {} if engine is None else {'type': engine, 'power': 200, 'tractiveEffort': 40}
        m['roadVehicle'] = physical
    elif carrier == 'AIR':
        physical.update(type=size, wingArea=25, maxThrust=10000, timeToFullThrust=3, weight=15000)
        m['airVehicle'] = physical
        m['soundConfig'] = {'soundSet': {'name': 'aircraft_prop_old'}}
    else:
        physical.update(type=size, availPower=10000, maxRpm=130, area=25, weight=15000)
        m['waterVehicle'] = physical
        m['soundConfig'] = {'soundSet': {'name': 'ship_diesel_old'}}
    return model


def donor(*, cargo='PASSENGERS', carrier='RAIL', engine='DIESEL', size='SMALL', payload=12000):
    src = source(cargo, carrier, engine, size)
    src['version'] = 2
    m = src['metadata']
    m['extent'] = bounds()
    t = m['transportVehicle']
    del t['compartmentsList']
    tag = {'COAL': 'BULK', 'OIL': 'LIQUID', 'GOODS': 'GOODS', 'WOOD': 'FLATBED'}.get(cargo, cargo)
    t['compartments'] = [] if cargo is None else [{'loadConfigs': [{'cargoEntry': {'capacity': 40, 'cargoTypeSet': {'cargoClassesIncluded': [tag]}}}]}]
    if carrier in ('RAIL', 'TRAM', 'ROAD'):
        block = m['railVehicle'] if carrier in ('RAIL', 'TRAM') else m['roadVehicle']
        engines = block.pop('engines') if carrier in ('RAIL', 'TRAM') else [block.pop('engine')]
        if engines == [{}]:
            engines = []
        m['landVehicle'] = {'engines': engines, 'topSpeed': block.pop('topSpeed'), 'weightEmpty': block.pop('weight') * 1000,
                            'weightMaxPayload': payload}
        mode = 'TRAIN' if carrier == 'RAIL' else 'TRAM' if carrier == 'TRAM' else 'BUS' if cargo == 'PASSENGERS' else 'TRUCK'
    else:
        block = m['airVehicle'] if carrier == 'AIR' else m['waterVehicle']
        block.pop('type')
        block['weightEmpty'] = block.pop('weight')
        block['weightMaxPayload'] = payload
        mode = ('SMALL_AIRCRAFT' if size == 'SMALL' else 'AIRCRAFT') if carrier == 'AIR' else 'SMALL_SHIP' if size == 'SMALL' else 'SHIP'
        name = 'aircraft_prop_old' if carrier == 'AIR' else 'ship_diesel_old'
        family = 'plane' if carrier == 'AIR' else 'ship'
        m['soundConfig']['soundSet']['name'] = f'/vehicle/{family}/shared/sound/{name}.snd'
    t['transportModes'] = [mode]
    return src


def catalog(models):
    return NativeDonorCatalog.from_native(Native(models))


def test_matching_incomplete_numeric_engine_data_uses_native_units_and_is_immutable():
    src = source()
    del src['metadata']['railVehicle']['weight']
    del src['metadata']['railVehicle']['engines'][0]['power']
    before = deepcopy(src)
    cat = catalog({'vehicle/train/model/model.mdl': donor()})
    match = cat.match(src, requirements=['landVehicle.weightEmpty', 'landVehicle.engines.0.power'])
    assert match.value('landVehicle.weightEmpty') == 15000
    assert match.value('landVehicle.engines.0.power') == 200
    assert src == before
    assert match.resource == 'vehicle/train/model/model.mdl'
    assert match.score == 0
    assert match.raw_capacity == 40
    assert any(row.get('feature') == 'raw_capacity' for row in match.evidence)
    copy = match.model
    copy['metadata']['landVehicle']['weightEmpty'] = 1
    assert match.value('landVehicle.weightEmpty') == 15000
    assert match.audit()['nativeTest'] == 'not_run'


@pytest.mark.parametrize('change', ['engine_type', 'engine_count', 'powered', 'carrier', 'cargo_role', 'cargo_class', 'size'])
def test_rejects_wrong_metadata_class_propulsion_and_size(change):
    src = source('PASSENGERS', 'AIR') if change == 'size' else source('COAL')
    native = donor(cargo='PASSENGERS', carrier='AIR', size='BIG') if change == 'size' else donor(cargo='COAL')
    m = native['metadata']
    if change == 'engine_type':
        m['landVehicle']['engines'][0]['type'] = 'ELECTRIC'
    elif change == 'engine_count':
        m['landVehicle']['engines'].append(deepcopy(m['landVehicle']['engines'][0]))
    elif change == 'powered':
        m['landVehicle']['engines'] = []
    elif change == 'carrier':
        native = donor(cargo='COAL', carrier='ROAD')
    elif change == 'cargo_role':
        native = donor(cargo='PASSENGERS')
    elif change == 'cargo_class':
        native = donor(cargo='OIL')
    cat = catalog({'vehicle/a/a.mdl': native})
    with pytest.raises(ValueError, match='No sufficiently similar'):
        cat.match(src, requirements=['nativePayloadRatio'])


def test_equal_size_aircraft_still_rejects_known_jet_vs_propeller():
    d = donor(carrier='AIR')
    d['metadata']['soundConfig']['soundSet']['name'] = '/vehicle/plane/shared/sound/aircraft_jet_old.snd'
    cat = catalog({'vehicle/plane/jet/jet.mdl': d})
    with pytest.raises(ValueError, match='No sufficiently similar'):
        cat.match(source(carrier='AIR'), requirements=['airVehicle.maxThrust'])


def test_unknown_custom_propulsion_allows_geometry_balancing_but_blocks_propulsion_data():
    src = source(carrier='AIR')
    src['metadata']['soundConfig']['soundSet']['name'] = 'my_jet_custom_sound'
    cat = catalog({'vehicle/plane/prop/prop.mdl': donor(carrier='AIR')})
    with pytest.raises(ValueError, match='propulsion is not verified'):
        cat.match(src, requirements=['airVehicle.maxThrust'])
    match = cat.match(src, requirements=['nativePayloadRatio'])
    assert match.value('nativePayloadRatio') == 300
    assert not match.evidence[0]['propulsionVerified']
    assert cat.match(src, requirements=['airVehicle.wingArea']).value('airVehicle.wingArea') == 25


def test_wrong_dimensions_and_conflicting_known_physics_are_not_donors():
    for field in ('dimensions', 'known_weight'):
        d = donor()
        if field == 'dimensions':
            d['metadata']['extent'] = bounds(length=30)
        else:
            d['metadata']['landVehicle']['weightEmpty'] = 50000
        cat = catalog({'vehicle/train/a/a.mdl': d})
        with pytest.raises(ValueError, match='No sufficiently similar'):
            cat.match(source(), requirements=['nativePayloadRatio'])


def test_near_equal_candidates_with_different_requested_values_block_ambiguity():
    a, b = donor(payload=12000), donor(payload=16000)
    cat = catalog({'vehicle/train/b/b.mdl': b, 'vehicle/train/a/a.mdl': a})
    with pytest.raises(ValueError, match='Ambiguous installed TF3 donors'):
        cat.match(source(), requirements=['nativePayloadRatio'])
    assert cat.native.references == set()


def test_equal_requested_data_ties_are_deterministic_and_do_not_require_whole_model_equality():
    a, b = donor(), donor()
    b['metadata']['description'] = {'name': 'Another object'}
    cat = catalog({'vehicle/train/z/z.mdl': b, 'vehicle/train/a/a.mdl': a})
    result = cat.match(source(), requirements=['nativePayloadRatio'])
    assert result.resource == 'vehicle/train/a/a.mdl'
    assert result.confidence == 'equivalent_required_values'
    assert result.equivalent_resources == ('vehicle/train/z/z.mdl',)
    assert result.runner_up['scoreGap'] == 0
    with pytest.raises(ValueError, match='Ambiguous'):
        cat.match(source())


@pytest.mark.parametrize('field,value', [('weight', -1), ('topSpeed', '20'), ('topSpeed', True)])
def test_invalid_supplied_source_data_cannot_be_replaced(field, value):
    src = source()
    src['metadata']['railVehicle'][field] = value
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    with pytest.raises(ValueError, match='invalid supplied data cannot be replaced'):
        cat.match(src, requirements=['landVehicle.weightEmpty'])


def test_lua_nil_numeric_values_are_missing_not_invalid_type_markers():
    src = source()
    src['metadata']['railVehicle']['weight'] = None
    src['metadata']['railVehicle']['engines'][0]['power'] = None
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    match = cat.match(src, requirements=['landVehicle.weightEmpty', 'landVehicle.engines.0.power'])
    assert match.value('landVehicle.weightEmpty') == 15000
    assert not any(row.get('feature') in ('weightEmpty', 'engine.0.power') for row in match.evidence)


def test_malformed_unhashable_type_markers_raise_actionable_value_errors():
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    for field in ('carrier', 'engine', 'cargo_class'):
        src = source()
        if field == 'carrier':
            src['metadata']['transportVehicle']['carrier'] = []
        elif field == 'engine':
            src['metadata']['railVehicle']['engines'][0]['type'] = {}
        else:
            entry = src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
            del entry['type']
            entry['cargoTypeSet'] = {'cargoClassesIncluded': [{}]}
        with pytest.raises(ValueError):
            cat.match(src, requirements=['nativePayloadPolicy'])
    with pytest.raises(ValueError, match='requirements'):
        cat.match(source(), requirements=[{}])


@pytest.mark.parametrize('missing', ['bounds', 'engine_type', 'carrier', 'cargo_type', 'ship_type'])
def test_missing_class_or_geometry_cannot_be_invented(missing):
    src = source(carrier='WATER') if missing == 'ship_type' else source()
    native = donor(carrier='WATER') if missing == 'ship_type' else donor()
    if missing == 'bounds':
        del src['boundingInfo']
    elif missing == 'engine_type':
        del src['metadata']['railVehicle']['engines'][0]['type']
    elif missing == 'carrier':
        del src['metadata']['transportVehicle']['carrier']
    elif missing == 'cargo_type':
        del src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['type']
    else:
        del src['metadata']['waterVehicle']['type']
    cat = catalog({'vehicle/a/a.mdl': native})
    with pytest.raises(ValueError):
        cat.match(src, requirements=['nativePayloadRatio'])


def test_parse_failures_are_reported_and_skipped_not_executed():
    native = Native({'vehicle/train/good/good.mdl': donor()})
    native.files['vehicle/train/bad/bad.mdl'] = b'function data() os.execute("must_not_run"); return {} end'
    cat = NativeDonorCatalog.from_native(native)
    assert len(cat.donors) == 1
    assert cat.diagnostics[0]['resource'] == 'vehicle/train/bad/bad.mdl'
    assert cat.diagnostics[0]['action'] == 'excluded_from_donor_catalog'
    assert cat.match(source(), requirements=['nativePayloadRatio']).resource.endswith('/good.mdl')


def test_catalog_is_cached_but_reference_provenance_binds_to_the_current_mod_fork():
    native = Native({'vehicle/train/a/a.mdl': donor()})
    first, second = native.fork(), native.fork()
    one = NativeDonorCatalog.from_native(first)
    reads = len(native.reads)
    two = NativeDonorCatalog.from_native(second)
    assert len(native.reads) == reads
    assert one.donors is two.donors
    one.match(source(), requirements=['nativePayloadRatio'])
    assert first.references == {'vehicle/train/a/a.mdl'}
    assert second.references == native.references == set()
    two.match(source(), requirements=['nativePayloadRatio'])
    assert second.references == first.references


def test_missing_capacity_is_not_similarity_evidence_but_declared_class_is_kept():
    src = source()
    del src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['capacity']
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    result = cat.match(src, requirements=['transportVehicle.compartments'])
    assert result.raw_capacity == 40
    assert not any(row.get('feature') == 'raw_capacity' for row in result.evidence)


def test_lua_nil_capacity_is_missing_but_a_present_invalid_capacity_still_blocks():
    src = source()
    entry = src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    entry['capacity'] = None
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    assert cat.match(src, requirements=['transportVehicle.compartments']).raw_capacity == 40
    entry['capacity'] = 'forty'
    with pytest.raises(ValueError, match='invalid supplied data'):
        cat.match(src, requirements=['transportVehicle.compartments'])


def test_native_placeholder_compartment_is_not_misclassified_as_freight():
    src = source(cargo=None)
    d = donor(cargo=None)
    d['metadata']['transportVehicle']['compartments'] = [{'loadConfigs': [{'cargoEntry': {'capacity': 4, 'cargoTypeSet': {'cargoClassesIncluded': []}}}]}]
    cat = catalog({'vehicle/train/a/a.mdl': d})
    result = cat.match(src, requirements=['landVehicle.weightEmpty'])
    assert result.raw_capacity == 0
    with pytest.raises(ValueError, match='positive declared cargo capacity'):
        result.value('nativePayloadRatio')


def test_body_extent_used_instead_of_expanded_effect_bounding_box():
    d = donor()
    d['boundingInfo'] = bounds(length=50, width=20, height=30)
    cat = catalog({'vehicle/train/a/a.mdl': d})
    assert cat.match(source(), requirements=['nativePayloadRatio']).dimensions == (10, 2, 3)


def test_catalog_and_scalar_values_do_not_eagerly_parse_selected_donor_lods(monkeypatch):
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    def unexpected_full_read(text):
        raise RuntimeError('Full LOD parser is only needed for selected geometry')
    monkeypatch.setattr('trf3_mod_converter.native_donors.load_resource_table', unexpected_full_read)
    match = cat.match(source(), requirements=['nativePayloadPolicy'])
    assert match.metadata['landVehicle']['weightEmpty'] == 15000
    assert match.value('nativePayloadRatio') == 300
    with pytest.raises(RuntimeError, match='Full LOD parser'):
        _ = match.model


def test_body_bounds_falls_back_to_projected_bounding_info_without_full_lod_parse(monkeypatch):
    d = donor()
    del d['metadata']['extent']
    cat = catalog({'vehicle/train/a/a.mdl': d})
    def unexpected_full_read(text):
        raise RuntimeError('body bounds must not read full LOD tables')
    monkeypatch.setattr('trf3_mod_converter.native_donors.load_resource_table', unexpected_full_read)
    match = cat.match(source(), requirements=['nativePayloadPolicy'])
    original = match.body_bounds
    original['bbMin'][0] = -500
    assert match.body_bounds == bounds()


def test_selected_full_model_is_cached_once_and_defensively_copied(monkeypatch):
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    match = cat.match(source(), requirements=['nativePayloadPolicy'])
    from trf3_mod_converter.resource_profiles import load_resource_table
    reads = []
    def read_once(text):
        reads.append(1)
        return load_resource_table(text)
    monkeypatch.setattr('trf3_mod_converter.native_donors.load_resource_table', read_once)
    first = match.model
    first['lods'].append({'node': {'mesh': 'changed'}})
    assert match.model['lods'] == [] and len(reads) == 1


def test_universal_freight_donor_cannot_change_source_classes_or_match_passengers():
    d = donor(cargo='UNIVERSAL')
    cat = catalog({'vehicle/train/universal/universal.mdl': d})
    match = cat.match(source('COAL'), requirements=['nativePayloadRatio'])
    gate = match.evidence[0]
    assert gate['sourceCargoClasses'] == ['BULK'] and gate['universalFreightDonor']
    with pytest.raises(ValueError, match='No sufficiently similar'):
        cat.match(source('PASSENGERS'), requirements=['nativePayloadRatio'])


def test_universal_donor_explicit_exclusions_are_preserved_in_matching():
    d = donor(cargo='UNIVERSAL')
    entry = d['metadata']['transportVehicle']['compartments'][0]['loadConfigs'][0]['cargoEntry']
    entry['cargoTypeSet']['cargoClassesExcluded'] = ['LIQUID']
    cat = catalog({'vehicle/train/a/a.mdl': d})
    with pytest.raises(ValueError, match='No sufficiently similar'):
        cat.match(source('OIL'), requirements=['nativePayloadPolicy'])
    assert cat.match(source('COAL'), requirements=['nativePayloadPolicy']).value('nativePayloadRatio') == 300


def test_partial_source_capacity_is_never_scored_as_the_complete_vehicle_total():
    src = source()
    comp = deepcopy(src['metadata']['transportVehicle']['compartmentsList'][0])
    del comp['loadConfigs'][0]['cargoEntries'][0]['capacity']
    src['metadata']['transportVehicle']['compartmentsList'].append(comp)
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    result = cat.match(src, requirements=['nativePayloadPolicy'])
    assert not any(row.get('feature') == 'raw_capacity' for row in result.evidence)


def test_named_source_cargo_entry_and_inactive_locomotive_placeholders_match():
    src = source()
    config = src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]
    config['cargoEntry'] = config.pop('cargoEntries')[0]
    cat = catalog({'vehicle/train/a/a.mdl': donor()})
    assert cat.match(src, requirements=['nativePayloadPolicy']).raw_capacity == 40
    for placeholder in ([], [{}]):
        src = source(cargo=None)
        src['metadata']['transportVehicle']['compartmentsList'] = [{'loadConfigs': [{'cargoEntries': placeholder}]}]
        inactive = catalog({'vehicle/train/a/a.mdl': donor(cargo=None)})
        assert inactive.match(src, requirements=['landVehicle.weightEmpty']).raw_capacity == 0


def test_missing_positive_cargo_identity_or_real_seats_still_blocks_placeholder_shortcut():
    for entry in ({'capacity': 1}, {'capacity': 0, 'seats': [0]}):
        src = source(cargo=None)
        src['metadata']['transportVehicle']['compartmentsList'] = [{'loadConfigs': [{'cargoEntries': [entry]}]}]
        cat = catalog({'vehicle/train/a/a.mdl': donor(cargo=None)})
        with pytest.raises(ValueError, match='cannot invent its class'):
            cat.match(src, requirements=['landVehicle.weightEmpty'])


def test_cargo_capacity_policy_ignores_donor_visuals_but_preserves_semantic_differences():
    a, b = donor(), donor()
    entry = b['metadata']['transportVehicle']['compartments'][0]['loadConfigs'][0]['cargoEntry']
    entry.update(loadIndicator='different_visual_nodes', seats=[1, 2])
    b['metadata']['transportVehicle']['compartments'][0]['loadConfigs'][0]['toHide'] = ['different_body']
    cat = catalog({'vehicle/train/a/a.mdl': a, 'vehicle/train/b/b.mdl': b})
    assert cat.match(source(), requirements=['nativeCargoCapacityPolicy']).resource == 'vehicle/train/a/a.mdl'
    with pytest.raises(ValueError, match='Ambiguous'):
        cat.match(source(), requirements=['transportVehicle.compartments'])
    b['metadata']['transportVehicle']['compartments'][0]['loadConfigs'][0]['cargoEntry']['capacity'] = 45
    cat = catalog({'vehicle/train/a/a.mdl': a, 'vehicle/train/b/b.mdl': b})
    with pytest.raises(ValueError, match='Ambiguous'):
        cat.match(source(), requirements=['nativeCargoCapacityPolicy'])


def test_localized_class_markers_never_establish_physical_identity():
    for field in ('carrier', 'engine', 'size', 'cargo_class'):
        src = source(carrier='AIR') if field == 'size' else source()
        native = donor(carrier='AIR') if field == 'size' else donor()
        if field == 'carrier':
            src['metadata']['transportVehicle']['carrier'] = TranslatedString('RAIL')
        elif field == 'engine':
            src['metadata']['railVehicle']['engines'][0]['type'] = TranslatedString('DIESEL')
        elif field == 'size':
            src['metadata']['airVehicle']['type'] = TranslatedString('SMALL')
        else:
            entry = src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
            del entry['type']
            entry['cargoTypeSet'] = {'cargoClassesIncluded': [TranslatedString('PASSENGERS')]}
        with pytest.raises(ValueError):
            catalog({'vehicle/a/a.mdl': native}).match(src, requirements=['nativePayloadPolicy'])


def test_missing_requested_native_field_excludes_that_donor():
    d = donor()
    del d['metadata']['landVehicle']['weightMaxPayload']
    cat = catalog({'vehicle/train/a/a.mdl': d})
    with pytest.raises(ValueError, match='No sufficiently similar'):
        cat.match(source(), requirements=['nativePayloadRatio'])


def test_aircraft_native_payload_omission_is_a_verified_policy_not_a_synthetic_ratio():
    d = donor(carrier='AIR')
    del d['metadata']['airVehicle']['weightMaxPayload']
    cat = catalog({'vehicle/plane/a/a.mdl': d})
    match = cat.match(source(carrier='AIR'), requirements=['nativePayloadPolicy'])
    assert match.value('nativePayloadPolicy') == {'field': 'airVehicle.weightMaxPayload', 'policy': 'omit_as_selected_native_profile', 'ratio': None}
    with pytest.raises(ValueError, match='does not declare'):
        match.value('nativePayloadRatio')
    rail = catalog({'vehicle/train/a/a.mdl': donor()}).match(source(), requirements=['nativePayloadPolicy'])
    assert rail.value('nativePayloadPolicy') == {'field': 'landVehicle.weightMaxPayload', 'policy': 'matched_native_capacity_ratio', 'ratio': 300}


def gear_config():
    return {'axles': ['axle_right', 'axle_left'], 'axleRadii': [.5, .5],
            'wheels': ['wheel_front'], 'wheelRadii': [.3]}


def test_gear_radius_policy_ignores_controls_contacts_and_visuals_in_donor_ties():
    a, b = donor(carrier='AIR'), donor(carrier='AIR')
    a['metadata']['airVehicle']['config'] = gear_config()
    b['metadata']['airVehicle']['config'] = gear_config()
    b['metadata']['airVehicle']['config'].update(fakeBogies=[[{'group': 'another_body', 'position': 1, 'offset': 0}]],
                                                steeringParts=['different_steering_node'])
    a['metadata']['airVehicle']['axles'] = [{'position': [1, .5], 'radius': .5}]
    b['metadata']['airVehicle']['axles'] = [{'position': [2, .6], 'radius': .6}]
    cat = catalog({'vehicle/plane/a/a.mdl': a, 'vehicle/plane/b/b.mdl': b})
    result = cat.match(source(carrier='AIR'), requirements=['nativeGearRadiusPolicy'])
    assert result.value('nativeGearRadiusPolicy') == {
        'axles': [{'node': 'axle_left', 'radius': .5}, {'node': 'axle_right', 'radius': .5}],
        'wheels': [{'node': 'wheel_front', 'radius': .3}]}
    assert result.confidence == 'equivalent_required_values'
    with pytest.raises(ValueError, match='Ambiguous'):
        cat.match(source(carrier='AIR'), requirements=['airVehicle.config'])


def test_gear_radius_policy_conflicts_in_donated_values_still_block_ambiguity():
    a, b = donor(carrier='AIR'), donor(carrier='AIR')
    a['metadata']['airVehicle']['config'] = gear_config()
    b['metadata']['airVehicle']['config'] = gear_config()
    b['metadata']['airVehicle']['config']['wheelRadii'] = [.4]
    cat = catalog({'vehicle/plane/a/a.mdl': a, 'vehicle/plane/b/b.mdl': b})
    with pytest.raises(ValueError, match='Ambiguous'):
        cat.match(source(carrier='AIR'), requirements=['nativeGearRadiusPolicy'])


@pytest.mark.parametrize('change', ['radius_zero', 'radius_negative', 'radius_bool', 'short_array', 'duplicate_node', 'localized_node', 'generated_node'])
def test_gear_radius_policy_rejects_unverified_native_arrays_and_ids(change):
    d = donor(carrier='AIR')
    config = d['metadata']['airVehicle']['config'] = gear_config()
    if change == 'radius_zero':
        config['wheelRadii'] = [0]
    elif change == 'radius_negative':
        config['wheelRadii'] = [-1]
    elif change == 'radius_bool':
        config['wheelRadii'] = [True]
    elif change == 'short_array':
        config['axleRadii'] = [.5]
    elif change == 'duplicate_node':
        config['axles'] = ['same', 'same']
    elif change == 'localized_node':
        config['wheels'] = [TranslatedString('wheel_front')]
    else:
        config['wheels'] = ['node_4']
    cat = catalog({'vehicle/plane/a/a.mdl': d})
    with pytest.raises(ValueError, match='No sufficiently similar'):
        cat.match(source(carrier='AIR'), requirements=['nativeGearRadiusPolicy'])

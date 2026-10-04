"""Completion policy and complete package exports, using authored native fixtures."""
from copy import deepcopy
import json

import pytest

from trf3_mod_converter.batch import _preflight_profile, convert_queue, scan_mods
from trf3_mod_converter.lua_metadata import load_lua_table
from trf3_mod_converter.lua_metadata import TranslatedString
from trf3_mod_converter.missing_data import (
    classify_missing_model, complete_missing_model, complete_payload,
)
from trf3_mod_converter.tf2_vehicle_port import NativeInventory, port_tf2_mod, snapshot
from test_export_profiles import cargo_files, native_files, write_model
from test_native_donors import Native, bounds, donor, source
from test_tf2_vehicle_port import fixture_mod, model


def pair(cargo=None, carrier='RAIL', engine='DIESEL'):
    empty_road = carrier=='ROAD' and cargo is None
    if empty_road: cargo='PASSENGERS'
    src = source(cargo, carrier, engine)
    dst = donor(cargo=cargo, carrier=carrier, engine=engine)
    for m in (src, dst):
        m['metadata']['transportVehicle']['loadSpeed'] = 3
    if empty_road:
        src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]['capacity']=0
        dst['metadata']['transportVehicle']['compartments'][0]['loadConfigs'][0]['cargoEntry']['capacity']=0
    if carrier == 'AIR':
        src['lods']=[{'node':{'name':'root','children':[]}}]
        src['metadata']['airVehicle']['configs'] = [{'axles':[],'wheels':[],'axleRadii':[],'wheelRadii':[]}]
    if carrier == 'WATER':
        src['metadata']['waterVehicle']['waterLine'] = [[-5,-1],[5,-1],[5,1],[-5,1]]
        dst['metadata']['waterVehicle']['waterLine'] = deepcopy(src['metadata']['waterVehicle']['waterLine'])
    return src, dst


def installed(dst):
    return Native({'vehicle/test/test.mdl': dst})


@pytest.mark.parametrize('carrier,block', [('RAIL','railVehicle'),('TRAM','railVehicle'),
    ('ROAD','roadVehicle'),('WATER','waterVehicle'),('AIR','airVehicle')])
def test_missing_weight_and_speed_completed_with_correct_source_units(carrier, block):
    src, dst = pair(carrier=carrier)
    src['metadata'][block].pop('weight')
    src['metadata'][block]['topSpeed'] = None
    before = deepcopy(src); report = {}
    completed, match = complete_missing_model(src, installed(dst), report=report,model_path='fixture.mdl')
    assert src == before
    assert completed['metadata'][block]['weight'] == (15 if carrier in ('RAIL','TRAM','ROAD') else 15000)
    assert completed['metadata'][block]['topSpeed'] == 20
    assert match.resource == 'vehicle/test/test.mdl'
    rows = report['dataCompletions']
    assert {r['field'] for r in rows} == {block+'.weight',block+'.topSpeed'}
    assert all(r['model']=='fixture.mdl' and r['nativeTest']=='not_run' for r in rows)
    assert all(r['estimated'] and r['sourceValue'] is None for r in rows)


def test_nil_engine_power_is_completed_and_existing_tractive_effort_retained():
    src,dst=pair(); engine=src['metadata']['railVehicle']['engines'][0]
    engine['power']=None;engine['tractiveEffort']=45
    completed, _ = complete_missing_model(src,installed(dst))
    assert completed['metadata']['railVehicle']['engines'][0] == {'type':'DIESEL','power':200,'tractiveEffort':45}
    assert engine['power'] is None
    assert classify_missing_model(src).engine_types==('DIESEL',)


def test_complete_source_and_zero_payload_never_search_for_donors():
    src,_=pair(); report={}
    completed,match=complete_missing_model(src,object(),report=report)
    assert completed==src and completed is not src and match is None and report=={}
    assert complete_payload(src,object(),0,report=report)==(0,'no_payload_for_zero_capacity')
    assert report=={}


def test_no_load_native_locomotive_omits_optional_loading_speed():
    src,dst=pair();src['metadata']['transportVehicle'].pop('loadSpeed')
    dst['metadata']['transportVehicle'].pop('loadSpeed')
    src['metadata']['railVehicle'].pop('weight');report={};progress=[]
    completed,_=complete_missing_model(src,installed(dst),report=report,progress=progress.append)
    assert completed['metadata']['railVehicle']['weight']==15
    assert 'loadSpeed' not in completed['metadata']['transportVehicle']
    assert len(report['dataCompletions'])==1 and len(progress)==1


def test_payload_overflow_is_rejected_before_recording_an_estimate():
    src,dst=pair(cargo='COAL');native=installed(dst);report={}
    with pytest.raises(ValueError,match='completed native payload'):
        complete_payload(src,native,1e308,report=report)
    assert report=={}


def test_finite_coordinates_whose_extent_overflows_are_not_matching_evidence():
    src,dst=pair();src['metadata']['railVehicle'].pop('weight')
    src['boundingInfo']['bbMin'][0]=-1e308;src['boundingInfo']['bbMax'][0]=1e308
    with pytest.raises(ValueError,match='extent must remain finite'):
        complete_missing_model(src,installed(dst))


@pytest.mark.parametrize('invalid',[False,'15',-1,float('nan'),float('inf')])
def test_invalid_supplied_value_stops_completion_without_source_or_report_changes(invalid):
    src,dst=pair();src['metadata']['railVehicle']['weight']=invalid
    src['metadata']['railVehicle'].pop('topSpeed');report={'previous':[1]}
    with pytest.raises(ValueError):
        complete_missing_model(src,installed(dst),report=report)
    assert src['metadata']['railVehicle'].get('topSpeed') is None
    assert report=={'previous':[1]}


@pytest.mark.parametrize('marker',['carrier','engine','size'])
def test_missing_identity_or_propulsion_type_cannot_be_invented(marker):
    src,dst=pair(carrier='AIR' if marker=='size' else 'RAIL')
    if marker=='carrier':src['metadata']['transportVehicle'].pop('carrier')
    elif marker=='engine':src['metadata']['railVehicle']['engines'][0].pop('type')
    else:src['metadata']['airVehicle'].pop('type')
    with pytest.raises(ValueError):complete_missing_model(src,installed(dst))


def test_no_matching_and_ambiguous_donors_do_not_commit_partial_report():
    src,dst=pair();src['metadata']['railVehicle']['weight']=None
    wrong=deepcopy(dst);wrong['metadata']['landVehicle']['engines'][0]['type']='ELECTRIC'
    report={'previous':[1]}
    with pytest.raises(ValueError,match='No sufficiently similar'):
        complete_missing_model(src,installed(wrong),report=report)
    other=deepcopy(dst);other['metadata']['landVehicle']['weightEmpty']=17000
    native=Native({'vehicle/a/a.mdl':dst,'vehicle/b/b.mdl':other})
    with pytest.raises(ValueError,match='Ambiguous'):
        complete_missing_model(src,native,report=report)
    assert src['metadata']['railVehicle']['weight'] is None and report=={'previous':[1]}


def test_missing_bulk_capacity_and_load_speed_share_one_donor_and_scale_payload():
    src,dst=pair(cargo='COAL')
    transport=src['metadata']['transportVehicle']
    transport.pop('loadSpeed')
    entry=transport['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    entry.pop('capacity');dst['metadata']['landVehicle']['weightMaxPayload']=8000
    report={};native=installed(dst)
    completed,match=complete_missing_model(src,native,report=report)
    completed_entry=completed['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
    assert completed_entry=={'type':'COAL','capacity':40}
    assert completed['metadata']['transportVehicle']['loadSpeed']==3
    assert 'capacity' not in entry
    value, policy=complete_payload(src,native,40,match=match,report=report)
    assert (value,policy)==(8000,'matched_native_capacity_ratio')
    assert report['donorCompletions'][0]['donorResource']==match.resource
    assert report['dataCompletions'][-1]['donorPolicy']['ratio']==200


def test_native_air_profile_can_omit_optional_payload_instead_of_inventing_it():
    src,dst=pair(cargo='PASSENGERS',carrier='AIR')
    dst['metadata']['airVehicle'].pop('weightMaxPayload')
    report={};native=installed(dst)
    _,match=complete_missing_model(src,native,report=report)
    value,policy=complete_payload(src,native,40,match=match,report=report)
    assert value is None and policy=='native_air_profile_omits_optional_payload'
    assert report['dataCompletions'][-1]['donorValue'] is None


def test_waterline_fills_only_missing_outline_and_preserves_hull_geometry():
    src,dst=pair(carrier='WATER');src['metadata']['waterVehicle'].pop('waterLine')
    src['boundingInfo']=bounds(11,2.2,3.3)
    original=deepcopy(src);report={}
    result,match=complete_missing_model(src,installed(dst),report=report)
    expected=[[-5.5,-1.1],[5.5,-1.1],[5.5,1.1],[-5.5,1.1]]
    assert all(a==pytest.approx(b) for a,b in zip(result['metadata']['waterVehicle']['waterLine'],expected))
    assert src==original and result['boundingInfo']==original['boundingInfo']
    assert report['dataCompletions'][0]['method']=='approximate_native_hull_waterline'
    assert report['dataCompletions'][0]['estimated']
    assert match.donor._full_model is None


def test_waterline_nonuniform_hull_or_invalid_polygon_fails_atomically():
    src,dst=pair(carrier='WATER');src['metadata']['waterVehicle'].pop('waterLine')
    src['boundingInfo']=bounds(11,2,3);report={}
    with pytest.raises(ValueError,match='uniformly comparable'):
        complete_missing_model(src,installed(dst),report=report)
    assert report=={} and 'waterLine' not in src['metadata']['waterVehicle']
    src['boundingInfo']=bounds();dst['metadata']['waterVehicle']['waterLine']=[[0,0],[1,1]]
    with pytest.raises(ValueError,match='valid waterLine'):
        complete_missing_model(src,installed(dst),report=report)
    assert report=={}


def test_empty_cargo_placeholder_does_not_request_a_payload_donor():
    src,_=pair()
    src['metadata']['transportVehicle']['compartmentsList']=[{'loadConfigs':[{'cargoEntries':[{}]}]}]
    result,match=complete_missing_model(src,object())
    assert result==src and match is None


@pytest.mark.parametrize('field',['carrier','engine','cargo','size'])
def test_complete_source_still_rejects_translated_class_identifiers(field):
    src,_=pair(cargo='PASSENGERS',carrier='AIR' if field=='size' else 'RAIL')
    if field=='carrier':src['metadata']['transportVehicle']['carrier']=TranslatedString('RAIL')
    elif field=='engine':src['metadata']['railVehicle']['engines'][0]['type']=TranslatedString('DIESEL')
    elif field=='size':src['metadata']['airVehicle']['type']=TranslatedString('SMALL')
    else:
        e=src['metadata']['transportVehicle']['compartmentsList'][0]['loadConfigs'][0]['cargoEntries'][0]
        e.update(type=TranslatedString('PASSENGERS'),capacity=0)
    with pytest.raises(ValueError,match='(?:non-localized|localized)'):
        complete_missing_model(src,object())


def test_air_radius_donation_integrates_matching_with_geometry_validation():
    from test_donor_geometry import source as gear_source, donor as gear_donor
    src,dst=pair(carrier='AIR')
    geometry=gear_source();native_geometry=gear_donor().model
    src['boundingInfo']=geometry['boundingInfo'];src['lods']=geometry['lods']
    src['metadata']['airVehicle']['type']='BIG'
    src['metadata']['airVehicle']['configs']=geometry['metadata']['airVehicle']['configs']
    dst['lods']=native_geometry['lods']
    dst['metadata']['extent']=native_geometry['metadata']['extent']
    dst['metadata']['transportVehicle']['transportModes']=['AIRCRAFT']
    dst['metadata']['airVehicle']['config']=native_geometry['metadata']['airVehicle']['config']
    before=deepcopy(src);report={}
    completed,match=complete_missing_model(src,installed(dst),report=report)
    assert completed['metadata']['airVehicle']['configs'][0]['axleRadii']==[0.6]
    assert completed['metadata']['airVehicle']['configs'][0]['wheelRadii']==[0.25]
    assert src==before and completed['lods']==src['lods']
    assert match.donor._full_model is not None
    assert report['dataCompletions'][0]['method']=='approximate_native_geometry_match'


def package_donor():
    dst=donor(cargo=None,engine='ELECTRIC')
    dst['metadata']['extent']=deepcopy(model()['boundingInfo'])
    dst['metadata']['landVehicle'].update(weightEmpty=79500,topSpeed=25,
        engines=[{'type':'ELECTRIC','power':1220,'tractiveEffort':120}])
    dst['metadata']['transportVehicle']['loadSpeed']=1
    return dst


def test_missing_engine_and_weight_pass_preflight_then_complete_entire_queued_package(fixture_mod):
    src,game,out=fixture_mod
    native_files(game,{**cargo_files(),'vehicle/train/donor/donor.mdl':package_donor()})
    data=model();data['metadata']['railVehicle'].pop('weight')
    data['metadata']['railVehicle']['engines'][0].pop('power')
    write_model(src,data);before=snapshot(src)
    _preflight_profile(src)
    items=scan_mods(src)['items'];converted=convert_queue(items,out,tf3_game=game)
    assert converted['counts']['completed']==1 and converted['counts']['failed']==0
    target=out/items[0].mod_id
    exported=load_lua_table((target/'content/models/model/vehicle/train/test.mdl').read_text())
    assert exported['metadata']['landVehicle']['weightEmpty']==79500
    assert exported['metadata']['landVehicle']['engines'][0]['power']==1220
    assert snapshot(src)==before
    report=json.loads((target/'conversion-report.json').read_text())
    assert len(report['migrationAudit']['dataCompletions'])==2
    assert 'vehicle/train/donor/donor.mdl' in report['baseGameResources']
    assert report['nativeTest']=='not_run'


def test_failed_donor_matching_preserves_existing_output_and_source(fixture_mod):
    src,game,out=fixture_mod;data=model();data['metadata']['railVehicle'].pop('weight')
    write_model(src,data);before=snapshot(src)
    wrong=package_donor();wrong['metadata']['landVehicle']['engines'][0]['type']='STEAM'
    native_files(game,{**cargo_files(),'vehicle/train/wrong/wrong.mdl':wrong})
    out.mkdir();(out/'sentinel').write_text('keep')
    with pytest.raises(ValueError,match='No sufficiently similar'):
        port_tf2_mod(src,out,tf3_game=game,mod_id='fixture',name='Fixture',overwrite=True)
    assert (out/'sentinel').read_text()=='keep' and snapshot(src)==before

import json
from pathlib import Path

import pytest

from trf3_mod_converter import batch
from trf3_mod_converter.base_resources import TF2Inventory
from trf3_mod_converter.source_game_resources import SourceGameResources
from trf3_mod_converter.tf2_vehicle_port import snapshot
from trf3_mod_converter.tf2_vehicle_port import emit
from trf3_mod_converter.workshop_resources import WorkshopResources
from test_source_game_resources import dds


FIELDS=('sourceGameDependencies','sourceGameResourceFingerprints',
        'sourceGameInventoryFingerprint','sourceGameInstallation','workshopAbsentDependencies')


@pytest.fixture
def setup(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir()
    (source/'mod.json').write_text(json.dumps({'name':'Exact stock dependency','authors':['Creator']}))
    game=tmp_path/'tf2'
    stock=game/'res/textures/stock.dds';stock.parent.mkdir(parents=True);stock.write_bytes(dds())
    tf3=tmp_path/'tf3'
    monkeypatch.setattr(batch,'find_tf2_game',lambda root,native:game)
    reader=SourceGameResources(TF2Inventory(game));reader.resolve('stock.dds','texture')
    report={'sourceGameDependencies':reader.rows,'sourceGameResourceFingerprints':reader.fingerprints,
            'sourceGameInventoryFingerprint':reader.inventory_fingerprint(),
            'sourceGameInstallation':str(game.resolve()),'workshopAbsentDependencies':[]}
    calls=[]
    actual=batch._export

    def export(*args):
        calls.append(args[0].mod_id)
        produced=actual(*args)
        # Persist bytes to represent a referenced source-game binary in this
        # receipt-focused fixture; source and TF2 installation remain separate.
        target=args[1]
        (target/'stock.dds').write_bytes(stock.read_bytes())
        return {**produced,**report}

    monkeypatch.setattr(batch,'_export',export)
    return source,game,tf3,tmp_path/'exports',report,calls


def run(setup,event=None):
    source,_,tf3,output,_,_=setup
    return batch.convert_queue(batch.scan_mods(source)['items'],output,tf3_game=tf3,event=event)


def test_source_game_receipt_is_durable_before_green_and_unchanged_resume_skips_export(setup):
    source,_,_,output,report,calls=setup
    saved=[]

    def event(kind,value):
        if kind=='item' and value['status']=='completed':
            state=json.loads((output/batch.STATE_NAME).read_text())
            receipt=state['receipts'][value['key']]
            assert {field:receipt[field] for field in FIELDS}==report
            saved.append(value['status'])

    first=run(setup,event)
    assert first['counts']['completed']==1
    target=Path(first['items'][0]['destination']);before=snapshot(target)
    resumed=run(setup)
    assert resumed['counts']['completed']==1
    assert resumed['items'][0]['message']=='Previous export verified'
    assert len(calls)==1 and saved==['completed']
    assert snapshot(target)==before


@pytest.mark.parametrize('change',['bytes','catalog','missing','installation','forged_path'])
def test_changed_or_forged_source_game_inputs_deny_resume_and_preserve_existing_export(setup,monkeypatch,change):
    _,game,_,output,_,calls=setup
    first=run(setup)
    target=Path(first['items'][0]['destination']);before=snapshot(target)
    stock=game/'res/textures/stock.dds'
    if change=='bytes':stock.write_bytes(stock.read_bytes()[:-1]+b'\1')
    elif change=='catalog':(game/'res/new_mount_input.txt').write_text('added source-game input')
    elif change=='missing':stock.unlink()
    elif change=='installation':
        other=game.parent/'other-tf2'
        (other/'res/textures').mkdir(parents=True)
        (other/'res/textures/stock.dds').write_bytes(stock.read_bytes())
        monkeypatch.setattr(batch,'find_tf2_game',lambda root,native:other)
    else:
        state_path=output/batch.STATE_NAME
        state=json.loads(state_path.read_text())
        receipt=next(iter(state['receipts'].values()))
        receipt['sourceGameInstallation']=str(game.parent/'forged-tf2')
        state_path.write_text(json.dumps(state))
    resumed=run(setup)
    assert resumed['counts']['failed']==1
    assert 'not overwritten' in resumed['items'][0]['message']
    assert len(calls)==1 and snapshot(target)==before


@pytest.mark.parametrize('change',['bytes','catalog','forged_path','missing_inventory'])
def test_game_input_changes_during_export_never_gain_completed_receipt(setup,monkeypatch,change):
    _,game,_,_,report,_=setup
    actual=batch._export

    def export(*args):
        result=actual(*args)
        if change=='bytes':
            stock=game/'res/textures/stock.dds';stock.write_bytes(stock.read_bytes()[:-1]+b'\1')
        elif change=='catalog':(game/'res/new.txt').write_text('source-game mount addition')
        elif change=='missing_inventory':result.pop('sourceGameInventoryFingerprint')
        else:result['sourceGameInstallation']=str(game.parent/'forged-tf2')
        return result

    monkeypatch.setattr(batch,'_export',export)
    state=run(setup)
    assert state['counts']['failed']==1 and state['receipts']=={}
    assert 'TF2 installation or resources changed' in state['items'][0]['message']


@pytest.mark.parametrize('keep_empty_fields',[True,False])
def test_old_receipts_without_source_game_inputs_remain_compatible(tmp_path,keep_empty_fields):
    source=tmp_path/'source';source.mkdir()
    (source/'mod.json').write_text(json.dumps({'name':'Old metadata export','authors':['Creator']}))
    output=tmp_path/'exports'
    items=batch.scan_mods(source)['items']
    assert batch.convert_queue(items,output)['counts']['completed']==1
    state_path=output/batch.STATE_NAME;state=json.loads(state_path.read_text())
    receipt=state['receipts'][items[0].key]
    if not keep_empty_fields:
        for field in FIELDS:receipt.pop(field)
        state_path.write_text(json.dumps(state))
    assert batch.convert_queue(batch.scan_mods(source)['items'],output)['counts']['completed']==1


def test_unused_or_malformed_source_game_evidence_is_not_a_valid_empty_receipt(setup):
    source,game,tf3,_,_,_=setup
    assert not batch._source_game_valid(source,tf3,{'sourceGameInstallation':str(game.resolve())})
    assert not batch._source_game_valid(source,tf3,{'sourceGameDependencies':None})


def with_workshop_absence(setup,tmp_path,owner_context):
    source,game,tf3,output,report,calls=setup
    workshop_source=tmp_path/'1066780/123';workshop_source.parent.mkdir()
    source.rename(workshop_source)
    (workshop_source/'mod.json').unlink()
    (workshop_source/'mod.lua').write_text(emit({'info':{'name':'Exact stock dependency',
        'authors':['Creator'],'requiredMods':[{'steamId':456,'modId':'declared'}]}}))
    declared=workshop_source.parent/'456';declared.mkdir()
    (declared/'mod.lua').write_text(emit({'info':{'modid':'declared','steamId':456}}))
    if owner_context:
        author=workshop_source.parent/'789';author.mkdir()
        (author/'mod.lua').write_text(emit({'info':{'modid':'author','steamId':789}}))
        row=WorkshopResources(author).absence('stock.dds','texture',prefer_local=True)
        late_provider=author
    else:
        row=WorkshopResources(workshop_source).absence('stock.dds','texture')
        late_provider=declared
    report['workshopAbsentDependencies']=[row]
    return (workshop_source,game,tf3,output,report,calls),late_provider


@pytest.mark.parametrize('owner_context',[False,True])
def test_late_exact_declared_or_author_asset_invalidates_stock_fallback_resume(setup,tmp_path,owner_context):
    setup,provider=with_workshop_absence(setup,tmp_path,owner_context)
    source,_,_,_,_,calls=setup
    first=run(setup)
    assert first['counts']['completed']==1
    target=Path(first['items'][0]['destination']);before=snapshot(target)
    original_source=snapshot(source);metadata=(provider/'mod.lua').read_bytes()
    late=provider/'res/textures/stock.dds';late.parent.mkdir(parents=True)
    late.write_bytes(dds()[:-1]+b'\1')
    resumed=run(setup)
    assert resumed['counts']['failed']==1
    assert snapshot(source)==original_source and (provider/'mod.lua').read_bytes()==metadata
    assert len(calls)==1 and snapshot(target)==before


def test_late_declared_asset_during_export_never_gains_green_receipt(setup,tmp_path,monkeypatch):
    setup,provider=with_workshop_absence(setup,tmp_path,False)
    actual=batch._export

    def export(*args):
        result=actual(*args)
        late=provider/'res/textures/stock.dds';late.parent.mkdir(parents=True)
        late.write_bytes(dds()[:-1]+b'\1')
        return result

    monkeypatch.setattr(batch,'_export',export)
    state=run(setup)
    assert state['counts']['failed']==1 and state['receipts']=={}


def test_pre_gap_source_game_receipt_without_absence_field_cannot_be_resumed(setup):
    _,_,_,output,_,calls=setup
    first=run(setup);assert first['counts']['completed']==1
    target=Path(first['items'][0]['destination']);before=snapshot(target)
    state_path=output/batch.STATE_NAME;state=json.loads(state_path.read_text())
    next(iter(state['receipts'].values())).pop('workshopAbsentDependencies')
    state_path.write_text(json.dumps(state))
    resumed=run(setup)
    assert resumed['counts']['failed']==1 and len(calls)==1
    assert snapshot(target)==before

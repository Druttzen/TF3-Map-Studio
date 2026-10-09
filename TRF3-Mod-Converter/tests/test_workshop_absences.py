from copy import deepcopy

import pytest

from trf3_mod_converter.dependency_context import DependencyContext
from trf3_mod_converter.tf2_vehicle_port import emit
from trf3_mod_converter.workshop_resources import WorkshopResources, verify_workshop_absences


@pytest.fixture
def collection(tmp_path):
    root=tmp_path/'1066780';source=root/'123';source.mkdir(parents=True)
    (source/'mod.lua').write_text(emit({'info':{'requiredMods':[{'steamId':456,'modId':'declared'}]}}))
    provider=root/'456';provider.mkdir()
    (provider/'mod.lua').write_text(emit({'info':{'modid':'declared','steamId':456}}))
    return root,source,provider


def texture(package,content=b'authored exact custom resource'):
    path=package/'res/textures/shared/stock.dds'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    return path


def test_missing_declared_input_row_invalidates_when_exact_provider_appears_without_metadata_change(collection):
    _,source,provider=collection
    metadata=(provider/'mod.lua').read_bytes()
    row=WorkshopResources(source).absence('shared/stock.dds','texture')
    assert row['lookupPolicy']=='declared_only'
    assert verify_workshop_absences(source,[row])
    texture(provider)
    assert (provider/'mod.lua').read_bytes()==metadata
    assert not verify_workshop_absences(source,[row])


def test_missing_imported_author_resource_invalidates_when_own_exact_file_appears(collection):
    root,source,_=collection
    author=root/'789';author.mkdir()
    (author/'mod.lua').write_text(emit({'info':{'modid':'author','steamId':789}}))
    row=WorkshopResources(author).absence('shared/stock.dds','texture',prefer_local=True)
    assert row['lookupPolicy']=='prefer_local_declared_only'
    assert verify_workshop_absences(source,[row])
    texture(author)
    assert not verify_workshop_absences(source,[row])


def test_absence_metadata_changes_invalidate_even_when_no_resource_appears(collection):
    _,source,_=collection
    row=WorkshopResources(source).absence('shared/stock.dds','texture')
    (source/'mod.lua').write_text((source/'mod.lua').read_text()+'\n-- source scope changed')
    assert not verify_workshop_absences(source,[row])


def test_unrelated_global_resources_do_not_invalidate_declared_only_absence(collection):
    root,source,_=collection
    row=WorkshopResources(source).absence('shared/stock.dds','texture')
    global_provider=root/'999';global_provider.mkdir()
    texture(global_provider)
    assert verify_workshop_absences(source,[row])


def test_record_absence_keeps_origin_hashes_separate_and_deduplicates_context_queries(collection):
    root,source,_=collection
    author=root/'789';author.mkdir()
    (author/'mod.lua').write_text(emit({'info':{'modid':'author','steamId':789}}))
    audit,fingerprints={},{}
    context=DependencyContext(source,WorkshopResources(source),{},audit,fingerprints)
    context.record_absence('shared//stock.dds','texture',owners=[source,author])
    context.record_absence('shared/stock.dds','texture',owners=[source,author])
    rows=audit['workshopAbsentDependencies']
    assert len(rows)==2 and fingerprints=={}
    assert all(row['originFingerprints'] for row in rows)
    assert verify_workshop_absences(source,rows)


def test_absence_recorder_refuses_existing_declared_and_owner_files(collection):
    _,source,provider=collection
    texture(provider)
    with pytest.raises(ValueError,match='no longer absent'):
        WorkshopResources(source).absence('shared/stock.dds','texture')
    texture(source)
    with pytest.raises(ValueError,match='no longer absent'):
        WorkshopResources(source).absence('shared/stock.dds','texture',prefer_local=True)


@pytest.mark.parametrize('damage',['outside','origin','policy','kind','traversal','duplicate','extra'])
def test_forged_absence_contexts_and_receipts_are_rejected(collection,tmp_path,damage):
    _,source,_=collection
    row=WorkshopResources(source).absence('shared/stock.dds','texture')
    rows=[deepcopy(row)]
    if damage=='outside':rows[0]['lookupSource']=str(tmp_path/'other/1066780/123')
    elif damage=='origin':rows[0]['originFingerprints']={str(tmp_path/'mod.lua'):'0'*64}
    elif damage=='policy':rows[0]['lookupPolicy']='declared_or_global'
    elif damage=='kind':rows[0]['kind']='script'
    elif damage=='traversal':rows[0]['sourceReference']='../stock.dds'
    elif damage=='duplicate':rows.append(deepcopy(row))
    else:rows[0]['sha256']='0'*64
    assert not verify_workshop_absences(source,rows)


def test_changed_declared_folder_link_cannot_remain_a_safe_absence(collection,monkeypatch):
    import trf3_mod_converter.workshop_resources as resources
    _,source,provider=collection
    row=WorkshopResources(source).absence('shared/stock.dds','texture')
    actual=resources.linked
    monkeypatch.setattr(resources,'linked',lambda path:path==provider or actual(path))
    assert not verify_workshop_absences(source,[row])


def test_empty_old_absences_and_nonlist_input_policy():
    assert verify_workshop_absences('not-a-Workshop-folder',[])
    assert not verify_workshop_absences('not-a-Workshop-folder',None)

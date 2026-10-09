import hashlib
import io
import struct
import wave
import zipfile

import pytest

from trf3_mod_converter.base_resources import TF2Inventory
from trf3_mod_converter.source_game_resources import (
    SourceGameResources, validate_mesh_pair, validate_animation, verify_source_game_dependencies,
)
from trf3_mod_converter.tf2_vehicle_port import emit


def installed(tmp_path, files):
    game=tmp_path/'tf2'
    (game/'res').mkdir(parents=True)
    for resource,data in files.items():
        path=game/'res'/resource
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    return game,SourceGameResources(TF2Inventory(game))


def geometry():
    positions=struct.pack('<9f',0,0,0,1,0,0,0,1,0)
    indices=struct.pack('<3I',0,1,2)
    descriptor={'vertexAttr':{'position':{'offset':0,'count':len(positions),'numComp':3}},
                'subMeshes':[{'indices':{'position':{'offset':len(positions),'count':len(indices)}}}]}
    return emit(descriptor).encode(),positions+indices,descriptor


def dds(width=4,height=4):
    header=bytearray(128)
    header[:4]=b'DDS '
    struct.pack_into('<I',header,4,124)
    struct.pack_into('<II',header,12,height,width)
    struct.pack_into('<I',header,28,1)
    struct.pack_into('<I',header,76,32)
    header[84:88]=b'DXT1'
    return bytes(header)+b'\0'*(max(1,(width+3)//4)*max(1,(height+3)//4)*8)


def wav():
    output=io.BytesIO()
    with wave.open(output,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(22050)
        stream.writeframes(b'\0\0'*8)
    return output.getvalue()


def test_exact_stock_input_records_mount_bytes_and_fresh_receipt(tmp_path):
    raw=emit({'type':'PHYSICAL','params':{}}).encode()
    game,resolver=installed(tmp_path,{'models/material/shared.mtl':raw})
    match=resolver.resolve('shared.mtl','material')
    assert match['data']==raw
    assert match['sourceContainer']=='res/models/material/shared.mtl'
    assert match['sourceMember'] is None
    assert match['sha256']==hashlib.sha256(raw).hexdigest()
    assert match['validation']['policy']=='requires_verified_category_adapter'
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints,resolver.inventory_fingerprint())
    (game/'res/models/material/shared.mtl').write_bytes(emit({'type':'PHYSICAL','params':{},'order':1}).encode())
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)


def test_repeated_animation_reuses_proof_but_reads_and_rejects_changed_input(tmp_path,monkeypatch):
    import trf3_mod_converter.source_game_resources as module
    matrix=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
    raw=emit({'times':[0,100], 'transfs':[matrix,matrix]}).encode()
    game,resolver=installed(tmp_path,{'models/animation/stock.ani':raw})
    parsed=[];reads=[]
    validate=module.validate_animation
    read=resolver.inventory.read
    def validation(data,resource):
        parsed.append(data)
        return validate(data,resource)
    def fresh_read(resource):
        reads.append(resource)
        return read(resource)
    monkeypatch.setattr(module,'validate_animation',validation)
    monkeypatch.setattr(resolver.inventory,'read',fresh_read)
    first=resolver.resolve('stock.ani','animation')
    first['validation']['durationMs']=-999
    assert resolver.resolve('stock.ani','animation')['validation']['durationMs']==100
    assert len(parsed)==1 and len(reads)==2
    (game/'res/models/animation/stock.ani').write_bytes(raw.replace(b'100',b'200'))
    with pytest.raises(ValueError,match='changed during adaptation'):
        resolver.resolve('stock.ani','animation')
    assert len(parsed)==2 and len(reads)==3
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)


def test_zip_mount_member_and_later_loose_override_are_revalidated(tmp_path):
    game,resolver=installed(tmp_path,{})
    archive=game/'res/models/material/material.zip'
    archive.parent.mkdir(parents=True)
    raw=emit({'type':'PHYSICAL','params':{}}).encode()
    with zipfile.ZipFile(archive,'w') as handle:handle.writestr('shared.mtl',raw)
    resolver=SourceGameResources(TF2Inventory(game))
    match=resolver.resolve('shared.mtl','material')
    assert match['sourceContainer']=='res/models/material/material.zip'
    assert match['sourceMember']=='shared.mtl'
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    # Same bytes are insufficient when selected mount provenance changes.
    (archive.parent/'shared.mtl').write_bytes(raw)
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)


def test_inventory_catalog_changes_invalidate_receipt_even_for_unchanged_input(tmp_path):
    game,resolver=installed(tmp_path,{'textures/stock.dds':dds()})
    resolver.resolve('stock.dds','texture')
    inventory=resolver.inventory_fingerprint()
    (game/'res/new_resource.txt').write_text('mount changed')
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints,inventory)


def test_mesh_pair_keeps_geometry_and_records_both_input_hashes(tmp_path):
    descriptor,blob,_=geometry()
    game,resolver=installed(tmp_path,{'models/mesh/stock.msh':descriptor,'models/mesh/stock.msh.blob':blob})
    match=resolver.resolve('stock.msh','mesh')
    assert match['data']==descriptor
    assert match['validation']['submeshCount']==1
    assert match['validation']['attributes'][0]['items']==3
    assert match['validation']['indices'][0]['maxIndex']==2
    assert resolver.resolve('stock.msh.blob','mesh_blob')['data']==blob
    assert len(resolver.rows)==2
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    (game/'res/models/mesh/stock.msh.blob').write_bytes(blob[:-1]+b'\1')
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)


@pytest.mark.parametrize('only_descriptor',[True,False])
def test_stock_mesh_requires_exact_paired_blob(tmp_path,only_descriptor):
    descriptor,blob,_=geometry()
    files={'models/mesh/stock.msh':descriptor} if only_descriptor else {'models/mesh/stock.msh.blob':blob}
    _,resolver=installed(tmp_path,files)
    with pytest.raises(ValueError,match='pair is incomplete'):
        resolver.resolve('stock.msh' if only_descriptor else 'stock.msh.blob','mesh' if only_descriptor else 'mesh_blob')


@pytest.mark.parametrize('damage,message',[
    ('truncated','truncated'),('bad_index','index outside'),('nonfinite','non-finite'),
    ('overlap','overlapping'),('unknown','unsupported'),('components','invalid'),
])
def test_geometry_rejects_corrupt_or_unproven_layout(damage,message):
    descriptor,blob,data=geometry()
    if damage=='truncated':blob=blob[:-4]
    if damage=='bad_index':blob=blob[:-4]+struct.pack('<I',3)
    if damage=='nonfinite':blob=struct.pack('<f',float('nan'))+blob[4:]
    if damage=='overlap':
        data['subMeshes'][0]['indices']['position']['offset']=0
    if damage=='unknown':data['vertexAttr']['unknown']=data['vertexAttr'].pop('position')
    if damage=='components':data['vertexAttr']['position']['numComp']=4
    with pytest.raises(ValueError,match=message):validate_mesh_pair(emit(data).encode(),blob,'stock.msh')


def test_literal_animation_preserves_authored_order_and_zero_duration_keys(tmp_path):
    matrix=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
    raw=emit({'times':[0,0,100],'transfs':[matrix,matrix,matrix]}).encode()
    game,resolver=installed(tmp_path,{'models/animation/stock.ani':raw})
    assert resolver.resolve('stock.ani','animation')['data']==raw
    assert resolver.rows[0]['validation']['keyframes']==3
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    bad=emit({'times':[0,100,50],'transfs':[matrix,matrix,matrix]}).encode()
    with pytest.raises(ValueError,match='animation schema'):validate_animation(bad)
    bad=emit({'times':[0],'transfs':[matrix[:-1]]}).encode()
    with pytest.raises(ValueError,match='animation schema'):validate_animation(bad)


@pytest.mark.parametrize('kind',['mesh','animation'])
def test_fresh_readers_reuse_exact_format_proofs_and_detect_changed_bytes(tmp_path,monkeypatch,kind):
    import trf3_mod_converter.source_game_resources as module
    if kind=='mesh':
        descriptor,blob,_=geometry()
        files={'models/mesh/stock.msh':descriptor,'models/mesh/stock.msh.blob':blob}
        reference='stock.msh';changed='models/mesh/stock.msh.blob';validator='validate_mesh_pair'
        valid=struct.pack('<f',2)+blob[4:];invalid=blob[:-4]
    else:
        matrix=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
        files={'models/animation/stock.ani':emit({'times':[0],'transfs':[matrix]}).encode()}
        reference='stock.ani';changed='models/animation/stock.ani';validator='validate_animation'
        valid=emit({'times':[0,1],'transfs':[matrix,matrix]}).encode();invalid=b'function data('
    original=getattr(module,validator);calls=[]
    def validate(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(module,validator,validate)
    game,reader=installed(tmp_path,files)
    first=reader.resolve(reference,kind);rows=reader.rows;fingerprints=reader.fingerprints
    first['validation'].clear()
    assert SourceGameResources(TF2Inventory(game)).resolve(reference,kind)['validation']
    assert len(calls)==1
    (game/'res'/changed).write_bytes(valid)
    assert SourceGameResources(TF2Inventory(game)).resolve(reference,kind)['validation']
    assert len(calls)==2
    assert not verify_source_game_dependencies(game,rows,fingerprints)
    (game/'res'/changed).write_bytes(invalid)
    with pytest.raises(ValueError):SourceGameResources(TF2Inventory(game)).resolve(reference,kind)
    assert len(calls)==3


@pytest.mark.parametrize('kind,reference,resource,data',[
    ('texture','stock.dds','textures/stock.dds',dds()),
    ('texture','stock.hdr','textures/stock.hdr',b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n'+b'\0\0\0\0'),
    ('texture','stock.tga','textures/stock.tga',bytes([0,0,2])+bytes(9)+struct.pack('<HH',1,1)+bytes([24,0])+bytes(3)),
    ('audio','stock.wav','audio/effects/stock.wav',wav()),
])
def test_recognized_binary_asset_copies_only_exact_verified_bytes(tmp_path,kind,reference,resource,data):
    game,resolver=installed(tmp_path,{resource:data})
    assert resolver.resolve(reference,kind)['data']==data
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    (game/'res'/resource).write_bytes(data[:-1])
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)


def test_hdr_rle_scanlines_have_bounded_component_runs(tmp_path):
    raw=b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 8\n'+b'\2\2\0\10'+b'\210\0'*4
    _,resolver=installed(tmp_path,{'textures/stock.hdr':raw})
    assert resolver.resolve('stock.hdr','texture')['validation']['width']==8
    (resolver.game/'res/textures/stock.hdr').write_bytes(raw[:-1])
    with pytest.raises(ValueError,match='HDR'):resolver.resolve('stock.hdr','texture')


@pytest.mark.parametrize('kind,resource',[
    ('model','models/model/stock.mdl'),('material','models/material/stock.mtl'),
    ('sound_set','config/sound_set/stock.lua'),
])
def test_game_localization_calls_never_inherit_mod_locale(tmp_path,kind,resource):
    _,resolver=installed(tmp_path,{resource:b'function data() return {name=_("game_key")} end'})
    with pytest.raises(ValueError,match='verified game locale adapter'):
        resolver.resolve('stock' if kind=='sound_set' else 'stock'+resource[resource.rfind('.'):],kind)


def test_static_models_and_sound_source_still_require_category_adapters(tmp_path):
    game,resolver=installed(tmp_path,{'models/model/stock.mdl':emit({'metadata':{},'lods':[]}).encode(),
        'config/sound_set/stock.lua':b'function data() return {updateFn=function(inputs) return {} end} end'})
    assert resolver.resolve('stock.mdl','model')['validation']['policy']=='requires_verified_category_adapter'
    assert resolver.resolve('stock','sound_set')['validation']['policy']=='requires_verified_sound_category_adapter'
    assert verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    (game/'res/models/model/stock.mdl').write_bytes(b'function data() return {metadata={callback=function() return 1 end}} end')
    with pytest.raises(ValueError,match='unsupported'):resolver.resolve('stock.mdl','model')


def test_absence_wrong_suffix_and_traversal_do_not_guess(tmp_path):
    _,resolver=installed(tmp_path,{'models/material/elsewhere/shared.mtl':emit({'type':'PHYSICAL'}).encode()})
    assert resolver.resolve('shared.mtl','material') is None
    for reference,kind in [('../shared.mtl','material'),('/shared.mtl','material'),('bad.dll','texture'),
                           ('stock.msh','mesh_blob'),('module','script')]:
        with pytest.raises(ValueError):resolver.resolve(reference,kind)


def test_forged_input_receipt_and_missing_mesh_pair_row_are_rejected(tmp_path):
    descriptor,blob,_=geometry()
    game,resolver=installed(tmp_path,{'models/mesh/stock.msh':descriptor,'models/mesh/stock.msh.blob':blob})
    resolver.resolve('stock.msh','mesh')
    rows=resolver.rows
    assert not verify_source_game_dependencies(game,rows[:1],resolver.fingerprints)
    rows[0]['sourceContainer']='res/elsewhere.zip'
    assert not verify_source_game_dependencies(game,rows,resolver.fingerprints)
    rows=resolver.rows
    rows[0]['targetReference']='draft::/models/mesh/stock.msh'
    assert verify_source_game_dependencies(game,rows,resolver.fingerprints)


def test_linked_and_out_of_root_inputs_rejected(tmp_path,monkeypatch):
    import trf3_mod_converter.source_game_resources as module
    game,resolver=installed(tmp_path,{'models/material/stock.mtl':emit({'type':'PHYSICAL'}).encode()})
    path=game/'res/models/material/stock.mtl'
    actual=module.linked
    monkeypatch.setattr(module,'linked',lambda value:value==path or actual(value))
    with pytest.raises(ValueError,match='Linked'):resolver.resolve('stock.mtl','material')
    monkeypatch.setattr(module,'linked',actual)
    outside=tmp_path/'outside.mtl';outside.write_text('function data() return {} end')
    resolver.inventory.files['models/material/stock.mtl']=(outside,None)
    with pytest.raises(ValueError,match='escapes'):resolver.resolve('stock.mtl','material')


def test_old_receipts_without_source_game_inputs_remain_valid():
    assert verify_source_game_dependencies(None,[],{})


def test_sound_reference_optional_lua_suffix_has_one_stable_receipt(tmp_path):
    _,resolver=installed(tmp_path,{'config/sound_set/stock.lua':b'function data() return {} end'})
    first=resolver.resolve('stock','sound_set')
    assert resolver.resolve('stock.lua','sound_set')==first
    assert len(resolver.rows)==1


def test_malformed_stock_lua_is_an_actionable_value_error(tmp_path):
    _,resolver=installed(tmp_path,{'models/material/stock.mtl':b'function data( return {} end'})
    with pytest.raises(ValueError,match='invalid installed TF2 Lua'):
        resolver.resolve('stock.mtl','material')


def test_exact_zip_member_bytes_and_zip_symlink_are_checked(tmp_path):
    game,resolver=installed(tmp_path,{})
    archive=game/'res/material.zip'
    raw=emit({'type':'PHYSICAL','order':0}).encode()
    with zipfile.ZipFile(archive,'w') as handle:handle.writestr('models/material/stock.mtl',raw)
    resolver=SourceGameResources(TF2Inventory(game));resolver.resolve('stock.mtl','material')
    with zipfile.ZipFile(archive,'w') as handle:handle.writestr('models/material/stock.mtl',raw.replace(b'order = 0',b'order = 1'))
    assert not verify_source_game_dependencies(game,resolver.rows,resolver.fingerprints)
    info=zipfile.ZipInfo('models/material/stock.mtl')
    info.create_system=3;info.external_attr=0o120777<<16
    with zipfile.ZipFile(archive,'w') as handle:handle.writestr(info,raw)
    with pytest.raises(ValueError,match='Linked.*zip member'):
        SourceGameResources(TF2Inventory(game)).resolve('stock.mtl','material')

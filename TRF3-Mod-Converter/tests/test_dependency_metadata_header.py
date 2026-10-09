import pytest

from trf3_mod_converter.shared_metadata_literals import load_literal_dependency_info


def test_literal_provider_header_can_be_inspected_independently_of_active_callbacks():
    text = '''local modId="author_pack"
    local hiddenFiles={}
    local function filterFiles(fileName, data) return false end
    function data() return {
      info={name=_("Title"), minorVersion=30,
        requiredMods={{steamId="123", modId="author_assets", minMinorVersion=2}}},
      runFn=function(settings) os.execute("must never run") end
    } end'''
    assert load_literal_dependency_info(text) == {'minorVersion':30,
        'requiredMods':[{'steamId':'123','modId':'author_assets','minMinorVersion':2}]}


def test_same_duplicate_dependency_literal_is_provably_unambiguous():
    assert load_literal_dependency_info('function data() return {info={minorVersion=1,minorVersion=1}} end') == {'minorVersion':1}


@pytest.mark.parametrize('source', [
    'return {info={modid="literal",minorVersion=2}}',
    '{info={modid="literal",minorVersion=2}}',
    'local function data() return {info={modid="literal",minorVersion=2}} end',
])
def test_existing_pure_metadata_chunk_and_local_data_shapes_remain_supported(source):
    assert load_literal_dependency_info(source) == {'modid':'literal','minorVersion':2}


@pytest.mark.parametrize('body', [
    'minorVersion=version', 'modid=modId', 'steamId=_("123")',
    'requiredMods=makeRequirements()', 'minorVersion=1e999',
    'requiredMods={{steamId="1",steamId="2"}}', 'minorVersion=1,minorVersion=2',
])
def test_dynamic_or_conflicting_dependency_identity_cannot_enter_provider_selection(body):
    with pytest.raises(ValueError):
        load_literal_dependency_info('function data() return {info={'+body+'}} end')


@pytest.mark.parametrize('text', [
    'function data() return {info={minorVersion=1}} end data=other',
    'local data={} function data() return {info={minorVersion=1}} end',
    'function data() local info={} return {info=info} end',
    'function data() return {info={minorVersion=1},info={minorVersion=1}} end',
    'function data() return {info={minorVersion=1},[external]={}} end',
    'function data() return {info={minorVersion=1,[external]={}}} end',
    'function data() return makeInfo() end',
    'function data(argument) return {info={minorVersion=1}} end',
    'function data() return {info={minorVersion=1}} end function data() return {info={minorVersion=1}} end',
    'os.execute("must not run") function data() return {info={}} end',
    'local helper=require "unverified" function data() return {info={}} end',
    'local helper=computeHeader() function data() return {info={}} end',
    'local x={} x.field=1 function data() return {info={}} end',
    'info={minorVersion=1} function data() return {info={}} end',
])
def test_ambiguous_or_computed_header_shape_remains_blocked(text):
    with pytest.raises(ValueError):
        load_literal_dependency_info(text)


def test_unused_metadata_data_is_not_claimed_as_a_converted_script():
    assert load_literal_dependency_info('function data() return {info={name=calculateName(),params=external}} end') == {}

"""Neighbouring DEM files must interpolate like one continuous native grid."""
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio import Affine
from rasterio.warp import Resampling, reproject

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import elevation
from alignment import mercator_bounds
from elevation import sample_sources
from height_settings import normalize


BOUNDS=[0,0,.01,.01]


def write_dem(path,values,affine,*,mask=None,scale=1,offset=0,units='m',datum='Test datum',nodata=-9999):
    with rasterio.open(path,'w',driver='GTiff',width=values.shape[1],height=values.shape[0],
                       count=1,dtype=values.dtype,crs='EPSG:3857',transform=affine,nodata=nodata) as out:
        out.write(values,1);out.scales=[scale];out.offsets=[offset]
        out.set_band_unit(1,units);out.update_tags(VERTICAL_DATUM=datum)
        if mask is not None:out.write_mask(mask.astype('uint8')*255)
    return path


def surface(points=129):
    x0,y0,x1,y1=mercator_bounds(BOUNDS)
    dx,dy=(x1-x0)/(points-1),(y1-y0)/(points-1)
    affine=Affine(dx,0,x0-dx/2,0,-dy,y1+dy/2)
    y,x=np.mgrid[:points,:points]
    values=100+x*2+y*.25+3*np.sin(x/9)*np.cos(y/13)
    return values,affine


@pytest.mark.parametrize('interpolation',['Bilinear','Cubic'])
@pytest.mark.parametrize('shared_endpoint',[False,True])
def test_adjacent_tiles_equal_a_single_native_raster(tmp_path,interpolation,shared_endpoint):
    values,affine=surface();cut=64
    whole=write_dem(tmp_path/'whole.tif',values,affine)
    left=write_dem(tmp_path/'left.tif',values[:,:cut+int(shared_endpoint)],affine)
    right=write_dem(tmp_path/'right.tif',values[:,cut:],affine@Affine.translation(cut,0))
    options=normalize({'resampling':interpolation})
    expected,_,_=sample_sources([whole],BOUNDS,(513,513),options)
    actual,_,metadata=sample_sources([left,right],BOUNDS,(513,513),options)
    np.testing.assert_allclose(actual,expected,atol=1e-9)
    assert all(m['interpolationAcrossTiles'] for m in metadata)
    assert all(m['mosaicSourceCount']==2 for m in metadata)
    assert sum(m['contributedSamples'] for m in metadata)==actual.size
    assert metadata[0]['fileListPosition']==1 and metadata[1]['fileListPosition']==2


@pytest.mark.parametrize('interpolation',['Bilinear','Cubic'])
def test_four_tiles_share_both_edge_kernels_and_corner(tmp_path,interpolation):
    values,affine=surface();whole=write_dem(tmp_path/'whole.tif',values,affine)
    paths=[]
    for row in (0,64):
        for col in (0,64):
            paths.append(write_dem(tmp_path/f'{row}-{col}.tif',values[row:row+65,col:col+65],
                                   affine@Affine.translation(col,row)))
    options=normalize({'resampling':interpolation})
    expected,_,_=sample_sources([whole],BOUNDS,(513,513),options)
    actual,_,_=sample_sources(paths,BOUNDS,(513,513),options)
    np.testing.assert_allclose(actual,expected,atol=1e-9)
    # Reversing matching shared endpoint values must not introduce a new seam.
    reverse,_,_=sample_sources(paths[::-1],BOUNDS,(513,513),options)
    np.testing.assert_allclose(reverse,expected,atol=1e-9)


@pytest.mark.parametrize('interpolation',['Bilinear','Cubic'])
def test_authoritative_mask_valid_nodata_and_gap_fallback_join_before_interpolation(tmp_path,interpolation):
    values,affine=surface();mask=np.ones(values.shape,dtype=bool)
    values[40,64]=-9999  # Valid despite the nominal nodata scalar.
    mask[70:75,62:68]=False
    background=np.full(values.shape,200.)
    expected_values=np.where(mask,values,background)
    whole=write_dem(tmp_path/'expected.tif',expected_values,affine,mask=np.ones_like(mask))
    left=write_dem(tmp_path/'left.tif',values[:,:65],affine,mask=mask[:,:65])
    right=write_dem(tmp_path/'right.tif',values[:,64:],affine@Affine.translation(64,0),mask=mask[:,64:])
    fallback=write_dem(tmp_path/'fallback.tif',background,affine)
    options=normalize({'resampling':interpolation,'source_priority':'File list order'})
    expected,_,_=sample_sources([whole],BOUNDS,(513,513),options)
    actual,_,metadata=sample_sources([left,right,fallback],BOUNDS,(513,513),options)
    np.testing.assert_allclose(actual,expected,atol=1e-8)
    assert actual[160,256]==pytest.approx(-9999)
    assert metadata[2]['contributedSamples']>0
    assert sum(m['contributedSamples'] for m in metadata)==actual.size


def test_first_valid_overlap_priority_and_per_file_counts_are_preserved(tmp_path):
    values,affine=surface();first=np.full(values.shape,50.);mask=np.ones(values.shape,dtype=bool)
    mask[:,64:]=False
    one=write_dem(tmp_path/'first.tif',first,affine,mask=mask)
    two=write_dem(tmp_path/'second.tif',np.full(values.shape,200.),affine)
    options=normalize({'source_priority':'File list order','resampling':'Nearest'})
    actual,_,metadata=sample_sources([one,two],BOUNDS,values.shape,options)
    np.testing.assert_array_equal(actual[:,:64],50)
    np.testing.assert_array_equal(actual[:,64:],200)
    assert metadata[0]['availableSamples']==129*64
    assert metadata[0]['contributedSamples']==129*64
    assert metadata[1]['availableSamples']==129*129
    assert metadata[1]['contributedSamples']==129*65
    reverse,_,metadata=sample_sources([two,one],BOUNDS,values.shape,options)
    np.testing.assert_array_equal(reverse,200)
    assert metadata[1]['contributedSamples']==0


@pytest.mark.parametrize('difference',[{'scale':2},{'offset':10},{'units':'ft'},{'datum':'Other datum'}])
def test_calibration_or_datum_mismatches_do_not_share_a_kernel(tmp_path,difference):
    values,affine=surface()
    first=write_dem(tmp_path/'first.tif',values[:,:65],affine)
    second=write_dem(tmp_path/'second.tif',values[:,64:],affine@Affine.translation(64,0),**difference)
    _,_,metadata=sample_sources([first,second],BOUNDS,(257,257),normalize({'source_priority':'File list order'}))
    assert all(not m.get('interpolationAcrossTiles') for m in metadata)


def test_priority_interruption_does_not_merge_nonconsecutive_sources(tmp_path):
    values,affine=surface()
    first=write_dem(tmp_path/'first.tif',values[:,:65],affine)
    middle=write_dem(tmp_path/'middle.tif',np.full(values.shape,200.),affine,datum='Other datum')
    last=write_dem(tmp_path/'last.tif',values[:,64:],affine@Affine.translation(64,0))
    _,_,metadata=sample_sources([first,middle,last],BOUNDS,(257,257),normalize({'source_priority':'File list order'}))
    assert all(not m.get('interpolationAcrossTiles') for m in metadata)
    assert metadata[2]['contributedSamples']==0


def test_matching_scale_offset_and_vertical_units_apply_once_after_join(tmp_path):
    values,affine=surface();kwargs={'scale':.5,'offset':12,'units':'ft'}
    whole=write_dem(tmp_path/'whole.tif',values,affine,**kwargs)
    left=write_dem(tmp_path/'left.tif',values[:,:65],affine,**kwargs)
    right=write_dem(tmp_path/'right.tif',values[:,64:],affine@Affine.translation(64,0),**kwargs)
    expected,_,_=sample_sources([whole],BOUNDS,(257,257),normalize())
    actual,_,metadata=sample_sources([left,right],BOUNDS,(257,257),normalize())
    np.testing.assert_allclose(actual,expected,atol=1e-10)
    assert all(m['heightUnitMultiplier']==.3048 for m in metadata)


def test_invalid_calibrated_heights_do_not_claim_coverage_or_block_fallback(tmp_path):
    values,affine=surface()
    invalid=write_dem(tmp_path/'overflow.tif',np.full(values.shape,1e200),affine,scale=1e200)
    fallback=write_dem(tmp_path/'fallback.tif',np.full(values.shape,200.),affine)
    actual,_,metadata=sample_sources([invalid,fallback],BOUNDS,values.shape,normalize({'resampling':'Nearest'}))
    np.testing.assert_array_equal(actual,200)
    assert metadata[0]['availableSamples']==metadata[0]['contributedSamples']==0
    assert metadata[1]['contributedSamples']==actual.size


def test_multiple_hgt_arrays_are_disk_backed_and_cropped_to_map(tmp_path):
    values=np.arange(129*129,dtype=np.int16).reshape(129,129)
    left=tmp_path/'N00E000.hgt';right=tmp_path/'N00E001.hgt'
    left.write_bytes(values.astype('>i2').tobytes());right.write_bytes(values.astype('>i2').tobytes())
    observed=[];original=elevation.disk_backed_array
    def capture(*args,**kwargs):
        result=original(*args,**kwargs)
        observed.append((result['source'].shape,getattr(getattr(result['source'],'ds',None),'name',None)))
        return result
    with patch('elevation.disk_backed_array',side_effect=capture):
        result,_,metadata=sample_sources([left,right],[.2,.2,.3,.3],(65,65),normalize())
    assert np.isfinite(result).all()
    assert observed[0][0][0]<32 and observed[0][0][1]<32
    assert observed[0][1] and not Path(observed[0][1]).exists()
    assert observed[1][0]==(1,1)
    assert metadata[0]['shape']==[129,129] and metadata[1]['contributedSamples']==0


@pytest.mark.parametrize('interpolation',['Bilinear','Cubic'])
def test_shared_hgt_endpoint_has_no_flat_strip(tmp_path,interpolation):
    rows,cols=np.mgrid[:129,:257];values=(100+cols*3+rows*2).astype(np.int16)
    left=tmp_path/'N00E000.hgt';right=tmp_path/'N00E001.hgt'
    left.write_bytes(values[:,:129].astype('>i2').tobytes());right.write_bytes(values[:,128:].astype('>i2').tobytes())
    expected=tmp_path/'whole.tif';step=1/128
    with rasterio.open(expected,'w',driver='GTiff',width=257,height=129,count=1,dtype='int16',
                       crs='EPSG:4326',transform=Affine(step,0,-step/2,0,-step,1+step/2),nodata=-32768) as out:
        out.write(values,1);out.set_band_unit(1,'m')
    bounds=[0,0,1,2];options=normalize({'resampling':interpolation})
    one,_,_=sample_sources([expected],bounds,(257,1025),options)
    joined,_,metadata=sample_sources([left,right],bounds,(257,1025),options)
    np.testing.assert_allclose(joined,one,atol=1e-9)
    assert all(m['format']=='HGT' and m['interpolationAcrossTiles'] for m in metadata)
    assert np.max(np.abs(np.diff(joined[:,510:516],axis=1)))<1


def test_joined_processing_rows_equal_single_full_warp(tmp_path):
    values,affine=surface()
    left=write_dem(tmp_path/'left.tif',values[:,:65],affine)
    right=write_dem(tmp_path/'right.tif',values[:,64:],affine@Affine.translation(64,0))
    actual,destination,_=sample_sources([left,right],BOUNDS,(513,513),normalize({'resampling':'Bilinear'}))
    expected=np.full(actual.shape,np.nan)
    reproject(values,expected,src_transform=affine,src_crs='EPSG:3857',src_nodata=-9999,
              dst_transform=destination,dst_crs='EPSG:3857',dst_nodata=np.nan,
              resampling=Resampling.bilinear,num_threads=2,warp_mem_limit=128,tolerance=0.0,XSCALE=1.0,YSCALE=1.0)
    np.testing.assert_allclose(actual,expected,atol=1e-9)

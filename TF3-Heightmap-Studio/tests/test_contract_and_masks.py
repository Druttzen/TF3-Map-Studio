import sys,subprocess,json
from pathlib import Path
import numpy as np
import pytest
import rasterio
from rasterio import Affine
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from alignment import mercator_bounds,load_context
from elevation import sample_sources
from height_settings import normalize

def test_current_osm_producer_contract(tmp_path):
 producer=ROOT.parent/'OSM-TF3-Vanilla-Converter'
 assert (producer/'tools/settings.py').read_bytes()==(ROOT/'vendor/settings.py').read_bytes()
 xml=tmp_path/'current.osm'
 xml.write_text('<osm version="0.6"><bounds minlat="0" minlon="0" maxlat=".01" maxlon=".01"/><node id="1" lat=".002" lon=".002"/><node id="2" lat=".008" lon=".008"/><way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way></osm>')
 lua=tmp_path/'current.lua'
 script="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from converter import write_outputs;write_outputs(sys.argv[2],sys.argv[3],str(Path(sys.argv[3]).with_suffix('.report.json')),[0,0,.01,.01],[256,256],18,100000,{'waterway_width':3},None,None)"
 # Real current producer in a separate interpreter, not the old vendored copy.
 subprocess.run([sys.executable,'-c',script,str(producer/'tools'),str(xml),str(lua)],check=True,capture_output=True,text=True)
 context=load_context(lua.with_suffix('.report.json'),xml,lua_path=lua)
 assert context['convertedLua']['reportChecksumVerified']
 assert context['report']['settings']['waterway_width']==3
 assert context['report']['settings']['features']['waterways']

@pytest.mark.parametrize('valid,stored,expected',[(False,9999,200),(True,-9999,-9999)])
def test_explicit_mask_overrides_scalar_nodata(tmp_path,valid,stored,expected):
 bounds=[0,0,.01,.01];x0,y0,x1,y1=mercator_bounds(bounds);dx=(x1-x0)/64;dy=(y1-y0)/64
 affine=Affine(dx,0,x0-dx/2,0,-dy,y1+dy/2);files=[]
 for index,value in enumerate([stored,200]):
  path=tmp_path/f'{index}.tif';files.append(path)
  with rasterio.open(path,'w',driver='GTiff',width=65,height=65,count=1,dtype='float64',crs='EPSG:3857',transform=affine,nodata=-9999) as dst:
   dst.write(np.full((65,65),value,dtype=float),1)
   if index==0:dst.write_mask(np.full((65,65),255 if valid else 0,dtype='uint8'))
 result,_,_=sample_sources(files,bounds,(65,65),normalize({'resampling':'Nearest'}))
 np.testing.assert_array_equal(result,expected)

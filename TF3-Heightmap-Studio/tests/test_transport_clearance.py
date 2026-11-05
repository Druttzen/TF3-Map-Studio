"""Coastal DSM road pixels need authored land, not only raised vehicle nodes."""
import sys
from pathlib import Path
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from height_settings import normalize
from job import Job
from terrain import corridor, sample_world, limit_grade


def test_partille_coastal_profile_gets_dry_land_without_altering_source_grid():
 size=(256,256)
 original=np.full((65,65),-1.47)
 original[:,:33]=.45
 baseline=original.copy();terrain=original.copy()
 points=[(-96,0),(96,0)]
 corridor(terrain,original,{'points':points},size,24,12,0,8,Job(),minimum_height=2)
 np.testing.assert_allclose(sample_world(terrain,[(-90,0),(0,0),(90,0)],size),2)
 np.testing.assert_array_equal(original,baseline)
 np.testing.assert_array_equal(terrain[:20],original[:20])
 np.testing.assert_array_equal(terrain[45:],original[45:])


def test_disabled_clearance_preserves_underwater_source_profile():
 original=np.full((65,65),-1.47);terrain=original.copy()
 corridor(terrain,original,{'points':[(-96,0),(96,0)]},(256,256),24,12,0,8,Job())
 np.testing.assert_allclose(terrain,original)


def test_clearance_only_preserves_dry_land_heights_at_overlapping_roads():
 yy,xx=np.mgrid[-128:129:4,-128:129:4]
 original=(xx*.1+yy*.07+12).astype(float)
 terrain=original.copy()
 for points in ([(-96,0),(96,0)],[(0,-96),(0,96)]):
  corridor(terrain,original,{'points':points},(256,256),40,20,0,0,Job(),minimum_height=2)
 np.testing.assert_array_equal(terrain[original>=2],original[original>=2])
 assert np.all(terrain>=original)
 assert sample_world(terrain,[(-96,0),(0,0),(96,0)],(256,256)).min()>=2


def test_clearance_respects_nonzero_water_and_grade_limit():
 points=np.array([[i*10,0] for i in range(30)],dtype=float)
 sampled=np.linspace(5,25,30)
 fitted=limit_grade(np.maximum(sampled,12),points,3)
 assert np.min(fitted)>=12
 assert np.max(np.abs(np.diff(fitted)))<=.300000000001


@pytest.mark.parametrize('value',[-1,101,True,float('nan'),'2'])
def test_invalid_clearance_is_rejected(value):
 with pytest.raises(ValueError):normalize({'transport_water_clearance':value})


def test_legacy_project_defaults_to_no_embankment_edit():
 assert normalize({'roads':True})['transport_water_clearance']==0

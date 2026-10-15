"""Unit tests for the run and post-processing helpers (no Docker, no SFINCS)."""

import numpy as np
import pytest
import xarray as xr

from mdg_pluvial.postprocess import _last_valid, depth_class_areas
from mdg_pluvial.sfincs_run import is_complete, sfincs_command

def test_depth_class_areas():
    depth = np.array([np.nan, 0.12, 0.2, 0.4, 0.9, 1.5, 3.0])
    areas = depth_class_areas(depth, cell_area_m2=1e6, edges=[0.1, 0.3, 0.5, 1, 2])
    assert areas == {"0.1-0.3 m": 2.0, "0.3-0.5 m": 1.0, "0.5-1 m": 1.0, "1-2 m": 1.0,
                     ">= 2 m": 1.0}

def test_last_valid_skips_partial_window():
    good = np.full((2, 2), 0.16)
    bad = np.full((2, 2), -591.0)                    # SFINCS fill in a partial last window
    da = xr.DataArray(np.stack([good, bad]), dims=("timemax", "y", "x"), name="cumprcp")
    active = np.ones((2, 2), dtype=bool)
    assert np.array_equal(_last_valid(da, active), good)
    with pytest.raises(ValueError):
        _last_valid(da.isel(timemax=[1]), active)

def test_sfincs_command(tmp_path):
    cmd = sfincs_command(tmp_path, {"engine": "docker", "image": "img:tag",
                                    "platform": "linux/amd64", "threads": 2})
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert f"{tmp_path.resolve()}:/data" in cmd and "OMP_NUM_THREADS=2" in cmd
    assert cmd[-1] == "img:tag"
    assert sfincs_command(tmp_path, {"engine": "executable", "executable": "/opt/sfincs"}) == \
        ["/opt/sfincs"]
    with pytest.raises(ValueError):
        sfincs_command(tmp_path, {"engine": "executable"})

def test_is_complete(tmp_path):
    assert not is_complete(tmp_path)
    (tmp_path / "sfincs_map.nc").touch()
    (tmp_path / "sfincs_log.txt").write_text("... crashed")
    assert not is_complete(tmp_path)
    (tmp_path / "sfincs_log.txt").write_text("---------- Simulation finished -----------")
    assert is_complete(tmp_path)

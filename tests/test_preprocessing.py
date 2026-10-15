"""Unit tests for the pure functions of the pipeline (no network, no local data)."""

import numpy as np
import pandas as pd
import pytest
import rasterio
import xarray as xr
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

import geopandas as gpd

from mdg_pluvial.basins import basin_bounds, read_polygons, select_by_ids
from mdg_pluvial.rainfall import cells_touching, design_hyetograph, gumbel_depths
from mdg_pluvial.sfincs_setup import hyetograph_timeseries
from mdg_pluvial.soils import texture_to_hsg, usda_texture
from mdg_pluvial.topography import (FABDEM_NODATA, fabdem_archive_name, fabdem_tile_name,
                                    fabdem_tiles_for_bounds, mosaic_tiles)


# --------------------------------------------------------------------- FABDEM
def test_fabdem_names():
    assert fabdem_tile_name(-19, 47) == "S19E047_FABDEM_V1-2.tif"
    assert fabdem_archive_name(-19, 47) == "S20E040-S10E050_FABDEM_V1-2.zip"


def test_fabdem_tiles_for_bounds_edges():
    # a bound exactly on a degree line must not pull an extra row or column
    tiles = fabdem_tiles_for_bounds((47.0, -19.0, 48.0, -18.0))
    assert [t for t, _ in tiles] == ["S19E047_FABDEM_V1-2.tif"]
    assert len(fabdem_tiles_for_bounds((46.5, -19.5, 47.5, -18.5))) == 4


def _tile(path, west, north, value, n=36):
    res = 1 / n
    with rasterio.open(path, "w", driver="GTiff", width=n, height=n, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(west, north, res, res),
                       nodata=FABDEM_NODATA) as dst:
        dst.write(np.full((1, n, n), value, dtype="float32"))
    return path


def test_mosaic_tiles_places_tiles_and_fills_gaps(tmp_path):
    res = 1 / 36
    a = _tile(tmp_path / "a.tif", 47, -18, 1.0)
    b = _tile(tmp_path / "b.tif", 48, -18, 2.0)            # east neighbour; no tile to the south
    dem, transform = mosaic_tiles([a, b], (47.5, -19.5, 48.5, -18.5), res=res)
    assert dem.shape == (36, 36)
    assert transform.c == pytest.approx(47.5) and transform.f == pytest.approx(-18.5)
    assert (dem[:18, :18] == 1).all() and (dem[:18, 18:] == 2).all()
    assert (dem[18:] == FABDEM_NODATA).all()                # ocean cells


# ---------------------------------------------------------------------- soils
def test_usda_texture_known_points():
    sand = np.array([90.0, 40.0, 10.0, 20.0, np.nan])
    clay = np.array([5.0, 20.0, 60.0, 10.0, 10.0])
    silt = 100 - sand - clay
    texture = usda_texture(sand, clay, silt)
    assert list(texture) == [1, 4, 12, 5, 0]                # sand, loam, clay, silt loam, nodata
    assert list(texture_to_hsg(texture)) == [1, 2, 4, 2, 0]


# ------------------------------------------------------------------- rainfall
def test_design_hyetograph_closes_and_peaks_in_middle():
    hyeto = design_hyetograph(200.0, duration_h=24, step_min=30, exponent=1 / 3)
    assert len(hyeto) == 48
    assert hyeto["depth_mm"].sum() == pytest.approx(200.0)
    assert hyeto["depth_mm"].idxmax() == 24
    assert hyeto["intensity_mm_hr"].max() == pytest.approx(hyeto["depth_mm"].max() * 2)


def test_gumbel_depths_increase_with_return_period():
    time = pd.date_range("2000-01-01", "2010-12-31", freq="D")
    rng = np.random.default_rng(0)
    precip = xr.DataArray(rng.gamma(0.5, 10, (len(time), 2, 2)), dims=("time", "lat", "lon"),
                          coords={"time": time, "lat": [-19.0, -19.1], "lon": [47.0, 47.1]})
    depth = gumbel_depths(precip, [2, 10, 100])
    assert depth.attrs["seasons"] == 10                      # 12 season labels, 2 partial dropped
    assert (depth.diff("return_period") > 0).all()


def test_cells_touching_small_basin_between_centres():
    lat = np.round(np.arange(-18.95, -19.6, -0.1), 2)
    lon = np.round(np.arange(47.05, 47.6, 0.1), 2)
    ds = xr.Dataset({"precip": (("time", "lat", "lon"), np.zeros((1, len(lat), len(lon))))},
                    coords={"time": [pd.Timestamp("2000-01-01")], "lat": lat, "lon": lon})
    tiny = box(47.21, -19.29, 47.22, -19.28)                # inside one cell, no centre inside it
    sub = cells_touching(ds, tiny)
    assert int(sub["touches_basin"].sum()) == 1


def test_hyetograph_timeseries_is_a_step_function(tmp_path):
    hyeto = tmp_path / "h.csv"
    pd.DataFrame({"time_h": [0.0, 0.5], "depth_mm": [1.0, 2.0],
                  "intensity_mm_hr": [2.0, 4.0]}).to_csv(hyeto, index=False)
    end = hyetograph_timeseries(hyeto, tmp_path / "p.csv", pd.Timestamp("2000-01-01"),
                                drain_time_h=2)
    ts = pd.read_csv(tmp_path / "p.csv", index_col=0, parse_dates=True)["precip"]
    assert end == pd.Timestamp("2000-01-01 03:00")          # 1 h of rain + 2 h of drain
    assert list(ts.values) == [2.0, 2.0, 4.0, 4.0, 0.0, 0.0]
    assert ts.index[-1] == end                              # forcing covers the whole run
    assert ts.index.is_monotonic_increasing


# --------------------------------------------------------------------- basins
@pytest.fixture
def catchments():
    return gpd.GeoDataFrame({"hybas_id": ["1060000010", "1060000010", "1060000020"],
                             "basin_id": ["1060000010_0", "1060000010_1", "1060000020_0"]},
                            geometry=[box(47, -19, 47.1, -18.9)] * 3, crs="EPSG:4326")


def test_select_by_ids_accepts_basin_and_hybas_ids(catchments):
    assert len(select_by_ids(catchments, ["1060000010"])) == 2
    assert list(select_by_ids(catchments, ["1060000020_0"])["basin_id"]) == ["1060000020_0"]
    with pytest.raises(KeyError, match="999"):
        select_by_ids(catchments, ["999"])


def test_read_polygons_ids(tmp_path):
    gdf = gpd.GeoDataFrame({"name": ["north", "south"]},
                           geometry=[box(47, -19, 47.1, -18.9), box(47, -20, 47.1, -19.9)],
                           crs="EPSG:4326")
    gdf.to_file(tmp_path / "p.geojson")
    assert list(read_polygons(tmp_path / "p.geojson", id_field="name")["basin_id"]) == \
        ["north", "south"]
    assert list(read_polygons(tmp_path / "p.geojson")["basin_id"]) == ["poly_000", "poly_001"]
    gdf.assign(name=["a b", "c"]).to_file(tmp_path / "bad.geojson")
    with pytest.raises(ValueError, match="folder names"):
        read_polygons(tmp_path / "bad.geojson", id_field="name")


def test_basin_bounds_buffer():
    poly = Polygon([(47, -19), (47.5, -19), (47.5, -18.5)])
    assert basin_bounds(poly, 0.1) == (46.9, -19.1, 47.6, -18.4)

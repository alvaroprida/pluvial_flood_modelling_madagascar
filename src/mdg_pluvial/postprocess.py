"""Post-process one SFINCS run: maximum flood depth map, flooded areas and a water balance.

The maximum water level of each 50 m cell is projected onto the 25 m subgrid DEM
(``hydromt_sfincs.utils.downscale_floodmap``), so depths follow the terrain inside each cell.
Depths below ``hmin`` are not counted as flooded.

Outputs, in ``outputs/<basin_id>/``:

* ``hmax_rp<T>.tif``          maximum flood depth (m), 25 m, model UTM CRS, nodata = not flooded
* ``flood_summary_rp<T>.json`` flooded area per depth class, depth statistics, water balance
* ``figures/flood_depth_rp<T>.png``
"""

from __future__ import annotations

import gc
import json
import logging
from pathlib import Path
from typing import Dict, Sequence

import geopandas as gpd
import numpy as np
import xarray as xr

from .io import write_raster

log = logging.getLogger(__name__)

NODATA = -9999.0


def depth_class_areas(depth: np.ndarray, cell_area_m2: float,
                      edges: Sequence[float]) -> Dict[str, float]:
    """Flooded area (km²) per depth class; the last class is open-ended."""
    d = depth[np.isfinite(depth)]
    out = {}
    for lo, hi in zip(edges, list(edges[1:]) + [None]):
        sel = (d >= lo) if hi is None else ((d >= lo) & (d < hi))
        label = f">= {lo:g} m" if hi is None else f"{lo:g}-{hi:g} m"
        out[label] = round(float(sel.sum()) * cell_area_m2 / 1e6, 3)
    return out


def _last_valid(da: xr.DataArray, active: np.ndarray) -> np.ndarray:
    """Last ``timemax`` window with physical values on the active cells.

    SFINCS writes an extra window at the end of the run when the run length is not a
    multiple of ``dtmaxout``; its cumulative fields can hold fill values.
    """
    for i in range(da.sizes["timemax"] - 1, -1, -1):
        vals = da.isel(timemax=i).values
        if np.all(vals[active] >= 0):
            return vals
    raise ValueError(f"no valid {da.name} window in the SFINCS output")


def postprocess_run(model_dir: Path, out_dir: Path, *, return_period: int,
                    hmin: float = 0.10, depth_classes: Sequence[float] = (0.1, 0.3, 0.5, 1, 2),
                    overwrite: bool = False) -> Dict[str, Path]:
    """Write the flood depth map and summary for one model run."""
    from hydromt.io import open_raster
    from hydromt_sfincs import SfincsModel, utils

    tif = out_dir / f"hmax_rp{return_period}.tif"
    summary_path = out_dir / f"flood_summary_rp{return_period}.json"
    sim = model_dir / "sfincs_map.nc"
    if not sim.exists():
        raise FileNotFoundError(f"no SFINCS output in {model_dir} - run the 'run' step first")
    up_to_date = (tif.exists() and summary_path.exists()
                  and summary_path.stat().st_mtime >= sim.stat().st_mtime)
    if up_to_date and not overwrite:
        log.info("post-processing complete, skipped")
        return {"hmax": tif, "summary": summary_path}

    quiet = logging.getLogger("mdg_pluvial.hydromt")
    sf = SfincsModel(root=str(model_dir), mode="r", logger=quiet)
    try:
        sf.read_results()
        res = sf.results
        zsmax = res["zsmax"].max("timemax")
        crs = zsmax.raster.crs
        active = res["msk"].values > 0
        cell_m2 = abs(float(zsmax.raster.res[0] * zsmax.raster.res[1]))
        rain = _last_valid(res["cumprcp"], active)[active] * 1000      # m -> mm
        infil = _last_valid(res["cuminf"], active)[active] * 1000
        h_cell = (zsmax.values - res["zb"].values)[active]
    finally:
        del sf
        gc.collect()

    dep = open_raster(model_dir / "subgrid" / "dep_subgrid.tif")
    region = gpd.read_file(model_dir / "region.geojson").to_crs(crs)
    hmax = utils.downscale_floodmap(zsmax, dep=dep, hmin=hmin, gdf_mask=region)
    if hmax.raster.res[1] > 0:                   # HydroMT grids run south-up: store north-up
        hmax = hmax.raster.flipud()
    depth = hmax.values.astype("float32")
    px_m2 = abs(float(hmax.raster.res[0] * hmax.raster.res[1]))

    out_dir.mkdir(parents=True, exist_ok=True)
    write_raster(tif, np.where(np.isfinite(depth), depth, NODATA), hmax.raster.transform,
                 crs=crs, nodata=NODATA, dtype="float32",
                 descriptions=[f"max_flood_depth_m_rp{return_period}"])

    flooded = depth[np.isfinite(depth)]
    basin_km2 = active.sum() * cell_m2 / 1e6
    mean_rain, mean_inf = float(rain.mean()), float(infil.mean())
    summary = {
        "basin_id": model_dir.name,
        "return_period_years": return_period,
        "hmin_m": hmin,
        "active_area_km2": round(basin_km2, 3),
        "flooded_area_km2": round(flooded.size * px_m2 / 1e6, 3),
        "flooded_share_pct": round(100 * flooded.size * px_m2 / 1e6 / basin_km2, 2),
        "max_depth_m": round(float(flooded.max()), 3) if flooded.size else 0.0,
        "mean_depth_flooded_m": round(float(flooded.mean()), 3) if flooded.size else 0.0,
        "p95_depth_flooded_m": round(float(np.percentile(flooded, 95)), 3) if flooded.size else 0.0,
        "flooded_volume_m3": round(float(flooded.sum()) * px_m2),
        "area_by_depth_km2": depth_class_areas(depth, px_m2, depth_classes),
        "water_balance_mm": {
            "rainfall": round(mean_rain, 1),
            "infiltration": round(mean_inf, 1),
            "effective_rainfall": round(mean_rain - mean_inf, 1),
            "runoff_coefficient": round((mean_rain - mean_inf) / mean_rain, 3) if mean_rain else None,
        },
        "max_depth_coarse_grid_m": round(float(np.nanmax(h_cell)), 3),
        "depth_raster": tif.name,
        "depth_raster_resolution_m": abs(float(hmax.raster.res[0])),
        "crs": crs.to_string(),
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    log.info("flooded %.2f km2 (%.1f%%), max depth %.2f m", summary["flooded_area_km2"],
             summary["flooded_share_pct"], summary["max_depth_m"])
    return {"hmax": tif, "summary": summary_path}

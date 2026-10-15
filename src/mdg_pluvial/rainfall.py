"""Design rainfall per basin, from the local GPM IMERG daily cube.

1. **Frequency analysis.** Seasonal maxima of daily rainfall per GPM cell (season year starts
   1 July, so one cyclone season is never split), fitted with a Gumbel (EV1) distribution by
   the method of moments -> 24 h depth per return period.
2. **Basin depth.** The per-cell depths of the cells touching the basin are reduced to one
   value (median by default).
3. **Hyetograph.** Depth-duration power law P(t) = P(24h) (t/24)^n, then the Alternating Block
   Method (Chow, Maidment & Mays, Applied Hydrology, 14.4).

The exponent n is uncalibrated (no sub-daily data yet), and it sets the peak intensity. Treat
the hyetographs as provisional until n is calibrated on IMERG half-hourly or sub-daily gauges.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import pandas as pd
import shapely
import xarray as xr

log = logging.getLogger(__name__)

EULER_GAMMA = 0.5772


def open_gpm(path: Path) -> xr.Dataset:
    ds = xr.open_dataset(path)
    rename = {k: v for k, v in (("latitude", "lat"), ("longitude", "lon")) if k in ds.dims}
    return ds.rename(rename).transpose("time", "lat", "lon")


def cells_touching(ds: xr.Dataset, geometry) -> xr.Dataset:
    """Subset of the cube whose cells intersect *geometry*.

    Cells are tested as boxes, not centre points: a small basin can fall between the
    centres of a 0.1 degree grid and would otherwise select nothing.
    """
    lat, lon = ds["lat"].values, ds["lon"].values
    dlat, dlon = abs(float(lat[1] - lat[0])), abs(float(lon[1] - lon[0]))
    w, s, e, n = geometry.bounds
    sub = ds.sel(lat=slice(*sorted((s - dlat, n + dlat), reverse=lat[0] > lat[-1])),
                 lon=slice(w - dlon, e + dlon))
    lon2d, lat2d = np.meshgrid(sub["lon"].values, sub["lat"].values)
    boxes = shapely.box(lon2d - dlon / 2, lat2d - dlat / 2, lon2d + dlon / 2, lat2d + dlat / 2)
    touch = shapely.intersects(boxes, geometry)
    if not touch.any():
        raise ValueError("the basin does not intersect the GPM grid")
    return sub.assign(touches_basin=(("lat", "lon"), touch))


def gumbel_depths(precip: xr.DataArray, return_periods: Sequence[int],
                  season_start_month: int = 7) -> xr.DataArray:
    """24 h depth per return period and cell: Gumbel (EV1), method of moments, seasonal maxima."""
    season = precip["time"].dt.year + (precip["time"].dt.month >= season_start_month)
    annual_max = precip.groupby(season.rename("season")).max("time")
    annual_max = annual_max.isel(season=slice(1, -1))          # drop the two partial seasons
    beta = annual_max.std("season", ddof=1) * np.sqrt(6) / np.pi
    mu = annual_max.mean("season") - EULER_GAMMA * beta
    rp = xr.DataArray(list(return_periods), dims="return_period",
                      coords={"return_period": list(return_periods)})
    depth = (mu - beta * np.log(-np.log(1 - 1 / rp))).transpose("return_period", ...)
    depth.name = "depth_24h"
    depth.attrs = {"units": "mm", "long_name": "24-hour rainfall depth",
                   "method": "Gumbel (EV1), method of moments, seasonal maxima",
                   "seasons": int(annual_max.sizes["season"]),
                   "season_start_month": season_start_month}
    return depth


def design_hyetograph(depth_24h_mm: float, *, duration_h: int = 24, step_min: int = 30,
                      exponent: float = 1 / 3) -> pd.DataFrame:
    """Alternating Block Method hyetograph from a 24-hour depth.

    Depth-duration curve: P(t) = P(24h) * (t/24)**exponent.
    Returns a frame with the time-ordered blocks in mm and mm/hr.
    """
    step_h = step_min / 60
    n_blocks = int(round(duration_h / step_h))
    durations = np.arange(1, n_blocks + 1) * step_h
    cumulative = depth_24h_mm * (durations / 24.0) ** exponent
    increments = np.diff(cumulative, prepend=0.0)          # descending by construction

    # alternating blocks: largest in the middle, then right, left, right, ...
    order = np.empty(n_blocks, dtype=int)
    right, left = n_blocks // 2, n_blocks // 2 - 1
    for i in range(n_blocks):
        if i % 2 == 0:
            order[right] = i
            right += 1
        else:
            order[left] = i
            left -= 1
    blocks = increments[order]

    return pd.DataFrame({
        "time_h": np.arange(n_blocks) * step_h,
        "depth_mm": blocks,
        "intensity_mm_hr": blocks / step_h,
    })


def basin_design_rainfall(gpm_file: Path, geometry, out_dir: Path, *,
                          return_periods: Sequence[int], season_start_month: int = 7,
                          statistic: str = "median", duration_h: int = 24, step_min: int = 30,
                          exponent: float = 1 / 3,
                          plausible_peak_mm_hr: float = 150) -> Dict[str, Path]:
    """Write the basin's design depths (netCDF, per cell) and one hyetograph CSV per return period."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open_gpm(gpm_file) as ds:
        sub = cells_touching(ds, geometry)
        depth = gumbel_depths(sub["precip"].load(), return_periods, season_start_month)

    depth_nc = out_dir / "design_depth_24h.nc"
    depth.to_dataset().assign(touches_basin=sub["touches_basin"]).to_netcdf(depth_nc)
    outputs = {"design_depth_24h": depth_nc}

    reducer = {"median": np.nanmedian, "mean": np.nanmean, "max": np.nanmax}[statistic]
    in_basin = sub["touches_basin"].values
    rows = []
    for rp in return_periods:
        d = float(reducer(depth.sel(return_period=rp).values[in_basin]))
        hyeto = design_hyetograph(d, duration_h=duration_h, step_min=step_min, exponent=exponent)
        path = out_dir / f"hyetograph_rp{rp}.csv"
        hyeto.round(4).to_csv(path, index=False)
        outputs[f"hyetograph_rp{rp}"] = path
        peak = float(hyeto["intensity_mm_hr"].max())
        rows.append({"return_period": rp, "depth_24h_mm": round(d, 1),
                     "peak_mm_hr": round(peak, 1)})
        if peak > plausible_peak_mm_hr:
            log.warning("RP %s: peak block %.0f mm/hr exceeds %s mm/hr - the depth-duration "
                        "exponent is the likely cause", rp, peak, plausible_peak_mm_hr)

    summary = out_dir / "design_rainfall_summary.csv"
    pd.DataFrame(rows).assign(gpm_cells=int(in_basin.sum()), statistic=statistic,
                              dd_exponent=exponent).to_csv(summary, index=False)
    outputs["design_rainfall_summary"] = summary
    return outputs

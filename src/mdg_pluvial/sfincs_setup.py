"""Build one SFINCS rain-on-grid model per basin with HydroMT-SFINCS.

HydroMT reads the basin's ``data_catalog.yml``, so every grid is clipped, reprojected to the
basin's UTM zone and resampled here, where the target grid is known.
"""

from __future__ import annotations

import gc
import logging
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger(__name__)


def hyetograph_timeseries(hyetograph_csv: Path, out_csv: Path, tref: pd.Timestamp) -> pd.Timestamp:
    """Convert a design hyetograph (blocks in mm/hr) to a HydroMT precipitation time series.

    Each block's intensity is stamped at the block start and repeated at the block end, so the
    forcing stays a step function however SFINCS interpolates. Returns the end of the rainfall.
    """
    hyeto = pd.read_csv(hyetograph_csv)
    step = pd.Timedelta(hours=float(hyeto["time_h"].iloc[1] - hyeto["time_h"].iloc[0]))
    starts = tref + pd.to_timedelta(hyeto["time_h"], unit="h")
    ends = starts + step - pd.Timedelta(seconds=1)
    times = pd.DatetimeIndex(pd.concat([starts, ends]).sort_values().values)
    values = hyeto["intensity_mm_hr"].repeat(2).values
    rain_end = starts.iloc[-1] + step
    series = pd.Series(list(values) + [0.0], index=times.append(pd.DatetimeIndex([rain_end])),
                       name="precip")
    series.index.name = "time"
    series.to_csv(out_csv)
    return rain_end


def build_sfincs_model(basin_dir: Path, model_dir: Path, geometry, *, model_cfg: dict,
                       overwrite: bool = False) -> Path:
    """Write a SFINCS model for one basin into *model_dir*. Returns the model folder."""
    try:
        from hydromt_sfincs import SfincsModel
    except ImportError as exc:                    # pragma: no cover
        raise ImportError("model setup needs hydromt_sfincs: pip install -r requirements.txt") from exc

    if (model_dir / "sfincs.inp").exists() and not overwrite:
        log.info("model exists, skipped: %s", model_dir)
        return model_dir
    if model_dir.exists():
        shutil.rmtree(model_dir)
    model_dir.mkdir(parents=True)

    region = gpd.GeoDataFrame(geometry=[geometry], crs="EPSG:4326")
    region_file = model_dir / "region.geojson"
    region.to_file(region_file, driver="GeoJSON")

    rp = model_cfg.get("design_return_period", 100)
    tref = pd.Timestamp(model_cfg.get("tref", "2000-01-01 00:00"))
    precip_csv = model_dir / f"precip_rp{rp}.csv"
    rain_end = hyetograph_timeseries(basin_dir / "rainfall" / f"hyetograph_rp{rp}.csv",
                                     precip_csv, tref)
    tstop = rain_end + pd.Timedelta(hours=model_cfg.get("drain_time_h", 12))
    arc = model_cfg.get("gcn250_arc", "ARCII").lower()

    hydromt_log = logging.getLogger("mdg_pluvial.hydromt")
    hydromt_log.setLevel(logging.WARNING)         # HydroMT is chatty at INFO
    sf = SfincsModel(root=str(model_dir), mode="w+",
                     data_libs=[str(basin_dir / "data_catalog.yml")], logger=hydromt_log)
    try:
        sf.setup_grid_from_region(region={"geom": region}, res=model_cfg.get("res", 50),
                                  crs=model_cfg.get("crs", "utm"))
        sf.setup_dep(datasets_dep=[{"elevtn": "fabdem"}])
        # a polygon drawn over the coast would otherwise model the sea as flat land at 0 m
        sf.setup_mask_active(mask=region, zmin=model_cfg.get("min_active_elevation", 0.01),
                             reset_mask=True)
        if model_cfg.get("outflow_boundaries", True):
            # without include_mask HydroMT sets no boundary cells at all; the basin
            # polygon makes its whole edge an outflow boundary. The edge is a drainage
            # divide, so in practice water leaves through the outlet.
            sf.setup_mask_bounds(btype="outflow", include_mask=region, all_touched=True,
                                 reset_bounds=True)
        sf.setup_subgrid(datasets_dep=[{"elevtn": "fabdem"}],
                         datasets_rgh=[{"lulc": "vito_lulc", "reclass_table": "vito_reclass"}],
                         nr_subgrid_pixels=model_cfg.get("nr_subgrid_pixels", 2),
                         write_dep_tif=True)
        sf.setup_cn_infiltration(cn=f"gcn250_{arc}",
                                 antecedent_moisture=model_cfg.get("antecedent_moisture", "avg"))
        sf.setup_config(tref=tref.strftime("%Y%m%d %H%M%S"),
                        tstart=tref.strftime("%Y%m%d %H%M%S"),
                        tstop=tstop.strftime("%Y%m%d %H%M%S"))
        sf.setup_precip_forcing(timeseries=str(precip_csv))
        sf.write()
    finally:
        # release the model (and its log file handle) now: HydroMT's destructor fails
        # noisily if it only runs at interpreter shutdown. The model holds reference
        # cycles, so a collection is needed to actually run it.
        del sf
        gc.collect()
    log.info("SFINCS model written: %s", model_dir)
    return model_dir

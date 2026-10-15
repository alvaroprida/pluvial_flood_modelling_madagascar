"""Per-basin pipeline: fetch inputs on the fly, build, run and post-process the SFINCS model.

Each basin is processed independently, so basins can run in series or in parallel. Every step
skips work whose output already exists, so an interrupted batch can simply be relaunched.

Per-basin layout::

    data/basins/<basin_id>/
    ├── basin.geojson
    ├── topography/dem.tif
    ├── landcover/lulc.tif, lulc_mapping.csv
    ├── curve_number/gcn250_<arc>.tif
    ├── soil/soil_{sand,clay,texture,hsg}.tif  (+ raw/ WCS downloads)
    ├── rainfall/design_depth_24h.nc, hyetograph_rp<T>.csv, design_rainfall_summary.csv
    ├── data_catalog.yml
    ├── provenance.json
    └── pipeline.log
    models/<basin_id>/                          SFINCS model ("setup") and raw output ("run")
    outputs/<basin_id>/                         flood depth map and summary ("postprocess")
"""

from __future__ import annotations

import logging
import multiprocessing
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import geopandas as gpd
import shapely

from .basins import basin_bounds
from .catalog import write_data_catalog, write_provenance
from .config import Settings, load_settings
from .curve_number import SOURCE as GCN250_SOURCE
from .curve_number import extract_curve_number
from .io import configure_http
from .landcover import VITO_MAPPING_URL, VITO_URL, extract_landcover, landcover_mapping
from .qc import plot_flood_map, plot_input_figures, plot_model_figures
from .rainfall import basin_design_rainfall
from .soils import SOURCE as SOILGRIDS_SOURCE
from .soils import extract_soils
from .topography import SOURCE as FABDEM_SOURCE
from .topography import extract_dem

log = logging.getLogger("mdg_pluvial")

STEPS = ("inputs", "setup", "run", "postprocess")


def _cached(path: Path, overwrite: bool, build: Callable[[], Path]) -> Path:
    if path.exists() and not overwrite:
        log.info("cached   %s", path.name)
        return path
    t0 = time.time()
    build()
    log.info("written  %s (%.0fs)", path.name, time.time() - t0)
    return path


def prepare_inputs(basin_id: str, geometry, settings: Settings, *,
                   overwrite: bool = False) -> Path:
    """Fetch and clip every model input for one basin. Returns the basin folder."""
    bdir = settings.basin_dir(basin_id)
    if (bdir / "provenance.json").exists() and not overwrite:
        log.info("inputs complete, skipped")
        return bdir

    bounds = basin_bounds(geometry, settings.domain.get("buffer_deg", 0.02))
    cache = settings.cache_dir
    static, rain = settings.static_data, settings.rainfall
    ua = settings.http.get("user_agent", "mdg-pluvial/0.1")
    log.info("bounds %s", bounds)

    bdir.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame({"basin_id": [basin_id]}, geometry=[geometry], crs="EPSG:4326").to_file(
        bdir / "basin.geojson", driver="GeoJSON")

    outputs: Dict[str, Path] = {}
    records: List[dict] = []

    def record(key: str, path: Path, source: str, note: str = "") -> None:
        outputs[key] = path
        records.append({"key": key, "path": path, "source": source, "note": note})

    # topography ------------------------------------------------------------
    p = bdir / "topography" / "dem.tif"
    _cached(p, overwrite, lambda: extract_dem(bounds, p, cache / "fabdem"))
    record("dem", p, FABDEM_SOURCE, "FABDEM V1-2, 1 arcsec, EGM2008, CC BY-NC-SA 4.0")

    # land cover ------------------------------------------------------------
    p = bdir / "landcover" / "lulc.tif"
    _cached(p, overwrite, lambda: extract_landcover(bounds, p, user_agent=ua))
    record("lulc", p, VITO_URL, "Copernicus LC100 v3.0.1 2019, native 100 m grid")
    p = bdir / "landcover" / "lulc_mapping.csv"
    _cached(p, overwrite, lambda: landcover_mapping(p, cache))
    record("lulc_mapping", p, VITO_MAPPING_URL, "class -> Manning's n (Deltares)")

    # curve number ----------------------------------------------------------
    for arc in static.get("gcn250_arcs", ["ARCII"]):
        p = bdir / "curve_number" / f"gcn250_{arc.lower()}.tif"
        _cached(p, overwrite, lambda: extract_curve_number(bounds, arc, p, cache / "gcn250"))
        record(f"gcn250_{arc.lower()}", p, GCN250_SOURCE, "0 and >100 recoded to nodata 255")

    # soils -----------------------------------------------------------------
    soil_dir = bdir / "soil"
    if overwrite or not (soil_dir / "soil_hsg.tif").exists():
        t0 = time.time()
        extract_soils(bounds, soil_dir, soil_dir / "raw",
                      depths=static.get("soilgrids_depths"),
                      weights=static.get("soilgrids_weights"))
        log.info("written  soil layers (%.0fs)", time.time() - t0)
    for key in ("sand", "clay", "texture", "hsg"):
        record(f"soil_{key}", soil_dir / f"soil_{key}.tif", SOILGRIDS_SOURCE)

    # rainfall --------------------------------------------------------------
    rain_dir = bdir / "rainfall"
    rps = rain.get("return_periods", [2, 5, 10, 25, 50, 100])
    if overwrite or not (rain_dir / "design_rainfall_summary.csv").exists():
        basin_design_rainfall(
            settings.gpm_daily, geometry, rain_dir, return_periods=rps,
            season_start_month=rain.get("season_start_month", 7),
            statistic=rain.get("basin_statistic", "median"),
            duration_h=rain.get("hyetograph_duration_h", 24),
            step_min=rain.get("hyetograph_step_min", 30),
            exponent=rain.get("dd_exponent", 1 / 3),
            plausible_peak_mm_hr=rain.get("plausible_peak_mm_hr", 150))
        log.info("written  design rainfall")
    gpm_note = f"GPM IMERG daily ({settings.gpm_daily.name}), Gumbel + alternating block"
    record("design_depth_24h", rain_dir / "design_depth_24h.nc", gpm_note)
    record("design_rainfall_summary", rain_dir / "design_rainfall_summary.csv", gpm_note)
    for rp in rps:
        record(f"hyetograph_rp{rp}", rain_dir / f"hyetograph_rp{rp}.csv", gpm_note)

    # catalogue and provenance (written last: provenance marks the step complete) --
    cat = write_data_catalog(outputs, bdir)
    records.append({"key": "data_catalog", "path": cat, "source": "derived"})
    write_provenance(records, bdir, basin_id=basin_id,
                     settings_snapshot={k: settings.raw.get(k) for k in
                                        ("domain", "static_data", "rainfall")})
    return bdir


def _qc(plot: Callable[[], object]) -> None:
    """Draw QC figures; a plotting failure is logged but never fails the basin."""
    try:
        plot()
    except Exception:
        log.warning("QC figures failed (the basin outputs are unaffected):\n%s",
                    traceback.format_exc())


def process_basin(basin_id: str, geometry_wkb: bytes, settings_path: Optional[str],
                  steps: Sequence[str], overwrite: bool = False) -> dict:
    """Run the requested *steps* for one basin. Never raises: errors are returned."""
    settings = load_settings(Path(settings_path) if settings_path else None)
    configure_http(**{k: settings.http[k] for k in ("user_agent", "timeout_s", "max_retries")
                      if k in settings.http})
    geometry = shapely.from_wkb(geometry_wkb)
    bdir = settings.basin_dir(basin_id)
    bdir.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(bdir / "pipeline.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    log.setLevel(logging.INFO)               # worker processes start at the WARNING default
    t0 = time.time()
    result = {"basin_id": basin_id, "status": "ok", "error": None}
    try:
        log.info("==== basin %s: steps %s", basin_id, list(steps))
        qc = settings.raw.get("qc_figures", True)
        if "inputs" in steps:
            prepare_inputs(basin_id, geometry, settings, overwrite=overwrite)
            if qc:
                _qc(lambda: plot_input_figures(
                    bdir, model_rp=settings.model.get("design_return_period", 100),
                    overwrite=overwrite))
        if "setup" in steps:
            from .sfincs_setup import build_sfincs_model
            model_dir = build_sfincs_model(bdir, settings.model_dir(basin_id), geometry,
                                           model_cfg=settings.model, overwrite=overwrite)
            if qc:
                _qc(lambda: plot_model_figures(model_dir, overwrite=overwrite))
        if "run" in steps:
            from .sfincs_run import run_sfincs
            run_sfincs(settings.model_dir(basin_id), settings.section("run"),
                       overwrite=overwrite)
        if "postprocess" in steps:
            from .postprocess import postprocess_run
            post = settings.section("postprocess")
            rp = settings.model.get("design_return_period", 100)
            model_dir, out_dir = settings.model_dir(basin_id), settings.output_dir(basin_id)
            files = postprocess_run(model_dir, out_dir, return_period=rp,
                                    hmin=post.get("hmin", 0.10),
                                    depth_classes=post.get("depth_classes", [0.1, 0.3, 0.5, 1, 2]),
                                    overwrite=overwrite)
            fig = out_dir / "figures" / f"flood_depth_rp{rp}.png"
            stale = not fig.exists() or fig.stat().st_mtime < files["summary"].stat().st_mtime
            if qc and (overwrite or stale):
                _qc(lambda: plot_flood_map(files["hmax"], files["summary"],
                                           model_dir / "subgrid" / "dep_subgrid.tif",
                                           model_dir / "region.geojson", fig))
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        log.error("basin %s failed:\n%s", basin_id, traceback.format_exc())
    finally:
        result["seconds"] = round(time.time() - t0, 1)
        root.removeHandler(handler)
        handler.close()
    return result


def run_basins(basins: gpd.GeoDataFrame, *, settings_path: Optional[Path] = None,
               steps: Sequence[str] = STEPS, workers: int = 1,
               overwrite: bool = False) -> List[dict]:
    """Process every basin in *basins* (columns ``basin_id`` + geometry), in series or in parallel."""
    unknown = set(steps) - set(STEPS)
    if unknown:
        raise ValueError(f"unknown step(s) {sorted(unknown)}; choose from {STEPS}")
    jobs = [(row.basin_id, shapely.to_wkb(row.geometry), str(settings_path) if settings_path else None,
             tuple(steps), overwrite) for row in basins.itertuples()]

    results = []
    if workers <= 1:
        for job in jobs:
            results.append(process_basin(*job))
            _report(results[-1], len(results), len(jobs))
        return results

    ctx = multiprocessing.get_context("spawn")       # same behaviour on macOS and Linux
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        futures = [pool.submit(process_basin, *job) for job in jobs]
        for fut in as_completed(futures):
            results.append(fut.result())
            _report(results[-1], len(results), len(jobs))
    return results


def _report(result: dict, done: int, total: int) -> None:
    msg = f"[{done}/{total}] {result['basin_id']}: {result['status']} ({result['seconds']}s)"
    if result["error"]:
        msg += f" - {result['error']}"
    log.info(msg)

"""Quality-control figures: one per basin input, and an overview of the built SFINCS model.

Inputs  -> data/basins/<basin_id>/figures/0X_<input>.png
Model   -> models/<basin_id>/figures/model_overview.png

Every map shows the basin outline. Magnitudes use one hue, light to dark; land cover uses the
official Copernicus class colours, with small classes folded into "Other" so no more than
seven colours carry meaning. Existing figures are kept unless ``overwrite`` is set.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import List, Optional

import matplotlib

matplotlib.use("Agg")                       # worker processes have no display

import geopandas as gpd                     # noqa: E402
import matplotlib.pyplot as plt             # noqa: E402
import numpy as np                          # noqa: E402
import pandas as pd                         # noqa: E402
import rasterio                             # noqa: E402
import shapely                              # noqa: E402
import xarray as xr                         # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib import patheffects          # noqa: E402
from matplotlib.patches import Patch        # noqa: E402

log = logging.getLogger(__name__)

INK, MUTED, GRID = "#1f1f1f", "#6b6b6b", "#e6e6e6"
OUTLINE = "#000000"                         # basin outline: black with a white halo, so it
                                            # never collides with a class colour
OUTFLOW = "#d62728"
plt.rcParams.update({
    "font.size": 10, "axes.titlesize": 11, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "figure.dpi": 100,
})

# Copernicus Global Land Service LC100 class colours (product user manual)
VITO_COLORS = {
    0: "#282828", 20: "#ffbb22", 30: "#ffff4c", 40: "#f096ff", 50: "#fa0000",
    60: "#b4b4b4", 70: "#f0f0f0", 80: "#0032c8", 90: "#0096a0", 100: "#fae6a0",
    111: "#58481f", 112: "#009900", 113: "#70663e", 114: "#00cc00", 115: "#4e751f",
    116: "#007800", 121: "#666000", 122: "#8db400", 123: "#8d7400", 124: "#a0dc00",
    125: "#929900", 126: "#648c00", 200: "#000080",
}
OTHER_COLOR = "#d9d9d9"
MAX_CLASSES = 7
HSG_LABELS = ["A (high infiltration)", "B (moderate)", "C (slow)", "D (very slow)"]


# ------------------------------------------------------------------- helpers
def _read(path: Path):
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True)
        b = src.bounds
    return arr, (b.left, b.right, b.bottom, b.top)


def _geo_axes(ax, extent, outline: gpd.GeoDataFrame) -> None:
    """Basin outline, degree axes and a latitude-correct aspect ratio."""
    outline.boundary.plot(ax=ax, color=OUTLINE, linewidth=1.4, path_effects=[
        patheffects.Stroke(linewidth=3.5, foreground="white"), patheffects.Normal()])
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_aspect(1 / math.cos(math.radians((extent[2] + extent[3]) / 2)))
    ax.set(xlabel="Longitude (°)", ylabel="Latitude (°)")
    ax.tick_params(labelsize=8)


def _short(label: str, n: int = 28) -> str:
    return label if len(label) <= n else label[: n - 1].rstrip() + "…"


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def _hbar(ax, labels, values, colors, xlabel: str) -> None:
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, color=colors, height=0.7, edgecolor="white", linewidth=2)
    ax.set_yticks(y, labels, fontsize=9)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for yi, v in zip(y, values):
        ax.text(v, yi, f" {v:.1f}%", va="center", fontsize=8, color=MUTED)
    ax.set_xlim(0, max(values) * 1.18 if len(values) else 1)


def _values_in_basin(arr: np.ma.MaskedArray, extent, outline) -> np.ndarray:
    """Valid values of *arr* whose cell centres fall inside the basin."""
    left, right, bottom, top = extent
    ny, nx = arr.shape
    xs = left + (np.arange(nx) + 0.5) * (right - left) / nx
    ys = top - (np.arange(ny) + 0.5) * (top - bottom) / ny
    xx, yy = np.meshgrid(xs, ys)
    inside = shapely.contains_xy(outline.geometry.iloc[0], xx, yy)
    return arr[inside & ~np.ma.getmaskarray(arr)].data


# -------------------------------------------------------------------- inputs
def plot_topography(dem_tif: Path, outline, out: Path) -> Path:
    dem, ext = _read(dem_tif)
    res_m = 111_320 * (ext[1] - ext[0]) / dem.shape[1]
    dy, dx = np.gradient(dem.filled(np.nan).astype("float32"), res_m)
    slope, aspect = np.arctan(np.hypot(dx, dy)), np.arctan2(-dx, dy)
    shade = (np.sin(np.radians(45)) * np.cos(slope)
             + np.cos(np.radians(45)) * np.sin(slope) * np.cos(np.radians(315) - aspect))
    inside = _values_in_basin(dem, ext, outline)

    fig, (ax, axh) = plt.subplots(1, 2, figsize=(13, 5.5), layout="constrained", gridspec_kw={"width_ratios": [1.3, 1]})
    ax.imshow(np.ma.masked_invalid(shade), extent=ext, cmap="Greys_r", vmin=0, vmax=1)
    im = ax.imshow(dem, extent=ext, cmap="YlOrBr", alpha=0.65)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Elevation (m, EGM2008)")
    _geo_axes(ax, ext, outline)
    ax.set_title("FABDEM elevation with hillshade")

    axh.hist(inside, bins=40, color="#8c510a", edgecolor="white", linewidth=0.5)
    axh.set(xlabel="Elevation (m)", ylabel="Cells inside basin",
            title=f"Inside basin: {inside.min():.0f}–{inside.max():.0f} m, "
                  f"median {np.median(inside):.0f} m")
    axh.grid(axis="y", color=GRID)
    axh.set_axisbelow(True)
    return _save(fig, out)


def plot_landcover(lulc_tif: Path, mapping_csv: Path, outline, out: Path) -> Path:
    lulc, ext = _read(lulc_tif)
    names = pd.read_csv(mapping_csv).set_index("landuse")["description"].to_dict()
    vals, counts = np.unique(_values_in_basin(lulc, ext, outline), return_counts=True)
    shares = pd.Series(100 * counts / counts.sum(), index=vals.astype(int)).sort_values(ascending=False)
    top = list(shares.index[:MAX_CLASSES - 1]) if len(shares) > MAX_CLASSES else list(shares.index)
    other = shares.drop(top).sum()

    # map: top classes in their official colours, the rest grey
    codes = np.full(lulc.shape, len(top), dtype="int16")
    for i, v in enumerate(top):
        codes[lulc.data == v] = i                # masked cells are hidden when drawn
    colors = [VITO_COLORS.get(v, OTHER_COLOR) for v in top] + [OTHER_COLOR]
    cmap = ListedColormap(colors)

    fig, (ax, axb) = plt.subplots(1, 2, figsize=(14, 5.5), layout="constrained", gridspec_kw={"width_ratios": [1.2, 1]})
    ax.imshow(np.ma.masked_where(np.ma.getmaskarray(lulc), codes), extent=ext, cmap=cmap,
              norm=BoundaryNorm(np.arange(len(colors) + 1) - 0.5, len(colors)),
              interpolation="nearest")
    _geo_axes(ax, ext, outline)
    ax.set_title("Copernicus LC100 land cover (2019)")

    labels = [_short(names.get(v, f"class {v}")) for v in top]
    values = [shares[v] for v in top]
    if other > 0:
        labels, values = labels + ["Other"], values + [other]
    _hbar(axb, labels, values, colors[:len(labels)], "Share of basin area (%)")
    axb.set_title("Land cover inside the basin")
    return _save(fig, out)


def plot_curve_number(cn_tif: Path, outline, out: Path, arc: str) -> Path:
    cn, ext = _read(cn_tif)
    inside = _values_in_basin(cn, ext, outline)
    fig, (ax, axh) = plt.subplots(1, 2, figsize=(13, 5.5), layout="constrained", gridspec_kw={"width_ratios": [1.3, 1]})
    im = ax.imshow(cn, extent=ext, cmap="Oranges", vmin=30, vmax=100, interpolation="nearest")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Curve number (-)")
    _geo_axes(ax, ext, outline)
    ax.set_title(f"GCN250 curve number, {arc}")
    axh.hist(inside, bins=np.arange(30, 102, 2), color="#d94801", edgecolor="white", linewidth=0.5)
    axh.set(xlabel="Curve number (-)", ylabel="Cells inside basin",
            title=f"Inside basin: mean CN {inside.mean():.1f} "
                  f"(S = {25.4 * (1000 / inside.mean() - 10):.0f} mm)")
    axh.grid(axis="y", color=GRID)
    axh.set_axisbelow(True)
    return _save(fig, out)


def plot_soil(hsg_tif: Path, outline, out: Path) -> Path:
    hsg, ext = _read(hsg_tif)
    # 0 is both the file's nodata and the "no soil data" class: count it, don't mask it
    inside = _values_in_basin(np.ma.masked_array(hsg.data), ext, outline)
    colors = ["#c6dbef", "#6baed6", "#2171b5", "#08306b"]       # ordinal: A light -> D dark
    fig, (ax, axb) = plt.subplots(1, 2, figsize=(13, 5.5), layout="constrained", gridspec_kw={"width_ratios": [1.3, 1]})
    ax.imshow(np.ma.masked_equal(hsg, 0), extent=ext, cmap=ListedColormap(colors),
              norm=BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5], 4), interpolation="nearest")
    _geo_axes(ax, ext, outline)
    ax.legend(handles=[Patch(color=c, label=l) for c, l in zip(colors, HSG_LABELS)]
              + [Patch(facecolor="white", edgecolor=MUTED, label="No data (built-up, water)")],
              loc="lower left", fontsize=8, framealpha=0.9)
    ax.set_title("Hydrologic Soil Group from SoilGrids texture (audit only)")

    n = max(len(inside), 1)
    nodata = 100 * (inside == 0).sum() / n
    values = [100 * (inside == g).sum() / n for g in (1, 2, 3, 4)] + [nodata]
    _hbar(axb, ["A", "B", "C", "D", "No data"], values, colors + ["#f0f0f0"],
          "Share of basin area (%)")
    axb.set_title("Soil groups inside the basin")
    return _save(fig, out)


def plot_rainfall(rain_dir: Path, outline, out: Path, model_rp: int) -> Path:
    summary = pd.read_csv(rain_dir / "design_rainfall_summary.csv")
    hyeto = pd.read_csv(rain_dir / f"hyetograph_rp{model_rp}.csv")
    with xr.open_dataset(rain_dir / "design_depth_24h.nc") as ds:
        depth = ds["depth_24h"].sel(return_period=model_rp).load()
        touch = ds["touches_basin"].load().astype(bool)
    lat, lon = depth["lat"].values, depth["lon"].values
    dlat, dlon = abs(lat[1] - lat[0]), abs(lon[1] - lon[0])
    ext = (lon.min() - dlon / 2, lon.max() + dlon / 2, lat.min() - dlat / 2, lat.max() + dlat / 2)
    step_h = float(hyeto["time_h"].iloc[1] - hyeto["time_h"].iloc[0])

    fig, axes = plt.subplots(1, 4, figsize=(22, 5), layout="constrained", gridspec_kw={"width_ratios": [1.1, 1, 1.2, 1]})
    ax = axes[0]
    im = ax.pcolormesh(lon, lat, depth.where(touch), cmap="Blues", shading="nearest",
                       edgecolors="white", linewidth=1.5)
    fig.colorbar(im, ax=ax, shrink=0.8, label=f"{model_rp}-year 24 h depth (mm)")
    _geo_axes(ax, ext, outline)
    ax.set_title(f"GPM cells used ({int(touch.sum())}), RP {model_rp}")

    ax = axes[1]
    ax.plot(summary["return_period"], summary["depth_24h_mm"], color="#08519c", lw=2,
            marker="o", ms=8)
    ax.set(xscale="log", xlabel="Return period (years)", ylabel="Basin 24 h depth (mm)",
           title="Design depth (basin median)")
    ax.set_xticks(summary["return_period"], summary["return_period"])
    ax.grid(color=GRID)
    row = summary.loc[summary["return_period"] == model_rp].iloc[0]
    ax.annotate(f"{row['depth_24h_mm']:.0f} mm", (model_rp, row["depth_24h_mm"]),
                textcoords="offset points", xytext=(-40, 6), color=INK, fontsize=9)

    ax = axes[2]
    ax.bar(hyeto["time_h"] + step_h / 2, hyeto["intensity_mm_hr"], width=step_h * 0.85,
           color="#2171b5")
    ax.set(xlabel="Time (h)", ylabel="Intensity (mm/h)",
           title=f"Model forcing: RP {model_rp} hyetograph, peak {row['peak_mm_hr']:.0f} mm/h")
    ax.grid(axis="y", color=GRID)
    ax.set_axisbelow(True)

    ax = axes[3]                                # cumulative on its own axis, never a twin axis
    ax.plot(np.r_[0, hyeto["time_h"] + step_h], np.r_[0, hyeto["depth_mm"].cumsum()],
            color="#2171b5", lw=2)
    ax.set(xlabel="Time (h)", ylabel="Cumulative depth (mm)", title="Cumulative rainfall")
    ax.grid(color=GRID)
    return _save(fig, out)


def plot_input_figures(basin_dir: Path, *, model_rp: int = 100, overwrite: bool = False) -> List[Path]:
    """One QC figure per input, in ``<basin_dir>/figures``. Returns the figures written."""
    fig_dir = basin_dir / "figures"
    outline = gpd.read_file(basin_dir / "basin.geojson")
    jobs = [
        ("01_topography.png", lambda p: plot_topography(basin_dir / "topography" / "dem.tif",
                                                        outline, p)),
        ("02_landcover.png", lambda p: plot_landcover(basin_dir / "landcover" / "lulc.tif",
                                                      basin_dir / "landcover" / "lulc_mapping.csv",
                                                      outline, p)),
    ]
    for cn in sorted((basin_dir / "curve_number").glob("gcn250_*.tif")):
        arc = cn.stem.split("_")[1].upper()
        jobs.append((f"03_curve_number_{arc.lower()}.png",
                     lambda p, cn=cn, arc=arc: plot_curve_number(cn, outline, p, arc)))
    jobs += [
        ("04_soil_hsg.png", lambda p: plot_soil(basin_dir / "soil" / "soil_hsg.tif", outline, p)),
        ("05_design_rainfall.png", lambda p: plot_rainfall(basin_dir / "rainfall", outline, p,
                                                           model_rp)),
    ]
    written = []
    for name, plot in jobs:
        path = fig_dir / name
        if path.exists() and not overwrite:
            continue
        try:                                     # one failing figure must not block the others
            written.append(plot(path))
        except Exception:
            plt.close("all")
            log.warning("QC figure %s failed", name, exc_info=True)
    if written:
        log.info("QC figures: %d written to %s", len(written), fig_dir)
    return written


# --------------------------------------------------------------------- model
def plot_model_figures(model_dir: Path, *, overwrite: bool = False) -> Optional[Path]:
    """2x2 overview of the built model: mask, elevation, infiltration, rainfall forcing."""
    out = model_dir / "figures" / "model_overview.png"
    if out.exists() and not overwrite:
        return None
    import gc

    from hydromt_sfincs import SfincsModel

    quiet = logging.getLogger("mdg_pluvial.hydromt")
    sf = SfincsModel(root=str(model_dir), mode="r", logger=quiet)
    try:
        sf.read()
        grid = sf.grid
        x, y = grid["x"].values, grid["y"].values
        res = abs(float(x[1] - x[0]))
        msk = grid["msk"].values
        elev = (sf.subgrid["z_zmin"] if sf.subgrid and "z_zmin" in sf.subgrid
                else grid["dep"]).values
        scs = grid["scs"].values
        precip = sf.forcing["precip"].to_series()
        epsg = sf.crs.to_epsg()
        cfg = {k: sf.config.get(k) for k in ("tstart", "tstop")}
    finally:
        del sf
        gc.collect()

    active = msk > 0
    ext = tuple(v / 1000 for v in (x.min() - res / 2, x.max() + res / 2,
                                   y.min() - res / 2, y.max() + res / 2))   # km
    origin = "lower" if y[0] < y[-1] else "upper"

    fig, axes = plt.subplots(2, 2, figsize=(13, 11), layout="constrained")
    ax = axes[0, 0]
    shown = np.ma.masked_equal(msk, 0)
    ax.imshow(shown, extent=ext, origin=origin, interpolation="nearest",
              cmap=ListedColormap(["#c6dbef", OUTFLOW]), norm=BoundaryNorm([0.5, 1.5, 3.5], 2))
    ax.legend(handles=[Patch(color="#c6dbef", label=f"Active ({int((msk == 1).sum()):,} cells)"),
                       Patch(color=OUTFLOW, label=f"Outflow boundary ({int((msk == 3).sum()):,})")],
              loc="lower left", fontsize=8, framealpha=0.9)
    ax.set_title(f"Mask: {active.sum() * res * res / 1e6:.1f} km² active, {res:.0f} m cells")

    ax = axes[0, 1]
    im = ax.imshow(np.ma.masked_where(~active, elev), extent=ext, origin=origin, cmap="YlOrBr")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Lowest subgrid elevation per cell (m)")
    ax.set_title("Subgrid elevation (z_zmin)")

    ax = axes[1, 0]
    im = ax.imshow(np.ma.masked_where(~active | (scs < 0), scs * 25.4), extent=ext,
                   origin=origin, cmap="Greens")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Max. soil retention S (mm)")
    ax.set_title("Infiltration capacity (from curve number)")

    for a in (axes[0, 0], axes[0, 1], axes[1, 0]):
        a.set_xlabel(f"Easting (km, EPSG:{epsg})")
        a.set_ylabel("Northing (km)")
        a.tick_params(labelsize=8)

    ax = axes[1, 1]
    hours = (precip.index - precip.index[0]) / pd.Timedelta(hours=1)
    ax.fill_between(hours, precip.values, step=None, color="#2171b5", alpha=0.85, linewidth=0)
    ax.set(xlabel="Time since start (h)", ylabel="Rainfall intensity (mm/h)",
           title=f"Precipitation forcing: {float(np.trapezoid(precip.values, hours)):.0f} mm, "
                 f"run {cfg['tstart']} → {cfg['tstop']}")
    run_h = (pd.Timestamp(cfg["tstop"]) - pd.Timestamp(cfg["tstart"])) / pd.Timedelta(hours=1)
    ax.set_xlim(0, run_h)                     # show the dry drain period too
    ax.grid(color=GRID)
    ax.set_axisbelow(True)

    fig.suptitle(f"SFINCS model {model_dir.name}", fontsize=13, color=INK)
    path = _save(fig, out)
    log.info("QC figure written: %s", path)
    return path

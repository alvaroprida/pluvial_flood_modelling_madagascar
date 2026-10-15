"""Soil texture and Hydrologic Soil Group from SoilGrids 2.0 (250 m).

ISRIC exposes SoilGrids through WCS 2.0.1. ``GetCoverage`` accepts the subset *and* the output
CRS, so the server delivers the basin window already reprojected from the native Homolosine grid
to EPSG:4326. Values are ``int16`` g/kg (divide by 10 for percent); ``0`` marks ocean/no-data.

Texture -> HSG uses the NRCS texture shortcut (NEH-630 ch. 7). It ignores depth to bedrock and
to the water table, both of which can demote a soil by one or two groups; HYSOGs250m (the
layer GCN250 itself uses) is the better source where Earthdata credentials are available.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Sequence

import numpy as np
import rasterio

from .io import Bounds, session, timeout, write_raster

SOILGRIDS_WCS = "https://maps.isric.org/mapserv?map=/map/{var}.map"
SOILGRIDS_NODATA = 0
SOURCE = "https://maps.isric.org WCS 2.0.1, sand/clay mean, 0-100 cm"

USDA_CLASSES = ["sand", "loamy sand", "sandy loam", "loam", "silt loam", "silt",
                "sandy clay loam", "clay loam", "silty clay loam", "sandy clay",
                "silty clay", "clay"]
TEXTURE_TO_HSG = {  # NRCS NEH-630 ch. 7 texture shortcut, 1-4 = A-D
    "sand": 1, "loamy sand": 1, "sandy loam": 1,
    "loam": 2, "silt loam": 2, "silt": 2,
    "sandy clay loam": 3,
    "clay loam": 4, "silty clay loam": 4, "sandy clay": 4, "silty clay": 4, "clay": 4,
}


def soilgrids_coverage(var: str, depth: str, bounds: Bounds, dest: Path, *,
                       stat: str = "mean") -> Path:
    """Download one SoilGrids coverage over *bounds*, reprojected to EPSG:4326 by the server."""
    if dest.exists():
        return dest
    west, south, east, north = bounds
    epsg4326 = "http://www.opengis.net/def/crs/EPSG/0/4326"
    params = {
        "SERVICE": "WCS", "VERSION": "2.0.1", "REQUEST": "GetCoverage",
        "COVERAGEID": f"{var}_{depth}_{stat}", "FORMAT": "GEOTIFF_INT16",
        "SUBSETTINGCRS": epsg4326, "OUTPUTCRS": epsg4326,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    query += f"&SUBSET=X({west},{east})&SUBSET=Y({south},{north})"
    resp = session().get(f"{SOILGRIDS_WCS.format(var=var)}&{query}", timeout=timeout())
    resp.raise_for_status()
    if not resp.content.startswith((b"II", b"MM")):        # WCS reports errors as XML, HTTP 200
        raise RuntimeError(f"WCS did not return a GeoTIFF for {var}_{depth}: "
                           f"{resp.content[:400].decode('utf-8', 'replace')}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(resp.content)
    part.replace(dest)
    return dest


def depth_weighted_mean(paths: Sequence[Path], weights: Sequence[float]) -> np.ndarray:
    """Thickness-weighted mean over the SoilGrids depth intervals, in percent."""
    stack = []
    for path in paths:
        with rasterio.open(path) as src:
            layer = src.read(1).astype("float32")
        layer[layer == SOILGRIDS_NODATA] = np.nan
        stack.append(layer / 10.0)                      # g/kg -> %
    stack = np.stack(stack)
    w = np.asarray(weights, dtype="float32")[:, None, None]
    valid = np.isfinite(stack)
    with np.errstate(invalid="ignore", divide="ignore"):     # all-nodata cells divide by 0
        mean = (np.nansum(np.where(valid, stack * w, 0), axis=0)
                / np.sum(w * valid, axis=0))
    return np.where(valid.any(axis=0), mean, np.nan)


def usda_texture(sand: np.ndarray, clay: np.ndarray, silt: np.ndarray) -> np.ndarray:
    """USDA texture class (1-12, 0 = nodata) from sand/clay/silt percentages.

    Conditions are evaluated in the canonical order of the USDA texture triangle, so the
    first match wins and the class boundaries need no special-casing.
    """
    with np.errstate(invalid="ignore"):
        conditions = [
            silt + 1.5 * clay < 15,                                                   # sand
            (silt + 1.5 * clay >= 15) & (silt + 2 * clay < 30),                       # loamy sand
            ((clay >= 7) & (clay < 20) & (sand > 52) & (silt + 2 * clay >= 30))
            | ((clay < 7) & (silt < 50) & (sand > 43)),                               # sandy loam
            (clay >= 7) & (clay < 27) & (silt >= 28) & (silt < 50) & (sand <= 52),     # loam
            ((silt >= 50) & (clay >= 12) & (clay < 27))
            | ((silt >= 50) & (silt < 80) & (clay < 12)),                              # silt loam
            (silt >= 80) & (clay < 12),                                                # silt
            (clay >= 20) & (clay < 35) & (silt < 28) & (sand > 45),                    # sandy clay loam
            (clay >= 27) & (clay < 40) & (sand > 20) & (sand <= 45),                   # clay loam
            (clay >= 27) & (clay < 40) & (sand <= 20),                                 # silty clay loam
            (clay >= 35) & (sand > 45),                                                # sandy clay
            (clay >= 40) & (silt >= 40),                                               # silty clay
            (clay >= 40) & (sand <= 45) & (silt < 40),                                 # clay
        ]
    texture = np.select(conditions, np.arange(1, 13), default=0).astype("uint8")
    return np.where(np.isfinite(sand) & np.isfinite(clay), texture, 0).astype("uint8")


def texture_to_hsg(texture: np.ndarray) -> np.ndarray:
    """Hydrologic Soil Group (1-4 = A-D, 0 = nodata) from USDA texture classes."""
    hsg = np.zeros_like(texture)
    for i, name in enumerate(USDA_CLASSES, start=1):
        hsg[texture == i] = TEXTURE_TO_HSG[name]
    return hsg


def extract_soils(bounds: Bounds, out_dir: Path, raw_dir: Path, *,
                  depths: Sequence[str], weights: Sequence[float]) -> Dict[str, Path]:
    """Sand, clay, USDA texture and HSG over *bounds*. Returns {layer: path}."""
    layers = {var: [soilgrids_coverage(var, d, bounds, raw_dir / f"soilgrids_{var}_{d}_mean.tif")
                    for d in depths]
              for var in ("sand", "clay")}
    with rasterio.open(layers["sand"][0]) as src:
        transform = src.transform

    sand = depth_weighted_mean(layers["sand"], weights)
    clay = depth_weighted_mean(layers["clay"], weights)
    texture = usda_texture(sand, clay, 100.0 - sand - clay)
    hsg = texture_to_hsg(texture)

    out = {}
    for key, arr, nodata, dtype, desc in [
        ("sand", sand, -9999.0, "float32", "sand_pct_0-100cm"),
        ("clay", clay, -9999.0, "float32", "clay_pct_0-100cm"),
        ("texture", texture, 0, "uint8", "usda_texture_class_1-12"),
        ("hsg", hsg, 0, "uint8", "hydrologic_soil_group_1A_2B_3C_4D"),
    ]:
        data = np.where(np.isfinite(arr), arr, nodata) if dtype == "float32" else arr
        out[key] = write_raster(out_dir / f"soil_{key}.tif", data, transform,
                                nodata=nodata, dtype=dtype, descriptions=[desc])
    return out

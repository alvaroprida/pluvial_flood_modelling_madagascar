"""Topography: FABDEM V1-2 (30 m), fetched tile by tile for a basin's bounding box.

There is no tile-level API. The University of Bristol repository publishes 10x10 degree ZIP
archives (up to 861 MB) of 1x1 degree GeoTIFFs. Each archive is opened over HTTP ``Range``
requests, so ``zipfile`` reads only its central directory and then the members it needs: a
single basin costs a few tens of MB instead of a whole archive. Tiles land in the shared cache
and are reused by every basin that overlaps them.

Tiles are named by their south-west corner (``S19E047_FABDEM_V1-2.tif`` spans 19-18 S,
47-48 E); archives by ``<SW corner>-<NE corner>``.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import rasterio
import requests
from rasterio.transform import from_origin

from .io import Bounds, file_lock, remote_zip, write_raster

log = logging.getLogger(__name__)

FABDEM_BASE = "https://data.bris.ac.uk/datasets/s5hqmjcdj8yo2ibzi9b4ew3sn"
FABDEM_SUFFIX = "_FABDEM_V1-2"
FABDEM_NODATA = -9999.0
FABDEM_RES = 1 / 3600
SOURCE = f"{FABDEM_BASE}/*.zip"


def _corner_label(lat: int, lon: int) -> str:
    """FABDEM corner label, e.g. (-19, 47) -> 'S19E047'."""
    return f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}{'E' if lon >= 0 else 'W'}{abs(lon):03d}"


def fabdem_tile_name(lat: int, lon: int) -> str:
    """1-degree tile file name from its south-west corner."""
    return f"{_corner_label(lat, lon)}{FABDEM_SUFFIX}.tif"


def fabdem_archive_name(lat: int, lon: int) -> str:
    """Name of the 10x10 degree archive holding the tile with that south-west corner."""
    a_lat, a_lon = math.floor(lat / 10) * 10, math.floor(lon / 10) * 10
    return (f"{_corner_label(a_lat, a_lon)}-{_corner_label(a_lat + 10, a_lon + 10)}"
            f"{FABDEM_SUFFIX}.zip")


def fabdem_tiles_for_bounds(bounds: Bounds) -> List[Tuple[str, str]]:
    """[(tile_name, archive_name)] for every 1-degree cell intersecting *bounds* (W, S, E, N).

    The upper edges use ceil so a bound falling exactly on a degree line does not pull an extra row.
    """
    west, south, east, north = bounds
    lats = range(math.floor(south), math.ceil(north))
    lons = range(math.floor(west), math.ceil(east))
    return [(fabdem_tile_name(la, lo), fabdem_archive_name(la, lo)) for la in lats for lo in lons]


def fetch_fabdem_tiles(bounds: Bounds, cache_dir: Path) -> List[Path]:
    """Make sure the FABDEM tiles covering *bounds* are in *cache_dir*; return their paths.

    Ocean-only cells are absent from the archives. That absence is remembered in a ``.absent``
    marker so later basins do not query the archive again.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    by_archive: Dict[str, List[str]] = {}
    for tile, archive in fabdem_tiles_for_bounds(bounds):
        by_archive.setdefault(archive, []).append(tile)

    paths = []
    for archive, tiles in sorted(by_archive.items()):
        with file_lock(cache_dir / archive):          # one worker per archive at a time
            todo = [t for t in tiles if not (cache_dir / t).exists()
                    and not (cache_dir / f"{t}.absent").exists()]
            if todo:
                try:
                    zf = remote_zip(f"{FABDEM_BASE}/{archive}")
                except requests.HTTPError as exc:     # archive does not exist = all-ocean block
                    if exc.response is None or exc.response.status_code != 404:
                        raise
                    members = set()
                else:
                    members = set(zf.namelist())
                for tile in todo:
                    dest = cache_dir / tile
                    if tile not in members:
                        (cache_dir / f"{tile}.absent").touch()
                        continue
                    part = dest.with_suffix(".tif.part")
                    part.write_bytes(zf.read(tile))
                    part.replace(dest)
                    log.info("FABDEM tile %s fetched", tile)
                if members:
                    zf.close()
        paths += [cache_dir / t for t in tiles if (cache_dir / t).exists()]
    return sorted(paths)


def mosaic_tiles(tiles: List[Path], bounds: Bounds, *, nodata: float = FABDEM_NODATA,
                 res: float = FABDEM_RES) -> Tuple[np.ndarray, object]:
    """Mosaic *tiles* onto a grid covering *bounds*, snapped outwards to the tile grid.

    Cells not covered by any tile (ocean) are *nodata*. All tiles must share the grid *res*,
    which is true of FABDEM and checked here so a mixed input fails loudly.
    """
    west = math.floor(bounds[0] / res) * res
    south = math.floor(bounds[1] / res) * res
    east = math.ceil(bounds[2] / res) * res
    north = math.ceil(bounds[3] / res) * res
    width, height = int(round((east - west) / res)), int(round((north - south) / res))
    out = np.full((height, width), nodata, dtype="float32")

    for tile in tiles:
        with rasterio.open(tile) as src:
            if not (math.isclose(src.res[0], res, rel_tol=1e-6)
                    and math.isclose(src.res[1], res, rel_tol=1e-6)):
                raise ValueError(f"{tile.name} resolution {src.res} != {res}")
            left, right = max(west, src.bounds.left), min(east, src.bounds.right)
            bottom, top = max(south, src.bounds.bottom), min(north, src.bounds.top)
            if left >= right or bottom >= top:
                continue
            ncols, nrows = int(round((right - left) / res)), int(round((top - bottom) / res))
            scol = int(round((left - src.bounds.left) / res))
            srow = int(round((src.bounds.top - top) / res))
            dcol, drow = int(round((left - west) / res)), int(round((north - top) / res))
            data = src.read(1, window=((srow, srow + nrows), (scol, scol + ncols)))
            if src.nodata is not None and src.nodata != nodata:
                data = np.where(data == src.nodata, nodata, data)
            out[drow:drow + nrows, dcol:dcol + ncols] = data
    return out, from_origin(west, north, res, res)


def extract_dem(bounds: Bounds, out_path: Path, cache_dir: Path) -> Path:
    """FABDEM over *bounds* as a single GeoTIFF on the native 1 arcsec grid."""
    tiles = fetch_fabdem_tiles(bounds, cache_dir)
    if not tiles:
        raise RuntimeError(f"no FABDEM land tiles intersect {bounds}")
    dem, transform = mosaic_tiles(tiles, bounds)
    return write_raster(out_path, dem, transform, nodata=FABDEM_NODATA, dtype="float32",
                        descriptions=["elevation_m_egm2008"])

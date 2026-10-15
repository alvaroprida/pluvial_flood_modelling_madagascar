"""Curve number: GCN250 (Jaafar et al. 2019), 250 m, one grid per antecedent runoff condition.

This is the one dataset that cannot be read per basin. figshare mints pre-signed download links
that expire within about 10 seconds, so ``/vsicurl`` streaming is not an option. Each global
GeoTIFF (~640 MB) is downloaded once into the shared cache, then windowed per basin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np

from .io import Bounds, clip_raster, http_download, session, timeout, write_raster

GCN250_FIGSHARE_ID = 7756202
GCN250_NODATA = 255
SOURCE = f"https://doi.org/10.6084/m9.figshare.{GCN250_FIGSHARE_ID}"


def figshare_files(article_id: int) -> Dict[str, dict]:
    """{file name: metadata} for a figshare article, via the public REST API."""
    resp = session().get(f"https://api.figshare.com/v2/articles/{article_id}", timeout=timeout())
    resp.raise_for_status()
    return {f["name"]: f for f in resp.json()["files"]}


def gcn250_global(arc: str, cache_dir: Path) -> Path:
    """Path to the cached global GCN250 grid for *arc* (``ARCI``, ``ARCII`` or ``ARCIII``)."""
    fname = f"GCN250_{arc}.tif"
    dest = cache_dir / fname
    if dest.exists():
        return dest
    files = figshare_files(GCN250_FIGSHARE_ID)
    if fname not in files:
        raise KeyError(f"{fname} not published in article {GCN250_FIGSHARE_ID}: {sorted(files)}")
    return http_download(files[fname]["download_url"], dest)


def extract_curve_number(bounds: Bounds, arc: str, out_path: Path, cache_dir: Path) -> Path:
    """GCN250 over *bounds*; 0 and >100 (ocean, unclassified) recoded to nodata 255."""
    cn, transform, _ = clip_raster(str(gcn250_global(arc, cache_dir)), bounds)
    cn = np.where((cn == 0) | (cn > 100), GCN250_NODATA, cn).astype("uint8")
    return write_raster(out_path, cn, transform, nodata=GCN250_NODATA, dtype="uint8",
                        descriptions=[f"curve_number_{arc}"])

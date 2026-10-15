"""Per-basin HydroMT data catalogue and provenance manifest."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import yaml

from . import __version__
from .curve_number import GCN250_NODATA
from .curve_number import SOURCE as GCN250_SOURCE
from .io import sha256
from .landcover import VITO_MAPPING_URL, VITO_NODATA, VITO_URL
from .topography import FABDEM_BASE, FABDEM_NODATA


def _rel(path: Path, root: Path) -> str:
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def write_data_catalog(outputs: Dict[str, Path], basin_dir: Path) -> Path:
    """``data_catalog.yml`` naming the basin's inputs the way HydroMT-SFINCS expects.

    Paths are relative to the catalogue file, so a basin folder can be moved as a unit.
    """
    entries = {
        "fabdem": {
            "path": _rel(outputs["dem"], basin_dir), "data_type": "RasterDataset",
            "driver": "raster", "crs": 4326, "nodata": FABDEM_NODATA,
            "meta": {"category": "topography", "unit": "m+EGM2008", "version": "V1-2",
                     "source_url": FABDEM_BASE, "source_license": "CC BY-NC-SA 4.0",
                     "paper_ref": "Hawker et al. (2022), Environ. Res. Lett. 17, 024016"},
        },
        "vito_lulc": {
            "path": _rel(outputs["lulc"], basin_dir), "data_type": "RasterDataset",
            "driver": "raster", "crs": 4326, "nodata": VITO_NODATA,
            "meta": {"category": "landuse", "version": "v3.0.1 epoch 2019",
                     "source_url": VITO_URL, "source_license": "Copernicus, free and open",
                     "paper_ref": "Buchhorn et al. (2020), doi:10.5281/zenodo.3939050"},
        },
        "vito_reclass": {
            "path": _rel(outputs["lulc_mapping"], basin_dir), "data_type": "DataFrame",
            "driver": "csv", "driver_kwargs": {"index_col": "landuse"},
            "meta": {"category": "landuse", "source_url": VITO_MAPPING_URL,
                     "notes": "VITO class -> Manning's n (column N) and description"},
        },
    }
    for key, path in outputs.items():
        if key.startswith("gcn250_"):
            entries[key] = {
                "path": _rel(path, basin_dir), "data_type": "RasterDataset",
                "driver": "raster", "crs": 4326, "nodata": GCN250_NODATA,
                "meta": {"category": "soil", "version": key.split("_")[1].upper(),
                         "source_url": GCN250_SOURCE, "source_license": "CC BY 4.0",
                         "paper_ref": "Jaafar et al. (2019), Sci. Data 6, 145"},
            }
    if "soil_hsg" in outputs:
        entries["hsg"] = {
            "path": _rel(outputs["soil_hsg"], basin_dir), "data_type": "RasterDataset",
            "driver": "raster", "crs": 4326, "nodata": 0,
            "meta": {"category": "soil", "unit": "1=A 2=B 3=C 4=D",
                     "source_url": "https://maps.isric.org (WCS 2.0.1)",
                     "source_license": "CC BY 4.0",
                     "paper_ref": "Poggio et al. (2021), SOIL 7, 217-240"},
        }

    path = basin_dir / "data_catalog.yml"
    header = "# HydroMT data catalogue for one basin - paths are relative to this file\n"
    # no meta.root: HydroMT then resolves paths against the catalogue's folder, whereas
    # root: "." would resolve them against the current working directory
    body = yaml.safe_dump({"meta": {"version": "1.0"}, **entries}, sort_keys=False)
    path.write_text(header + body)
    return path


def write_provenance(records: List[dict], basin_dir: Path, *, basin_id: str,
                     settings_snapshot: dict) -> Path:
    """``provenance.json``: source, size and SHA-256 of every file the basin step wrote."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import rasterio
    import xarray as xr

    rows = []
    for rec in records:
        p = Path(rec["path"])
        rows.append(dict(rec, path=_rel(p, basin_dir), size_mb=round(p.stat().st_size / 1e6, 3),
                         sha256=sha256(p)))
    manifest = {
        "basin_id": basin_id,
        "package_version": __version__,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "library_versions": dict({m.__name__: getattr(m, "__version__", "n/a")
                                  for m in (np, pd, gpd, rasterio, xr)},
                                 GDAL=rasterio.__gdal_version__),
        "settings": settings_snapshot,
        "outputs": rows,
    }
    path = basin_dir / "provenance.json"
    path.write_text(json.dumps(manifest, indent=2, default=str))
    return path

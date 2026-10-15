"""Land cover: Copernicus Global Land Cover (VITO PROBA-V LC100 v3.0.1, 2019, 100 m).

Zenodo serves the global classification as a tiled GeoTIFF that honours HTTP range requests,
so ``/vsicurl`` reads just the basin window out of the 1.7 GB file. The class -> Manning's n
table (Deltares ``vito_mapping.csv``) is cached once and copied next to each basin's raster.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import rasterio

from .io import Bounds, clip_raster, http_download, write_raster

VITO_URL = ("https://zenodo.org/records/3939050/files/"
            "PROBAV_LC100_global_v3.0.1_2019-nrt_Discrete-Classification-map_EPSG-4326.tif")
VITO_MAPPING_URL = ("https://raw.githubusercontent.com/Deltares/hydromt_sfincs/main/"
                    "hydromt_sfincs/data/lulc/vito_mapping.csv")
VITO_NODATA = 255


def extract_landcover(bounds: Bounds, out_path: Path, *, user_agent: str) -> Path:
    """LC100 classes over *bounds*, on the native 100 m grid."""
    # GDAL_HTTP_USERAGENT is not optional: Zenodo answers 403 to GDAL's default user agent
    # (seen with GDAL 3.5; GDAL 3.10 is let through). Overriding it fixes the read on both.
    with rasterio.Env(GDAL_HTTP_USERAGENT=user_agent,
                      GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                      GDAL_HTTP_MAX_RETRY=5, GDAL_HTTP_RETRY_DELAY=3):
        lulc, transform, _ = clip_raster(f"/vsicurl/{VITO_URL}", bounds)
    return write_raster(out_path, lulc, transform, nodata=VITO_NODATA, dtype="uint8",
                        descriptions=["discrete_classification"])


def landcover_mapping(out_path: Path, cache_dir: Path) -> Path:
    """Class -> description and Manning's n look-up, next to the basin's land cover."""
    cached = http_download(VITO_MAPPING_URL, cache_dir / "vito_mapping.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, out_path)
    return out_path

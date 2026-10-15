"""Modelling domains: HydroBASINS catchments, or any user-supplied polygons.

A *basin* is one row of a GeoDataFrame with a ``basin_id`` column and a polygon in EPSG:4326.
Each basin becomes its own SFINCS model, so the id names every per-basin folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import geopandas as gpd

from .config import Settings
from .io import Bounds


def load_catchments(hybas_file: Path, *, min_area_km2: float = 50.0,
                    area_crs: str = "EPSG:32738", work_crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """HydroBASINS polygons split into single parts, filtered on area, with a stable id.

    ``basin_id`` = ``<hybas_id>_<part>``: a HydroBASINS feature can bundle a mainland basin
    with offshore islets, and each part surviving the area filter is its own domain. The id is
    derived from ``hybas_id`` so it does not shift when the threshold changes.
    """
    gdf = gpd.read_file(hybas_file).explode(index_parts=True).reset_index(drop=True)
    gdf["area_km2"] = gdf.to_crs(area_crs).area / 1e6
    gdf = gdf[gdf["area_km2"] >= min_area_km2].copy()
    gdf["part"] = gdf.groupby("hybas_id").cumcount()
    gdf["hybas_id"] = gdf["hybas_id"].astype("int64").astype(str)
    gdf["basin_id"] = gdf["hybas_id"] + "_" + gdf["part"].astype(str)
    return (gdf.sort_values("basin_id").drop(columns="part")
               .reset_index(drop=True).to_crs(work_crs))


def catchments_from_settings(settings: Settings) -> gpd.GeoDataFrame:
    dom = settings.domain
    return load_catchments(settings.hydrobasins,
                           min_area_km2=dom.get("min_catchment_area_km2", 50.0),
                           area_crs=dom.get("area_crs", "EPSG:32738"),
                           work_crs=dom.get("work_crs", "EPSG:4326"))


def select_by_ids(catchments: gpd.GeoDataFrame, ids: Iterable[str]) -> gpd.GeoDataFrame:
    """Rows matching *ids*, given either as ``basin_id`` (``1060012345_0``) or as ``hybas_id``
    (``1060012345``, which selects every surviving part of that basin)."""
    ids = [str(i).strip() for i in ids]
    by_basin = catchments["basin_id"].isin(ids)
    by_hybas = catchments["hybas_id"].isin(ids)
    found = set(catchments.loc[by_basin, "basin_id"]) | set(catchments.loc[by_hybas, "hybas_id"])
    missing = [i for i in ids if i not in found]
    if missing:
        raise KeyError(f"basin id(s) not found: {missing}. Run scripts/list_basins.py to see the "
                       f"available ids (polygons below the area threshold are excluded).")
    return catchments[by_basin | by_hybas].reset_index(drop=True)


def read_polygons(path: Path, *, id_field: Optional[str] = None,
                  work_crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """Basins from any vector file (GeoJSON, GeoPackage, Shapefile...).

    The id is taken from *id_field*, else from a ``basin_id``, ``catchment_id`` or ``hybas_id``
    column, else generated as ``poly_000``, ``poly_001``...
    """
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path} has no CRS")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].to_crs(work_crs)
    field = id_field or next((c for c in ("basin_id", "catchment_id", "hybas_id")
                              if c in gdf.columns), None)
    if id_field and id_field not in gdf.columns:
        raise KeyError(f"id field '{id_field}' not in {path}: {list(gdf.columns)}")
    gdf["basin_id"] = (gdf[field].astype(str) if field
                       else [f"poly_{i:03d}" for i in range(len(gdf))])
    if gdf["basin_id"].duplicated().any():
        dups = sorted(gdf.loc[gdf["basin_id"].duplicated(), "basin_id"].unique())
        raise ValueError(f"duplicate basin ids in {path}: {dups[:10]}")
    bad = [c for c in gdf["basin_id"] if any(ch in c for ch in r'/\:*?"<>| ')]
    if bad:
        raise ValueError(f"basin ids are used as folder names and cannot contain path "
                         f"characters or spaces: {bad[:10]}")
    return gdf.reset_index(drop=True)


def basin_bounds(geometry, buffer_deg: float) -> Bounds:
    """Bounding box of a basin geometry plus a halo, so edge cells are never clipped."""
    w, s, e, n = geometry.bounds
    return (round(w - buffer_deg, 6), round(s - buffer_deg, 6),
            round(e + buffer_deg, 6), round(n + buffer_deg, 6))

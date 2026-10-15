"""List the HydroBASINS catchments available as model domains.

    python scripts/list_basins.py                          # table on screen
    python scripts/list_basins.py --out basins.geojson     # polygons, to select in QGIS
    python scripts/list_basins.py --out basins.csv         # attributes only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mdg_pluvial.basins import catchments_from_settings
from mdg_pluvial.config import load_settings

COLUMNS = ["basin_id", "hybas_id", "area_km2", "lon", "lat"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, help=".csv, .geojson or .gpkg output")
    parser.add_argument("--config", type=Path, help="settings file (default config/settings.yml)")
    args = parser.parse_args(argv)

    gdf = catchments_from_settings(load_settings(args.config))
    centroids = gdf.to_crs("EPSG:32738").centroid.to_crs(gdf.crs)
    gdf = gdf.assign(lon=centroids.x.round(4), lat=centroids.y.round(4),
                     area_km2=gdf["area_km2"].round(1))

    if args.out is None:
        print(gdf[COLUMNS].to_string(index=False))
    elif args.out.suffix.lower() == ".csv":
        gdf[COLUMNS].to_csv(args.out, index=False)
    else:
        gdf[COLUMNS + ["geometry"]].to_file(args.out)
    print(f"{len(gdf)} basins", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

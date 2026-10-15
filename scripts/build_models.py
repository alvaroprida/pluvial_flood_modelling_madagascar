"""Fetch inputs, build, run and post-process SFINCS models for selected basins, in series or in parallel.

Examples
--------
Two HydroBASINS catchments, all four steps, two at a time::

    python scripts/build_models.py --basin-ids 1071494550_0 1071491870_0 --workers 2

Only (re)run the simulation and post-processing of an existing model::

    python scripts/build_models.py --basin-ids 1071494550_0 --steps run postprocess

Any polygons (e.g. a selection of agricultural or urban catchments), inputs only::

    python scripts/build_models.py --basins selection.geojson --id-field name --steps inputs

Basin ids come from scripts/list_basins.py. A HydroBASINS id without the ``_<part>`` suffix
selects every part of that basin.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mdg_pluvial.basins import catchments_from_settings, read_polygons, select_by_ids
from mdg_pluvial.config import load_settings
from mdg_pluvial.pipeline import STEPS, run_basins


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--basin-ids", nargs="+", metavar="ID",
                       help="HydroBASINS basin ids (from scripts/list_basins.py)")
    which.add_argument("--basins", type=Path, metavar="FILE",
                       help="vector file of polygons, one model per feature")
    parser.add_argument("--id-field", help="column naming each polygon in --basins")
    parser.add_argument("--steps", nargs="+", choices=STEPS, default=list(STEPS),
                        help="steps to run (default: all)")
    parser.add_argument("--workers", type=int, default=1,
                        help="basins processed in parallel (default 1 = in series)")
    parser.add_argument("--overwrite", action="store_true",
                        help="rebuild outputs that already exist")
    parser.add_argument("--config", type=Path, help="settings file (default config/settings.yml)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")

    settings = load_settings(args.config)
    if args.basins:
        basins = read_polygons(args.basins, id_field=args.id_field,
                               work_crs=settings.domain.get("work_crs", "EPSG:4326"))
    else:
        basins = select_by_ids(catchments_from_settings(settings), args.basin_ids)
    logging.info("%d basin(s), steps %s, %d worker(s)", len(basins), args.steps, args.workers)

    results = run_basins(basins, settings_path=args.config, steps=args.steps,
                         workers=args.workers, overwrite=args.overwrite)
    failed = [r for r in results if r["status"] != "ok"]
    logging.info("done: %d ok, %d failed", len(results) - len(failed), len(failed))
    for r in failed:
        logging.info("  %s: %s  (see %s)", r["basin_id"], r["error"],
                     settings.basin_dir(r["basin_id"]) / "pipeline.log")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

# pluvial_flood_modelling_madagascar

Pluvial (rain-on-grid) flood modelling for Madagascar with
[SFINCS](https://sfincs.readthedocs.io) and [HydroMT-SFINCS](https://deltares.github.io/hydromt_sfincs/).
Each catchment is an independent SFINCS model. Its inputs are downloaded **on the fly**, only for
the area it covers, from public global datasets. No data is stored in this repository.

> **Status:** input fetching and model setup implemented and tested. Running the models and
> post-processing the results are the next steps.

## How it works

```
basin ids or polygons ──► 1. inputs ──► 2. setup ──► (3. run) ──► (4. post-process)
                          fetch + clip   SFINCS model
```

You choose the basins: HydroBASINS catchments by id, or any polygons (for example, a selection of
agricultural or urban areas). For each basin, in series or in parallel:

1. **inputs**: download what intersects the basin (plus a small buffer) and write it to
   `data/basins/<basin_id>/`, with a HydroMT data catalogue and a provenance manifest.
2. **setup**: build the SFINCS model in `models/<basin_id>/` (UTM grid, subgrid topography and
   roughness, curve-number infiltration, design-storm rainfall).

Each step also writes QC figures: one per input in `data/basins/<basin_id>/figures/`, and a
model overview in `models/<basin_id>/figures/model_overview.png`.

Downloads that several basins share (FABDEM tiles, the global GCN250 grid) go to `data/cache/`
and are fetched only once. Every step skips outputs that already exist, so an interrupted batch
can simply be relaunched.

## Repository structure

```
├── config/settings.yml  Run settings: paths, buffers, rainfall and model parameters
├── data/                Local data (not versioned) - see data/README.md
├── docs/                Methodology, data sources and licences
├── models/              SFINCS models, one folder per basin (not versioned)
├── notebooks/           National-scale exploration and QC
├── scripts/             Command-line entry points
├── src/mdg_pluvial/     The pipeline, as an importable package
└── tests/               Unit tests
```

## Getting started

### 1. Environment

Python 3.12, in a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .                 # makes the mdg_pluvial package importable
```

Raster I/O goes through `rasterio` (which bundles its own GDAL); the GDAL Python bindings and
command-line tools are not required. The pipeline runs on macOS and Linux.

### 2. Local inputs

Two inputs are not downloaded: the HydroBASINS catchments and the GPM daily rainfall cube. Put
them in `data/raw/`, or point `config/settings.yml` (or the `MDG_HYDROBASINS` / `MDG_GPM_DAILY`
environment variables) at them. See [data/README.md](data/README.md).

### 3. Run

```bash
# which basins exist (276 HydroBASINS catchments >= 50 km2)
python scripts/list_basins.py --out basins.geojson      # open in QGIS to pick ids

# two basins, inputs + model, two at a time
python scripts/build_models.py --basin-ids 1071494550_0 1071491870_0 --workers 2

# your own polygons, named by a column, inputs only
python scripts/build_models.py --basins selection.geojson --id-field name --steps inputs
```

Options: `--steps inputs setup` (default both), `--workers N` (default 1 = in series),
`--overwrite` (rebuild existing outputs), `--config other_settings.yml`.

Failures don't stop the batch. The command reports which basins failed, and each basin's
`data/basins/<basin_id>/pipeline.log` holds the full traceback.

### 4. Tests

```bash
pytest
```

## Data sources

| Dataset | Use | Access | Licence |
|---------|-----|--------|---------|
| HydroBASINS (level 7) | Catchments | Local file | HydroSHEDS licence |
| FABDEM 30 m | Topography | 1-degree tiles via HTTP range requests | **CC BY-NC-SA 4.0 (non-commercial)** |
| Copernicus LC100 | Roughness | Windowed read of the global COG | Free and open |
| GCN250 | Curve number | Global file, cached once | CC BY 4.0 |
| SoilGrids 250 m | Hydrologic soil groups (audit) | WCS, per basin | CC BY 4.0 |
| GPM IMERG daily | Design rainfall | Local file | NASA open data |

Details and citations: [docs/data_sources.md](docs/data_sources.md).

## Known limitations

- FABDEM's non-commercial licence must be checked against the intended use of the results.
- The rainfall record is daily. The design hyetographs rely on an uncalibrated sub-daily
  disaggregation exponent. See [docs/methodology.md](docs/methodology.md).
- The model setup has been tested; the models have not been run yet.

## Licence

*To be confirmed.* Add a `LICENSE` file once the code licence has been agreed.

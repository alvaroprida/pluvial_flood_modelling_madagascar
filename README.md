# pluvial_flood_modelling_madagascar

Pluvial (rain-on-grid) flood modelling for Madagascar with
[SFINCS](https://sfincs.readthedocs.io) and [HydroMT-SFINCS](https://deltares.github.io/hydromt_sfincs/).
Each catchment is an independent SFINCS model. Its inputs are downloaded **on the fly**, only for
the area it covers, from public global datasets. No data is stored in this repository.

> **Status:** the full chain (inputs, setup, simulation, post-processing) is implemented and
> tested on single basins. Calibration of the design rainfall is the main open item.

## How it works

```
basin ids or polygons ──► 1. inputs ──► 2. setup ──► 3. run ──► 4. postprocess
                          fetch + clip   SFINCS model   SFINCS     flood depth map
```

You choose the basins: HydroBASINS catchments by id, or any polygons (for example, a selection of
agricultural or urban areas). For each basin, in series or in parallel:

1. **inputs**: download what intersects the basin (plus a small buffer) and write it to
   `data/basins/<basin_id>/`, with a HydroMT data catalogue and a provenance manifest.
2. **setup**: build the SFINCS model in `models/<basin_id>/` (UTM grid, subgrid topography and
   roughness, curve-number infiltration, design-storm rainfall).
3. **run**: run SFINCS in Docker (official Deltares image) or with a native executable.
4. **postprocess**: write the maximum flood depth at 25 m (`outputs/<basin_id>/hmax_rp<T>.tif`)
   and a summary with flooded area per depth class and the water balance.

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
├── outputs/             Flood depth maps and summaries, one folder per basin (not versioned)
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

The **run** step needs [Docker](https://www.docker.com/) running (Docker Desktop on a Mac). The
pinned SFINCS image (`deltares/sfincs-cpu:sfincs-v2.4.1`) is pulled on first use. It is published
for Intel/amd64 only, so on Apple Silicon it runs emulated: about 2 minutes for a 70 km² basin.
On Linux, `run.engine: executable` in `config/settings.yml` uses a native SFINCS build instead.
With several workers, set `run.threads` so the models don't compete for the same cores.

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

Options: `--steps inputs setup run postprocess` (default: all four), `--workers N` (default 1 = in series),
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
- Results have not been validated against observed flooding yet.

## Licence

*To be confirmed.* Add a `LICENSE` file once the code licence has been agreed.

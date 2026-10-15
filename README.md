# pluvial_flood_modelling_madagascar

National-scale pluvial (rain-on-grid) flood model for Madagascar, built with
[SFINCS](https://sfincs.readthedocs.io) and [HydroMT-SFINCS](https://deltares.github.io/hydromt_sfincs/).
Every model input is derived from public global datasets by reproducible code; no data is stored
in this repository.

> **Status:** input pre-processing implemented. Model set-up, simulations and post-processing to come.

## Repository structure

```
├── config/              Run settings and the HydroMT data catalogue
├── data/                Local data (not versioned) — see data/README.md
│   ├── raw/             Downloaded source datasets
│   ├── interim/         Intermediate products
│   └── processed/       Model-ready inputs + provenance.json
├── docs/                Methodology, data sources and licences
├── models/templates/    SFINCS configuration templates (model runs are not versioned)
├── notebooks/           Numbered workflow notebooks, run in order
├── outputs/             Maps, rasters and run logs (not versioned)
├── scripts/             Command-line entry points
├── src/mdg_pluvial/     Reusable Python package used by notebooks and scripts
└── tests/               Unit tests for src/
```

## Getting started

### 1. Environment

Python 3.12. Either a virtual environment:

```bash
python3.12 -m venv .venv-mdg_pluvial
source .venv-mdg_pluvial/bin/activate
pip install -r requirements.txt
python -m ipykernel install --user --name mdg_pluvial --display-name "Python (mdg_pluvial)"
```

or conda:

```bash
conda env create -f environment.yml
conda activate mdg_pluvial
```

Raster I/O goes through `rasterio` (which bundles its own GDAL); the GDAL Python bindings and
command-line tools are not required.

### 2. Data

See [data/README.md](data/README.md). Most datasets are downloaded automatically by the notebooks;
two local inputs must be provided by hand.

### 3. Workflow

| Step | Notebook | Output |
|------|----------|--------|
| 1 | [01_input_preprocessing.ipynb](notebooks/01_input_preprocessing.ipynb) | SFINCS-ready topography, land cover, curve numbers, soils, rainfall; data catalogue; provenance |
| 2 | `02_model_setup.ipynb` *(to do)* | SFINCS models per catchment |
| 3 | `03_results_analysis.ipynb` *(to do)* | Flood depth / extent maps |

Run the notebooks with the `mdg_pluvial` kernel.

## Data sources

| Dataset | Use | Licence |
|---------|-----|---------|
| HydroBASINS (level 7) | Pluvial catchments | HydroSHEDS licence |
| FABDEM 30 m | Topography | **CC BY-NC-SA 4.0 (non-commercial)** |
| Copernicus Global Land Cover (LC100) | Land use / roughness | CC BY 4.0 |
| GCN250 | Curve numbers | CC BY 4.0 |
| SoilGrids 250 m | Hydrologic soil groups | CC BY 4.0 |
| GPM IMERG | Rainfall | NASA open data |
| IBTrACS v04 | Tropical cyclone events | NOAA open data |

Details, access methods and caveats: [docs/data_sources.md](docs/data_sources.md).

## Known limitations

- FABDEM's non-commercial licence must be checked against the intended use of the results.
- The rainfall record is daily; design hyetographs rely on an uncalibrated sub-hourly
  disaggregation. See [docs/methodology.md](docs/methodology.md).

## Licence

*To be confirmed.* Add a `LICENSE` file once the code licence has been agreed.

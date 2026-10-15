# Data

Nothing in this folder is versioned except this file. Everything can be rebuilt from the sources below.

## Layout

| Folder | Content |
|--------|---------|
| `raw/` | Source datasets as downloaded (FABDEM tiles, GCN250 rasters, …) |
| `interim/` | Intermediate products |
| `processed/` | SFINCS-ready inputs, `sfincs_data_catalog.yml`, `provenance.json` |

> **Note:** `01_input_preprocessing.ipynb` currently resolves its data folder by walking up from
> the notebook until it finds a directory holding both `Data/` and `Scripts/`, or from the
> `MDG_EXEC_DIR` environment variable. It will be pointed at this folder when its code moves to
> `src/mdg_pluvial/`.

## Local inputs (provide by hand)

| File | Description |
|------|-------------|
| `hybas_af_lev07_v1c_mdg.geojson` | HydroBASINS Africa level 7, clipped to Madagascar |
| `gpm_daily_precipitation_pp.nc` | GPM IMERG daily precipitation cube over Madagascar |

## Downloaded automatically

| Dataset | Access route | Notes |
|---------|--------------|-------|
| FABDEM 30 m | HTTP range requests into 10°×10° ZIP archives | Only the needed 1° tiles are pulled (~1.4 GB) |
| Copernicus LC100 | Cloud-optimised GeoTIFF on Zenodo via `/vsicurl` | Needs `GDAL_HTTP_USERAGENT` set |
| GCN250 | figshare download | Download URLs expire within seconds, so the file is fetched once and then read locally |
| SoilGrids 250 m | WCS, subset and reprojected server-side | Returned in EPSG:4326 |
| IBTrACS v04 (South Indian) | Direct NetCDF from NOAA NCEI | ~7 MB |

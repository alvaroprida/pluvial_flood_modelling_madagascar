# Data

Nothing in this folder is versioned except this file. Everything except the two local inputs is
downloaded by `scripts/build_models.py`.

## Layout

| Folder | Content |
|--------|---------|
| `raw/` | The two local inputs (below) |
| `cache/` | Downloads shared by all basins: FABDEM 1-degree tiles, global GCN250 grids, the land-cover look-up table |
| `basins/<basin_id>/` | One basin's inputs, `data_catalog.yml`, `provenance.json` and `pipeline.log` |

The cache only grows with the areas you model. As a guide, a FABDEM 1° tile is 8–30 MB (less
on the coast) and a small basin needs one to four of them. The global GCN250 grid is ~640 MB per
antecedent runoff condition, downloaded once.

## Local inputs (provide by hand)

| File | Description |
|------|-------------|
| `raw/hybas_af_lev07_v1c_mdg.geojson` | HydroBASINS v1c, Africa level 7, clipped to Madagascar ([hydrosheds.org](https://www.hydrosheds.org/products/hydrobasins)) |
| `raw/gpm_daily_precipitation_pp.nc` | GPM IMERG Final Run daily precipitation (mm/day, 0.1°), 1998-01-01 to 2024-09-30, over 42.4–50.8 °E / 26.0–11.1 °S. Variable `precip`, dimensions `time`, `latitude`, `longitude`. *To document: how it was downloaded and pre-aggregated, and where colleagues can get a copy.* |

The GPM cube is 183 MB, above GitHub's 100 MB file limit, so it can never be committed.

If the files live elsewhere, change `local_inputs` in `config/settings.yml` or set environment
variables instead of copying them:

```bash
export MDG_HYDROBASINS=/path/to/hybas_af_lev07_v1c_mdg.geojson
export MDG_GPM_DAILY=/path/to/gpm_daily_precipitation_pp.nc
```

`MDG_DATA_DIR`, `MDG_CACHE_DIR`, `MDG_BASINS_DIR` and `MDG_MODELS_DIR` move the other folders the
same way. Pointing `MDG_CACHE_DIR` at a folder that already holds FABDEM tiles or GCN250 grids
reuses them: file names match the originals.

## Downloaded per basin

| Dataset | Access route | Notes |
|---------|--------------|-------|
| FABDEM 30 m | HTTP range requests into the 10°×10° ZIP archives | Only the 1° tiles that intersect the basin; cached and shared |
| Copernicus LC100 | Windowed read of the global COG on Zenodo via `/vsicurl` | Needs `GDAL_HTTP_USERAGENT` set (done by the code) |
| GCN250 | figshare | Download links expire within seconds, so the global file is fetched once and windowed locally |
| SoilGrids 250 m | WCS, subset and reprojected server-side | 10 requests per basin |

Parallel workers share the cache safely: each download is written to a temporary file under a
file lock, and other workers wait for it rather than downloading it again.

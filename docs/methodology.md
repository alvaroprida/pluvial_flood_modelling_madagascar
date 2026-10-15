# Methodology

## Modelling approach

Rain-on-grid pluvial flood modelling with SFINCS. Each basin is an independent model, which
lets the work be restricted to areas of interest and run in parallel. A basin is either a
HydroBASINS level 7 catchment, split into single parts and kept if at least 50 km², or any
user-supplied polygon.

## Inputs per basin

Every input is clipped to the basin's bounding box plus a buffer (`domain.buffer_deg`, 0.02° by
default) and kept on its native grid in EPSG:4326. Reprojection happens at model setup, when the
target grid is known.

- **Topography:** FABDEM V1-2, 1 arcsec (~30 m), EGM2008. No datum shift: pluvial modelling only
  needs relative elevations within a catchment.
- **Roughness:** Manning's n from Copernicus LC100 land cover via the Deltares look-up table.
- **Infiltration:** SCS curve number from GCN250, antecedent runoff condition II by default.
  ARC III (wet) is the natural sensitivity test for cyclones arriving on saturated soils.
- **Soils (audit only):** USDA texture and Hydrologic Soil Group from SoilGrids sand and clay,
  depth-weighted over 0–100 cm. SoilGrids has no data over built-up areas and water, so this
  layer has gaps in towns.

## Design rainfall

1. Seasonal maxima of daily GPM rainfall per cell. Seasons start on 1 July, so a cyclone season
   is never split, and the two partial seasons are dropped.
2. Gumbel (EV1) fit by the method of moments, giving the 24-hour depth per return period and cell.
3. Reduction to one basin depth: the median over the GPM cells that intersect the basin.
4. Depth-duration law P(t) = P(24 h) · (t/24)^n with n = 1/3, then the Alternating Block
   Method in 30-minute blocks.

## Model setup

- UTM grid (zone chosen per basin by HydroMT), 50 m cells.
- Subgrid tables with 2 pixels per cell (25 m), close to FABDEM's resolution. HydroMT requires
  an even number of pixels.
- Active cells: those inside the basin polygon and above `model.min_active_elevation` (0.01 m).
  FABDEM sets the sea to exactly 0 m, so a polygon drawn over the coast does not model the sea
  as land. The basin edge (including the coastline) is an outflow boundary. Since an inland
  edge is mostly a drainage divide, water leaves in practice through the outlet.
- Forcing: the design hyetograph for `model.design_return_period` (100 years by default), applied
  uniformly over the basin, followed by `model.drain_time_h` hours without rain.

## Simulation

SFINCS v2.4.1 (Deltares Docker image, pinned). The rainfall series carries zeros to the end of
the run: SFINCS does not treat the end of the precipitation file as "no rain", and without the
zeros the drain period is undefined. Maxima and cumulative rainfall/infiltration are written once,
over the whole run (`dtmaxout` = run length).

## Post-processing

- The maximum water level of each 50 m cell is projected onto the 25 m subgrid DEM
  (`hydromt_sfincs.utils.downscale_floodmap`), giving `hmax_rp<T>.tif` (north-up, model UTM CRS).
- Depths below `postprocess.hmin` (0.10 m) are not counted as flooded.
- `flood_summary_rp<T>.json` reports flooded area per depth class, depth statistics, flooded
  volume, and the water balance (basin-mean rainfall, infiltration, runoff coefficient). The
  rainfall total equals the design depth, which is a check that the forcing was applied in full.

## Assumptions and limitations

- **The depth-duration exponent n is uncalibrated.** It sets the peak intensity, and so the
  modelled flood depth. Calibrate it on IMERG half-hourly data or sub-daily gauges before the
  results are used for anything but ranking.
- The Gumbel fit assumes stationarity over 1998–2024. With 26 seasons, 100-year depths are
  indicative.
- The alternating block shape assumes a single central peak. Multi-band cyclones are better
  represented by observed events.
- Design rainfall is spatially uniform over each basin.
- GCN250 has no data on some coastal cells. HydroMT turns these into zero retention (full
  runoff), which is conservative; in a coastal test area this affected 1.7% of active cells.

## Quality control

Every basin gets QC figures (switch off with `qc_figures: false`):

- `data/basins/<id>/figures/`: one per input (topography, land cover, curve number, soil
  groups, design rainfall), each with the basin outline and the distribution inside the basin.
- `models/<id>/figures/model_overview.png`: active mask and outflow boundary, subgrid
  elevation, infiltration capacity, and the rainfall forcing over the whole run.
- `outputs/<id>/figures/flood_depth_rp<T>.png`: maximum flood depth over a hillshade, and
  flooded area per depth class with the water balance.

## Validation

*To complete.*

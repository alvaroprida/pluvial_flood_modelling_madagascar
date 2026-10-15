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
- Active cells: those inside the basin polygon. The basin edge is an outflow boundary. Since
  the edge is mostly a drainage divide, water leaves in practice through the outlet.
- Forcing: the design hyetograph for `model.design_return_period` (100 years by default), applied
  uniformly over the basin, followed by `model.drain_time_h` hours without rain.

## Assumptions and limitations

- **The depth-duration exponent n is uncalibrated.** It sets the peak intensity, and so the
  modelled flood depth. Calibrate it on IMERG half-hourly data or sub-daily gauges before the
  results are used for anything but ranking.
- The Gumbel fit assumes stationarity over 1998–2024. With 26 seasons, 100-year depths are
  indicative.
- The alternating block shape assumes a single central peak. Multi-band cyclones are better
  represented by observed events.
- Design rainfall is spatially uniform over each basin.

## Validation

*To complete.*

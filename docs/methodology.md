# Methodology

## Modelling approach

Rain-on-grid pluvial flood modelling with SFINCS, run per catchment (HydroBASINS level 7)
across Madagascar.

## Inputs

- **Topography:** FABDEM 30 m
- **Roughness:** derived from Copernicus LC100 land cover
- **Infiltration:** SCS curve number (GCN250), checked against SoilGrids-derived hydrologic soil groups
- **Rainfall:** design storms from GPM IMERG daily data; historical tropical cyclone events from IBTrACS

## Grid and CRS

Inputs are kept in EPSG:4326. Reprojection to a metric CRS is done per model domain by
HydroMT-SFINCS, because Madagascar straddles UTM zones 38S and 39S.

## Assumptions and limitations

- The daily rainfall record is disaggregated to sub-hourly hyetographs using an uncalibrated exponent.
- *To complete.*

## Validation

*To complete.*

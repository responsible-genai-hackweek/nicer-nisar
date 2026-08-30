---
name: snowmelt-runoff-onset-dowy
description: Reports mean snowmelt runoff-onset day-of-water-year inside any polygon from the Gagliano et al. Sentinel-1 Zarr (Zenodo 19618062). Use when the user asks for average DOWY, snowmelt timing, runoff onset, or zonal stats for a shapefile, KML, GeoJSON, or named AOI, or mentions mean_dowy.py or global_snowmelt_runoff_onset.
---

# Snowmelt runoff-onset DOWY

This is **onset timing** (Sentinel-1 VV backscatter minimum), not SWE, snow depth, or streamflow. Product: Gagliano, Shean & Henderson, ESSD 2026, v1.1.0, water years 2015–2024. Cite [10.5281/zenodo.16953614](https://doi.org/10.5281/zenodo.16953614) and [10.5194/essd-18-5871-2026](https://doi.org/10.5194/essd-18-5871-2026).

## Do this

Run the existing helper with the user’s polygon. Do not rewrite the helper. Do not download the ~56 GB `.zarr.tar`.

```bash
pixi run python contributors/ajoros/mean_dowy.py path/to.shp   # also .kml / .geojson
pixi run python contributors/ajoros/mean_dowy.py --max-res 14  # paper quality cut
pixi run python contributors/ajoros/mean_dowy.py --self-check  # parse AOIs only, no Zenodo
```

Named aliases (`davis`, `mcs`) are optional shortcuts for polygons already wired in the script. Prefer a file path for any new AOI.

Report the printed **10-year median mean DOWY** and the annual table (mean DOWY, n valid, mean res d).

## Polygon

Clip to the analysis ring, not a search/download envelope.

- Accept `.shp`, `.kml`, or `.geojson`. Reproject to WGS84 (EPSG:4326) if needed (the helper does this).
- If several candidate polygons exist for a site, ask which one (survey box vs watershed vs lidar domain). Do not silently swap.
- Dissolve multi-part basins when the user wants one number for the combined area.
- Southern Hemisphere water year starts 1 Apr; Northern Hemisphere starts 1 Oct. The helper reports DOWY in that convention.

## How to read the table

- **mean DOWY:** day of water year. Linear mean is fine when values sit in a single melt season (typical ~80–260); do not treat it as a calendar date without converting.
- **n valid:** pixels with an onset date inside the polygon. Flag if this is a small fraction of the clip window or the year is mostly nodata.
- **mean res (d):** mean Sentinel-1 sampling interval used to pick the minimum, not retrieval uncertainty. Paper quality cut is **&lt; 14 days**. Mention or drop years coarser than that (`--max-res 14`).

## Guardrails

- Access is lazy kerchunk from `https://zenodo.org/records/19618062/files/global_snowmelt_runoff_onset.zarr.tar.refs.json`. Subset variables and bbox before `.compute()`. Zenodo rate-limits queries that touch ≳100 Zarr chunks.
- `Transformer.from_crs` (projected CRS → 4326) can return `inf` in this pixi env. The script uses `TransformerGroup`; do not change that.
- Dataset ends WY 2024. Use it as a C-band climatology or overlap baseline, not as a same-year stand-in for later NISAR retrievals unless the years actually overlap.
- Not for burn-scar mapping, glacier velocity, or SWE / ΔSWE.

## When not to use this

- Downloading OPERA RTC or NISAR granules.
- Local incidence angle (`incidence_angle`).
- Snow depth or L-band ΔSWE — different products.

# Sentinel-1 coverage — Winters Creek + Davis Creek (Davis Fire)

Metadata-only CMR search (no bulk download). Queried 2026-08-26.

## Region of interest

Source shapefiles: [aoi/gis/](aoi/gis/) (also Dropbox `IRP2026_DRI_Proposal/share/IRP_NISAR_AOI_Winters_Davis.zip`).

- **Winters Creek** + **Davis Creek** basins, Mt Rose / eastern Sierra (Eastern Lake Tahoe).
- Native shapefiles: NAD83 UTM Zone 11N (EPSG:26911). Winters 4.42 km², Davis 4.07 km², **combined 8.49 km²**.
- Use `winters_davis_aoi_wgs84.geojson` for ASF / NISAR / Python.
- **Lon/lat envelope (W,S,E,N):** `-119.88496, 39.29819, -119.82518, 39.32630`
- ASF WKT: `POLYGON((-119.88496 39.29819, -119.82518 39.29819, -119.82518 39.32630, -119.88496 39.32630, -119.88496 39.29819))`

The earlier Washoe Valley pad (`-119.92, 39.24, -119.72, 39.40`) and a Path 42 box west of these basins are **too large / offset**. Searches below use this envelope.

## Timescale of interest

Davis Fire: **2024-09-07 to 2024-09-25** (~5,800 acres, contained 2024-09-25). NISAR was not on orbit yet (launch 2025-07-30), so **pre/during/post of the burn is Sentinel-1 only**.

Windows used: pre 2024-08-01–09-06, during 09-07–09-25, post 09-26–10-31.

## Product choice

Use **OPERA L2 RTC-S1** (`OPERA_L2_RTC-S1_V1`) for a first burn-scar look: same acquisition days as S1A SLC/GRD, already radiometric + terrain corrected. Raw **SENTINEL-1A_SLC** / **SENTINEL-1A_DP_GRD_HIGH** match the same 23 days if you need SLC (coherence) later. S1B has nothing here in 2024. Skip OPERA DSWX (water) and DISP (displacement) for the scar.

## Pair dates

- **Pre (last before ignition):** **2024-09-04**
- **During:** 2024-09-09 (first after 7 Sep), also 11, 16, 21, 23 Sep
- **Post (first after containment):** **2024-09-28**

Primary pair: **4 Sep vs 28 Sep**. Optional extra: 9 Sep.

Do **not** bulk-download. Inventory first; at most two RTC granules after a separate OK.

## What is on the archive (this envelope, Aug–Oct 2024)

Same **23 distinct days** for SLC, GRD High, and OPERA RTC. RTC has extra files on some days (tiles/bursts).

| Window | S1A SLC | S1A GRD High | OPERA RTC-S1 |
| --- | ---: | ---: | ---: |
| Pre (1 Aug–6 Sep) | 12 | 12 | 15 |
| During (7–25 Sep) | 6 | 6 | 8 |
| Post (26 Sep–31 Oct) | 12 | 12 | 15 |
| Aug–Oct 2024 total | 30 | 30 | 38 |

| Date | Window | S1A SLC/GRD files | OPERA RTC files |
| --- | --- | ---: | ---: |
| 2024-08-04 | pre | 1 | 1 |
| 2024-08-06 | pre | 1 | 1 |
| 2024-08-11 | pre | 2 | 3 |
| 2024-08-16 | pre | 1 | 1 |
| 2024-08-18 | pre | 1 | 1 |
| 2024-08-23 | pre | 2 | 3 |
| 2024-08-28 | pre | 1 | 1 |
| 2024-08-30 | pre | 1 | 1 |
| **2024-09-04** | **pre (pair)** | 2 | 3 |
| **2024-09-09** | during | 1 | 1 |
| 2024-09-11 | during | 1 | 2 |
| 2024-09-16 | during | 2 | 3 |
| 2024-09-21 | during | 1 | 1 |
| 2024-09-23 | during | 1 | 1 |
| **2024-09-28** | **post (pair)** | 2 | 3 |
| 2024-10-03 | post | 1 | 1 |
| 2024-10-05 | post | 1 | 1 |
| 2024-10-10 | post | 2 | 3 |
| 2024-10-15 | post | 1 | 1 |
| 2024-10-17 | post | 1 | 1 |
| 2024-10-22 | post | 2 | 3 |
| 2024-10-27 | post | 1 | 1 |
| 2024-10-29 | post | 1 | 1 |

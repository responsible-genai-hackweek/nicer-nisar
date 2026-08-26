# README.md

Tools for downloading and processing NISAR radar data over regional survey areas (specifically Mores Creek Summit / MCS domain).

## Data Acquisition
- **MCS_domain.kml** — Area of interest polygon (Mores Creek Summit, Idaho)
- **testNISARdownload.py** — Initial test script demonstrating asf_search usage
- **nisar_downloader.py** — Reusable Python module with `download_nisar_data()` function that:
  - Parses KML AOI polygons
  - Searches for NISAR GCOV and GUNW products within a date range
  - Filters GCOV products to match GUNW acquisition endpoints
  - Reports inventory with frame/path/size/date info
  - Downloads test file for verification
- **download_MCS_NISAR.py** — Wrapper script calling `nisar_downloader()` for the MCS domain, Feb 1-25, 2026

## Incidence Angle Processing
- **incidence_angle.py** — Reusable Python module with functions to calculate local incidence angle:
  - `fetch_copernicus_dem()` — Downloads Copernicus 30 m DEM from AWS COG bucket (windowed HTTP read)
  - `calculate_local_incidence_angle()` — Computes true local incidence angle (angle between radar LOS and actual terrain surface normal) by:
    - Extracting LOS vectors from NISAR GCOV metadata cube
    - Interpolating LOS geometry to full resolution using actual DEM-derived terrain height
    - Computing surface normals from DEM via gradient
    - Calculating dot product of LOS and normal
    - Outputting georeferenced GeoTIFFs + quicklook PNG
    - Supports user-provided higher-resolution DEMs as alternative to Copernicus
- **run_incidence_angle_MCS.py** — Wrapper script applying incidence angle calculation to the MCS GCOV product

## Outputs
- **nisar_data/** — Downloaded NISAR HDF5 files
- **incidence_angle_output/** — Incidence angle results:
  - `local_incidence_angle.tif` — Local incidence angle in degrees (main product)
  - `ellipsoidal_incidence_angle.tif` — For comparison (angle to ellipsoid normal, no terrain)
  - `incidence_difference.tif` — Local − ellipsoidal difference
  - `dem_subset.tif` — DEM used for surface normal calculations
  - `quicklook.png` — Visual sanity check (hillshade + incidence angle)
#!/usr/bin/env python3
"""
Download the SnowEx20-21 QSI 0.5 m airborne lidar snow-off DEM for the MCS site.

Source: NSIDC SNEX20_QSI_DEM v1 (DOI 10.5067/YO583L7ZOLOO)
Site:   USIDMC = Mores Creek, Idaho, scanned 2021-09-17 (snow OFF, bare earth)
CRS:    EPSG:6340 (NAD83(2011) / UTM 11N), vertical datum NAVD88 (Geoid 12b)

There is exactly one granule covering our area of interest (~407 MB), so the
"test download one file first" rule is satisfied trivially: the one file IS the
whole download. We still print the size before fetching so there are no surprises.

Auth comes from ~/.netrc (machine urs.earthdata.nasa.gov), same as the NISAR
downloads in nisar_downloader.py.
"""

import os
import earthaccess

# MCS domain bounding box in lon/lat, taken from MCS_domain.kml
MCS_BBOX = (-115.7305, 43.9136, -115.6424, 43.9748)

OUTPUT_DIR = './lidar_data'

print("=" * 100)
print("Downloading SnowEx 0.5 m Lidar DEM for MCS (Mores Creek, USIDMC)")
print("=" * 100)

# Log in using the Earthdata credentials already stored in ~/.netrc
earthaccess.login(strategy='netrc')

# Search NSIDC for DEM granules intersecting the MCS domain
results = earthaccess.search_data(
    short_name='SNEX20_QSI_DEM',
    version='1',
    bounding_box=MCS_BBOX,
)

print(f"\nFound {len(results)} granule(s) over the MCS domain:\n")

total_mb = 0.0
for granule in results:
    links = granule.data_links()
    name = links[0].split('/')[-1] if links else '(no data link)'
    size_mb = granule.size()
    total_mb += size_mb
    print(f"  {size_mb:8.1f} MB  {name}")

print(f"\nTotal download size: {total_mb:.1f} MB ({total_mb / 1024:.2f} GB)")

if not results:
    raise SystemExit("No granules found - check the bounding box or the collection name.")

# Skip the download if every expected file is already on disk. The lidar DEM is
# static (a 2021 survey), so there is never a reason to re-fetch it.
os.makedirs(OUTPUT_DIR, exist_ok=True)
expected = [g.data_links()[0].split('/')[-1] for g in results if g.data_links()]
already_here = [f for f in expected if os.path.exists(os.path.join(OUTPUT_DIR, f))]

if len(already_here) == len(expected):
    print(f"\nAll {len(expected)} file(s) already present in {OUTPUT_DIR}/ - skipping download.")
else:
    print(f"\nDownloading to {OUTPUT_DIR}/ ...")
    earthaccess.download(results, local_path=OUTPUT_DIR)

print("\nFiles in", OUTPUT_DIR)
for f in sorted(os.listdir(OUTPUT_DIR)):
    path = os.path.join(OUTPUT_DIR, f)
    print(f"  {os.path.getsize(path) / 1e6:8.1f} MB  {f}")

print("\n" + "=" * 100)
print("Download complete.")
print("=" * 100)

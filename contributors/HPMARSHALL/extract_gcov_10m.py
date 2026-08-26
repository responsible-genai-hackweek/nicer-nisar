#!/usr/bin/env python3
"""
Extract native 10m resolution GCOV data from the MCS domain.
Saves backscatter in both linear and dB scales as GeoTIFF files.
"""

import h5py
import numpy as np
import xml.etree.ElementTree as ET
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin

# Parse KML to get bounds
tree = ET.parse('./MCS_domain.kml')
root = tree.getroot()
ns = {'kml': 'http://www.opengis.net/kml/2.2'}
coords_elem = root.find('.//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', ns)
coord_pairs = coords_elem.text.strip().split()
lons, lats = [], []
for pair in coord_pairs:
    lon, lat, alt = pair.split(',')
    lons.append(float(lon))
    lats.append(float(lat))
bounds_lonlat = (min(lons), min(lats), max(lons), max(lats))

# Convert to UTM
transformer = Transformer.from_crs('EPSG:4326', 'EPSG:32611', always_xy=True)
utm_min_x, utm_min_y = transformer.transform(bounds_lonlat[0], bounds_lonlat[1])
utm_max_x, utm_max_y = transformer.transform(bounds_lonlat[2], bounds_lonlat[3])
bounds_utm = (min(utm_min_x, utm_max_x), min(utm_min_y, utm_max_y),
              max(utm_min_x, utm_max_x), max(utm_min_y, utm_max_y))

print("=" * 100)
print("Extracting GCOV 10m Resolution Data from MCS Domain")
print("=" * 100)
print(f"\nMCS domain bounds (UTM): {bounds_utm}")

gcov_file_1 = './nisar_data/NISAR_L2_PR_GCOV_012_077_A_024_4005_DHDH_A_20260207T124619_20260207T124654_P05023_N_F_J_001.h5'
gcov_file_2 = './nisar_data/NISAR_L2_PR_GCOV_013_077_A_024_4005_DHDH_A_20260219T124619_20260219T124654_P05023_N_F_J_001.h5'

for date_label, gcov_file in [('Feb 7', gcov_file_1), ('Feb 19', gcov_file_2)]:
    print(f"\n{'='*100}")
    print(f"Processing GCOV {date_label}")
    print(f"{'='*100}")

    with h5py.File(gcov_file, 'r') as f:
        x_a = f['science/LSAR/GCOV/grids/frequencyA/xCoordinates'][:]
        y_a = f['science/LSAR/GCOV/grids/frequencyA/yCoordinates'][:]
        hhhh_ds = f['science/LSAR/GCOV/grids/frequencyA/HHHH']

        # Find crop indices
        xi0 = np.searchsorted(x_a, bounds_utm[0])
        xi1 = np.searchsorted(x_a, bounds_utm[2])

        # Y is descending
        in_range = (y_a >= bounds_utm[1]) & (y_a <= bounds_utm[3])
        y_indices = np.where(in_range)[0]
        yi0 = y_indices[0]
        yi1 = y_indices[-1] + 1

        print(f"Crop indices: rows [{yi0}:{yi1}], cols [{xi0}:{xi1}]")
        print(f"Output size: {yi1-yi0} × {xi1-xi0} pixels at 10m resolution")

        # Read the cropped data
        hhhh_crop = hhhh_ds[yi0:yi1, xi0:xi1]
        print(f"Data loaded, shape: {hhhh_crop.shape}")

        # Get the actual UTM coordinates for this window
        x_crop = x_a[xi0:xi1]
        y_crop = y_a[yi0:yi1]
        # NISAR xCoordinates/yCoordinates are pixel CENTRES, but a GeoTIFF transform is
        # anchored on the outer EDGE of the first pixel - so step back half a pixel.
        # Calling from_bounds() on the centre coordinates instead makes the pixel size
        # span/(n-1) rather than span/n: 9.9856 m instead of 10.0 m here, which accumulates
        # to a full 10 m (one pixel) of georeferencing error across this 696-column tile.
        dx = float(x_a[1] - x_a[0])          # +10 m
        dy = float(y_a[1] - y_a[0])          # -10 m (y descends)
        west  = x_crop[0] - dx / 2.0
        north = y_crop[0] - dy / 2.0
        east  = west + dx * hhhh_crop.shape[1]
        south = north + dy * hhhh_crop.shape[0]

        grid_transform = from_origin(west, north, dx, abs(dy))

        print(f"Pixel size: {dx:.1f} x {abs(dy):.1f} m")
        print(f"UTM extent (pixel edges): X [{west:.1f}, {east:.1f}], Y [{south:.1f}, {north:.1f}]")

        # Save linear scale (power) GeoTIFF
        output_linear = f'./GCOV_10m_linear_{date_label.replace(" ", "_")}.tif'

        with rasterio.open(
            output_linear, 'w',
            driver='GTiff',
            height=hhhh_crop.shape[0],
            width=hhhh_crop.shape[1],
            count=1,
            dtype=rasterio.float32,
            crs='EPSG:32611',
            transform=grid_transform,
        ) as dst:
            dst.write(hhhh_crop, 1)
        print(f"✓ Saved linear scale: {output_linear}")

        # Convert to dB
        hhhh_db = 10 * np.log10(np.abs(hhhh_crop) + 1e-12)

        # Save dB scale GeoTIFF
        output_db = f'./GCOV_10m_dB_{date_label.replace(" ", "_")}.tif'

        with rasterio.open(
            output_db, 'w',
            driver='GTiff',
            height=hhhh_db.shape[0],
            width=hhhh_db.shape[1],
            count=1,
            dtype=rasterio.float32,
            crs='EPSG:32611',
            transform=grid_transform,
        ) as dst:
            dst.write(hhhh_db, 1)
        print(f"✓ Saved dB scale: {output_db}")

        print(f"\nData statistics:")
        print(f"  Linear - min: {np.nanmin(hhhh_crop):.6f}, max: {np.nanmax(hhhh_crop):.6f}")
        print(f"  dB     - min: {np.nanmin(hhhh_db):.2f}, max: {np.nanmax(hhhh_db):.2f}")

print(f"\n{'='*100}")
print("✓ Extraction complete!")
print(f"{'='*100}")

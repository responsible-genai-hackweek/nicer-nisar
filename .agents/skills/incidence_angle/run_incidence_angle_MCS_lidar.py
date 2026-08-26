#!/usr/bin/env python3
"""
Calculate local incidence angle for the MCS domain using the 10 m LIDAR DEM.

This is the lidar counterpart to run_incidence_angle_MCS.py, which uses the Copernicus
30 m DEM. Two differences that matter:

  1. dem_file points at LIDAR_DEM_10m_MCS.tif - the 0.5 m SnowEx lidar Gaussian-smoothed
     to 10 m (see smooth_lidar_to_gcov.py). Terrain normals are resolved at the same scale
     as the GCOV backscatter instead of being smeared over 30 m.

  2. match_grid snaps the output to the GCOV grid exactly, so incidence angle and
     backscatter overlay pixel-for-pixel with no further resampling.

Output goes to a separate directory so the 30 m results stay available for comparison.

NOTE: the lidar covers the rotated MCS survey box, while the GCOV grid is that box's
axis-aligned bounding box. The four corners of the output will therefore be NaN - that is
expected, not a failure. Coverage inside the MCS survey polygon itself is ~99.5%.
"""

import numpy as np

from incidence_angle import calculate_local_incidence_angle

gcov_file  = './nisar_data/NISAR_L2_PR_GCOV_012_077_A_024_4005_DHDH_A_20260207T124619_20260207T124654_P05023_N_F_J_001.h5'
kml_file   = './MCS_domain.kml'
dem_file   = './LIDAR_DEM_10m_MCS.tif'
match_grid = './GCOV_10m_dB_Feb_7.tif'
output_dir = './incidence_angle_lidar'

print("=" * 140)
print("Local Incidence Angle for MCS Domain - from 10 m LIDAR DEM")
print("=" * 140)
print()

results = calculate_local_incidence_angle(
    gcov_file=gcov_file,
    kml_file=kml_file,
    dem_file=dem_file,        # 10 m smoothed lidar, NOT the Copernicus 30 m DEM
    frequency='frequencyA',
    match_grid=match_grid,    # snap output to the GCOV grid
    output_dir=output_dir,
)

print()
print("Sanity checks:")
print(f"  Mean local incidence:       {np.nanmean(results['local_incidence']):.2f} deg")
print(f"  Mean ellipsoidal incidence: {np.nanmean(results['ellipsoidal_incidence']):.2f} deg")
print("  These should be within a few degrees of each other.")
print()
print(f"Results saved to: {output_dir}/")
print("  - local_incidence_angle.tif: main product, on the GCOV grid")
print("  - ellipsoidal_incidence_angle.tif: for comparison")
print("  - incidence_difference.tif: local - ellipsoidal")
print("  - dem_subset.tif: the lidar DEM as actually used")
print("  - quicklook.png: hillshade + incidence angle")

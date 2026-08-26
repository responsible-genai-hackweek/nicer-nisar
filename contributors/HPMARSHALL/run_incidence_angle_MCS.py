#!/usr/bin/env python3
"""
Calculate local incidence angle for NISAR GCOV data over the MCS domain.

This script computes local incidence angle (angle between radar line-of-sight and
actual terrain surface normal) by combining the NISAR GCOV product stored over
the MCS area with the Copernicus 30 m DEM.

Output includes GeoTIFFs of local/ellipsoidal incidence angles and a quicklook PNG.
"""

from incidence_angle import calculate_local_incidence_angle

# Paths to input files
gcov_file = './nisar_data/NISAR_L2_PR_GCOV_012_077_A_024_4005_DHDH_A_20260207T124619_20260207T124654_P05023_N_F_J_001.h5'
kml_file = './MCS_domain.kml'
output_dir = './incidence_angle_output'

print("=" * 140)
print("Local Incidence Angle Calculation for MCS Domain")
print("=" * 140)
print()

# Call the calculation function
# Parameters:
#   gcov_file: path to the downloaded GCOV product
#   kml_file: path to the MCS domain KML
#   dem_file: None → fetch from Copernicus AWS; or provide path to a higher-res DEM
#   buffer_m: buffer around the KML AOI (200 m default)
#   frequency: 'frequencyA' or 'frequencyB' (default 'frequencyA' — L-band)
#   output_dir: where to save results

results = calculate_local_incidence_angle(
    gcov_file=gcov_file,
    kml_file=kml_file,
    dem_file=None,  # Use Copernicus DEM from AWS. To use a local DEM, set: dem_file='path/to/dem.tif'
    buffer_m=200,
    frequency='frequencyA',
    output_dir=output_dir
)

print()
print("Sanity checks:")
print(f"  Mean local incidence: {results['local_incidence'].mean():.2f}°")
print(f"  Mean ellipsoidal incidence: {results['ellipsoidal_incidence'].mean():.2f}°")
print(f"  These should be close — if very different, check for NaN or outliers")
print()
print(f"Results saved to: {output_dir}/")
print("  - local_incidence_angle.tif: main product")
print("  - ellipsoidal_incidence_angle.tif: for comparison")
print("  - incidence_difference.tif: local - ellipsoidal")
print("  - dem_subset.tif: the DEM used for surface normals")
print("  - quicklook.png: visual sanity check (hillshade + incidence angle)")

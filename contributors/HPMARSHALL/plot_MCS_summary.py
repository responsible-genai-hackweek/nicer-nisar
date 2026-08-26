#!/usr/bin/env python3
"""
Generate a 3×2 summary figure for the MCS domain NISAR data.

Combines GCOV backscatter (both dates), GUNW wrapped/unwrapped phase, the 10 m lidar
DEM, and the local incidence angle derived from it into a single publication-ready PNG.

Terrain comes from the 0.5 m SnowEx lidar smoothed to 10 m on the GCOV grid - the
Copernicus 30 m DEM is not used anywhere in this figure.
"""

from summary_plot import create_summary_figure

# Input files
gcov_tif_1 = './GCOV_10m_dB_Feb_7.tif'
gcov_tif_2 = './GCOV_10m_dB_Feb_19.tif'
wrapped_tif = './GUNW_10m_wrapped_phase.tif'
unwrapped_tif = './GUNW_10m_unwrapped_phase.tif'
dem_file = './LIDAR_DEM_10m_MCS.tif'
lia_file = './incidence_angle_lidar/local_incidence_angle.tif'
output_png = './MCS_summary.png'

print("=" * 140)
print("Creating MCS Domain Summary Figure")
print("=" * 140)
print()

create_summary_figure(
    gcov_tif_1=gcov_tif_1,
    gcov_tif_2=gcov_tif_2,
    wrapped_tif=wrapped_tif,
    unwrapped_tif=unwrapped_tif,
    dem_file=dem_file,
    lia_file=lia_file,
    output_png=output_png,
    gcov_db_range=(-25, 5)
)

print()
print("Summary figure complete: MCS_summary.png")
print("  - Row 1: GCOV backscatter at 10m resolution (Feb 7 & 19) with shared -25 to 5 dB scale")
print("  - Row 2: GUNW wrapped & unwrapped phase, resampled to the same 10m grid")
print("  - Row 3: 10 m lidar DEM & local incidence angle derived from it")
print("  - All six panels share the identical GCOV grid (691x696, EPSG:32611)")

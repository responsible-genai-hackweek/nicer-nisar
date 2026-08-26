#!/usr/bin/env python3
"""
Create a 3x2 summary figure of NISAR GCOV, GUNW, DEM, and local incidence angle data.

Every panel reads a GeoTIFF that lives on the SAME 10 m grid (691 x 696, EPSG:32611,
defined by the GCOV product), so all six share one UTM extent and overlay pixel-for-pixel:

    GCOV       extract_gcov_10m.py
    GUNW       extract_gunw_10m.py
    lidar DEM  smooth_lidar_to_gcov.py
    incidence  run_incidence_angle_MCS_lidar.py
"""

import numpy as np
import rasterio
import matplotlib.pyplot as plt


def create_summary_figure(gcov_tif_1, gcov_tif_2, wrapped_tif, unwrapped_tif,
                          dem_file, lia_file,
                          output_png='./MCS_summary.png', gcov_db_range=(-25, 5)):
    """
    Create a 3x2 summary figure combining GCOV, GUNW, DEM, and incidence angle data.

    Layout:
      Row 1: GCOV from date 1 | GCOV from date 2 (shared colorbar)
      Row 2: GUNW wrapped phase | GUNW unwrapped phase
      Row 3: Lidar DEM | Local incidence angle

    Parameters:
    -----------
    gcov_tif_1, gcov_tif_2 : str
        Paths to the first and second GCOV 10m dB-scale GeoTIFF files
    wrapped_tif, unwrapped_tif : str
        Paths to the GUNW wrapped and unwrapped phase GeoTIFFs, cropped to the MCS
        domain and resampled to the GCOV grid by extract_gunw_10m.py
    dem_file : str
        Path to the DEM GeoTIFF (the 10 m lidar DEM, on the GCOV grid)
    lia_file : str
        Path to the local incidence angle GeoTIFF derived from that DEM
    output_png : str
        Output PNG file path (default './MCS_summary.png')
    gcov_db_range : tuple
        (vmin, vmax) in dB for GCOV colorbar (default (-25, 5))
    """

    def read(path):
        """Return (array, imshow extent) for a single-band GeoTIFF."""
        with rasterio.open(path) as src:
            data = src.read(1)
            b = src.bounds
        return data, [b.left, b.right, b.bottom, b.top]

    fig, axes = plt.subplots(3, 2, figsize=(14, 18))

    # ========================================================================
    # Row 1: GCOV from both dates (shared dB scale)
    # ========================================================================

    gcov_ims = []
    for gcov_tif, ax, date_label in [
        (gcov_tif_1, axes[0, 0], 'Feb 7'),
        (gcov_tif_2, axes[0, 1], 'Feb 19'),
    ]:
        hhhh_db, extent = read(gcov_tif)
        im = ax.imshow(hhhh_db, cmap='gray',
                       vmin=gcov_db_range[0], vmax=gcov_db_range[1],
                       origin='upper', aspect='auto', extent=extent)
        ax.set_title(f'GCOV {date_label} (10m)', fontsize=12, fontweight='bold')
        ax.set_xlabel('Easting (UTM m)')
        ax.set_ylabel('Northing (UTM m)')
        gcov_ims.append(im)

    # One colorbar shared by both GCOV panels, since they use the same dB scale.
    # Attach it to both axes (rather than placing it manually with add_axes) so matplotlib
    # steals the space from the pair - that keeps row 1 the same width as rows 2 and 3,
    # which have their own per-panel colorbars.
    cbar = plt.colorbar(gcov_ims[0], ax=[axes[0, 0], axes[0, 1]], fraction=0.046, pad=0.04)
    cbar.set_label('Backscatter (dB)', fontsize=10)

    # ========================================================================
    # Row 2: GUNW wrapped and unwrapped phase
    #
    # These come from GeoTIFFs, not straight from the GUNW HDF5. The HDF5 layers span
    # the whole ~360 x 356 km NISAR frame, of which the MCS domain is about 0.04% - so
    # plotting them directly put this row on wildly different UTM axes from rows 1 and 3.
    # extract_gunw_10m.py crops them to the MCS domain and resamples onto the GCOV grid.
    # ========================================================================

    wrapped_phase, wrapped_extent = read(wrapped_tif)
    im_wrapped = axes[1, 0].imshow(wrapped_phase, cmap='twilight', vmin=-np.pi, vmax=np.pi,
                                   origin='upper', extent=wrapped_extent, aspect='auto')
    axes[1, 0].set_title('GUNW Wrapped Phase (10m)', fontsize=12, fontweight='bold')
    axes[1, 0].set_xlabel('Easting (UTM m)')
    axes[1, 0].set_ylabel('Northing (UTM m)')
    plt.colorbar(im_wrapped, ax=axes[1, 0], label='Phase (rad)')

    unwrapped, unwrapped_extent = read(unwrapped_tif)
    # Percentile-based scaling, so a few outliers don't wash out the fringe pattern.
    valid_unw = unwrapped[np.isfinite(unwrapped)]
    p2, p98 = np.percentile(valid_unw, [2, 98]) if valid_unw.size else (-5, 5)

    im_unwrapped = axes[1, 1].imshow(unwrapped, cmap='RdBu_r', vmin=p2, vmax=p98,
                                     origin='upper', extent=unwrapped_extent, aspect='auto')
    axes[1, 1].set_title('GUNW Unwrapped Phase (10m)', fontsize=12, fontweight='bold')
    axes[1, 1].set_xlabel('Easting (UTM m)')
    axes[1, 1].set_ylabel('Northing (UTM m)')
    plt.colorbar(im_unwrapped, ax=axes[1, 1], label='Phase (rad)')

    # ========================================================================
    # Row 3: Lidar DEM and the local incidence angle derived from it
    #
    # The corners are NaN because the lidar was flown over the rotated MCS survey box
    # while this grid is that box's axis-aligned bounding box.
    # ========================================================================

    dem, dem_extent = read(dem_file)
    im_dem = axes[2, 0].imshow(dem, cmap='terrain', origin='upper',
                               extent=dem_extent, aspect='auto')
    axes[2, 0].set_title('Lidar DEM (10 m, smoothed from 0.5 m)', fontsize=12, fontweight='bold')
    axes[2, 0].set_xlabel('Easting (UTM m)')
    axes[2, 0].set_ylabel('Northing (UTM m)')
    plt.colorbar(im_dem, ax=axes[2, 0], label='Elevation (m)')

    lia, lia_extent = read(lia_file)
    im_lia = axes[2, 1].imshow(lia, cmap='RdYlBu_r', vmin=0, vmax=90, origin='upper',
                               extent=lia_extent, aspect='auto')
    axes[2, 1].set_title('Local Incidence Angle (from lidar DEM)', fontsize=12, fontweight='bold')
    axes[2, 1].set_xlabel('Easting (UTM m)')
    axes[2, 1].set_ylabel('Northing (UTM m)')
    plt.colorbar(im_lia, ax=axes[2, 1], label='Angle (deg)')

    plt.savefig(output_png, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"Summary figure saved to {output_png}")
    return output_png

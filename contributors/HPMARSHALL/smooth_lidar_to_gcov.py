#!/usr/bin/env python3
"""
Smooth the 0.5 m SnowEx lidar DEM to 10 m on a grid that exactly matches the GCOV product.

Method: low-pass FIRST at native 0.5 m resolution, THEN resample. Going straight from
0.5 m to 10 m with bilinear/nearest would alias sub-metre terrain roughness (boulders,
tree throw, road cuts) into the 10 m samples. A Gaussian pre-filter removes that energy
before it can fold back in.

  sigma = (10 m FWHM) / 2.355 / 0.5 m  ~=  8.5 pixels

The output grid is read from GCOV_10m_dB_Feb_7.tif rather than hard-coded, so the lidar
DEM stays locked to whatever grid the GCOV extraction produced.

CAVEAT - vertical datum: the lidar is NAVD88 (Geoid 12b) orthometric height. Downstream,
incidence_angle.py treats DEM values as height above ellipsoid. Geoid separation at Mores
Creek is roughly -16 m. The Copernicus DEM this replaces is EGM2008 orthometric and has
the same class of offset, so this is not a regression, and a ~16 m height offset moves the
interpolated radar line-of-sight vector negligibly. No geoid correction is applied.

CAVEAT - epoch: the lidar is bare-earth September 2021 (snow OFF); the GCOV scenes are
February 2026 (snow ON). This is the correct input for terrain geometry, but it is not
the February snow surface.
"""

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.windows import from_bounds as window_from_bounds
from scipy.ndimage import gaussian_filter

LIDAR_FILE = './lidar_data/SNEX20_QSI_DEM_0.5M_USIDMC_20210917_20210917.tif'
GCOV_REF   = './GCOV_10m_dB_Feb_7.tif'      # defines the target grid
OUTPUT_TIF = './LIDAR_DEM_10m_MCS.tif'

# The GeoTIFF ships an *unnamed* PROJCS (UTM 11N on GRS80, datum "not specified"), so
# rasterio cannot resolve a datum shift from it. The NSIDC user guide states the data are
# NAD83 / UTM zone 11N = EPSG:6340, so declare that explicitly. Without this the transform
# to EPSG:32611 is silently treated as an identity (~1 m error in Idaho - sub-pixel at
# 10 m, but there is no reason to accept it when the true CRS is documented).
LIDAR_CRS = 'EPSG:6340'

# Pad the read window so the Gaussian kernel has real data to work with at the edges of
# the target grid, instead of tapering off into nothing.
PAD_M = 100.0

print("=" * 100)
print("Smoothing 0.5 m lidar DEM to 10 m on the GCOV grid")
print("=" * 100)

# ---------------------------------------------------------------------------
# 1. Read the target grid definition from the GCOV product
# ---------------------------------------------------------------------------

with rasterio.open(GCOV_REF) as ref:
    dst_crs       = ref.crs
    dst_transform = ref.transform
    dst_shape     = ref.shape
    dst_bounds    = ref.bounds
    dst_res       = ref.res

print(f"\nTarget grid (from {GCOV_REF}):")
print(f"  CRS    : {dst_crs}")
print(f"  Shape  : {dst_shape[0]} rows x {dst_shape[1]} cols")
print(f"  Res    : {dst_res[0]:.6f} x {dst_res[1]:.6f} m")
print(f"  Bounds : {dst_bounds}")

# ---------------------------------------------------------------------------
# 2. Windowed read of the lidar - only the part covering the GCOV grid (+ pad)
# ---------------------------------------------------------------------------

with rasterio.open(LIDAR_FILE) as src:
    src_res    = src.res
    src_nodata = src.nodata

    # Where does the GCOV footprint land in the lidar's own coordinates?
    w, s, e, n = transform_bounds(dst_crs, LIDAR_CRS, *dst_bounds)
    win = window_from_bounds(w - PAD_M, s - PAD_M, e + PAD_M, n + PAD_M,
                             transform=src.transform)
    # Snap to whole pixels and clip to the file, so we never ask for data off the edge
    win = win.round_offsets().round_lengths().intersection(
        rasterio.windows.Window(0, 0, src.width, src.height))

    print(f"\nLidar source ({LIDAR_FILE}):")
    print(f"  Declared CRS : {LIDAR_CRS} (file ships an unnamed PROJCS)")
    print(f"  Full size    : {src.height} rows x {src.width} cols at "
          f"{src_res[0]} m -> {src.height * src.width / 1e6:.0f} Mpx")
    print(f"  Read window  : {int(win.height)} rows x {int(win.width)} cols "
          f"-> {win.height * win.width / 1e6:.0f} Mpx "
          f"({win.height * win.width * 4 / 1e9:.2f} GB as float32)")

    win_transform = src.window_transform(win)
    win_h, win_w = int(win.height), int(win.width)

    # ---------------------------------------------------------------------------
    # 3. NaN-aware Gaussian low-pass at native 0.5 m, streamed in row-blocks
    # ---------------------------------------------------------------------------

    # sigma chosen so the low-pass FWHM matches the 10 m target pixel size
    sigma_m  = dst_res[0] / 2.355
    sigma_px = sigma_m / src_res[0]
    print(f"\nGaussian sigma: {sigma_m:.3f} m = {sigma_px:.2f} px at {src_res[0]} m "
          f"(FWHM = {dst_res[0]:.2f} m)")

    # The full 0.5 m window is ~0.8 GB, and gaussian_filter needs several temporaries of
    # that size at once - enough to get the process OOM-killed. Instead, filter one
    # horizontal stripe at a time. The Gaussian has finite support (scipy truncates at
    # 4 sigma), so each stripe is read with a halo of that radius above and below and the
    # halo is discarded afterwards; the result is identical to filtering the whole array.
    halo = int(np.ceil(4.0 * sigma_px)) + 2
    block_rows = 2000

    smoothed = np.full((win_h, win_w), np.nan, dtype=np.float32)
    n_valid_total = 0

    for r0 in range(0, win_h, block_rows):
        r1 = min(r0 + block_rows, win_h)

        # Extend by the halo, clipped to the window
        h0 = max(0, r0 - halo)
        h1 = min(win_h, r1 + halo)

        stripe_win = rasterio.windows.Window(win.col_off, win.row_off + h0, win_w, h1 - h0)
        dem = src.read(1, window=stripe_win).astype(np.float32)

        # A plain gaussian_filter would smear the nodata sentinel (-3.4e38) across hundreds
        # of metres of valid terrain. Normalised convolution instead: blur the data with
        # holes zeroed, blur the validity mask, and divide. Each output pixel is then the
        # weighted mean of only the valid neighbours that actually contributed.
        valid = np.isfinite(dem)
        if src_nodata is not None:
            valid &= (dem != src_nodata)
        # Guard against any other absurd sentinel values that are not the declared nodata
        valid &= (dem > -1e4) & (dem < 1e5)

        # Only count the interior rows so halo overlap is not double-counted
        n_valid_total += int(valid[r0 - h0:r1 - h0].sum())

        numerator   = gaussian_filter(np.where(valid, dem, 0.0).astype(np.float32), sigma_px)
        denominator = gaussian_filter(valid.astype(np.float32), sigma_px)

        # Require at least half the kernel weight to come from real data, else nodata
        stripe = np.where(denominator > 0.5,
                          numerator / np.maximum(denominator, 1e-6),
                          np.nan).astype(np.float32)

        smoothed[r0:r1] = stripe[r0 - h0:r1 - h0]

        del dem, valid, numerator, denominator, stripe

    print(f"Valid lidar pixels in window: "
          f"{n_valid_total / (win_h * win_w) * 100:.2f}% "
          f"({n_valid_total:,} of {win_h * win_w:,})")

# ---------------------------------------------------------------------------
# 4. Reproject onto the exact GCOV grid (this is where the datum shift happens)
# ---------------------------------------------------------------------------

print(f"\nReprojecting {LIDAR_CRS} -> {dst_crs} onto the GCOV grid...")

dst = np.full(dst_shape, np.nan, dtype=np.float32)
reproject(
    source=smoothed,
    destination=dst,
    src_transform=win_transform,
    src_crs=LIDAR_CRS,
    src_nodata=np.nan,
    dst_transform=dst_transform,
    dst_crs=dst_crs,
    dst_nodata=np.nan,
    resampling=Resampling.bilinear,
)

# ---------------------------------------------------------------------------
# 5. Write the 10 m DEM and report sanity statistics
# ---------------------------------------------------------------------------

with rasterio.open(
    OUTPUT_TIF, 'w',
    driver='GTiff',
    height=dst_shape[0],
    width=dst_shape[1],
    count=1,
    dtype=rasterio.float32,
    crs=dst_crs,
    transform=dst_transform,
    nodata=np.nan,
) as out:
    out.write(dst, 1)
    out.update_tags(1, description='Lidar DEM, 0.5 m SNEX20_QSI_DEM Gaussian-smoothed '
                                   'to 10 m FWHM and resampled onto the NISAR GCOV grid. '
                                   'Vertical datum NAVD88 (Geoid 12b).')

finite = np.isfinite(dst)
print(f"\nWrote {OUTPUT_TIF}")
print(f"  Shape        : {dst.shape[0]} x {dst.shape[1]}")
print(f"  Valid pixels : {finite.sum() / dst.size * 100:.2f}%")
print(f"  Elevation    : min {np.nanmin(dst):.1f} m, max {np.nanmax(dst):.1f} m, "
      f"mean {np.nanmean(dst):.1f} m, std {np.nanstd(dst):.1f} m")

print("\n" + "=" * 100)
print("Done.")
print("=" * 100)

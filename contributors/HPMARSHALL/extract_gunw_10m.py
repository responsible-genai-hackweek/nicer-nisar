#!/usr/bin/env python3
"""
Crop the GUNW wrapped and unwrapped interferograms to the MCS domain and resample them
onto the 10 m GCOV grid.

WHY THIS EXISTS
---------------
The GUNW product covers the whole NISAR frame: roughly 360 km x 356 km, versus the
6.95 x 6.9 km MCS domain. Plotting the GUNW arrays straight from the HDF5 therefore put
the middle row of MCS_summary.png on completely different axes from the GCOV row - the
MCS domain is about 0.04% of the frame, an invisible speck. extract_gcov_10m.py already
cropped the GCOV side; this is the missing equivalent for GUNW.

Native grids (both EPSG:32611, same as GCOV):
    wrappedInterferogram   17784 x 18000  complex64  @ 20 m  -> 2x upsample to 10 m
    unwrappedPhase          4446 x  4500  float32    @ 80 m  -> 8x upsample to 10 m

WRAPPED PHASE IS INTERPOLATED AS A COMPLEX FIELD
------------------------------------------------
The wrapped interferogram is stored complex. Resampling np.angle() directly would average
across the +pi/-pi branch cut and produce meaningless values wherever a fringe wraps.
Instead the real and imaginary parts are resampled separately (coherent interpolation) and
the phase is taken afterwards.
"""

import h5py
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling

GUNW_FILE = './nisar_data/NISAR_L2_PR_GUNW_012_077_A_024_013_4000_SH_20260207T124619_20260207T124654_20260219T124619_20260219T124654_P05023_N_F_J_001.h5'
GCOV_REF  = './GCOV_10m_dB_Feb_7.tif'      # defines the target grid
BASE      = 'science/LSAR/GUNW/grids/frequencyA'
POL       = 'HH'

# Read a few extra source pixels beyond the target so bilinear interpolation has
# neighbours available right at the edge of the MCS domain.
MARGIN_PX = 4

print("=" * 100)
print("Cropping GUNW to the MCS domain and resampling to the 10 m GCOV grid")
print("=" * 100)

# ---------------------------------------------------------------------------
# Target grid, taken from the GCOV product
# ---------------------------------------------------------------------------

with rasterio.open(GCOV_REF) as ref:
    dst_crs       = ref.crs
    dst_transform = ref.transform
    dst_shape     = ref.shape
    dst_bounds    = ref.bounds

print(f"\nTarget grid (from {GCOV_REF}):")
print(f"  {dst_crs}, {dst_shape[0]} rows x {dst_shape[1]} cols @ "
      f"{dst_transform.a:.1f} m")
print(f"  bounds {tuple(round(v, 1) for v in dst_bounds)}")


def crop_and_resample(h5, group, dataset, label):
    """Crop one GUNW layer to the MCS domain, then resample it onto the GCOV grid."""

    path = f'{BASE}/{group}/{POL}'
    x = h5[f'{path}/xCoordinates'][:]
    y = h5[f'{path}/yCoordinates'][:]
    ds = h5[f'{path}/{dataset}']

    dx = float(x[1] - x[0])          # +20 m or +80 m
    dy = float(y[1] - y[0])          # negative: y descends

    print(f"\n{label}")
    print(f"  Native : {ds.shape[0]} x {ds.shape[1]} {ds.dtype} @ {dx:.0f} m")
    print(f"  Frame  : X {x[0]:.0f}..{x[-1]:.0f}, Y {y[-1]:.0f}..{y[0]:.0f} "
          f"({(x[-1] - x[0]) / 1000:.0f} x {abs(y[-1] - y[0]) / 1000:.0f} km)")

    # Column indices covering the target bounds. x ascends, so searchsorted works directly.
    xi0 = max(0, int(np.searchsorted(x, dst_bounds.left)) - MARGIN_PX)
    xi1 = min(len(x), int(np.searchsorted(x, dst_bounds.right)) + MARGIN_PX)

    # y DESCENDS, so searchsorted would always return 0 here - use a boolean mask instead.
    rows = np.where((y >= dst_bounds.bottom) & (y <= dst_bounds.top))[0]
    yi0 = max(0, int(rows[0]) - MARGIN_PX)
    yi1 = min(len(y), int(rows[-1]) + 1 + MARGIN_PX)

    print(f"  Crop   : rows [{yi0}:{yi1}], cols [{xi0}:{xi1}] "
          f"-> {yi1 - yi0} x {xi1 - xi0} px "
          f"({(yi1 - yi0) * (xi1 - xi0) / (ds.shape[0] * ds.shape[1]) * 100:.3f}% of the frame)")

    block = ds[yi0:yi1, xi0:xi1]

    # Pixel centres -> outer edge of the first pixel (same convention as extract_gcov_10m.py)
    src_transform = from_origin(x[xi0] - dx / 2.0, y[yi0] - dy / 2.0, dx, abs(dy))

    def resample(arr):
        """Bilinear-resample one real-valued band onto the GCOV grid."""
        out = np.full(dst_shape, np.nan, dtype=np.float32)
        reproject(
            source=np.ascontiguousarray(arr, dtype=np.float32),
            destination=out,
            src_transform=src_transform, src_crs=dst_crs, src_nodata=np.nan,
            dst_transform=dst_transform, dst_crs=dst_crs, dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
        return out

    if np.iscomplexobj(block):
        # Coherent interpolation: resample real and imaginary parts, THEN take the angle.
        # Interpolating the wrapped phase itself would break across the +pi/-pi branch cut.
        result = np.angle(resample(block.real) + 1j * resample(block.imag)).astype(np.float32)
    else:
        result = resample(block)

    return result


with h5py.File(GUNW_FILE, 'r') as h5:
    wrapped_phase = crop_and_resample(
        h5, 'wrappedInterferogram', 'wrappedInterferogram', 'Wrapped interferogram')
    unwrapped_phase = crop_and_resample(
        h5, 'unwrappedInterferogram', 'unwrappedPhase', 'Unwrapped phase')


def write(data, path, description):
    with rasterio.open(
        path, 'w', driver='GTiff',
        height=data.shape[0], width=data.shape[1], count=1,
        dtype=rasterio.float32, crs=dst_crs, transform=dst_transform, nodata=np.nan,
    ) as dst:
        dst.write(data, 1)
        dst.update_tags(1, description=description)
    finite = np.isfinite(data)
    print(f"\nWrote {path}")
    print(f"  valid {finite.mean() * 100:.2f}%   "
          f"range {np.nanmin(data):.3f} .. {np.nanmax(data):.3f} rad")


write(wrapped_phase, './GUNW_10m_wrapped_phase.tif',
      'GUNW wrapped interferometric phase (radians), coherently resampled from the '
      '20 m native grid onto the 10 m NISAR GCOV grid')
write(unwrapped_phase, './GUNW_10m_unwrapped_phase.tif',
      'GUNW unwrapped interferometric phase (radians), resampled from the 80 m native '
      'grid onto the 10 m NISAR GCOV grid')

print("\n" + "=" * 100)
print("Done.")
print("=" * 100)

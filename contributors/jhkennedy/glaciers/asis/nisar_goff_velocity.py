#!/usr/bin/env python3
"""
Glacier surface velocity from a NISAR L2 GOFF (Geocoded Pixel Offsets) granule.

GOFF stores raw speckle-tracking offsets in METERS on an 80 m geocoded grid
(UTM or polar stereographic). This converts them to east/north/magnitude
velocity in m/yr, with SNR + correlation masking.

Requires: h5py, numpy   (rasterio/matplotlib optional, for GeoTIFF/quicklook)
Usage:  python nisar_goff_velocity.py GRANULE.h5 -o velocity.tif
"""

import argparse
import datetime as dt

import h5py
import numpy as np

BASE = "/science/LSAR/GOFF"
ID = "/science/LSAR/identification"


def parse_time(raw):
    """GOFF zero-Doppler times are ISO strings, occasionally with trailing nulls."""
    s = raw.decode() if isinstance(raw, bytes) else str(raw)
    s = s.strip().strip("\x00").replace("Z", "")
    return dt.datetime.fromisoformat(s)


def read_offsets(f, pol, layer):
    g = f[f"{BASE}/grids/frequencyA/pixelOffsets/{pol}/{layer}"]
    return {
        "rg": g["slantRangeOffset"][:].astype("f8"),   # meters, slant range
        "az": g["alongTrackOffset"][:].astype("f8"),   # meters, along track
        "snr": g["snr"][:].astype("f8"),
        "corr": g["correlationSurfacePeak"][:].astype("f8"),
        "rg_var": g["slantRangeOffsetVariance"][:].astype("f8"),
        "az_var": g["alongTrackOffsetVariance"][:].astype("f8"),
        "x": g["xCoordinates"][:],
        "y": g["yCoordinates"][:],
        "epsg": int(g["projection"].attrs.get("epsg_code", 0)),
    }


def geometry_layers(f, shape):
    """
    Pull incidence angle and the LOS / along-track unit vectors from the radar
    metadata cube and resample to the offset grid.

    The cube is (height, length, width) over a coarse x/y grid at several
    heights. We take the mid-height slice -- for velocity work the height
    dependence of viewing geometry is negligible over a glacier's relief.
    """
    rg = f[f"{BASE}/metadata/radarGrid"]
    k = rg["incidenceAngle"].shape[0] // 2

    cube_x, cube_y = rg["xCoordinates"][:], rg["yCoordinates"][:]
    out = {}
    for name in ("incidenceAngle", "losUnitVectorX", "losUnitVectorY",
                 "alongTrackUnitVectorX", "alongTrackUnitVectorY"):
        out[name] = rg[name][k, :, :].astype("f8")
    return out, cube_x, cube_y


def regrid(src, src_x, src_y, dst_x, dst_y):
    """Nearest-neighbour resample of a coarse metadata plane onto the offset grid."""
    ix = np.clip(np.searchsorted(src_x, dst_x), 0, len(src_x) - 1)
    # y descends in these grids, so search on the reversed axis
    yr = src_y[::-1]
    iy = np.clip(np.searchsorted(yr, dst_y), 0, len(yr) - 1)
    iy = len(src_y) - 1 - iy
    return src[np.ix_(iy, ix)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("granule")
    p.add_argument("--pol", default="HH")
    p.add_argument("--layer", default="layer2",
                   help="layer1=finest/noisiest, layer3=coarsest/smoothest")
    p.add_argument("--min-snr", type=float, default=5.0)
    p.add_argument("--min-corr", type=float, default=0.05)
    p.add_argument("--max-speed", type=float, default=10000.0,
                   help="m/yr; reject blunders above this")
    p.add_argument("-o", "--out", help="write GeoTIFF (needs rasterio)")
    p.add_argument("--plot", help="write a quicklook PNG (needs matplotlib)")
    args = p.parse_args()

    with h5py.File(args.granule, "r") as f:
        t_ref = parse_time(f[f"{ID}/referenceZeroDopplerStartTime"][()])
        t_sec = parse_time(f[f"{ID}/secondaryZeroDopplerStartTime"][()])
        dt_days = (t_sec - t_ref).total_seconds() / 86400.0

        d = read_offsets(f, args.pol, args.layer)
        geom, cx, cy = geometry_layers(f, d["rg"].shape)

    print(f"pair: {t_ref:%Y-%m-%d} -> {t_sec:%Y-%m-%d}  ({dt_days:.2f} days)")
    print(f"grid: {d['rg'].shape}  EPSG:{d['epsg']}  layer={args.layer} pol={args.pol}")

    if abs(dt_days) < 1e-6:
        raise SystemExit("zero temporal baseline -- cannot form velocity")

    inc = np.deg2rad(regrid(geom["incidenceAngle"], cx, cy, d["x"], d["y"]))
    los_e = regrid(geom["losUnitVectorX"], cx, cy, d["x"], d["y"])
    los_n = regrid(geom["losUnitVectorY"], cx, cy, d["x"], d["y"])
    az_e = regrid(geom["alongTrackUnitVectorX"], cx, cy, d["x"], d["y"])
    az_n = regrid(geom["alongTrackUnitVectorY"], cx, cy, d["x"], d["y"])

    # --- slant range -> ground range -------------------------------------
    # Offsets are in metres of SLANT range. Under the standard assumption of
    # horizontal flow (no vertical motion), project onto the ground:
    with np.errstate(invalid="ignore", divide="ignore"):
        gr = d["rg"] / np.sin(inc)

    # Horizontal ground-range look direction = normalised horizontal part of LOS.
    # losUnitVector points FROM TARGET TO SENSOR, so a positive (increasing)
    # slant-range offset means motion AWAY from the sensor -> negate.
    h = np.hypot(los_e, los_n)
    with np.errstate(invalid="ignore", divide="ignore"):
        ge, gn = los_e / h, los_n / h

    # Solve the 2x2 system per pixel:
    #   -gr = dE*ge  + dN*gn      (ground-range projection)
    #    az = dE*azE + dN*azN     (along-track projection)
    # NOTE: do NOT just project with the transpose -- the ground-range and
    # along-track basis vectors are close to, but not exactly, orthogonal, and
    # the transpose shortcut biases speeds by several percent.
    det = ge * az_n - gn * az_e
    with np.errstate(invalid="ignore", divide="ignore"):
        dE = (-gr * az_n - d["az"] * gn) / det
        dN = (d["az"] * ge + gr * az_e) / det

    # Near-parallel look directions make the inversion ill-posed.
    ill = np.abs(det) < 0.15
    if ill.any():
        print(f"warning: {ill.mean():.1%} of pixels have near-parallel "
              f"range/azimuth geometry (|det|<0.15); masking them")
        dE[ill] = np.nan
        dN[ill] = np.nan

    # --- displacement -> velocity ----------------------------------------
    scale = 365.25 / dt_days
    vE, vN = dE * scale, dN * scale
    speed = np.hypot(vE, vN)

    # --- masking ----------------------------------------------------------
    good = (
        np.isfinite(speed)
        & (d["snr"] >= args.min_snr)
        & (d["corr"] >= args.min_corr)
        & (speed <= args.max_speed)
    )
    for a in (vE, vN, speed):
        a[~good] = np.nan

    frac = good.mean()
    print(f"valid pixels: {good.sum():,} / {good.size:,} ({frac:.1%})")
    if good.any():
        q = np.nanpercentile(speed, [50, 90, 99])
        print(f"speed m/yr -- median {q[0]:.1f}  p90 {q[1]:.1f}  p99 {q[2]:.1f}  "
              f"max {np.nanmax(speed):.1f}")
        # 1-sigma offset precision propagated to a velocity precision
        sig = np.sqrt(np.nanmedian(d["rg_var"][good]) + np.nanmedian(d["az_var"][good]))
        print(f"typical velocity precision: ~{sig * scale:.1f} m/yr")

    if args.out:
        import rasterio
        from rasterio.transform import from_origin
        px = float(abs(d["x"][1] - d["x"][0]))
        py = float(abs(d["y"][1] - d["y"][0]))
        tr = from_origin(d["x"][0] - px / 2, d["y"][0] + py / 2, px, py)
        with rasterio.open(
            args.out, "w", driver="GTiff",
            height=speed.shape[0], width=speed.shape[1], count=3,
            dtype="float32", crs=f"EPSG:{d['epsg']}", transform=tr,
            nodata=np.nan, compress="deflate",
        ) as ds:
            for i, (band, name) in enumerate(
                [(vE, "vE_m_per_yr"), (vN, "vN_m_per_yr"), (speed, "speed_m_per_yr")], 1
            ):
                ds.write(band.astype("float32"), i)
                ds.set_band_description(i, name)
        print(f"wrote {args.out}")

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        vmax = np.nanpercentile(speed, 98) if good.any() else 1
        plt.figure(figsize=(9, 8))
        plt.imshow(speed, cmap="magma", vmin=0, vmax=vmax,
                   extent=[d["x"][0], d["x"][-1], d["y"][-1], d["y"][0]])
        plt.colorbar(label="surface speed (m/yr)")
        plt.title(f"{t_ref:%Y-%m-%d} to {t_sec:%Y-%m-%d}  ({dt_days:.0f} d)")
        plt.tight_layout()
        plt.savefig(args.plot, dpi=140)
        print(f"wrote {args.plot}")


if __name__ == "__main__":
    main()

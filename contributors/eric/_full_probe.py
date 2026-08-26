import shutil, sys, time, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import xarray as xr
import virtualizarr as vz
from virtualizarr.parsers import HDFParser

import nisar_virtual as nv

warnings.filterwarnings("ignore", category=UserWarning)
BBOX = (-121.932, 46.754, -121.5707, 46.964)
REPO = Path("/tmp/nisar_icechunk")

def main():
    track = nv.find_track(BBOX)
    key, items = next(iter(track.items()))
    print(f"track {key}: {len(items)} granules "
          f"{items[0][0][:8]} -> {items[-1][0][:8]}")

    registry = nv.obstore_registry()
    parser = HDFParser(group=nv.GCOV_GRIDS)

    # --- build all manifests ---------------------------------------------
    t0 = time.perf_counter()
    vdss = [vz.open_virtual_dataset(u, registry=registry, parser=parser)
            for _, u in items]
    t_build = time.perf_counter() - t0
    print(f"\nmanifest build: {t_build:.1f}s for {len(vdss)} granules "
          f"({t_build/len(vdss):.2f}s each)")

    # Same track+frame does NOT guarantee the same output grid: group by the
    # actual grid signature, which the virtual coords give us for free.
    from collections import defaultdict
    by_grid = defaultdict(list)
    for (start, url), v in zip(items, vdss):
        sig = (v.sizes["yCoordinates"], v.sizes["xCoordinates"],
               float(v.xCoordinates[0]), float(v.yCoordinates[0]))
        by_grid[sig].append((start, url, v))
    print(f"\n{len(by_grid)} distinct grids on this track:")
    for sig, members in sorted(by_grid.items(), key=lambda kv: -len(kv[1])):
        print(f"  n={len(members):2d}  {sig[0]}x{sig[1]}  origin=({sig[2]:.0f}, {sig[3]:.0f})")
    sig, members = max(by_grid.items(), key=lambda kv: len(kv[1]))
    items = [(s, u) for s, u, _ in members]
    vdss = [v for _, _, v in members]
    print(f"-> concatenating the {len(vdss)} granules on the dominant grid")

    times = pd.to_datetime([s for s, _ in items], format="%Y%m%dT%H%M%S")
    t0 = time.perf_counter()
    cube = xr.concat(vdss, dim="time", coords="minimal",
                     compat="override", join="exact")
    cube = cube.assign_coords(time=("time", times))
    print(f"concat: {time.perf_counter() - t0:.1f}s")
    print(cube)
    nrefs = sum(len(cube[n].data.manifest) for n in cube.data_vars
                if hasattr(cube[n].data, "manifest"))
    print(f"\ntotal chunk references: {nrefs:,}")
    print(f"logical size: {cube.nbytes / 1e12:.2f} TB")

    # --- persist to icechunk ---------------------------------------------
    import icechunk
    if REPO.exists():
        shutil.rmtree(REPO)
    prefix = f"s3://{nv.BUCKET}/"
    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(prefix, icechunk.s3_store(region=nv.REGION))
    )
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(REPO)),
        config=cfg,
        authorize_virtual_chunk_access={
            prefix: icechunk.Credentials.S3(
                icechunk.s3_refreshable_credentials(nv.icechunk_credentials)
            )
        },
    )
    t0 = time.perf_counter()
    session = repo.writable_session("main")
    cube.vz.to_icechunk(session.store)
    snap = session.commit(f"NISAR GCOV virtual cube, track {key}")
    t_write = time.perf_counter() - t0
    size = sum(f.stat().st_size for f in REPO.rglob("*") if f.is_file())
    print(f"\nicechunk write: {t_write:.1f}s -> snapshot {snap[:12]}")
    print(f"icechunk store on disk: {size/1e6:.1f} MB "
          f"(vs {cube.nbytes/1e12:.2f} TB of referenced pixels)")

    # --- reopen ----------------------------------------------------------
    t0 = time.perf_counter()
    ro = repo.readonly_session("main")
    back = xr.open_zarr(ro.store, consolidated=False, zarr_format=3, chunks={})
    t_open = time.perf_counter() - t0
    print(f"\nreopen from icechunk: {t_open:.2f}s")

    # --- correctness: compare a window against the original HDF5 ---------
    print("\n### byte-exactness vs original HDF5")
    import h5py
    from obspec_utils.readers import BlockStoreReader
    ys, xs = slice(20000, 20016), slice(15000, 15016)
    for gi in (0, len(items) // 2, len(items) - 1):
        url = items[gi][1]
        store, path = registry.resolve(url)
        with h5py.File(BlockStoreReader(store, path), "r") as f:
            truth = f[f"{nv.GCOV_GRIDS}/HHHH"][ys, xs]
        got = back["HHHH"].isel(time=gi, yCoordinates=ys, xCoordinates=xs).values
        ok = np.array_equal(truth, got, equal_nan=True)
        print(f"  granule {gi:2d} ({items[gi][0][:8]}): match={ok} "
              f"mean={np.nanmean(truth):.5f}")

    # --- a real query: AOI backscatter time series ------------------------
    print("\n### Mt Rainier AOI time series through the virtual cube")
    t0 = time.perf_counter()
    aoi = back["HHHH"].sel(
        xCoordinates=slice(596000, 606000), yCoordinates=slice(5197000, 5187000)
    )
    print("  AOI shape:", aoi.shape)
    series = aoi.mean(dim=("yCoordinates", "xCoordinates")).compute()
    t_q = time.perf_counter() - t0
    print(f"  {t_q:.1f}s for {aoi.nbytes/1e6:.0f} MB across {len(items)} dates")
    for t, v in zip(series.time.values[:5], series.values[:5]):
        print(f"    {str(t)[:10]}  {v:.5f}")

    print("\nSUMMARY")
    print(f"  build {t_build:.1f}s | write {t_write:.1f}s | reopen {t_open:.2f}s "
          f"| {size/1e6:.0f} MB index | {nrefs:,} refs")

if __name__ == "__main__":
    main()

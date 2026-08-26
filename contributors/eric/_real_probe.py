"""Run VirtualiZarr's HDFParser against real NISAR GCOV granules on S3."""
import re, sys, time, warnings
from contextlib import contextmanager

import earthaccess
import numpy as np

BUCKET = "sds-n-cumulus-prod-nisar-products"
BBOX = (-121.932, 46.754, -121.5707, 46.964)  # Mt Rainier
GRIDS = "/science/LSAR/GCOV/grids/frequencyA"

@contextmanager
def timed(label):
    t = time.perf_counter()
    yield
    print(f"    [{label}: {time.perf_counter() - t:.1f}s]")

def s3_store():
    from obstore.store import S3Store
    auth = earthaccess.login(strategy="netrc")
    c = auth.get_s3_credentials(
        endpoint="https://nisar.asf.earthdatacloud.nasa.gov/s3credentials"
    )
    return S3Store(
        BUCKET,
        region="us-west-2",
        access_key_id=c["accessKeyId"],
        secret_access_key=c["secretAccessKey"],
        session_token=c["sessionToken"],
    )

def pick_urls(n=3):
    res = earthaccess.search_data(
        short_name="NISAR_L2_GCOV_PROVISIONAL_V1", bounding_box=BBOX, count=200
    )
    rx = re.compile(r"GCOV_\d+_\d+_D_065_4005_DHDH_A_(\d{8}T\d{6})_")
    out = []
    for g in res:
        for u in g.data_links(access="direct"):
            if u.endswith(".h5") and (m := rx.search(u)):
                out.append((m.group(1), u))
    out.sort()
    return [u for _, u in out[:n]]

def main():
    urls = pick_urls(3)
    print(f"track D/065 frame 4005, {len(urls)} granules:")
    for u in urls:
        print("   ", u.rsplit("/", 1)[-1])

    store = s3_store()
    from obspec_utils.registry import ObjectStoreRegistry
    import virtualizarr as vz
    from virtualizarr.parsers import HDFParser

    registry = ObjectStoreRegistry({f"s3://{BUCKET}": store})

    # --- 1. baseline: how long does xarray/h5netcdf take to open one? -----
    print("\n### 1. baseline metadata open (h5netcdf over s3fs)")
    try:
        import xarray as xr, s3fs
        auth = earthaccess.login(strategy="netrc")
        c = auth.get_s3_credentials(
            endpoint="https://nisar.asf.earthdatacloud.nasa.gov/s3credentials")
        fs = s3fs.S3FileSystem(key=c["accessKeyId"], secret=c["secretAccessKey"],
                               token=c["sessionToken"])
        with timed("h5netcdf open"):
            ds = xr.open_dataset(fs.open(urls[0].replace("s3://", ""), "rb"),
                                 engine="h5netcdf", group=GRIDS, phony_dims="access")
        print("    vars:", list(ds.data_vars)[:8])
    except Exception as e:
        print(f"    {type(e).__name__}: {e}")

    # --- 2. scoped virtual open -------------------------------------------
    print(f"\n### 2. HDFParser(group={GRIDS!r}) on granule 0")
    parser = HDFParser(group=GRIDS)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        with timed("manifest build"):
            vds = vz.open_virtual_dataset(urls[0], registry=registry, parser=parser)
        for x in {str(i.message)[:160] for i in w}:
            print("    WARN:", x)
    print(vds)
    for name in list(vds.data_vars):
        v = vds[name].data
        if not hasattr(v, "manifest"):
            continue
        print(f"\n  {name}: shape={v.shape} chunks={v.metadata.chunks} "
              f"dtype={v.metadata.data_type}")
        print(f"    codecs={v.metadata.codecs}")
        print(f"    chunkgrid={v.manifest.shape_chunk_grid} n={len(v.manifest)} "
              f"refbytes={v.manifest.nbytes / 1e6:.1f} MB")

    # --- 3. root-level parse (expected to fail) ---------------------------
    print("\n### 3. HDFParser() at file root (no group scoping)")
    try:
        vz.open_virtual_datatree(urls[0], registry=registry, parser=HDFParser())
        print("    OK (unexpected!)")
    except Exception as e:
        print(f"    {type(e).__name__}: {str(e)[:300]}")

    # --- 4. the go/no-go: concat across the track -------------------------
    print(f"\n### 4. concat {len(urls)} granules along time")
    import xarray as xr
    vdss = [vds]
    with timed(f"parse remaining {len(urls)-1}"):
        for u in urls[1:]:
            vdss.append(vz.open_virtual_dataset(u, registry=registry, parser=parser))
    try:
        combined = xr.concat(vdss, dim="time", coords="minimal",
                             compat="override", join="exact")
        print(combined)
        for n in ("HHHH", "HVHV"):
            if n in combined:
                print(f"  {n} chunkgrid:", combined[n].data.manifest.shape_chunk_grid)
    except Exception as e:
        print(f"    CONCAT FAILED {type(e).__name__}: {str(e)[:500]}")
        import traceback; traceback.print_exc()
        return

    print("\n### 5. total virtual refs")
    tot = sum(len(combined[n].data.manifest) for n in combined.data_vars
              if hasattr(combined[n].data, "manifest"))
    print(f"    {tot} chunk references across {len(combined.data_vars)} variables")

if __name__ == "__main__":
    main()

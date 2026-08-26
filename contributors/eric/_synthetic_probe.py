"""Probe VirtualiZarr's HDF parser against a NISAR-GCOV-shaped synthetic file.

Mirrors the real product layout: /science/LSAR/GCOV/grids/frequency{A,B} with
dimension-scale coordinates and gzip+shuffle chunked float32 grids, an
/science/LSAR/identification group of strings, and a metadata group containing
the awkward HDF5 types (vlen string, vlen array, compound) that NISAR uses.
"""

import shutil
from pathlib import Path

import h5py
import numpy as np

TMP = Path("/tmp/nisar_probe")
NY, NX = 2048, 2048
CHUNKS = (128, 512)  # reported chunking for NISAR SLC-family rasters
GRIDS = "/science/LSAR/GCOV/grids/frequencyA"


def write_granule(path: Path, epsg: int = 32610, x0: float = 664_500.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    with h5py.File(path, "w") as f:
        g = f.create_group(GRIDS)

        x = x0 + 20.0 * np.arange(NX, dtype="float64")
        y = 5_182_000.0 - 20.0 * np.arange(NY, dtype="float64")
        for name, vals in (("xCoordinates", x), ("yCoordinates", y)):
            d = g.create_dataset(name, data=vals)
            d.make_scale(name)

        for name in ("HHHH", "HVHV", "mask", "numberOfLooks", "rtcGammaToSigmaFactor"):
            data = rng.random((NY, NX), dtype="float32")
            d = g.create_dataset(
                name,
                data=data,
                chunks=CHUNKS,
                compression="gzip",
                compression_opts=4,
                shuffle=True,
            )
            d.dims[0].attach_scale(g["yCoordinates"])
            d.dims[1].attach_scale(g["xCoordinates"])
            d.attrs["units"] = "1"

        proj = g.create_dataset("projection", data=np.uint32(epsg))
        proj.attrs["epsg_code"] = np.uint32(epsg)
        g.create_dataset("listOfPolarizations", data=np.array([b"HH", b"HV"], dtype="S2"))

        ident = f.create_group("/science/LSAR/identification")
        ident.create_dataset("listOfFrequencies", data=np.array([b"A"], dtype="S1"))
        ident.create_dataset("absoluteOrbitNumber", data=np.int64(5005))

        # The types that are known to give the parser trouble.
        meta = f.create_group("/science/LSAR/GCOV/metadata/awkward")
        meta.create_dataset(
            "vlenString", data=["a string of variable length"],
            dtype=h5py.string_dtype(),
        )
        meta.create_dataset(
            "vlenArray", data=[np.arange(3), np.arange(5)],
            dtype=h5py.vlen_dtype(np.int32),
        )
        meta.create_dataset(
            "compound",
            data=np.array([(1.0, 2, b"ok")], dtype=[("a", "f8"), ("b", "i4"), ("c", "S2")]),
        )


def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)

    paths = []
    for i in range(2):
        p = TMP / f"granule_{i}.h5"
        write_granule(p, seed=i)
        paths.append(p)
    print(f"wrote {len(paths)} granules, {paths[0].stat().st_size / 1e6:.0f} MB each\n")

    import virtualizarr as vz
    from obstore.store import LocalStore
    from virtualizarr.parsers import HDFParser
    from virtualizarr.registry import ObjectStoreRegistry

    registry = ObjectStoreRegistry({"file://": LocalStore()})

    # --- 1. scoped to the grids group -------------------------------------
    print("### 1. HDFParser(group=grids/frequencyA)")
    parser = HDFParser(group=GRIDS)
    vds = vz.open_virtual_dataset(paths[0].as_uri(), registry=registry, parser=parser)
    print(vds)
    ma = vds["HHHH"].data
    print("\nchunks :", ma.metadata.chunks)
    print("codecs :", ma.metadata.codecs)
    print("dtype  :", ma.metadata.data_type)
    print("nchunks:", ma.manifest.shape_chunk_grid, "->", len(ma.manifest))

    # --- 2. whole-file (does the metadata group break it?) ----------------
    print("\n### 2. HDFParser() at file root")
    try:
        root = vz.open_virtual_datatree(
            paths[0].as_uri(), registry=registry, parser=HDFParser()
        )
        print("OK:", root)
    except Exception as e:
        print(f"{type(e).__name__}: {e}")

    # --- 3. concat two granules along time --------------------------------
    print("\n### 3. concat two granules along a new time dim")
    import xarray as xr

    vdss = [
        vz.open_virtual_dataset(p.as_uri(), registry=registry, parser=parser)
        for p in paths
    ]
    try:
        combined = xr.concat(
            vdss, dim="time", coords="minimal", compat="override", join="exact"
        )
        print(combined)
        print("\nHHHH nchunks after concat:", combined["HHHH"].data.manifest.shape_chunk_grid)
    except Exception as e:
        print(f"{type(e).__name__}: {e}")
        return

    # --- 4. write to icechunk, reopen, verify bytes -----------------------
    print("\n### 4. icechunk round-trip + value check")
    import icechunk

    repo_dir = TMP / "repo"
    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(
            f"{TMP.as_uri()}/", icechunk.local_filesystem_store(str(TMP))
        )
    )
    repo = icechunk.Repository.create(
        storage=icechunk.local_filesystem_storage(str(repo_dir)),
        config=cfg,
        authorize_virtual_chunk_access={f"{TMP.as_uri()}/": None},
    )
    session = repo.writable_session("main")
    combined.vz.to_icechunk(session.store)
    session.commit("virtual NISAR-like GCOV cube")

    ro = repo.readonly_session("main")
    back = xr.open_zarr(ro.store, consolidated=False, zarr_format=3)
    print(back)

    with h5py.File(paths[1], "r") as f:
        truth = f[f"{GRIDS}/HHHH"][100:110, 200:210]
    got = back["HHHH"].isel(time=1, yCoordinates=slice(100, 110), xCoordinates=slice(200, 210)).values
    print("\nvalues match original HDF5:", np.array_equal(truth, got))


if __name__ == "__main__":
    main()

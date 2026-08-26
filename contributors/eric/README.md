# VirtualiZarr for NISAR access

Scratch space for the project idea in the top-level [`README.md`](../../README.md):

> Explore a [VirtualiZarr](https://virtualizarr.readthedocs.io/en/stable/) approach to working with NISAR data.

Everything here is exploratory. The result of the exploration is
[`test_virtualizarr.ipynb`](test_virtualizarr.ipynb) — executed end-to-end against real
`NISAR_L2_GCOV_PROVISIONAL_V1` granules, with the failures kept in.

## The idea

NISAR standard products are HDF5 files in an ASF S3 bucket, tens of GB each. To build a time
series you open every granule, and h5py walks each file's internal B-tree to find where the
chunks live. That metadata walk is the expensive part of "opening" a NISAR granule, and you pay
it again on every re-open, in every session, for every user.

VirtualiZarr offers a different deal: read each file's chunk offsets **once**, store them as a
Zarr chunk manifest, and afterwards treat the whole archive as a single Zarr array. No pixels are
copied — reads still stream byte-ranges out of the original `.h5` files in the ASF bucket. Only
the index is new, and it is small enough to commit to an [Icechunk](https://icechunk.io) repo and
share.

For this project's two target workflows — snow melt timing and glacier velocity, both of which
want a repeat-pass stack over a fixed AOI — that is exactly the shape of access we need.

## What we measured

Track D / relative orbit 065 / frame 4005 / DHDH over Mt. Rainier, 29 granules,
2025-11-10 → 2026-08-18. Run from a `us-west-2` JupyterHub, in-region.

| | Result |
|---|---|
| Virtualize one GCOV granule | 1.1 s |
| Same granule, `h5netcdf` + `s3fs` lazy open | 16 s |
| Index all 29 granules | 20 s |
| Concatenated cube (24 compatible granules) | 0.56 TB logical, 715,824 chunk references |
| Persist to Icechunk | 2.8 s → **13.4 MB** on disk |
| Re-open the persisted cube | 0.06 s |
| Pixels vs. direct `h5py` read | byte-identical |
| 1000×1000 AOI × 24 dates, mean backscatter | 3.5 s, 96 MB streamed |

The headline: **VirtualiZarr eliminates the metadata cost of opening NISAR archives, not the
pixel cost.** A 0.56 TB cube reduces to a 13.4 MB index — but every pixel you actually read still
comes over the wire from the original granule, at the original speed.

The 15× first-open speedup is not purely VirtualiZarr's doing. Part of it is that the parser
reads through `obstore`'s `BlockStoreReader` rather than `s3fs`, and part is that building a
manifest genuinely does less work than constructing an xarray dataset. The notebook says so
where it reports the number. The durable win is the 0.06 s re-open, which is a real 300×
against re-running the `h5netcdf` route.

## Where it breaks

Per `AGENTS.md`, failures are results. Four of them, all reproduced in the notebook:

**1. You cannot virtualize a whole NISAR granule.** `HDFParser()` at the file root raises
`TypeError: Object of type complex is not JSON serializable`. There are 40 `complex64`-valued
attributes under `metadata/calibrationInformation/crosstalk/`, and Zarr v3 metadata is JSON.
Scoping the parser to `/science/LSAR/GCOV/grids/frequencyA` avoids them, which means a virtual
cube carries the rasters and their coordinates but **not** NISAR's full metadata tree.
`metadata/sourceData` can be virtualized as a separate group; `identification` cannot — it has no
dimension scales, so its variables collide on `phony_dim_0`, and `drop_variables` only exposes the
next collision.

**2. One track is not one grid.** Concatenating all 29 granules fails with an `AlignmentError` on
`xCoordinates`. Auditing the coordinates shows 24 granules on a 35712 × 36144 grid at origin
(334805, 5320075) and 5 granules from 2026-06-19 onward on 35352 × 35784 at origin
(496805, 5320795) — same EPSG:32610, same relative orbit, same frame. **Group granules by their
actual coordinate arrays, not by track/frame metadata.** VirtualiZarr cannot reproject or
resample, so incompatible grids need one cube each or a genuine data-copying regrid.

**3. RSLC does not attach HDF5 dimension scales.** GCOV and GSLC attach `yCoordinates` /
`xCoordinates` to every raster; RSLC attaches nothing. The parser falls back to `phony_dim_N`,
which then collides between the 2-element `listOfPolarizations` and the 54720-row image. It can be
forced through by dropping every non-raster variable, but the result has no geolocation at all.
(An earlier guess of mine that RSLC would be blocked by a CFloat16 dtype was wrong — it stores
`complex64`, which virtualizes fine. If NISAR ships half-precision RSLC later, retest.)

**4. Credentials expire hourly.** EDL S3 tokens for the ASF bucket last an hour. A static token
silently dies partway through building or reading a large cube. Icechunk needs
`icechunk.Credentials.S3(icechunk.s3_refreshable_credentials(callable))` with a **module-level**
(picklable) callable — hence `nisar_virtual.py` rather than a notebook cell. `earthaccess` also
hands back `expiration` as a string where Icechunk wants a `datetime`.

## When it is and isn't worth it

**Worth it** for a repeat-pass stack on a fixed grid that will be queried many times, by more
than one person. Build the index once, commit it, and everyone's open is instant.

**Not worth it** for a single granule, or one AOI read once. VirtualiZarr never reduces the pixel
bytes you stream; if you want a small subset repeatedly, subsetting into a real Zarr store is
simpler and faster.

## Files

- `test_virtualizarr.ipynb` — the executed notebook. Start here.
- `nisar_virtual.py` — helpers the notebook imports: EDL login, refreshable S3 credentials for
  Icechunk, an `obstore` registry for the NISAR bucket, and a granule-grouping search.
- `_*.py` — throwaway probe scripts written while working this out. Superseded by the notebook;
  kept only because this is scratch space.

## Running it

```bash
pixi install
pixi run jupyter lab   # then open test_virtualizarr.ipynb
```

Requires Earthdata Login credentials in `~/.netrc` — NISAR provisional products are not
anonymously accessible; an unauthenticated GET bounces to the URS OAuth endpoint with a 401. **No
credentials or tokens appear in this folder**; they are fetched at runtime from `~/.netrc`.
Reads are direct-S3, so this is intended to run in `us-west-2`.

## Next

- Parallelize the manifest build with `open_virtual_mfdataset`.
- Append new acquisitions to the Icechunk repo as they are published — the transactional model
  supports it, so the index need never be rebuilt from scratch.
- Put the Icechunk repo in S3 so the index is shared across the team rather than rebuilt per user.
- Test a GSLC stack for the glacier-velocity workflow, where phase matters and RSLC's missing
  geolocation would otherwise be the blocker.

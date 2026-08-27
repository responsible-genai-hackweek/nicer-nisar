# VirtualiZarr for NISAR access

Scratch space for the project idea in the top-level [`README.md`](../../README.md):

> Explore a [VirtualiZarr](https://virtualizarr.readthedocs.io/en/stable/) approach to working with NISAR data.

Two executed notebooks:

| | |
|---|---|
| [`test_virtualizarr.ipynb`](test_virtualizarr.ipynb) | **Does it work?** Feasibility, measured against real granules, failures kept in. |
| [`cube_maintenance.ipynb`](cube_maintenance.ipynb) | **Can we run it?** Parallel build, incremental append, compaction. |

`nisar_virtual.py` holds the shared helpers both import.

---

## The idea, in one paragraph

NISAR standard products are HDF5 files in an ASF S3 bucket, tens of GB each. To build a time
series you open every granule, and h5py walks each file's internal B-tree to find where the chunks
live. That walk is what "opening" a NISAR granule actually costs, and you pay it again in every
session, for every user. VirtualiZarr reads those chunk offsets **once**, stores them as a Zarr
chunk manifest, and afterwards the whole archive behaves like a single Zarr array. No pixels are
copied — reads still stream byte ranges out of the original `.h5` files. Only the index is new,
and it is small enough to commit to an [Icechunk](https://icechunk.io) repo and share.

## The data model

This is the part worth being precise about, because most of the failures below are the data model
asserting itself.

### What is in a NISAR file

A GCOV granule is an HDF5 file with everything under `/science/LSAR/`:

```
/science/LSAR/
├── identification/                    strings and scalars: orbit, frame, track, times
├── GCOV/
│   ├── grids/frequencyA/              ← the rasters
│   │   ├── HHHH, HVHV                 float32, (35712, 36144), chunked (512, 512),
│   │   │                              shuffle + zlib level 1
│   │   ├── xCoordinates, yCoordinates float64, HDF5 *dimension scales*
│   │   ├── projection                 scalar, EPSG code in an attribute
│   │   └── mask, numberOfLooks, ...   9 more per-granule layers
│   └── metadata/
│       ├── sourceData/                geometry and processing provenance
│       └── calibrationInformation/    ← complex64 attributes live here
└── ...
```

Two structural facts do all the work:

**Chunking.** Each raster is stored as a grid of independently compressed `(512, 512)` blocks —
4,970 of them per polarization. Every block has a byte offset and a length in the file. That is
precisely what a Zarr chunk is, which is why the translation is lossless rather than approximate:
a NISAR raster *is already* a Zarr array, described in a different dialect.

**Dimension scales.** `HHHH` has `yCoordinates` and `xCoordinates` attached to its two axes as
HDF5 dimension scales. That is what lets a reader know the array is geolocated, and it is the
single thing that decides whether a product virtualizes cleanly. GCOV and GSLC attach them. RSLC
does not.

### What VirtualiZarr makes of it

`HDFParser(group=...)` walks the group once and emits a `ManifestArray` per raster: Zarr v3
metadata (shape, chunk shape, dtype, codec chain, dimension names, attributes) plus a
`ChunkManifest` — three parallel arrays of `(path, offset, length)`, one entry per chunk.

The compression ratio is the whole argument:

```
one granule   : 29,826 chunk references          (14 variables)
                 9,941 chunk references          (3 variables — see below)
24-date cube  : 715,824 references, 0.56 TB logical, 13.4 MB index
```

The manifest is ~40,000× smaller than the data it addresses, and it is the *only* thing that gets
written. Reading `cube.HHHH[5, 1000:2000, 1000:2000]` looks up the covering chunk entries, issues
range GETs against the original `.h5` objects, and decompresses. Same bytes, same speed, as if you
had opened that granule directly — because you did.

### What a "cube" is, exactly

```
xr.concat([vds_20251110, vds_20251122, ...], dim="time")
```

A cube is a stack of granules whose `xCoordinates` and `yCoordinates` are **identical arrays**.
Not similar, not overlapping — identical, because concatenation along a new axis requires every
other axis to line up exactly. VirtualiZarr records where bytes are; it has no capacity to
reproject, resample, or shift anything to make that true.

So the unit of work is: **one AOI → one track → one output grid → one Icechunk repo.** That is not
a simplification we chose; it is the largest thing the model supports.

### Icechunk's role

Icechunk stores the manifest transactionally and versioned. It matters for three reasons: 715k
references are too many for a Kerchunk JSON sidecar; the virtual chunk container carries the S3
credentials needed to resolve references at read time; and `append_dim` lets new acquisitions be
added without rewriting what is already indexed.

---

## Yes — start with GCOV, one region

To answer the question directly: **yes.** GCOV over a fixed AOI is the right starting scope, and
for reasons that come out of the measurements rather than convenience:

- **GCOV is geocoded and dimension-scaled**, so it virtualizes with no coaxing. RSLC does not, and
  cannot be given geolocation by this route at all.
- **GCOV is what the snow-melt workflow wants anyway** — terrain-corrected backscatter on a fixed
  map grid, stacked in time. The virtual cube is exactly that object.
- **The grid constraint forces a regional scope.** A cube cannot span UTM zones or frame changes,
  so "one AOI, one track" is the natural unit whether we like it or not.
- **It is where the payoff is largest.** Repeat-pass stacks are the case VirtualiZarr is good at;
  single-granule access it does nothing for.

GSLC is the natural second product — it virtualizes unchanged, keeps `complex64` phase, and is
what glacier velocity would need.

---

## What we measured

Track D / relative orbit 065 / frame 4005 / DHDH over Mt. Rainier, 28 granules,
2025-11-10 → 2026-08-18. Run in-region from a `us-west-2` JupyterHub.

| | Result |
|---|---|
| Virtualize one GCOV granule | 0.6–1.1 s |
| Same granule, `h5netcdf` + `s3fs` lazy open | 16 s |
| Index the full track, serial | 17 s |
| …dropping the 9 variables we don't need | 8.9 s, and 3× fewer references |
| …8 processes instead of 1 | 12.5 s (1.4×) |
| …8 threads instead of 1 | 15.6 s (1.1× — i.e. no) |
| Concatenated cube (23 granules on one grid) | 0.24 TB logical, 4.6 MB index |
| Re-open the persisted cube | 0.06 s |
| Append one new acquisition | 0.8–1.0 s |
| Pixels vs. direct `h5py` read | byte-identical |
| 1000×1000 AOI × 24 dates, mean backscatter | 3.5 s, 96 MB streamed |

**VirtualiZarr eliminates the metadata cost of opening NISAR archives, not the pixel cost.** Every
pixel you read still comes over the wire from the original granule at the original speed. What
disappears is the repeated cost of finding it.

The 15× first-open speedup is not purely VirtualiZarr's doing — part of it is `obstore`'s
`BlockStoreReader` rather than `s3fs`, and part is that building a manifest genuinely does less
work than constructing an xarray dataset. The notebook says so where it reports the number. The
durable win is the 0.06 s re-open.

### On parallelizing the build

Threads buy nothing, and profiling says why: `validate_and_normalize_path_to_uri` runs **once per
chunk reference** — ~30,000 times per granule — calling `urlparse` on the same S3 URL every time.
That is 26% of the build, in pure Python, holding the GIL. The actual S3 reads are 14%. So the
build is not I/O bound and threads cannot help it.

Processes give 1.4×, capped by pickling manifests back to the parent and by each worker paying for
its own Earthdata login at startup. On 28 granules the pool startup roughly cancels the gain when
combined with a lean parse; it would pay on a few hundred granules.

The better lever is `drop_variables`. `frequencyA` has 14 variables; a backscatter series needs
three. Dropping the rest halves the build and cuts the index 3×.

`open_virtual_mfdataset` is the same story with a nicer API — it does the combine for you, but the
per-granule work is identical, so it hits the same ceiling: 13.8 s serial, 11.5 s with threads
(1.2×, the GIL again), 12.8 s with dask. Its `parallel=` argument takes any `Executor`, though,
including `ProcessPoolExecutor` and **lithops** — which is the door that matters at scale, since
lithops is what Earthmover used to build a 380,000-file store (below). At 28 granules the
executor's startup dominates; at a few hundred it stops mattering, and at 380,000 it is the only
way.

## Prior art: Earthmover's GOES-16 store

[Cloud-Optimizing GOES-16 with Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr) is the
same technique at a scale that makes ours look like a unit test: 380,000 netCDF4 files, ~115 TB,
**7.1 billion chunk references**. Four things in it are worth carrying over.

**The economic argument is stronger than the speed argument.** They report ~$100 to generate the
manifests and **$1.84/month to store ~80 GB of metadata, against $2,600/month** to host a
duplicated archive. That is the case for this project, better stated than our 15× first-open
number: the point is not that virtualizing is fast, it is that the alternative — a converted copy
of the NISAR archive — is a recurring cost nobody wants to carry, and it goes stale every time ASF
publishes.

**"Archives must be homogeneous" is a general law, not our bad luck.** GOES-16 had to be split
into several Zarr groups because the encoding changed partway through the record. We hit the same
class of problem from a different direction — a grid change partway through the track (failure #2)
— and the resolution is the same: detect the discontinuity, split into separate stores, do not try
to paper over it. Expect more of these as the NISAR record lengthens and processing versions
change.

**Virtual works better for cube-like data than for swath data.** Their framing explains our RSLC
result more crisply than we did: geocoded products stack because they already live on a shared map
grid, and no amount of manifest cleverness will make a swath product do that. GCOV is
terrain-corrected onto a map grid, so it behaves like the cube-like case despite being L2.

**They still recommend native Zarr where it is feasible.** Worth repeating in our own conclusions.
Virtual Zarr is the pragmatic answer when the data must stay in its original format and copying it
is prohibitive — which is exactly NISAR's situation — not a claim that it beats a purpose-built
store.

One operational note the post raises that applies directly to us: Icechunk warns when a referenced
archival file has been modified. Our references point at specific `.h5` objects, so if ASF ever
replaces or withdraws a granule in place, the index breaks. Combined with the duplicate-version
finding below, that argues for recording the product version we indexed and re-validating
periodically.

## Where it breaks

Per `AGENTS.md`, failures are results. Five, all reproduced in the notebooks:

**1. You cannot virtualize a whole NISAR granule.** `HDFParser()` at the file root raises
`TypeError: Object of type complex is not JSON serializable` — 40 `complex64` attributes under
`metadata/calibrationInformation/crosstalk/`, and Zarr v3 metadata is JSON. Scoping to
`grids/frequencyA` avoids them, which means a virtual cube carries rasters and coordinates but
**not** NISAR's metadata tree. `metadata/sourceData` can be virtualized as a separate group;
`identification` cannot — no dimension scales, so its variables collide on `phony_dim_0`, and
`drop_variables` only exposes the next collision.

**2. One track is not one grid.** Concatenating the full track fails with `AlignmentError` on
`xCoordinates`. The audit: 23 granules on 35712 × 36144 at origin (334805, 5320075), and 5 from
2026-06-19 on 35352 × 35784 at (496805, 5320795) — same EPSG:32610, same relative orbit, same
frame. A processing-side frame change partway through the archive. **Group on the actual
coordinate arrays** (`nv.grid_signature`), never on track and frame.

**3. The archive holds duplicate product versions.** One acquisition appears as both `..._001.h5`
and `..._002.h5`. Indexing both puts the same date into the cube twice, under one timestamp,
silently — nothing about the concatenation objects. `find_track` now keeps the highest version.
This is the most dangerous of the five, because it produces a wrong answer instead of an error.

**4. RSLC does not attach dimension scales.** GCOV and GSLC attach `yCoordinates`/`xCoordinates`
to every raster; RSLC attaches nothing, so the parser falls back to `phony_dim_N` and then collides
between the 2-element `listOfPolarizations` and the 54,720-row image. Forcible by dropping every
non-raster variable, but the result has no geolocation at all. (An earlier guess of mine that RSLC
would be blocked by a CFloat16 dtype was wrong — it stores `complex64`, which virtualizes fine. If
NISAR ships half-precision RSLC later, retest.)

**5. Credentials expire hourly, and appends leak space.** EDL S3 tokens last an hour; a static
token dies partway through a large cube. Icechunk needs
`icechunk.Credentials.S3(icechunk.s3_refreshable_credentials(callable))` with a **module-level**
(picklable) callable — hence `nisar_virtual.py` rather than a notebook cell. Separately, every
append writes a new immutable manifest and keeps the old one: the repo grew 4.6 MB → 36.2 MB over
11 appends. `nv.compact()` (expire + garbage collect) returns it to 4.6 MB, at the cost of the
history.

## Files

- `test_virtualizarr.ipynb` — feasibility. Start here.
- `cube_maintenance.ipynb` — parallel build, appending, compaction.
- `nisar_virtual.py` — EDL login and refreshable S3 credentials, an `obstore` registry for the
  NISAR bucket, version-deduplicating granule search, grid grouping, parallel manifest build, and
  `append_new` / `compact` for repo maintenance.
- `_*.py` — throwaway probe scripts from working this out. Superseded by the notebooks; kept only
  because this is scratch space.

## Running it

```bash
pixi install
pixi run jupyter lab
```

Requires Earthdata Login credentials in `~/.netrc` — NISAR provisional products are not
anonymously accessible; an unauthenticated GET bounces to the URS OAuth endpoint with a 401. **No
credentials or tokens appear in this folder**; they are fetched at runtime. Reads are direct-S3,
so this is meant to run in `us-west-2`.

One gotcha: `build_manifests(workers=N)` uses a process pool, and Python 3.14 defaults to the
`forkserver` start method, which re-imports `__main__`. In a script, put the call behind
`if __name__ == "__main__":`. In a notebook it just works.

## Next

- Put the Icechunk repo in S3 so the index is shared rather than rebuilt per user. Everything else
  here is already in place for it; `nv.open_repo` just needs an S3 storage backend.
- Run `append_new` on a schedule and see whether it keeps up with the 12-day revisit unattended.
- Build a GSLC cube for the glacier-velocity workflow, where phase matters.
- Raise the per-chunk `urlparse` cost upstream — the path is identical for every chunk in a
  granule, so it is validated ~30,000 times more than necessary.

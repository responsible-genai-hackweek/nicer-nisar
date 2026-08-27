# VirtualiZarr for NISAR access

Scratch space for the project idea in the top-level [`README.md`](../../README.md):

> Explore a [VirtualiZarr](https://virtualizarr.readthedocs.io/en/stable/) approach to working with NISAR data.

Four executed notebooks, in order:

| | | |
|---|---|---|
| 1 | [`1_test_virtualizarr.ipynb`](1_test_virtualizarr.ipynb) | **Does it work?** Feasibility against real granules, failures kept in. |
| 2 | [`2_cube_maintenance.ipynb`](2_cube_maintenance.ipynb) | **Can we operate it?** Parallel build, incremental append, compaction. |
| 3 | [`3_real_example_pipeline.ipynb`](3_real_example_pipeline.ipynb) | **What is it for?** Full lifecycle, a round-trip proof, then L-band backscatter at the Paradise SNOTEL station beside Sentinel-1, Sentinel-2 and the snow pillow. |
| 4 | [`4_with_and_without_virtualizarr.ipynb`](4_with_and_without_virtualizarr.ipynb) | **Is it worth it?** The same analysis four ways — timed and byte-counted. |

`nisar_virtual.py` holds the helpers all four import.

Everything below was measured in-region on CryoCloud (`us-west-2`), against
`NISAR_L2_GCOV_PROVISIONAL_V1` over Mount Rainier.

---

## The idea, in one paragraph

NISAR standard products are HDF5 files in an ASF S3 bucket, ~6.9 GB each. To build a time series
you open every granule, and h5py walks each file's internal B-tree to find where the chunks live.
That walk is what "opening" a NISAR granule actually costs, and you pay it again in every session,
for every user. VirtualiZarr reads those chunk offsets **once**, stores them as a Zarr chunk
manifest, and afterwards the whole archive behaves like a single Zarr array. No pixels are copied
— reads still stream byte ranges out of the original `.h5` files. Only the index is new, and it is
small enough to commit to an [Icechunk](https://icechunk.io) repo and share.

## The data model

Worth being precise about, because most of the failures below are the data model asserting itself.

### What is in a NISAR file

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

**Chunking.** Each raster is a grid of independently compressed `(512, 512)` blocks — 4,970 per
polarization — each with a byte offset and a length. That is precisely what a Zarr chunk is, which
is why the translation is lossless rather than approximate: a NISAR raster *is already* a Zarr
array, described in a different dialect.

**Dimension scales.** `HHHH` has `yCoordinates`/`xCoordinates` attached to its axes as HDF5
dimension scales. That is what tells a reader the array is geolocated, and it is the single thing
that decides whether a product virtualizes cleanly. GCOV and GSLC attach them. RSLC does not.

### What VirtualiZarr makes of it

`HDFParser(group=...)` walks the group once and emits a `ManifestArray` per raster: Zarr v3
metadata plus a `ChunkManifest` — three parallel arrays of `(path, offset, length)`, one entry per
chunk.

```
one granule   : 29,826 chunk references          (all 14 variables)
                 9,941 chunk references          (the 3 we actually need)
23-date cube  : 0.23 TB logical, 4.7 MB index    (~48,000x smaller)
```

Reading `cube.HHHH[5, 1000:2000, 1000:2000]` looks up the covering entries, issues range GETs
against the original `.h5` objects, and decompresses. Same bytes as opening that granule directly
— because you did.

### What a "cube" is, exactly

```python
xr.concat([vds_20251110, vds_20251122, ...], dim="time")
```

A cube is a stack of granules whose `xCoordinates` and `yCoordinates` are **identical arrays**. Not
similar, not overlapping — identical, because concatenation along a new axis requires every other
axis to line up exactly. VirtualiZarr records where bytes are; it cannot reproject, resample or
shift anything to make that true.

So the unit of work is **one product → one track → one output grid → one Icechunk repo**. Not a
simplification we chose; the largest thing the model supports.

### Icechunk's role

It stores the manifest transactionally and versioned. Three reasons it matters: hundreds of
thousands of references are too many for a Kerchunk JSON sidecar; the virtual chunk container
carries the S3 credentials needed to resolve references at read time; and `append_dim` adds new
acquisitions without rewriting what is already indexed.

---

## Yes — start with GCOV, one region

- **GCOV is geocoded and dimension-scaled**, so it virtualizes with no coaxing. RSLC cannot be
  given geolocation by this route at all.
- **It is what the snow workflow wants anyway** — terrain-corrected backscatter on a fixed map
  grid, stacked in time. The virtual cube is exactly that object.
- **The grid constraint forces a regional scope.** A cube cannot span UTM zones or frame changes.
- **It is where the payoff is largest.** Repeat-pass stacks are the case VirtualiZarr is good at;
  for single-granule access it does nothing.

GSLC is the natural second product — virtualizes unchanged, keeps `complex64` phase, and is what
glacier velocity would need.

---

## What we measured: building the index

Track D / relative orbit 065 / frame 4005 / DHDH, 28 granules, 2025-11-10 → 2026-08-18.

| | Result |
|---|---|
| Virtualize one GCOV granule | 0.4–1.1 s |
| Same granule, `h5netcdf` + `s3fs` lazy open | 16 s |
| Index the full track, serial | 17 s |
| …dropping the 9 variables we don't need | 8.9 s, and 3× fewer references |
| …8 processes instead of 1 | 12.5 s (1.4×) |
| …8 threads instead of 1 | 15.6 s (1.1× — i.e. no) |
| Cube of the 23 granules on one grid | 0.23 TB logical, 4.7 MB index |
| Re-open the persisted cube | 0.06–0.12 s |
| Append one new acquisition | 0.8–2.5 s |
| Pixels vs. a direct `h5py` read | byte-identical |

**VirtualiZarr eliminates the metadata cost of opening NISAR archives, not the pixel cost.** Every
pixel still comes over the wire at the original speed. What disappears is the repeated cost of
finding it.

The 15× first-open figure is not purely VirtualiZarr's doing — part is `obstore`'s
`BlockStoreReader` rather than `s3fs`, and part is that building a manifest does less work than
constructing an xarray dataset. The durable win is the sub-second re-open.

### On parallelizing the build

Threads buy nothing, and profiling says why: `validate_and_normalize_path_to_uri` runs **once per
chunk reference** — ~30,000 times per granule — calling `urlparse` on the same S3 URL every time.
That is 26% of the build, in pure Python, holding the GIL. The actual S3 reads are 14%. The build
is not I/O bound, so threads cannot help it.

Processes give 1.4×, capped by pickling manifests back to the parent and by each worker paying for
its own Earthdata login. At 28 granules the pool startup roughly cancels the gain; it would pay at
a few hundred.

The better lever is `drop_variables`: `frequencyA` has 14 variables, a backscatter series needs
three. Dropping the rest halves the build and cuts the index 3×.

`open_virtual_mfdataset` is the same story with a nicer API — 13.8 s serial, 11.5 s threads, 12.8 s
dask. Its `parallel=` argument takes any `Executor` though, including **lithops**, which is the
door that matters at scale.

---

## Is it worth it? (measured, not asserted)

Notebook 4 runs one analysis — median HH over the Paradise field, 23 acquisitions — four ways.
A/B/C are measured in `us-west-2`; D is computed from file sizes.

| Path | Wall time | Bytes moved | Requests |
|---|---|---|---|
| **A** Icechunk virtual cube, direct S3 | **2.4 s** | **61 MB** | 92 |
| **B** open every HDF5, direct S3 | 19.7 s | 1,092 MB | 253 |
| **C** open every HDF5, over HTTPS | 74.9 s | 1,092 MB | 253 |
| **D** download all granules first | 3.5 h *(modelled, 100 Mbit/s)* | 158 GB | 23 |

All paths return **the same numbers** — A and B agree to 7 decimal places, which is the check that
makes the rest of the table mean anything.

**Against the realistic in-region baseline (B), virtualizing is ~8× faster and moves ~18× less.**
What disappears is not pixel reads — both paths read the same chunks — but the HDF5 B-tree
traversal, re-paid per granule per session. The AOI's chunks are 2.64 MB per granule; the direct
path moves 11.8 MB (1 MB blocks), 43.3 MB (4 MB) or 167.6 MB (16 MB) before it can find them.

**The protocol switch alone costs 3.8×.** Off-AWS users cannot use direct S3 — credentials are
region-scoped — so path C is what they are forced onto. Measuring it *in-region* isolates the
endpoint cost from the slower link; a slower link is then modelled on top from the measured byte
and request counts, with the assumptions written down.

**The index pays for itself in ~1.2 runs**, because building it is itself a metadata-only
operation (0.88 s/granule). Anyone who runs an analysis twice, or shares the cube once, is past
break-even.

**Scale note.** The answer is 184 bytes; the granules holding it are 158 GB — 860 million times
more data than result. The comparison narrows for analyses that read most of every granule, where
metadata stops dominating: virtualization helps least when you need everything.

---

## Does the cube produce a usable signal?

Notebook 3 checks it three ways rather than asserting it.

**The round trip closes.** Pixels read back out of the Icechunk store are byte-identical to the
same window read straight from the source `.h5` with `h5py`. Virtual references in, real pixels
out, nothing copied.

**Against ground truth.** Median γ⁰ over a field beside the Paradise SNOTEL station (679),
correlated with the station's own snow-water-equivalent record interpolated to each acquisition:

| Channel | n | r vs SWE | Range |
|---|---|---|---|
| NISAR HH (L-band, 24 cm) | 22 | **−0.67** | 3.4 dB |
| NISAR HV | 22 | −0.63 | 3.9 dB |
| Sentinel-1 VV (C-band, 5.5 cm) | 35 | **−0.83** | 6.6 dB |
| Sentinel-1 VH | 35 | −0.86 | 7.4 dB |

Peak SWE 0.98 m on 24 April; snow-free 15 June.

Every channel anti-correlates with the snow pillow — more water in the pack, less backscatter —
and the two radars differ by the amount wavelength predicts. Sentinel-1 at 5.5 cm tracks SWE
substantially more tightly than NISAR at 24 cm, over roughly twice the dynamic range, because
L-band penetrates further and keeps more ground return. Both minima land near peak SWE. Coincident
Sentinel-2 chips confirm snow on the ground on the dates the radars say there is. Two satellites
sharing nothing but a target, ordering themselves the way the physics says they should, is a far
better check than any single series looking seasonal.

**At mountain scale.** Six windows from summit to lowland forest, median HH, full range over ten
months:

| Site | Elevation | HH range |
|---|---|---|
| Summit | 4,300 m | 0.9 dB |
| Muir snowfield | 3,000 m | 3.4 dB |
| Emmons Glacier | 2,000 m | 4.3 dB |
| Paradise | 1,650 m | 4.4 dB |
| Forest SW | 800 m | 3.7 dB |
| Forest W | 400 m | 0.7 dB |

Flat at both ends, loud in the middle. The 400 m forest control is nearly invariant, which is what
L-band forest should do and is the permission slip for reading the rest; the summit is nearly as
flat because at 4,300 m there is no seasonal melt transition to see.

**None of this is a melt-timing retrieval.** One descending NISAR track and one look geometry; a
single Sentinel-1 relative orbit chosen to hold geometry constant; hand-drawn fields; no DEM, so
no incidence-angle or layover treatment; and provisional NISAR products with no guaranteed
radiometric stability. Read the melt window alone and L-band is nearly flat. The continuous
comparison against SWE is the more honest instrument, and it exists only because the cube made a
22-date series cheap enough to compute in a second.

---

## Prior art: Earthmover's GOES-16 store

[Cloud-Optimizing GOES-16 with Virtual Zarr](https://www.earthmover.io/blog/virtual-zarr) is the
same technique at a scale that makes ours look like a unit test: 380,000 netCDF4 files, ~115 TB,
**7.1 billion chunk references**. Four things worth carrying over.

**The economic argument is stronger than the speed argument.** ~$100 to generate the manifests and
**$1.84/month to store ~80 GB of metadata, against $2,600/month** for a duplicated archive. The
point is not that virtualizing is fast; it is that the alternative — a converted copy of the NISAR
archive — is a recurring cost nobody wants to carry, and it goes stale every time ASF publishes.

**"Archives must be homogeneous" is a general law, not our bad luck.** GOES-16 had to be split into
several Zarr groups because the encoding changed partway through the record. We hit the same class
of problem from a different direction (failure #2) and the resolution is the same: detect the
discontinuity, split into separate stores, do not paper over it.

**Virtual works better for cube-like data than swath data.** Geocoded products stack because they
already live on a shared map grid, and no manifest cleverness will make a swath product do that.

**They still recommend native Zarr where feasible.** Virtual Zarr is the pragmatic answer when the
data must stay in its original format and copying it is prohibitive — exactly NISAR's situation —
not a claim that it beats a purpose-built store.

One operational note that applies directly: Icechunk warns when a referenced archival file has
been modified. Our references point at specific `.h5` objects, so if ASF replaces or withdraws a
granule in place, the index breaks.

---

## Where it breaks

Per `AGENTS.md`, failures are results. Eight, all reproduced in the notebooks.

**1. You cannot virtualize a whole NISAR granule.** `HDFParser()` at the file root raises
`TypeError: Object of type complex is not JSON serializable` — 40 `complex64` attributes under
`metadata/calibrationInformation/crosstalk/`, and Zarr v3 metadata is JSON. Scoping to
`grids/frequencyA` avoids them, which means a virtual cube carries rasters and coordinates but
**not** NISAR's metadata tree. `metadata/sourceData` can be virtualized as a separate group;
`identification` cannot — no dimension scales, so its variables collide on `phony_dim_0`.

**2. One track is not one grid.** Concatenating the full track fails with `AlignmentError`. The
audit: 23 granules on 35712 × 36144 at origin (334805, 5320075), and 5 on 35352 × 35784 at
(496805, 5320795) — same EPSG, same relative orbit, same frame. **Group on the actual coordinate
arrays** (`nv.grid_signature`), never on track and frame. The trailing relative-orbit field in the
filename happens to predict it here, but filenames describe intent; coordinates describe what was
written.

**3. The archive holds duplicate product versions.** One acquisition appears as both `..._001.h5`
and `..._002.h5`. Indexing both puts the same date into the cube twice under one timestamp,
silently. `find_track` keeps the highest version. The most dangerous of the eight, because it
produces a wrong answer instead of an error — and it recurred in notebook 4, where it would have
made the benchmark unfair by giving one path an extra file to open.

**4. RSLC does not attach dimension scales.** The parser falls back to `phony_dim_N` and then
collides between the 2-element `listOfPolarizations` and the 54,720-row image. Forcible by
dropping every non-raster variable, but the result has no geolocation at all. (An earlier guess
that RSLC would be blocked by a CFloat16 dtype was wrong — it stores `complex64`, which virtualizes
fine.)

**5. Credentials expire hourly, and appends leak space.** EDL S3 tokens last an hour; a static
token dies partway through a large cube. Icechunk needs
`icechunk.Credentials.S3(icechunk.s3_refreshable_credentials(callable))` with a **module-level**
(picklable) callable — hence `nisar_virtual.py` rather than a notebook cell. Separately, every
append writes a new immutable manifest and keeps the old one: the repo grew 4.6 → 36.2 MB over 11
appends. `nv.compact()` returns it to 4.6 MB, at the cost of the history.

**6. Reusing pixel indices across grids fails silently, and looks like science.** A first pass at
the time series sampled the same `(y, x)` windows across all 28 granules and produced a clean 6 dB
"seasonal" drop at every site — including the forest control. The five granules on the second grid
put those indices ~250 km away. Nothing errored; the numbers were plausible; only the control site
being *wrong in the same way* gave it away. Group by grid, and keep an invariant site in every
analysis.

**7. Orbit direction does not mean the same thing to two missions.** NISAR ascending is ~06:00
local and descending ~19:20; Sentinel-1 is the reverse — ascending ~18:00, descending ~07:15.
Pairing "ascending with ascending" pairs a dawn overpass with a dusk one, which for a spring
snowpack is the difference between refrozen and wet, i.e. most of the signal. Pair on **local
time**, not the direction flag, and label every series with its relative orbit.

**8. A grid can contain your AOI and still hold no data there.** NISAR ascending track 026's grid
covers Paradise, but the pixels are fill — the grid is a rectangle, the imaged swath inside it is
not. Checking bounds is not checking coverage.

Two smaller traps worth recording. Transient S3 failures (`InternalError`, dropped connections)
are normal at this request volume and will kill an unattended run without retries — notebook 3
wraps its reads. And when instrumenting fsspec, patch `file.cache.fetcher`, not
`file._fetch_range`: the cache captures the bound method at construction, so the obvious patch
silently reports **zero bytes**.

---

## Files

- `1_test_virtualizarr.ipynb` — feasibility. Start here.
- `2_cube_maintenance.ipynb` — parallel build, appending, compaction.
- `3_real_example_pipeline.ipynb` — the pipeline as you would actually run it, plus the analysis it
  exists to serve. Read this one if you only read one. It mirrors
  [`nisar/notebooks/mt_rainier_GCOV_backscatter_time_series.ipynb`](../../../nisar/notebooks/mt_rainier_GCOV_backscatter_time_series.ipynb)
  — same study area, same geometries, same field medians — so the two access paths can be compared
  directly, and it reuses that repo's `geometries/*.geojson`.
- `4_with_and_without_virtualizarr.ipynb` — the cost argument, measured rather than asserted.
- `nisar_virtual.py` — EDL login and refreshable S3 credentials, an `obstore` registry for the
  NISAR bucket, version-deduplicating granule search, grid grouping, parallel manifest build, and
  `append_new` / `compact` for repo maintenance.

## Running it

```bash
pixi install
```

Requires Earthdata Login credentials in `~/.netrc` — NISAR provisional products are not
anonymously accessible; an unauthenticated GET bounces to the URS OAuth endpoint with a 401. **No
credentials or tokens appear in this folder**; they are fetched at runtime. Reads are direct-S3, so
this is meant to run in `us-west-2`.

Three things to know:

- **Jupyter is not declared in `pixi.toml`** — it comes from the CryoCloud hub. Either run the
  notebooks with the hub's Jupyter using the pixi environment as a kernel, or `pixi add jupyterlab`
  if you want the environment to be self-contained.
- Notebook 3 additionally reads geometries from the sibling `nisar` repo
  (`/home/jovyan/repos/nisar/geometries/*.geojson`) and pulls Sentinel-1 and SNOTEL through
  `easysnowdata`, Sentinel-2 through the Element84 STAC API. Those are network calls to non-NASA
  services; the NISAR half of the notebook runs without them.
- `build_manifests(workers=N)` uses a process pool, and Python 3.14 defaults to the `forkserver`
  start method, which re-imports `__main__`. In a script, put the call behind
  `if __name__ == "__main__":`. In a notebook it just works.

---

## Next steps: wider scale, and running it for real

Everything above is one AOI, one product, one mountain, on one person's disk. The gap between that
and something the group can rely on is not research — it is four pieces of plumbing and a
decision about scope.

### Scaling out

**1. Put the index in S3. This is the one that unblocks everything else.** Today the cube lives at
`~/nisar_cubes/…`, which means every user rebuilds it, and `/tmp` being cleared mid-project already
destroyed one. `nv.open_repo` needs one change — `icechunk.s3_storage(...)` in place of
`local_filesystem_storage` — and the virtual-chunk-container config is already correct. Once the
index is shared, the ~1.2-run break-even becomes "free for everyone but the first person".

**2. Partition deliberately, and catalog the partitions.** The data model forces one cube per
(product, track, output grid); over Rainier alone that is three tracks and at least four grids. At
regional scale nobody will find the right cube by convention, so the partitioning needs a catalog —
a STAC item per cube, with its grid signature, time span, relative orbit, local overpass time and
granule versions, is the obvious shape and costs little.

**3. Use an executor that actually scales.** `open_virtual_mfdataset(parallel=…)` takes any
`Executor`, including **lithops**, which is how Earthmover built a 380,000-file store. Our process
pool is a wash at 28 granules because each worker pays for an Earthdata login; the crossover is a
few hundred. Anything continental should skip the pool and go straight to serverless fan-out.

**4. Fix the per-chunk URI validation upstream.** `validate_and_normalize_path_to_uri` is 26% of
build time and runs once per chunk reference, re-parsing an identical path ~30,000 times per
granule. Validating once per granule is a small, well-scoped PR to VirtualiZarr and would take a
meaningful bite out of every large ingest, not just ours.

**5. The arithmetic, so someone can size a real ingest.** From our measurements: **0.88 s and
~214 KB of index per granule** (two polarizations, lean variable list). Extrapolating linearly —
which is the right first approximation, since the work is per-granule — **per million granules**
that is roughly **10 core-days of indexing** (about 2.5 hours on 100 lithops workers) and **~210 GB
of index**, call it $5/month on S3. The alternative, duplicating the pixels, is ~6.9 PB and six
figures a month. That ratio, not the 8× speedup, is the argument.

### Running it operationally

**6. Scheduled append.** `nv.append_new` is idempotent and grid-filtered, so it is already safe to
run on a timer; a cron job after each 12-day cycle is the natural cadence. What is missing is what
to do when it finds a *new* grid: today those granules are silently skipped, which is correct
behaviour and the wrong notification. That case should open a new cube and tell someone.

**7. A compaction policy, not a compaction call.** Appends leak ~3 MB each because Icechunk
manifests are immutable. `nv.compact()` currently expires *everything*, trading all history for
space. A real deployment needs a retention rule — keep the last N snapshots, or expire older than
some window — chosen deliberately rather than by whichever call was convenient.

**8. Guard against source drift.** References point at specific `.h5` objects. ASF can republish or
withdraw a granule, and Icechunk will warn only when a read hits the changed file. Since the
product version is in the filename, record it at index time and re-validate periodically — an
ETag/size check across referenced objects is cheap and catches this before a user does.

**9. Assert the things that fail silently.** Failures #3, #6 and #8 all produce plausible numbers
rather than errors. Any unattended pipeline should assert, per commit: time strictly increasing, no
duplicate timestamps, grid signature unchanged, and a sane fill fraction over a known-good AOI. The
forest control site earned its place the same way — keep one in every analysis.

**10. Retry, because transient S3 errors are routine.** A cube read is hundreds of range requests
against a busy bucket; we saw `InternalError` and dropped connections in normal use. Notebook 3
wraps its reads and that should be the default in anything scheduled.

**11. Decide what off-AWS users get.** Path C measured a 3.8× penalty for the HTTPS endpoint before
any network difference, and the laptop model suggests minutes rather than seconds. A shared index
helps them most — they skip the build entirely — but they still stream pixels over HTTPS. Worth
knowing whether the audience is in-region before optimizing further.

### What would tell us this is the wrong approach

Worth stating so it stays falsifiable:

- **If the analyses people actually run read most of every granule**, the metadata cost stops
  dominating and the advantage narrows toward nothing. Our 8× came from a 1 km AOI.
- **If grids change often enough that cubes fragment faster than they accumulate** — one grid
  change already split a single track — then the catalog becomes the hard problem and the cubes
  become too short to be worth indexing.
- **If ASF ships analysis-ready NISAR cubes**, this is obsolete, and that is fine. Earthmover say
  it themselves: native Zarr where feasible, virtual Zarr when the data must stay where it is.

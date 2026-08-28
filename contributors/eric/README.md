# VirtualiZarr for NISAR access

Scratch space for the project idea in the top-level [`README.md`](../../README.md):

> Explore a [VirtualiZarr](https://virtualizarr.readthedocs.io/en/stable/) approach to working with NISAR data.

## Abstract

**What.** A NISAR granule is a 6.9 GB HDF5 file whose rasters are already stored as thousands of
independently compressed 512 × 512 blocks. *Virtualization* reads the location of every block —
byte offset and length — exactly once and writes that list down as a Zarr chunk manifest. Nothing
is copied or converted: the pixels stay in ASF's bucket, and the manifest (a few hundred KB per
granule) makes a stack of granules look like a single Zarr array you can slice by time, y and x.

**Why here.** Every time anyone opens a NISAR file, h5py walks the file's internal B-tree over the
network to find those same blocks — and pays again next session, for every granule, for every
user. For a time series that cost dominates: the science asks for a 1 km field across 24 dates, but
finding those chunks moves ~1 GB and takes ~20 s per analysis. The archive is also too large to
duplicate — 80 TB/day, ~7 PB for a million granules — so a converted copy is not on the table. A
manifest is: it is ~48,000× smaller than the data it indexes, cheap to store in Icechunk, and can
be shared so only the first person ever pays the build.

**What we found.** Over Mount Rainier, one track, 24 acquisitions: building the index takes
~0.4–1 s per granule; reopening the finished cube takes 0.1 s versus 16 s to open a single granule
the usual way. The same median-backscatter analysis runs **in 2.7 s instead of 20–36 s in-region (9–13×),
moving 63 MB instead of 1.1 GB (18× less)**, and returns byte-identical pixels. It still works off
AWS over HTTPS (4–6× faster than granule-at-a-time), and appending a new acquisition takes about a
second. The signal is real: L-band HH over the Paradise SNOTEL field anti-correlates with measured
snow-water-equivalent (r = −0.67), ordered against Sentinel-1 the way wavelength predicts. The
catch is that a cube can only span granules on one identical output grid — so the unit of work is
one track-frame, and scaling up is a cataloguing problem, not a data problem.

## Plain-language summary

If you have worked with cloud-optimized GeoTIFFs, you already know the trick that makes them fast:
the file carries a small table of contents up front, so a reader can jump straight to the tiles it
needs instead of downloading the whole image. NISAR's radar images are not stored that way. Each
scene is a 7 GB HDF5 file, and its table of contents is scattered through the file in a way a reader
has to reassemble, over the network, every single time the file is opened. Open 23 scenes to build a
time series and you do that 23 times; come back tomorrow and you do it all again.

"Virtualization" is simply doing that reassembly once and saving the answer. We open each scene,
note where every 512 × 512-pixel tile lives (which file, which byte, how long), and write those
notes into a small index. The index is what people then open. It is a few hundred kilobytes per
scene — tens of thousands of times smaller than the imagery — but to software like `xarray` it looks
like one tidy stack of images with a time axis, ready to slice by place and date. The pixels are
never copied; when you ask for a window over your study site, the index tells the reader exactly
which byte ranges to fetch from NASA's original files, and nothing else.

Why not just convert NISAR to a cloud-friendly format? Because it produces 80 TB a day, and keeping a
second copy current would cost more than most groups can carry. An index, by contrast, is cheap
enough to keep on S3 and share, so the first person to build it is the last one who pays.

Over Mount Rainier we measured the difference on a real snow question. Finding the scenes is not
the problem: both `earthaccess` (NASA's CMR) and `asf_search` (ASF's own index) return the list in
under a second — though they disagree by one scene, so a pipeline should check both. Opening them
is the problem. The same 24-date backscatter time series took under 3 seconds from the index versus
20–36 seconds opening the files directly with `s3fs`, and about 30 seconds with the idiomatic
`earthaccess.open()` — moving 18 to 30 times less data over the wire, with pixel-for-pixel identical
results. (Tuning `earthaccess.open()`'s cache to NISAR's chunk size gets it to 15 seconds; the
rest of the gap is the file-opening cost that only an index removes.) It also works from a laptop outside AWS. The one constraint to know about: scenes can only
be stacked if they sit on the same map grid, so a continent's worth of NISAR becomes a *collection*
of stacks plus a catalog to find the right one — the familiar STAC pattern, applied to indexes
instead of files.

Four executed notebooks, in order:

| | | |
|---|---|---|
| 1 | [`1_test_virtualizarr.ipynb`](1_test_virtualizarr.ipynb) | **Does it work?** Feasibility against real granules, failures kept in. |
| 2 | [`2_cube_maintenance.ipynb`](2_cube_maintenance.ipynb) | **Can we operate it?** Parallel build, incremental append, compaction. |
| 3 | [`3_real_example_pipeline.ipynb`](3_real_example_pipeline.ipynb) | **What is it for?** A context map of the study sites, the full lifecycle, a round-trip proof, then L-band backscatter at the Paradise SNOTEL station beside Sentinel-1, Sentinel-2 and the snow pillow. |
| 4 | [`4_with_and_without_virtualizarr.ipynb`](4_with_and_without_virtualizarr.ipynb) | **Is it worth it?** The same analysis eight ways — timed and byte-counted — and recommendations by where you are. |

`nisar_virtual.py` holds the helpers all four import.

The notebooks are the study; **`nisar_cubes/` is the thing built from it** — a catalogued
collection of virtual GCOV cubes covering western North America, on S3, with a three-function API.
See [Using the western North America cubes](#using-the-western-north-america-cubes) below and
[`5_western_north_america.ipynb`](5_western_north_america.ipynb). The plan it implements is
[`PLAN_western_north_america_cube.md`](PLAN_western_north_america_cube.md).

Everything below was measured in-region on CryoCloud (`us-west-2`), against
`NISAR_L2_GCOV_PROVISIONAL_V1` over Mount Rainier.

> **Erratum (2026-08-28).** The prose below and the first version of `nisar_virtual.GRANULE_RX`
> mislabelled the filename fields. In `NISAR_L2_PR_GCOV_004_172_D_065_4005_DHDH_…`, `172` is the
> **relative orbit**, `065` is the **frame** and `4005` is the **bandwidth mode** (40 MHz + 5 MHz)
> — see the naming figure in `nisar-docs`. Where the text says "relative orbit 065, frame 4005",
> read "frame 065, mode 4005". The consequence is real: `find_track` grouped by *frame across all
> relative orbits*, which is why "one track was not one grid" (failure #2). Keyed on the true
> track-frame, every track-frame audited so far (7/7, 167 granules) sits on exactly one grid.
> `nisar_virtual.py` and `nisar_cubes/` use the correct fields; notebooks 1–3 were not re-run, so
> their printed keys carry the old labels (notebook 4 was re-run on 2026-08-28 and filters by name).

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
| Index the full track over HTTPS, 8 threads | 84 s (threads *do* help here) |
| Granule discovery, `earthaccess` (CMR) | 0.85 s → 23 acquisitions |
| Granule discovery, `asf_search` (ASF) | 0.37 s → 24 acquisitions |

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

Notebook 4 runs one analysis — median HH over the Paradise field, 24 acquisitions — eight ways.
All but E are measured in `us-west-2`; E is computed from file sizes. Numbers are from the final
2026-08-28 run, which added paths C′, D′ and F.

| Path | Wall time | Bytes moved | Requests |
|---|---|---|---|
| **A** Icechunk virtual cube, direct S3 | **2.6 s** | **63 MB** | 96 |
| **A′** the same cube, referenced over HTTPS | 9.5 s | 63 MB | 96 |
| **B** open every HDF5, direct S3 (`s3fs`, 4 MB blocks) | 23.5 s | 1,139 MB | 264 |
| **C** open every HDF5, over HTTPS (`fsspec`, 4 MB blocks) | 82.0 s | 1,139 MB | 264 |
| **C′** the same over HTTPS, 1 MB blocks | 71.7 s | 334 MB | 288 |
| **D** `earthaccess.open()` — the idiomatic call, default cache | 32.0 s | 2,101 MB | 130 |
| **D′** `earthaccess.open()` with `block_size` = 1 MB (one NISAR chunk) | 14.6 s | 185 MB | 176 |
| **F** `earthaccess.virtualize()` — index built per session, never saved | 14.6 s *(11.7 build + 2.9 read)* | 63 MB | 96 |
| **E** download all granules first | 3.7 h *(modelled, 100 Mbit/s)* | 165 GB | 24 |

(Wall times for the granule-at-a-time paths moved by up to 1.8× across four runs today — B ran in
19.7, 21.6, 36.2 and 23.5 s — while byte and request counts did not move at all. Trust the byte
columns; read the time ratios as ranges. All eight paths return the same 24 medians.)

All paths return **the same numbers** — A and B agree to 7 decimal places, which is the check that
makes the rest of the table mean anything.

**Against the realistic in-region baseline (B), virtualizing is 9–13× faster and moves 18× less** —
and path A moves *exactly* the chunk bytes the answer needs, which is the floor. B and C move 18×
that; downloading everything moves 2,600×.
What disappears is not pixel reads — both paths read the same chunks — but the HDF5 B-tree
traversal, re-paid per granule per session. The AOI's chunks are 2.64 MB per granule; the direct
path moves 11.8 MB (1 MB blocks), 43.3 MB (4 MB) or 167.6 MB (16 MB) before it can find them.

**A virtual cube is not an in-region-only technique.** Path A′ builds the manifest from `https://`
URLs and resolves it through `icechunk.http_store` with an Earthdata bearer token — no S3 anywhere
— and returns pixels identical to path A. Off-AWS the honest pairing is A′ against C, both on the
HTTPS endpoint: **9.5 s against 82 s in the final run (4.4–8.6× across runs), moving 18× less data.** So the advantage
survives leaving the region; it just shrinks, because HTTPS costs the virtual path more per request
than S3 does.

Two details fell out of building it, both of which invert advice given elsewhere in this README:

- **Threads help over HTTPS.** Over S3 the build is ~50% pure-Python URI validation holding the
  GIL, so threads buy nothing. Over HTTPS the network wait dominates, the GIL stops mattering, and
  8 threads bring the 23-granule build to 84 s. Same code, opposite advice.
- **Authentication is *easier* over HTTPS.** The EDL bearer token is good for weeks (29 days on
  the run above), where the S3 credentials expire hourly and need the refreshable-callable dance of
  failure #5. `icechunk.http_store` takes static headers and that is genuinely sufficient — though
  it has no refresh hook, so a job outliving its token still needs it re-issued.

**The idiomatic call, configured well, gets halfway (path D′).** `earthaccess.open()` picks its
fsspec block size from *file size* — 16 MB for anything over 1 GB, so for every NISAR granule —
a heuristic tuned for ICESat-2-style files with hundreds of small datasets. earthaccess's own
[fsspec how-to](https://earthaccess.readthedocs.io/en/stable/user/howto/fsspec/) says to align the
block with the file's internal chunk instead; a NISAR chunk is ~1 MB. One keyword,
`open_kwargs={"cache_type": "blockcache", "block_size": 1 << 20}`, halves the wall time and cuts
the bytes 11× (2,101 → 185 MB), making it leaner than hand-rolled B. It still moves 2.9× the bytes
the answer needs and takes 5.6× as long as the cube, because the cost it cannot tune away — walking
each file's HDF5 metadata, per granule, per session — is exactly the cost the cube pays once.
Anyone reading NISAR granule-at-a-time should set that keyword; anyone reading it twice should use
the cube.

**Over HTTPS the block size matters less than the request count (path C′).** The same 1 MB block
cuts C's bytes 3.4× but saves only 13 % of its time: 288 requests at HTTPS latency dominate. The
cube's advantage off-AWS is that it makes the *fewest requests* (96) as well as moving the fewest
bytes — path A′ at 9.5 s against C′ at 72 s.

**`earthaccess.virtualize()` is path A without the repository (path F).** Built per session with a
scoped `HDFParser`, it costs 11.7 s to index plus 2.9 s to read — the same bytes and requests as A,
because it is A's index, rebuilt and discarded. That 12 s is precisely what a shared index
amortises. See [Recommendations, by where you are](#recommendations-by-where-you-are).

**The protocol switch alone costs 2.5–3.7× for granule-at-a-time reads, 3.7–6.5× for the cube.** Off-AWS users cannot use direct S3 — credentials are
region-scoped — so path C is what they are forced onto. Measuring it *in-region* isolates the
endpoint cost from the slower link; a slower link is then modelled on top from the measured byte
and request counts, with the assumptions written down.

**The idiomatic call is not the leanest one.** `earthaccess.open()` is what most people would
actually write, and it resolves to direct S3 in-region — but with its default cache it runs
0.9–1.5× the wall time of hand-rolled `s3fs` and moves nearly twice the bytes in half the requests,
trading data volume for round trips via a larger read-ahead block. That matters for the benchmark's honesty: path B is not a strawman,
it is *leaner* than what a NISAR user would type, so the virtual cube's advantage over real-world
practice is larger than the headline, not smaller.

**Discovery is free, and the two search APIs disagree.** `earthaccess` (CMR) and `asf_search`
(ASF) both answer in well under a second, so finding granules is nowhere near the cost of opening
them. But they do not return the same record — see failure #9.

**The index pays for itself in about one run**, because building it is itself a metadata-only
operation (0.78 s/granule, 18 s for the whole track). Off-AWS it pays back in a fifth of a run. Anyone who runs an analysis twice, or shares the cube once, is past
break-even.

**Scale note.** The answer is 184 bytes; the granules holding it are 158 GB — 860 million times
more data than result. The comparison narrows for analyses that read most of every granule, where
metadata stops dominating: virtualization helps least when you need everything.

---

## Recommendations, by where you are

The ranking depends on two things: whether you are in `us-west-2`, and whether anyone will ask the
question twice. Full table with numbers in notebook 4's last section.

**In AWS `us-west-2`** (CryoCloud, any Earthdata Cloud hub)

| You want | Use | Cost here |
|---|---|---|
| A time series anyone might ask for again | **A** — the shared cube: `nisar_cubes.find` → `open` | 2.6 s, 63 MB |
| A one-off stack, no repository | **F** — `earthaccess.virtualize(…, parser=HDFParser(group, drop_variables))` | 15 s, 63 MB |
| The HDF5 files themselves (metadata trees, masks) | **D′** — `earthaccess.open(…, open_kwargs={"cache_type": "blockcache", "block_size": 1 << 20})` | 15 s, 185 MB |
| Most of every granule | D′, or `earthaccess.download()` (~2 min for 165 GB at 10 Gbit/s) | — |
| *avoid* | default `earthaccess.open()`; `xr.open_datatree(…, engine="h5netcdf")` on a whole granule | 32 s, 2.1 GB |

**Outside AWS** (laptop, university cluster)

| You want | Use | Cost, in-region-equivalent |
|---|---|---|
| A time series, an HTTPS index is reachable | **A′** — the cube's `https/` tree (needs the ~1.7 GB repo mirrored publicly — open item) | 9.5 s, 63 MB, 96 requests |
| A time series, no index | **C′** — `fsspec` HTTPS with 1 MB blocks, or `earthaccess.virtualize(access="indirect")` once per session | 72 s, 334 MB, 288 requests |
| Whole scenes, or many dates × many sites | `earthaccess.download()` / Vertex / `asf_search`, then local `h5py` | 3.7 h per 24 granules at 100 Mbit/s |
| One band in QGIS / GDAL | GDAL `/vsicurl` on the `.h5` subdataset ([nisar-docs](https://nisar-docs.asf.alaska.edu/access-overview/)) | — |

Everywhere: set the fsspec block to the chunk (~1 MB); scope to `grids/frequencyA` (or `B`);
deduplicate product versions; if the same stack will be read twice, build the index once and keep it.

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

**7. Orbit direction does not mean the same thing to two missions.** NISAR ascending is ~6:00 am
local and descending ~7:50 pm; Sentinel-1 is the reverse — ascending ~6:25 pm, descending ~6:55 am.
(Those are circular means of local time-of-day across each series, not single overpasses:
acquisitions drift a few minutes between cycles and the PST/PDT switch moves them an hour.)
Pairing "ascending with ascending" pairs a dawn overpass with a dusk one, which for a spring
snowpack is the difference between refrozen and wet, i.e. most of the signal. Pair on **local
time**, not the direction flag, and label every series with its relative orbit.

**8. A grid can contain your AOI and still hold no data there.** NISAR ascending track 026's grid
covers Paradise, but the pixels are fill — the grid is a rectangle, the imaged swath inside it is
not. Checking bounds is not checking coverage.

**9. `earthaccess` and `asf_search` do not index the same archive.** Over the same bounding box
and track, CMR returns **23** distinct acquisitions and ASF returns **24** — ASF surfaces
`20251029T031847`, which CMR does not. ASF also exposes multiple *reprocessing campaigns* of the
same take (CRIDs `P05023` and `X05009`) where CMR shows one. Neither is wrong; they are different
indexes. But a pipeline that assumes they agree quietly indexes a different record depending on
which library it imported, and the cube in these notebooks is built from the CMR list, so it is
one acquisition short of what ASF knows about.

This also sharpens failure #3: there are **two** duplication axes, not one. The CRID (reprocessing
campaign) *and* the trailing `_NNN` within a campaign — three of the nine duplicated acquisitions
have two files under the same CRID. `asf_search` hands you `crid` as metadata; with `earthaccess`
you parse the filename yourself. And `max(crid)` — picking `X05009` over `P05023` — is the
convention the reference notebook uses, not a documented ordering. Worth confirming with ASF
before trusting it.

Two smaller traps worth recording. Transient S3 failures (`InternalError`, dropped connections)
are normal at this request volume and will kill an unattended run without retries — notebook 3
wraps its reads. And when instrumenting fsspec, patch `file.cache.fetcher`, not
`file._fetch_range`: the cache captures the bound method at construction, so the obvious patch
silently reports **zero bytes**.

---

## Using the western North America cubes

Every `NISAR_L2_GCOV_PROVISIONAL_V1` granule over `(-130, 30, -100, 62)` — British Columbia,
Alberta and southern Yukon to the Mexican border, Pacific to the Rockies' east flank — is indexed in
one Icechunk repository:

```
s3://nasa-cryo-persistent/egagli/nisar-gcov/wna/
├── s3/     {D172_F065}/{4005_DHDH}/{freqA|freqB}     cubes referencing s3:// granules (in-region)
├── https/  …the same tree…                           cubes referencing https:// granules (anywhere)
└── catalog/cubes.parquet, collection.json, items/    one row / STAC Item per cube
```

One group per **track-frame × mode × polarisation × band**; each is a `(time, y, x)` virtual cube.
`freqA` is the 10 m primary band (HH/HV, or VV/VH), `freqB` the 80 m secondary band that every
granule also carries — and the *only* band in the 5 MHz `0005`/`NADV` acquisitions.

```python
import sys; sys.path.insert(0, "contributors/eric")     # or run from that directory
import nisar_cubes as nc

cat = nc.load_catalog()                                  # GeoDataFrame, ~1000 cubes
hits = nc.find(bbox=(-121.9, 46.7, -121.6, 46.95))       # cubes whose imaged footprint sees Rainier
ds = nc.open(hits.iloc[0])                               # lazy xarray.Dataset: HHHH, HVHV (time, y, x)
frac = nc.coverage(hits.iloc[0], my_polygon)             # valid-pixel fraction at the AOI, newest scene
chip = nc.clip(ds.HHHH, my_polygon)                      # index-subset then clip; reads only those chunks
tree = nc.open_region()                                  # everything as one lazy DataTree (~5 min; open one track-frame's group for speed)
```

`nc.open(..., scheme="auto")` uses the `s3/` tree in `us-west-2` and the `https/` tree elsewhere.
Both need Earthdata Login in `~/.netrc`. **The index itself lives in a CryoCloud bucket that is not
public**, so today the `https/` tree only helps a CryoCloud user who wants to test the off-AWS path;
serving laptop users needs the repository mirrored to a public bucket (a copy, not a rebuild — the
repository is ~1.5 GB).

Operations, from the repo root:

```bash
pixi run nisar-inventory     # CMR → inventory.parquet; diff against asf_search
pixi run nisar-build         # index what is not yet indexed; resumable; idempotent
pixi run nisar-append        # inventory + build + catalog — run after each 12-day cycle
pixi run nisar-validate      # per-group checks + random byte-identity round trips vs h5py
pixi run nisar-drift         # HEAD every referenced granule; report changed/missing
pixi run nisar-compact       # expire snapshots (keep last 10 + one tag per month), collect garbage
```

### What metadata a cube carries — and what it does not

Virtualisation copies no pixels, and it copies very little metadata either: only the `grids/`
group is walked, so NISAR's `identification/`, `metadata/calibrationInformation/` and
`metadata/sourceData/` trees are **not** in the cube (the first cannot be virtualised at all —
its `complex64` attributes are not JSON; README failure #1). What a cube does carry, by layer:

| Where | What | Origin |
|---|---|---|
| **Coordinates** | `time` (acquisition start); per-time `granule` (product name), `coverage` (`F`ull / `P`artial frame), `ctr` (product counter); `x`/`y` (from `xCoordinates`/`yCoordinates`) | filenames; the first granule's HDF5 dimension scales |
| **`projection` variable** | CF `grid_mapping` attributes: `epsg_code`, `spatial_ref` WKT, `utm_zone_number`, `grid_mapping_name`, ellipsoid parameters | copied from the granule, unchanged |
| **Raster attrs** | `description`, `long_name`, `units`, `valid_min`, `grid_mapping`, `_FillValue` | copied; the per-granule statistics (`mean_value`, `max_value`, `min_value`, `sample_stddev`) are **dropped** — `compat="override"` would have stamped the first granule's onto the whole stack |
| **Group attrs** | `grid_signature`, `epsg`, `posting_m`, `bounds`, `band`, `channels`, `track_frame`, `relative_orbit`, `frame`, `direction`, `mode`, `pols`, `collection`, `crids`, `granules` (the ledger), `times`, `time_sorted`, `last_indexed`, `source_urls` | derived by `nisar_cubes.build` |
| **Chunk references** | per chunk: source URL, offset, length, plus a `last_updated_at` checksum | VirtualiZarr manifest → Icechunk |
| **Catalog** (STAC / GeoParquet) | grid footprint in lon/lat, **imaged** footprint (union of CMR polygons), `local_overpass_time`, `n_times`, `sat:`/`sar:`/`proj:` fields, `icechunk:group`/`snapshot` | `nisar_cubes.catalog`, from group attrs + CMR |

The first build wrote the ledger only as group attributes; `pixi run nisar-backfill-coords` (or
`python -m nisar_cubes backfill-coords`) adds the three per-time coordinates and strips the leaked
statistics on existing groups. New builds write them directly.

**Relation to `earthaccess.virtualize()`.** earthaccess 0.18 ships its own VirtualiZarr entry
point, and it converged on the same design: an `obstore` registry with
`NasaEarthdataCredentialProvider` for `access="direct"` and an `HTTPStore` with an EDL bearer
header for `access="indirect"` — the `s3/` and `https/` duality above. Its default parser is
DMR++, which NISAR does not ship, so on these granules it falls back to `HDFParser` with a warning
and, called at the file root, returns an *empty* dataset. Given a scoped parser it works and is the
right tool for a one-off stack that does not need the shared repository:

```python
from virtualizarr.parsers import HDFParser
vds = earthaccess.virtualize(
    granules, access="direct", concat_dim="time", preprocess=lambda ds: ds.expand_dims("time"),
    parser=HDFParser(group=nisar_cubes.config.HDF_GROUPS["freqA"], drop_variables=list(nisar_cubes.config.DENY_VARIABLES)),
    coords="minimal", compat="override",
)   # 3 Rainier granules in ~3 s; access="indirect" gives https:// references
```

What it does not do is the part `nisar_cubes` exists for: deduplicate product versions, group by
output grid, persist to Icechunk, resume, or handle `frequencyB`.

Design notes, each answering a failure above: duplicate product versions are resolved by product
counter in the inventory (#3); cube membership is decided by the coordinate arrays, and a new grid
in an existing track-frame opens a *sibling* group and logs a warning instead of being skipped or
merged (#2, #6); `find(require_data=True)` intersects the *imaged* footprint, not just the grid
rectangle (#8); CMR and ASF are both queried and their disagreement is printed, not merged (#9);
every virtual reference carries a `last_updated_at` checksum so a republished granule fails loudly;
the granule ledger lives in group attributes so a killed build resumes where it stopped; a fixed
variable deny-list keeps `inputDataExceptionMask` and `listOfPolarizations` from colliding on
dimensions in `frequencyB` and quad-pol files. `ManifestBuilder` holds one process pool for the
whole run, because 440 of the 548 cube keys have only four or five granules and could not amortise
a pool each. Reads over `s3://` refresh their hourly credentials via
`icechunk.s3_refreshable_credentials`; the build refreshes its own through
`obstore.auth.earthdata.NasaEarthdataCredentialProvider`.

## Files

- `nisar_cubes/` — the package: `config` (regions, storage, deny-list), `naming` (filename
  fields), `inventory` (CMR + ASF), `build` (manifests, grids, commits), `catalog` (STAC +
  GeoParquet), `api` (`find/open/coverage/clip/open_region`), `validate`, `ops`, `__main__` (CLI).
- `5_western_north_america.ipynb` — the regional cube in use: catalog map, three sites, timing.
- `PLAN_western_north_america_cube.md` — the plan, with the measurements it rests on.
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
pixi run jupyter lab
```

Requires Earthdata Login credentials in `~/.netrc` — NISAR provisional products are not
anonymously accessible; an unauthenticated GET bounces to the URS OAuth endpoint with a 401. **No
credentials or tokens appear in this folder**; they are fetched at runtime. Reads are direct-S3, so
this is meant to run in `us-west-2`.

Three things to know:

- `jupyterlab` and `nbconvert` are declared in `pixi.toml`, so `pixi run jupyter lab` works and
  the environment is self-contained. They were added after an environment rebuild removed the
  hub-provided Jupyter and left the committed notebooks un-runnable.
- Notebook 4 uses `asf_search` alongside `earthaccess` to compare the two discovery APIs.
- Notebook 3 additionally reads geometries from the sibling `nisar` repo
  (`/home/jovyan/repos/nisar/geometries/*.geojson`) and pulls Sentinel-1 and SNOTEL through
  `easysnowdata`, Sentinel-2 through the Element84 STAC API. Those are network calls to non-NASA
  services; the NISAR half of the notebook runs without them.
- `build_manifests(workers=N)` uses a process pool, and Python 3.14 defaults to the `forkserver`
  start method, which re-imports `__main__`. In a script, put the call behind
  `if __name__ == "__main__":`. In a notebook it just works.

---

## Next steps: wider scale, and running it for real

> **Status (2026-08-28):** items 1, 2, 6, 7, 8, 9, 10 and 11 below are implemented in
> [`nisar_cubes/`](nisar_cubes/) and the western North America repository has been built — see
> [Using the western North America cubes](#using-the-western-north-america-cubes). Item 3
> (serverless fan-out) turned out to be unnecessary at this scale (548 cube keys, ~30 minutes on one
> node); item 4 (the upstream VirtualiZarr PR) and a public mirror of the index for off-AWS users
> remain open. The list is kept as written, as the record of what the study said needed doing.

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

**11. Off-AWS users are served, and the index helps them most.** Path A′ settles the open question:
an HTTPS-referenced cube works, and beats granule-at-a-time on the same endpoint by 4–6×. Since
they skip the build entirely when the index is shared, off-AWS users get the *largest* relative
benefit — their break-even is 1.5 runs against C, and zero if someone else built it. Two caveats
for a deployment: the manifest must be built from `https://` URLs (an S3-referenced cube is
useless to them, so a shared store may need both, or a container mapping), and the bearer token
needs re-issuing when it expires.

### What would tell us this is the wrong approach

Worth stating so it stays falsifiable:

- **If the analyses people actually run read most of every granule**, the metadata cost stops
  dominating and the advantage narrows toward nothing. Our 8× came from a 1 km AOI.
- **If grids change often enough that cubes fragment faster than they accumulate** — one grid
  change already split a single track — then the catalog becomes the hard problem and the cubes
  become too short to be worth indexing.
- **If ASF ships analysis-ready NISAR cubes**, this is obsolete, and that is fine. Earthmover say
  it themselves: native Zarr where feasible, virtual Zarr when the data must stay where it is.

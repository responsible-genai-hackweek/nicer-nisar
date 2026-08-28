# Plan: a virtual NISAR GCOV data cube for western North America

*2026-08-28. Builds on notebooks 1–4 and `nisar_virtual.py` in this folder; every number below that
is not cited from the README was measured today on CryoCloud (`us-west-2`) and is reproducible
with the snippets in the appendix.*

## Status — implemented 2026-08-28

Phases 0–6 are done; the code is `nisar_cubes/` and the repository is live. What the full build
actually produced, against the estimates below:

| | Planned | Actual |
|---|---|---|
| Inventory | 3,421 files / 3,375 acquisitions / 520 track-frames | 3,428 files / 3,384 kept / **548 cube keys** (the archive grew during the day; keys include mode × pols) |
| Groups | ~520 × (1–2 bands) | **1,008** (460 freqA + 548 freqB; every `4005` granule has both bands) |
| Granule-bands indexed | — | **6,359**, 0 failures, 148 commits |
| Build wall time | 25–35 min | **35 min** (2,093 s) on one 16-core node, 8-process pool, both schemes |
| Index size | ~1.5 GB | **1.73 GB**, 17,559 objects |
| Grids per track-frame | 1 expected | **1 in all 548** — no sibling groups were needed |
| CRS | UTM 10–15 | UTM zones 8–14 **plus EPSG:3413** (polar stereographic) on the northernmost frames |
| CMR vs ASF | disagree | ASF knows **15** provisional acquisitions CMR does not; CMR none ASF lacks |
| Validation | byte-identical round trips | **PASSED** — 1,008 groups consistent (time unique, ledger lengths, `s3`/`https` twins); 12/12 random windows byte-identical to direct `h5py` |
| Demo notebook | 3 sites, < 10 min | `5_western_north_america.ipynb` executed clean: Paradise 24 dates in 7 s, Tuolumne 23 dates in 1.5 s, Athabasca 5 dates in 1 s; HTTPS read identical to S3 |

**Later the same day.** Per-time `granule` / `coverage` / `ctr` coordinates were added to every cube
and the leaked per-granule statistics attrs removed (`nisar-backfill-coords`). The first version of
that backfill used `xarray.to_zarr(mode="a")`, which **replaces** a group's attributes with the
Dataset's — it wiped the granule ledger on all 2,016 groups. Icechunk's history made the repair
exact (`ops.restore_group_attrs` copies attributes from the pre-backfill snapshot); the backfill now
carries attributes through, and `nisar-validate` fails on a group whose ledger is missing.

Open items carried forward: a public mirror of the index for off-AWS users (the CryoCloud bucket
is not anonymously readable); the BETA collection as a separate tree; Alaska; the upstream
VirtualiZarr URI-validation PR; an `asf_search`-fed inventory path for the 15 ASF-only
acquisitions.

---

## TL;DR

Index every `NISAR_L2_GCOV_PROVISIONAL_V1` granule over western North America into **one shared
Icechunk repository on S3**, organised as **one virtual cube per track-frame** (relative orbit ×
frame × mode × polarisation), with a **STAC/GeoParquet catalog** on top and a three-function Python
API (`find`, `open`, `coverage`) so nobody needs to know the layout.

The whole region is **3,421 granules (19.5 TB) in 520 track-frames**. At the measured build rate
that is **~30 minutes on one CryoCloud node** and **~1.3 GB of index** (S3 and HTTPS references
both). No serverless fan-out is needed. The full-region build is a lunch break, not a project; the
project is the plumbing around it — inventory, resumability, catalog, validation, append.

Three findings today change the design relative to the README:

1. **The filename fields were mislabelled.** `NISAR_L2_PR_GCOV_004_172_D_065_4005_…`: `172` is the
   **relative orbit**, `065` is the **frame**, `4005` is the **bandwidth mode** (40 MHz + 5 MHz),
   not a frame. `find_track` therefore grouped by *frame across all orbits*, which is why "one track
   was not one grid" (README failure #2).
2. **One track-frame *is* one grid.** Audited 7 track-frames / 167 granules across three UTM zones,
   both directions, both bands: every one is a single output grid, partial-coverage granules
   included. Fragmentation is not the hard problem the README feared. We still verify by coordinate
   signature; we just expect it to pass.
3. **12 % of the archive is not in `frequencyA`.** 409 granules are 5 MHz-only (`0005` / `NADV`):
   VV+VH at 80 m posting, living in `frequencyB`. And every `4005` granule *also* carries an 80 m
   `frequencyB` HH/HV that costs ~1 % of the references to index. Both need handling.

---

## 1. What is being built

### Definition of "the cube"

A virtual cube cannot span grids (README, "What a cube is, exactly"), and western North America
spans six UTM zones and 520 track-frames. So the deliverable is not one array. It is:

| Layer | What | Where |
|---|---|---|
| **Store** | One Icechunk repo; one Zarr group per (track-frame, mode, pols, band); each group a `(time, y, x)` virtual cube | `s3://nasa-cryo-persistent/egagli/nisar-gcov/wna/` |
| **Catalog** | One STAC Item per group with footprint, time span, orbit metadata, granule list; also as one GeoParquet file | same prefix, `catalog/` |
| **API** | `nisar_cubes.find(geom, time)`, `.open(item, scheme)`, `.coverage(item, geom)`, `.build/append` | `contributors/eric/nisar_cubes/` → graduate to `scripts/` |
| **Ops** | Idempotent `append`, per-commit assertions, retention, drift check | `pixi run` tasks |

A user experience of "one cube": `xr.open_datatree(store, group="s3")` returns the entire region as
a lazy DataTree in well under a second; `nisar_cubes.find(point)` returns the two or three cubes
that see it; `open()` gives the `xr.Dataset` the Rainier notebooks already work with.

### Scope

| | Decision | Reason |
|---|---|---|
| **Region** | bbox `(-130, 30, -100, 62)` — BC/Alberta/southern Yukon to the Mexican border, Pacific to the Rockies' east flank. A config value, not a constant. | 3,421 granules. Adding Alaska (`-170…-100, 30…72`) doubles it to 6,835 / 28.7 TB — same code, second run. |
| **Collection** | `NISAR_L2_GCOV_PROVISIONAL_V1` (CRID `P05023`). `NISAR_L2_GCOV_BETA_V1` (2,234 granules, CRIDs `X05008–10`, Oct 2025–Jan 2026) as a **separate top-level tree**, not merged. | BETA and PROVISIONAL share only 223 acquisitions; 1,978 are BETA-only. Different processing → different radiometry → different tree. Never mix CRIDs on one time axis. |
| **Bands / variables** | `frequencyA`: `HHHH, HVHV` (+ `VVVV, VHVH` when quad-pol) + coords + `projection`. `frequencyB`: same, 80 m. Fixed **deny-list**, not a probe-derived one. | The 9 masks/scalars triple the references and two of them (`inputDataExceptionMask`, `listOfPolarizations`) *break* virtualisation of `frequencyB` and quad-pol granules by dimension collision. |
| **Reference scheme** | Both. Build once over S3; derive the HTTPS manifest with `vds.vz.rename_paths()` (verified in vz 2.7.3); write to sibling groups `s3/…` and `https/…` in the same commit. | Icechunk **rejects** an `s3://` prefix on an `http_store` (verified), so one manifest cannot serve both audiences. Renaming paths is free; re-reading over HTTPS would take ~3.5 h. |
| **Non-goals** | No reprojection, no mosaicking, no resampling, no pixels copied. | VirtualiZarr records where bytes are. A regional *analysis-ready* mosaic is a derived native-Zarr product built *from* these cubes — a later, separate compute job. |

---

## 2. Sizing (measured)

| Quantity | Value | Source |
|---|---|---|
| Granules / unique acquisitions | 3,421 / 3,375 (46 duplicate product versions, `_002`/`_003`) | CMR, today |
| Track-frames (dir, rel-orbit, frame) | 520 — 59 with ≥ 10 acquisitions, 442 with 3–5 | CMR, today |
| Modes | `4005 DHDH` 3,005 · `0005 NADV` 409 · `2005 QPDH` 4 · `0005 NASV` 1 | CMR, today |
| UTM zones | 10–15 (`EPSG:32610–32615`) | audit |
| Grids per track-frame | **1** (7/7 sampled, n = 23–24 each, F and P coverage mixed) | audit |
| frequencyA grid | ~35 000 × 36 000 px @ 10 m, 512 × 512 chunks, ~4 970 chunks/pol | audit |
| frequencyB grid | ~4 400 × 4 500 px @ 80 m, 9 × 9 chunks/pol | probe |
| Chunk references, freqA, 2 pols | ~9 600 / granule → **~33 M** region-wide | audit |
| Index size | ~214 KB/granule → **~730 MB per scheme, ~1.5 GB total** | README ×3,421 |
| Build rate, 8 processes, S3 | 0.34–0.63 s/granule → **~25–35 min** for the region | audit |
| Build rate, serial | 0.88 s/granule → ~50 min | README |
| Discovery | < 1 s per query | README |
| Icechunk write to `nasa-cryo-persistent` via hub IAM role | works (`from_env=True`) | verified today |

Nothing here needs lithops, Dask or GitHub Actions. A single 16-core node does it before the S3
credentials expire — which is the one operational constraint that does bite (§4, Phase 2).

---

## 3. Design

### 3.1 Repository layout

```
s3://nasa-cryo-persistent/egagli/nisar-gcov/wna/          one Icechunk repo, branch main
├── s3/                                                    manifests with s3:// references
│   ├── D172_F065/                                         {dir}{rel-orbit}_F{frame}
│   │   └── 4005_DHDH/                                     {mode}_{pols}
│   │       ├── freqA/   HHHH, HVHV (time, y, x) f32 @10 m · projection · time
│   │       └── freqB/   HHHH, HVHV (time, y, x) f32 @80 m
│   ├── D042_F071/
│   │   └── 0005_NADV/
│   │       └── freqB/   VVVV, VHVH @80 m                  (no freqA in this mode)
│   └── … 520 track-frames
├── https/                                                 same tree, https:// references
└── catalog/
    ├── collection.json, items/*.json                      static STAC
    └── cubes.parquet                                      stac-geoparquet, one row per group
```

Group attrs carry: `grid_signature (ny, nx, x0, y0, dx)`, `epsg`, `relative_orbit`, `frame`,
`direction`, `mode`, `pols`, `band`, `collection`, `crid`, `granules` (name + CTR per time step),
`local_overpass_mean`.

**Why one repo, not 520.** One thing to open and share, one commit history, one GC policy, and a
`DataTree` view of the region for free. Icechunk keeps a manifest per array, so opening one cube
does not touch the others. Writers to different groups never conflict — `session.commit(...,
rebase_with=ConflictDetector())` is exactly the pattern that let hundreds of GitHub runners write one
store in `icechunk_github_actions_demo`.

**If a second grid ever appears in a track-frame** (the audit says it will be rare): open a sibling
group `freqA_g<hash>`, record it in the catalog, and *notify*. Never concatenate across grids; never
silently skip (README, next-steps #6).

### 3.2 Inventory

A GeoParquet table, `inventory.parquet`, regenerated from CMR (and ASF, see below) each run:

`granule, url_s3, url_https, collection, cycle, relative_orbit, direction, frame, mode, pols,
start, end, crid, accuracy, coverage(F/P), ctr, size_bytes, footprint, in_cube(bool), group`

Rules baked in, each one a README failure:

- **Dedup** per `(collection, rel-orbit, frame, mode, pols, start)`: keep max `ctr`. Log what was
  dropped. (#3)
- **Both search APIs**, union'd: CMR via `earthaccess` is primary; `asf_search` results diffed and
  the difference logged, not silently adopted. (#9)
- **Track-frame key is `(direction, relative_orbit, frame, mode, pols)`** — field positions
  4/3/5/6/7 of the filename, per the naming figure in `nisar-docs`. Not frame-alone. (#2)

### 3.3 Build engine

`nisar_cubes.build(track_frame, band)` — one call, idempotent, one commit:

1. Look up the group; read its `time` index (empty if absent).
2. Select inventory rows newer than / absent from the cube.
3. Virtualise with `HDFParser(group=freqA|freqB, drop_variables=DENY)` in a process pool (8).
4. `group_by_grid`; assert exactly one grid matching the group's signature; otherwise → sibling
   group + notification.
5. `concat_cube`; assert time strictly increasing, unique; assert fill fraction over the frame's
   centre tile < 0.99 on the newest granule (catches "grid contains AOI, holds no data", #8).
6. `vds.vz.to_icechunk(store, group="s3/…", append_dim="time" if exists, last_updated_at=now)` —
   `last_updated_at` makes Icechunk checksum the source objects so a republished granule fails
   loudly at read time instead of returning wrong pixels.
7. `vds.vz.rename_paths(s3→https)`, write to `https/…`.
8. `commit(msg, rebase_with=ConflictDetector())`; write/refresh the STAC item.

`nisar_cubes.build_region()` iterates track-frames largest-first, skipping ones whose cube is
already complete, so a killed run resumes where it stopped (the commit log is the ledger, as in the
GitHub Actions demo's `generate_tile_matrix`).

**Credentials.** NISAR S3 tokens live one hour; the build is ~30 min but appends over a slow bucket
or a second region will cross the boundary. Two options, in order of preference: (a)
`obstore.auth.earthdata.NasaEarthdataCredentialProvider` on the `S3Store` (present in obstore
0.11.1 — needs a five-minute test that it accepts the NISAR `s3credentials` endpoint); (b) rebuild
the registry every N track-frames. The Icechunk side is already solved (`s3_refreshable_credentials`
in `nisar_virtual.py`). The repo's *own* storage uses the hub IAM role (`from_env=True`) and never
expires.

### 3.4 Catalog and access API

```python
import nisar_cubes as nc
items = nc.find(geometry_or_bbox, time="2025-11/2026-06", band="freqA")   # GeoParquet query, ms
ds    = nc.open(items[0], scheme="auto")        # s3 in us-west-2, https elsewhere → xr.Dataset
frac  = nc.coverage(items[0], my_polygon)       # fraction of valid pixels at the AOI, newest scene
tree  = nc.open_region(scheme="s3")             # xr.DataTree of everything, lazy
```

Item properties (STAC + `sar:`/`sat:` extensions where they fit): `sat:relative_orbit`,
`sat:orbit_state`, `nisar:frame`, `nisar:mode`, `sar:polarizations`, `sar:center_frequency`,
`proj:epsg`, `proj:shape`, `proj:transform`, `nisar:grid_signature`, `nisar:local_overpass_time`,
`nisar:granules`, `icechunk:group`, `icechunk:snapshot`, time range, `n_times`.

`scheme="auto"` picks S3 when the caller's region is `us-west-2` (env / IMDS) and HTTPS otherwise,
handing the http container an EDL bearer token from `earthaccess.login()`.

### 3.5 Operations

- **Append**: `pixi run nisar-append` = inventory refresh → `build_region()`. Safe on a timer; run
  after each 12-day cycle. Initially a manual/hub cron; GitHub Actions is *blocked* on write
  credentials for `nasa-cryo-persistent` (IAM role is hub-only) — would need a bucket with static
  keys in repo secrets, as the demo does with Azure.
- **Retention**: keep the last 10 snapshots plus one per month; `expire_snapshots` + `garbage_collect`
  on that rule. Not "expire everything" (README next-steps #7).
- **Drift**: weekly `HEAD` of every referenced object vs. recorded size/ETag; plus
  `last_updated_at` at read time as the backstop.
- **Assertions on every commit**: time monotonic & unique; grid signature unchanged; fill fraction
  sane; s3 and https groups have identical shapes and `time`.

---

## 4. Work plan

| Phase | Deliverable | Acceptance | Effort |
|---|---|---|---|
| **0. Correct the model** | `GRANULE_RX` groups renamed to `cycle, relative_orbit, direction, frame, mode, pols, …`; README erratum paragraph; `find_track` keyed on track-frame | Rainier D172_F065 returns 24 granules on 1 grid without `group_by_grid` discarding any | 1–2 h |
| **1. Inventory** | `nisar_cubes/inventory.py` → `inventory.parquet` + CMR/ASF diff report | 3,375 unique acquisitions; the 46 duplicates listed; footprints render | ½ day |
| **2. Build engine** | `nisar_cubes/build.py` per §3.3, incl. deny-list, freqB, quad-pol, `rename_paths`, credential refresh, assertions | Rainier track-frame builds to the S3 repo from scratch, appends one held-back granule, resumes after `kill -9`, round-trip is byte-identical via **both** schemes | 1–2 days |
| **3. Full build** | The region in `s3://nasa-cryo-persistent/egagli/nisar-gcov/wna/` | 520 track-frames committed; validation report: 20 random granules byte-identical from cube vs. `h5py`; per-cube time monotonic; `open_datatree` < 2 s | ½ day (30 min compute) |
| **4. Catalog + API** | `nisar_cubes/catalog.py`, `api.py`; `catalog/cubes.parquet`, STAC items | `find(Paradise SNOTEL)` returns the 3 Rainier cubes; `open()` reproduces notebook 3's medians to 7 dp; laptop (off-AWS) `open(scheme="https")` returns identical pixels | 1 day |
| **5. Demo notebook** | `5_western_north_america.ipynb`: catalog map (520 footprints coloured by n_times), pick a SNOTEL site and a glacier, time series from `find→open`, timing vs. granule-at-a-time | Runs top to bottom on CryoCloud in < 10 min; HTTPS cell runs on a laptop | 1 day |
| **6. Ops** | `pixi` tasks `nisar-inventory`, `nisar-build`, `nisar-append`, `nisar-validate`, `nisar-compact`; retention + drift scripts; new-grid notification (stdout + STAC `nisar:alerts`) | Two consecutive `nisar-append` runs: second is a no-op with a clean log | 1 day |
| **Stretch** | BETA tree; Alaska; GSLC (complex64, for velocity); derived native-Zarr regional product; upstream PR: validate URI once per granule in VirtualiZarr (26 % of build) | — | — |

Phases 1–2 can proceed in parallel with 0. Phase 3 depends on 2. Phase 4 on 3. Phase 5 on 4.
Total to a usable regional cube with catalog: **~4 working days**; the build itself is 30 minutes.

---

## 5. Risks and what would tell us we're wrong

| Risk | Likelihood | Mitigation / signal |
|---|---|---|
| Grids fragment within a track-frame as processing evolves | Low (0/7 today) | Sibling groups + notification; if > 10 % of track-frames grow a second grid, the catalog becomes the product and cubes get short |
| ASF republishes/withdraws granules → dangling references | Medium over a year | `last_updated_at` checksums; weekly drift check; inventory diff shows removals |
| Hourly S3 token expires mid-build | Certain for long runs | Credential provider or registry rotation (§3.3) — test on Phase 2 |
| CMR and ASF disagree (README #9) | Known | Union + diff report; never silently pick one |
| Credential provider `NasaEarthdataCredentialProvider` doesn't accept the NISAR endpoint | Unknown | 5-minute test; fallback (b) is already written in spirit |
| GitHub Actions cannot write to the hub bucket | Certain | Accept manual/hub-cron append for the hackweek; document the static-key bucket path |
| Users read whole granules, not AOIs | Possible | Then metadata stops dominating and the win shrinks toward ~1× (README). The cube still costs nothing to keep. |
| ASF ships analysis-ready GCOV cubes | Possible, later | Then this is obsolete and that is fine |

---

## 6. Appendix — measurements and API checks from today

**Filename fields** (`nisar-docs/assets/nisar-naming-conventions-single.png`):
`NISAR_IL_PT_PROD_CYL_REL_P_FRM_MODE_POLE_S_Start_End_CRID_A_C_LOC_CTR.EXT` — REL = relative orbit
001–173, FRM = frame 001–176, MODE = bandwidth codes (40/20/77/05/00 × 2), C = coverage F/P,
CTR = product counter.

**Footprint test** (CMR polygons, 3,421 granules): grouping by field 3 gives 46 groups whose
centroids run 28–60 °N along a line (tracks); grouping by field 5 gives 36 groups each pinned to one
latitude band, σ ≈ 0.02° (frames); grouping by both gives 520 groups with σ ≈ 0.014°.

**Grid audit** (8 processes, `drop_variables` = deny-list):

| Track-frame | n | grids | coverage | s/granule | EPSG | shape | refs |
|---|---|---|---|---|---|---|---|
| A019_F020 4005 DHDH freqA | 24 | 1 | 24 F | 0.39 | 32613 | 34704 × 35208 | 225 216 |
| A019_F021 | 24 | 1 | 24 F | 0.43 | 32613 | 34776 × 35280 | 225 216 |
| A019_F022 | 24 | 1 | 22 F + 2 P | 0.63 | 32613 | 34776 × 35280 | 225 216 |
| A033_F025 | 24 | 1 | 24 F | 0.45 | 32614 | 35712 × 36144 | 238 560 |
| D172_F065 (Rainier) | 24 | 1 | 24 F | 0.42 | 32610 | 35712 × 36144 | 238 560 |
| D172_F066 | 24 | 1 | 24 F | 0.34 | 32610 | 35712 × 36144 | 238 560 |
| D042_F071 0005 NADV **freqB** | 23 | 1 | 23 P | 0.47 | 32610 | 4293 × 4365 @ 80 m | 3 726 |
| D142_F071 2005 QPDH | 4 | — | — | — | — | fails without deny-list (`listOfPolarizations` dim collision) | — |

**Verified APIs (vz 2.7.3 / icechunk 2.1.2 / obstore 0.11.1 / xarray 2026.7):**
`vds.vz.to_icechunk(store, group=, append_dim=, last_updated_at=)`; `vds.vz.rename_paths(fn)`;
`Session.commit(rebase_with=ConflictDetector())`; `icechunk.s3_storage(from_env=True)` writes to
`nasa-cryo-persistent` under the hub role; `VirtualChunkContainer("s3://…", http_store)` is
rejected (`Invalid url prefix scheme`); `xr.open_datatree` available;
`obstore.auth.earthdata.NasaEarthdataCredentialProvider` importable.

**Reproduce the counts:**

```python
import earthaccess
r = earthaccess.search_data(short_name="NISAR_L2_GCOV_PROVISIONAL_V1",
                            bounding_box=(-130, 30, -100, 62), count=-1)   # 3,421
```

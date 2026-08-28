---
name: nisar-data-access
description: How to search, stream, and read NISAR (NASA-ISRO SAR) L-band data — GUNW interferometric products, GCOV backscatter, literal HDF5 layer paths, CMR/earthaccess search recipes, byte-range streaming without bulk download, auth setup, and the archive's known traps. Includes the verified Mores Creek Summit (ID) pair inventory. Use when locating NISAR granules, parsing NISAR HDF5 files, or deciding which NISAR product level to use.
---

# NISAR data access

**Verified August 2026.** The archive is actively changing — a full validated
reprocessing of the L0–L3 backlog is targeted for Q4 2026. Re-verify anything a
decision depends on.

Every claim below is tagged:

- **VERIFIED** — checked against the live archive or a real file; method stated.
- **INFERRED** — consistent pattern across real granules, not read from a spec.
  Usable, but confirm before building on it.
- **UNVERIFIED** — from documentation only, not seen in a real granule.

Do not promote a tag without doing the check.

## Which product

| Need | Product | Why |
|---|---|---|
| Geocoded interferometric phase + coherence, no DIY processing | **L2 GUNW** | Ready-made: unwrapped phase, coherence, connected components. |
| Same content but you pick the pair dates | **L2 GSLC** | Geocoded complex; form interferograms at any baseline. Costs you interferogram formation + unwrapping; coregistration is done. |
| Per-date backscatter (σ⁰/γ⁰) | **L2 GCOV** | GUNW has **no** amplitude layer. Only way to get backscatter. |
| Soil moisture covariate | **L3 SME2** | 200 m. Coarse, but soil moisture is a major non-snow phase contributor. |

Ruled out: **RUNW** is GUNW in radar geometry (you geocode it yourself).
**ROFF/GOFF** are speckle-tracking offsets for metre-scale displacement — wrong
signal for most applications. **RSLC/RIFG** are earlier in the chain.

All L-band products come from **ASF DAAC**. S-band is ISRO-only via Bhoonidhi
(`bhoonidhi.nrsc.gov.in/NISAR/`) and will never appear in CMR/earthaccess.

## Searching

**CMR is public — no auth, no login, no account.** This is the cheapest way to
answer availability questions, and it is how the entire inventory below was built.

```python
import json, urllib.request, urllib.parse

q = {
    'short_name': 'NISAR_L2_GUNW_PROVISIONAL_V1',
    'bounding_box': '-115.73524,43.9072,-115.63549,43.98398',   # W,S,E,N
    'temporal': '2025-11-01T00:00:00Z,2026-04-30T23:59:59Z',
    'page_size': '2000',
}
url = 'https://cmr.earthdata.nasa.gov/search/granules.umm_json?' + urllib.parse.urlencode(q)
with urllib.request.urlopen(url, timeout=180) as r:
    items = json.load(r)['items']

for it in items:
    umm  = it['umm']
    gid  = umm['GranuleUR']
    attrs = {a['Name']: a['Values'] for a in umm.get('AdditionalAttributes', [])}
    direction = attrs.get('ASCENDING_DESCENDING', [None])[0]
    poly = umm['SpatialExtent']['HorizontalSpatialDomain']['Geometry']['GPolygons'][0]
```

Or `earthaccess` (needs login even for search):

```python
import earthaccess
earthaccess.login()
results = earthaccess.search_data(
    short_name='NISAR_L2_GUNW_PROVISIONAL_V1',
    bounding_box=(w, s, e, n),
    temporal=('2025-12-01', '2026-01-31'),
)
```

Collections: `NISAR_L2_{GUNW,GCOV,GSLC}_{BETA,PROVISIONAL}_V1`,
`NISAR_L1_RUNW_PROVISIONAL_V1`, `NISAR_L3_SME2_{BETA,PROVISIONAL}_V1`.

Server-side filters are thin. **Search broadly, post-filter in Python.** There is
no server-side filter for orbit direction or temporal baseline — compute both from
the granule name and `AdditionalAttributes`.

`asf_search` has the deepest NISAR object model (`NISARProduct`, `dataMaturity`
filter) but **may not be installed** — it was absent from a working environment
that had `earthaccess`. Check before relying on it; raw CMR always works.

## Auth

CMR search needs nothing. **Granule bytes need Earthdata Login.** An
unauthenticated GET on a granule 401s and redirects to `urs.earthdata.nasa.gov`
(VERIFIED). Free account, no NISAR-specific EULA.

```
machine urs.earthdata.nasa.gov
    login <username>
    password <password>
```

`~/.netrc`, `chmod 600`. Both libraries and GDAL pick it up automatically.

For in-region S3 (us-west-2 only), temporary credentials from
`https://nisar.asf.earthdatacloud.nasa.gov/s3credentials`, expire hourly.

## Streaming — do not bulk-download

VERIFIED: the HTTPS granule URL 303-redirects to plain S3 in us-west-2, and range
requests work. A typical AOI is a fraction of a percent of a granule (~0.1% for a
66 km² box against a ~63,000 km² footprint), so streaming is a ~1000× reduction,
not a convenience.

**Clipping *is* the streaming.** Compute the pixel window from the geotransform and
read only that window; never materialize the granule.

```python
import s3fs, h5py

fs = s3fs.S3FileSystem(anon=False)         # or fsspec over HTTPS with .netrc
with fs.open(s3_url, 'rb') as f:
    with h5py.File(f, 'r') as h5:
        g = h5['/science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH']
        print(list(g))                      # enumerate, don't hardcode
        d = g['unwrappedPhase']
        print(d.shape, d.chunks)            # chunk shape governs read cost
        window = d[row0:row1, col0:col1]    # only these chunks are fetched
```

HDF5 **cannot read half a chunk**. You pay for every chunk the window intersects,
so chunk shape decides how much of the win is real: small square chunks → seconds;
full-row chunks → you pull full-width stripes. Always print `.chunks` before
designing a read pattern.

The same trick works on remote GeoTIFFs, one level down (IFD instead of B-tree):

```python
import rasterio
# reads ~32 KB in two range requests; does NOT fetch the file
with rasterio.open('/vsicurl/https://host/path/big.tif') as ds:
    print(ds.crs, ds.width, ds.height, ds.res, ds.nodata, ds.profile['blockxsize'])
```

Set `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR` to stop GDAL probing for sidecars.
Requires `Accept-Ranges: bytes` on the server — check with `curl -I` first; without
it GDAL silently falls back to fetching whole files.

To confirm what was actually transferred, `CPL_CURL_VERBOSE=YES` and grep the log
for `Range:` (GDAL logs its own request headers **without** curl's `>` prefix) and
`Content-Range:`. Do not sum `Content-Length` — the `HEAD` response reports the
full file size while transferring no body, and summing it overstates transfer by
the entire file.

## GUNW internal structure

**VERIFIED Aug 2026** by opening a real granule over Mores Creek
(`h5py.visititems` on `NISAR_L2_PR_GUNW_012_077_A_024_013_..._P05023_N_F_J_001`,
product version 1.0.11, spec version 1.5.0). Shapes and chunks below are that
granule's; enumerate at runtime rather than hardcoding them, since they vary by
track and frame.

All imagery under `/science/LSAR/GUNW/grids/frequencyA/`. Only frequencyA is
processed for GUNW. The 20 m / 80 m split is by *group*, not by a resolution-named
path:

```
unwrappedInterferogram/<POL>/          <- 80 m posting, (4446, 4500) here
    unwrappedPhase                     float32, radians, fill nan
    coherenceMagnitude                 float32, fill nan
    connectedComponents                uint16,  fill 65535
    ionospherePhaseScreen              float32, radians, fill nan
    ionospherePhaseScreenUncertainty   float32, fill nan
unwrappedInterferogram/mask            uint32,  fill 255      <- NOT UByte

wrappedInterferogram/<POL>/            <- 20 m posting, (17784, 18000) here
    wrappedInterferogram               complex64, fill (nan+nanj)
    coherenceMagnitude                 float32, fill nan
wrappedInterferogram/mask              uint32,  fill 255

pixelOffsets/<POL>/                    <- 80 m posting
    slantRangeOffset                   float32, fill nan
    alongTrackOffset                   float32, fill nan
    correlationSurfacePeak             float32, fill nan
pixelOffsets/mask                      uint32,  fill 255
```

Every 2D dataset is chunked **(512, 512)** — small and square, so a windowed read
costs only the chunks it touches. A 99 x 106 cell AOI is one chunk per layer:
~1 MB against a 2437 MB granule. Each group also carries `xCoordinates`,
`yCoordinates`, `xCoordinateSpacing`, `yCoordinateSpacing` and `projection`
(a scalar uint32 whose `epsg_code` attribute gives the CRS).

The 20 m grid nests **exactly** 4x inside the 80 m grid here (18000/4500 and
17784/4446 are both exactly 4) and shares an origin — but assert both rather than
assuming, since a non-nesting pair would silently misalign every aggregate.

`<POL>` is `HH` or `VV` — GUNW is **co-pol only**. `frequencyA/listOfPolarizations`
(here `[b'HH']`) is a cleaner enumeration source than walking group children.
`frequencyA/centerFrequency` reads **1.239 GHz**, so lambda = **0.2420 m**, not the
0.238 m often quoted for L-band.

**`mask` decoding — a 32-bit field, not a 3-digit number.** VERIFIED from the
dataset's own `description` attribute: "Each pixel value is encoded as a 32-bit
unsigned integer."

| Bits | Meaning |
|---|---|
| 0-7 | subswath encoding, read as **decimal digits** `W R S` |
| 8-15 | data-anomaly flags, secondary RSLC |
| 16-23 | data-anomaly flags, reference RSLC |
| 24 | ionosphere phase screen was **interpolated** (filled), not measured |
| 25-31 | reserved |

Within the low byte the digits are: most significant = water flag of the reference
RSLC pixel (1=water, 0=land); second = subswath number in reference; least
significant = subswath in secondary. A `0` in *either* subswath digit means an
invalid sample. So low-byte `11` and `12` are land samples in valid subswaths.

Two traps this creates. Masking with `mask != 255` is not enough — 255 is the
fill value, but a *valid* pixel can also have high bits set. And bit 24 is not a
phase-quality flag: it says the ionospheric correction was interpolated there.
Over Mores Creek 60% of AOI pixels have bit 24 set while the interpolated and
measured populations are statistically indistinguishable in phase, so it is a
provenance flag, not a filter.

`pixelOffsets/mask` is **plural** — VERIFIED, resolving the spec's inconsistent
`pixelOffset/mask` (singular) print.

### Identification

At `/science/LSAR/identification/` — **sibling to `GUNW/`, not nested under it**:

`referenceZeroDopplerStartTime`, `referenceZeroDopplerEndTime`,
`secondaryZeroDopplerStartTime`, `secondaryZeroDopplerEndTime`
(`YYYY-mm-ddTHH:MM:SS.sssssssss`), `trackNumber`, `frameNumber`,
`orbitPassDirection`, `lookDirection`, `compositeReleaseId`, `productVersion`,
`productSpecificationVersion`, `granuleId`, `productDoi`, `boundingPolygon` (WKT,
EPSG 4326), `isFullFrame`, `radarBand`, `processingDateTime`.

VERIFIED Aug 2026, plus these not in the pre-launch list: `productType`,
`productLevel`, `missionId`, `platformName`, `instrumentName`, `processingCenter`,
`processingType`, `diagnosticModeFlag`, `isDithered`, `isGeocoded`, `isMixedMode`,
`isUrgentObservation`, `listOfFrequencies`, `staticLayersDataAccess`,
`{reference,secondary}AbsoluteOrbitNumber`, `…HasInputDataException`,
`…IsJointObservation`, `…ListOfObservationModes`, `…PlannedDatatakeId`,
`…PlannedObservationId`.

Everything a provenance record needs is inside the file — **prefer this over
filename parsing.** Three cautions:

- **`processingType` is not data maturity.** It reads `Nominal`, not
  `BETA`/`PROVISIONAL`. Maturity comes from the *collection* you searched
  (`NISAR_L2_GUNW_PROVISIONAL_V1`); there is no in-file field for it, so carry it
  through from the search.
- **`lookDirection` is `Left`** on these granules. Do not assume right-looking.
- **`listOfObservationModes` reads `(NOT SPECIFIED)`** — it will not tell you the
  observation mode. Read polarization from `listOfPolarizations` instead.

`staticLayersDataAccess` gives a URL to a matching **NISAR_L2_STATIC** product.
That is the route to full-resolution geometry layers (incidence angle and
friends) if interpolating the coarse `radarGrid` cube is not good enough.
UNVERIFIED — the static product has not been opened.

### Geometry cube

`/science/LSAR/GUNW/metadata/radarGrid/` — **coarse 3D cube**, nominally 3 km
azimuth × 1 km slant range × 1.5 km height. Requires interpolation to a
full-resolution grid using a DEM.

VERIFIED Aug 2026: the cube is `(height, y, x)` with **20 height levels** and its
own `xCoordinates` / `yCoordinates` in the product CRS, at ~500 m posting — finer
than the nominal figures above. **Its shape varies by track**: (20, 723, 731) on
track 077 against (20, 731, 738) on track 149 over the same AOI. Read the
coordinate arrays and interpolate against them; never index the cube by a
hardcoded shape. `heightAboveEllipsoid` gives the height axis, and the y axis is
descending, which trips interpolators that require ascending coordinates.

Contains `incidenceAngle` (Float32, degrees), `elevationAngle`,
`losUnitVectorX/Y` (Z as `sqrt(1 − X² − Y²)`), `alongTrackUnitVectorX/Y`,
`groundTrackVelocity`, `referenceSlantRange`, `secondarySlantRange`,
`hydrostaticTroposphericPhaseScreen`, `wetTroposphericPhaseScreen`,
`slantRangeSolidEarthTidesPhase`, `perpendicularBaseline`, `parallelBaseline`
(baselines computed only at top and bottom cube heights).

Also `/science/LSAR/GUNW/metadata/orbit/temporalBaseline` and
`orbit/{reference,secondary}/{time,position,velocity}`.

## The phase datum problem

Read this before using `unwrappedPhase` as a feature.

Unwrapping resolves phase only **within** a connected component, up to an arbitrary
integer-cycle offset `2πk_c` that differs per component. On top of that sits a
**global `N·2π`** ambiguity for the map as a whole. Two nested ambiguities. ASF's
Sentinel-1 guide states components "can have phases that differ by an arbitrary and
unknown multiple of 2π."

Consequences:

- **There is no absolute datum.** Without a snow-free scene or a known point change,
  relative phase change cannot be tied to absolute snow depth. Predict **change**.
- **`connectedComponents` is a datum label, not only a quality mask.** Two cells
  with equal phase in different components are not comparable. Carry the label into
  the feature table. If one component dominates and the others are slivers,
  consider keeping only the dominant one — fewer rows, one consistent datum.
- **Restricting to one component is a reduction, not an elimination** — the global
  `N·2π` survives it.

Using raw unwrapped phase as a plain ML feature column, uncalibrated, is defensible
and published: Alabi et al. 2024 (Frontiers) used UAVSAR unwrapped phase this way
with no phase calibration. Scale reference: at L-band (λ = 0.2420 m, θ ≈ 35°,
ε ≈ 1.5) one 2π fringe is roughly 45 cm of depth change — **back-of-envelope,
unverified**, useful only for sanity-checking magnitudes.

### The ionosphere screen is not applied for you

`ionospherePhaseScreen` ships alongside `unwrappedPhase`, and it is tempting to
read it as a correction already folded in. VERIFIED Aug 2026 over Mores Creek that
it is **not** pre-subtracted, and that subtracting it is not obviously an
improvement:

- screen mean **+14.70 rad**, spatial std **0.326 rad**
- `ionospherePhaseScreenUncertainty` **2.197 rad** — about **7x the screen's own
  spatial variation**
- `corr(unwrappedPhase, ionospherePhaseScreen) = +0.572`
- subtracting it reduces the phase std only 1.649 -> 1.486 rad

So the screen is dominated by a large, nearly constant offset that a
change-based target removes anyway, its uncertainty swamps its structure, and
`mask` bit 24 says 60% of AOI pixels had it interpolated rather than measured.
Carry it as a diagnostic column; think hard before hard-subtracting it at
L-band mid-latitude. At low latitudes near solar max the trade is different.

## Resampling rules

| Layer | Native | Method | Why |
|---|---|---|---|
| `unwrappedPhase` | 80 m | none, or **nearest** | preserves value and datum |
| `connectedComponents` | 80 m | **nearest only** | categorical — interpolating labels invents categories |
| `mask` | 80 m | **nearest only** | categorical |
| `coherenceMagnitude` | 20 m | mean + std | real-valued |
| GCOV γ⁰ | 10 m | mean **in linear power** | log-then-average ≠ average-then-log |
| Fine ancillary (LiDAR etc.) | 0.5 m | mean + std | real-valued |

**Never average wrapped phase.** Mean of 359° and 1° is 180°; the answer is 0°.
Average complex vectors, take the argument.

**Never average unwrapped phase across a component boundary** — it blends two
unrelated `2πk` offsets into a number matching no physical phase. That is a
coordinate error, not noise. Safe at 80 m native (one label per cell); a live risk
on the GSLC path where you form 20 m interferograms and bin up.

**Direction matters more than method.** Aggregating many fine values into one
coarse cell is honest. Upsampling coarse phase to a fine grid is fabrication *even
with nearest neighbour* — every value is genuine, but you get thousands of
duplicate rows per real measurement, error bars shrink by √(ratio), and the model
is fit on an `n` that does not exist. Nearest neighbour solves the interpolation
problem and does nothing about the sample-size problem.

Ratio is not alignment. A clean block reduce also needs the coarse cell edges to
land on fine pixel edges. Compute each cell's window from the geotransform; a naive
`.reshape(-1, k, k).mean()` will misalign every cell by a fixed fraction and look
entirely normal.

## GCOV

Posting is bandwidth-dependent:

| Bandwidth | frequencyA posting |
|---|---|
| 5 MHz | 80 m |
| 20 MHz | 20 m |
| 40 MHz | 10 m |

frequencyB is always 80 m (the 5 MHz split-spectrum ionospheric aux channel). Do
not reuse the "5–40 m" figure quoted for GSLC.

Layers under `/science/LSAR/GCOV/grids/frequencyA/`: diagonal terms `HHHH`,
`HVHV`, `VHVH`, `VVVV` (`RHRH`/`RVRV` for compact-pol); off-diagonal complex terms
(`HHHV`, `HHVV`, …) **only for quad-pol**; plus `mask`, `numberOfLooks`,
`rtcGammaToSigmaFactor`, `projection`.

Values are **gamma-nought, RTC-corrected by default**. Use `rtcGammaToSigmaFactor`
to convert to σ⁰.

GCOV also carries incidence angle — a 1 km secondary layer plus its own radarGrid
cube at ~500 m, **finer than GUNW's cube**. Prefer it when pulling both.

UNVERIFIED: `rtcAreaNormalizationFactor` appears in some sources but could not be
confirmed; `rtcGammaToSigmaFactor` is the confirmed name. Granule size is not
authoritatively documented (~1–7 GB from secondary sources) — query CMR.

## Polarization

Mode is set by a pre-planned Reference Observation Plan distributed only as
ArcGIS/KMZ layers — **there is no queryable text table of mode by lat/lon.** The
reliable method is to query CMR for the site and read the `pol` field of real
granule names.

Documented modes (Science Users' Handbook Appendix G, Table 19-1) — UNVERIFIED as a
per-site predictor, and the CONUS row did **not** hold at Mores Creek:

| Target | Pol | Bandwidth |
|---|---|---|
| Background Land (CONUS default) | dual-pol HH/HV | 20+5 MHz → 20 m GCOV |
| US Agriculture | quad-pol | 40+5 MHz → 10 m GCOV |
| Urban / Himalayas | dual-pol HH/HV | 40+5 MHz |
| Land Ice | single-pol HH | 80 MHz or 40+5 |

VERIFIED at Mores Creek: GUNW is `SH` at **40 MHz**, and GCOV is dual-pol HH/HV at
**40+5 MHz → 10 m**, not the 20+5 MHz / 20 m the CONUS row predicts. An earlier
version of this skill asserted 20 m GCOV from that table; it was wrong. **Query,
don't extrapolate.**

GUNW is co-pol only, so on a dual-pol HH/HV site **HH is the interferometric
channel** and HV exists in GCOV with no interferometric counterpart. VERIFIED that
`SV`/VV GUNW granules do exist in the archive (3 of a 2,000-granule sample) — so
"GUNW is always HH" is false as a general claim, even though it holds here.

**Therefore: enumerate the datasets present at runtime rather than hardcoding a
polarization set.** Cheap insurance, correct regardless.

## Traps

1. **Reference/secondary date order is opposite the ARIA/Sentinel-1 convention.**
   NISAR's "reference" is not guaranteed to be the later date. Pair logic ported
   from S1 tooling will silently misorder. (ARIA-tools auto-flips internally.)

2. **Never key on CRID or filename.** CRIDs churn across reprocessing campaigns
   (P00407 → X0500x → P05006 → P05012 → P05023, more in Q4 2026). The same
   acquisition reappears under new granule names. Key on acquisition date + track
   + frame.

3. **Orbit direction is not a first-class search property.** `pathNumber` and
   `frameNumber` are. For direction:
   ```python
   attrs = {a['Name']: a['Values'] for a in granule.umm['AdditionalAttributes']}
   direction = attrs['ASCENDING_DESCENDING'][0]
   ```
   Same fallback for `REFERENCE_ZERO_DOPPLER_START_TIME` /
   `SECONDARY_ZERO_DOPPLER_START_TIME`.

4. **Data maturity — the published windows understate availability.** Documented:
   BETA Oct 17 2025 – Jan 20 2026; backfill "uncertain" Jan 20 – Jun 17 2026;
   PROVISIONAL from Jun 17 2026. VERIFIED contradiction: PROVISIONAL GUNW
   (`P05023`) exists over Mores Creek back to **Nov 3 2025**, inside the nominal
   BETA-only window. **Query the archive; do not reason from the windows.** Still
   record which maturity you used — mixing BETA and PROVISIONAL introduces
   processing-version inconsistency.

5. **Empty search ≠ no acquisition.** The observation plan shows *intended*
   coverage; much acquired data was not released until July 2026.

6. **Known provisional-quality issues:** ionospheric artifacts at low latitudes
   (solar max), phase-unwrapping errors from transmit-gap masking, geolocation
   offsets, radiometric banding, coregistration artifacts in high-deformation areas.

7. **A site may be single-direction in practice.** Mores Creek has 10 usable
   ascending 12-day PROVISIONAL pairs and **zero** descending. Check before
   designing around ascending/descending comparison.

## Granule naming

Pair products (RIFG/RUNW/GUNW/ROFF/GOFF) carry four timestamps — ref start, ref
end, sec start, sec end:

```
NISAR_L2_PR_GUNW_009_149_A_024_010_4000_SH_20260107T123757_20260107T123832_20260119T123758_20260119T123833_P05023_N_F_J_001
  0  1  2   3   4   5  6  7   8    9   10  └─ ref start ─┘ └─ ref end ──┘ └─ sec start ─┘ └─ sec end ───┘ └CRID┘
            │    │   │  │  │   │    │   └─ polarization (SH/SV/DH/DV/QP)
            │    │   │  │  │   │    └───── bandwidth ×10 kHz — 4000 = 40 MHz [1]
            │    │   │  │  │   └────────── secondary cycle  [INFERRED]
            │    │   │  │  └────────────── frame (of 176)
            │    │   │  └───────────────── A = ascending, D = descending
            │    │   └──────────────────── relative orbit / track (1–173)
            │    └──────────────────────── reference cycle
            └───────────────────────────── product
```

[1] An earlier version of this line said **×100 kHz** while keeping the same
`4000 = 40 MHz` example. The two contradict; the example is right and the
multiplier is 10 kHz. Confirmed against `frequencyA/centerFrequency`
(1.239 GHz) and the 40 MHz figure in the Mores Creek inventory below.

```python
p = granule_name.split('_')
cycle, track, direction, frame, sec_cycle, bandwidth, pol = p[4:11]
bandwidth_hz = int(bandwidth) * 10_000        # 4000 -> 40 MHz

import re
ref_start, ref_end, sec_start, sec_end = re.findall(r'\d{8}T\d{6}', granule_name)
```

**There are two fields between direction and bandwidth, not one.** A previous
version of this skill documented only one and read the track slot as cycle —
producing wrong track numbers under a frame heading.

Evidence for the field-5 reading (INFERRED, n=14 Mores Creek granules): `frame`
is constant at `024` across both tracks, correct for a latitude-defined frame at
44°N, while field 5 is **exactly cycle + 1** in every row (004→005, 009→010,
018→019). One cycle = the 12-day repeat, so field 5 is almost certainly the
secondary cycle. This also explains apparent "duplicate frames" on a track: it is
this field incrementing, not a frame variant — so a pair keys cleanly on
(track, ref_date). **Confirm against `identification/frameNumber`.**

Single-date products (RSLC/GSLC/GCOV/SME2) use a one-timestamp template.

## Verified inventory — Mores Creek Summit, ID

VERIFIED Aug 2026 via public CMR. AOI bounding box
`-115.73524, 43.9072, -115.63549, 43.98398` (EPSG:4326), from the NIVAL LiDAR
flight box in EPSG:32611.

- **17 PROVISIONAL GUNW pairs**, Nov 2025 – Apr 2026, CRID `P05023`
- **All ascending.** Tracks **077** and **149**, frame **024**, all `SH` / 40 MHz
- Descending: 4 winter granules (track 114), all BETA, all 24-day → **unusable**
- After 12-day + PROVISIONAL + `04-01` cutoff: **ascending 10, descending 0**
- **Every pair covers the AOI 100%.** Footprints ~63,000 km² vs a 66 km² box —
  the AOI is ~0.1% of a granule (~99 × 105 cells at 80 m out of ~3100 × 3100)
- Track 149 contiguous 12-day run: 20251226 → 20260107 → 20260119 → 20260131 →
  20260212

Reference granule for structural checks:
```
NISAR_L2_PR_GUNW_009_149_A_024_010_4000_SH_20260107T123757_20260107T123832_20260119T123758_20260119T123833_P05023_N_F_J_001
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L2_GUNW_PROVISIONAL_V1/<granule>/<granule>.h5
s3://sds-n-cumulus-prod-nisar-products/NISAR_L2_GUNW_PROVISIONAL_V1/<granule>/<granule>.h5
```
Sidecars: `_QA_SUMMARY.csv`, `_QA_STATS.h5`, `_QA_REPORT.pdf`, `_LATLON.png`,
`.iso.xml`, `.rc.yaml`.

## Tooling

- `earthaccess` — generic CMR search, no NISAR object model. Commonly present.
- `asf_search` — deepest NISAR support (`NISARProduct`, S3 URLs, `dataMaturity`).
  **Verify it is installed**; it was absent from an otherwise complete environment.
- Raw CMR `granules.umm_json` over `urllib` — no dependency, no auth, always works.
- `h5py` + `s3fs`/`fsspec` — the streaming path. `rasterio` `/vsicurl/` for GeoTIFFs.
- **ISCE3** — reference processor, conda-forge only (`conda install -c conda-forge isce3`)
- **nisarqa** — JPL QA package, `github.com/isce-framework/nisarqa`
- **ARIA-tools** — ingests NISAR GUNW, handles the date-order flip
- `h5netcdf` / `xarray.open_datatree` for reading HDF5 as xarray

## Key references

- NISAR Data User Guide: https://nisar-docs.asf.alaska.edu/
- Product specs index: https://nisar-docs.asf.alaska.edu/product-specification/
- GUNW spec (D-102272 Rev E): https://nisar.asf.earthdatacloud.nasa.gov/NISAR-SAMPLE-DATA/DOCS/NISAR_D-102272_RevE_NASA_SDS_Product_Specification_L2_GUNW_Nov8_2024_w-sigs.pdf
- Science Users' Handbook (modes, Appendix G): https://assets.science.nasa.gov/content/dam/science/missions/nisar/nisar-jpl/pdf/NISAR_FINAL_9-6-19.pdf
- CRID reference: https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/nisar/nisar-composite-release-id-crid
- CMR granule search: https://cmr.earthdata.nasa.gov/search/granules.umm_json

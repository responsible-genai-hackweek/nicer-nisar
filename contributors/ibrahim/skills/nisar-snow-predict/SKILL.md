---
name: nisar-snow-predict
description: Run the Mores Creek snow-depth-change predictor end to end — parse a natural-language request into an AOI and season, list real NISAR pairs from CMR, let the user pick one, run the pinned model, and report the result with its actual caveats. Use when someone asks for a snow depth map, snow depth change, or "what did the snow do between X and Y" over Mores Creek Summit, or when interpreting an existing dsd_*.tif product.
---

# Predicting snow depth change

The user-facing half of the system (workflow B in CLAUDE.md). Deterministic,
pinned, and it **never trains**. Your job here is at the two edges — turning a
request into a query, and turning a raster into an honest sentence. Everything
between those is called, not reasoned about.

```
request → list_acquisitions(aoi, season) → user picks → predict_snow_depth() → report
   ^ you                                      ^ them                             ^ you
```

## 1. Parse the request

```python
from nisar_snow import config as C
from nisar_snow.catalog import list_acquisitions

pairs = list_acquisitions(C.AOI_BOUNDS_LONLAT, season=("2025-12-01", "2026-01-31"))
```

Defaults that are almost always right: `aoi_lonlat=C.AOI_BOUNDS_LONLAT` (the NIVAL
flight box) and `season=("2025-11-01", "2026-04-30")`. Only widen the AOI if the
user names somewhere else — and if they do, say plainly that the model was fit at
Mores Creek and the ancillary layers are the NIVAL LiDAR, so it does not transfer.

`list_acquisitions` hits public CMR and needs **no auth**. It applies the peak-SWE
cutoff itself (invariant 3, water year). Do not filter by date again afterwards;
you will double-apply it.

## 2. Present pairs. Do not pick one.

Invariant 2. `list_acquisitions` offers, the user chooses. Show `ref_date`,
`sec_date`, `track`, `baseline_days`, and let them decide. This is the whole point
of the availability-first design — the user picks from what flew rather than naming
a date the satellite did not image.

If they say "just use the best one," that is explicit delegation and you may pick —
say which you picked and why. Silently picking is the failure mode.

Expect ~10 usable ascending pairs, tracks 077 and 149, over Nov 2025 – Apr 2026.
Zero descending are usable here.

## 3. Predict

```python
from nisar_snow.predict import predict_snow_depth, MeltCorrupted
prod = predict_snow_depth(C.AOI_BOUNDS_UTM, granule_id, model_id)
```

Or `python scripts/run_predict.py <model_id> <granule_id>`. Granule bytes need
Earthdata Login via `~/.netrc`; CMR search did not.

`model_id` is pinned — get it from the user, or default to the newest directory in
`models/`. `predict` reads its thresholds from the model card, not from `config.py`,
so editing config cannot change what a pinned model returns.

`model.load()` **refuses** on featurizer or ancillary version drift rather than
warning. That refusal is correct: a version mismatch means the model would see a
different feature distribution than it was fit on. Do not work around it — refit.

### When the gate refuses

`MeltCorrupted` means per-pair coherence says the interferogram is melt- or
rain-on-snow-corrupted. L-band coherence that low over snow carries no signal, and
a prediction would be a plausible-looking raster with nothing in it.

**Do not** lower `gate_coh_median_min`, edit the model card, or quietly retry the
next pair. Report the refusal, show the coherence percentiles, and offer the user
other pairs. The gate existing and firing is the system working.

Note what the gate measures: `usable_fraction` is conditioned on **predictable**
cells (mask + connected-component + ancillary all OK), not on the whole AOI window.
An earlier version divided by the whole window and refused a healthy pair at 0.154 —
the denominator was dominated by two site-constant geometric factors that cannot
indicate melt.

## 4. Report

The product is 3 bands — `dsd_pred_m`, `coherence`, `gate_code` — EPSG:32611, with
23 required provenance tags in the GeoTIFF itself (invariant 5). `gate_code` bits:
`1` low coherence, `2` mask, `4` connected-component, `8` missing/ancillary.

Say, every time:

- **Units are metres of snow depth *change* over the pair interval**, not depth.
- **The map carries an unknown additive constant.** The per-component median is
  removed, so what the raster shows is the *spatial pattern* of change. There is no
  absolute datum — unwrapping fixes phase only within a component, and a global
  `N·2π` survives even that.
- **Only ~half the AOI has a prediction.** The LiDAR box is ~50% nodata padding and
  the ancillary gate follows it. Cite `CELLS_PREDICTED` rather than implying full
  coverage.
- **The error bars do not mean what they look like.** See below.

### What not to claim

The model card reports R² up to 0.92 at 800 m spatial blocks. Do not quote it as
accuracy. Three reasons, all in the card:

1. The residual variogram range is **1480 m**. Any block narrower than that leaks —
   held-out cells are near-duplicates of training cells. The honest column is the
   **E/W-halves** split, ~**0.077 m RMSE**, against a target sd of 0.186 m.
2. `n_eff = 1`. With that correlation range over an 8 km AOI the 1,518 training
   cells are roughly one independent sample, so every confidence interval in the
   card is decorative.
3. **Nothing tests transfer across dates.** The model was fit on one pair, so the
   holdout measures interpolation across space and not the thing CLAUDE.md says
   actually breaks. Predicting a *different* pair than the training one is
   extrapolation of an untested kind.

The `CAVEAT` tag says this in the file. Repeat it; do not soften it.

## Invariants this path must not break

1. **Never trains.** No `fit`, no threshold tuning, no refitting on the query pair.
2. **Never picks the pair** unless explicitly delegated.
3. **Never applies the cutoff here** — that is listing-time only.
7. **Uses `features.build_feature_table`**, the same function training used. Never
   hand-roll a feature step for prediction.

A useful check after any change to this path:
`python scripts/check_determinism.py` — runs predict twice and asserts the bands
and all tags but `CREATED_UTC` are identical.

Related: **`nisar-data-access`** for granule search and HDF5 layer paths,
**`nisar-snow-train`** for refitting, **`nisar-snow-diagnose`** for reading
residuals off a product that already exists.

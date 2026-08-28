---
name: nisar-snow-diagnose
description: Read residuals and failure structure off an existing Mores Creek snow-depth product — where the model is wrong, against coherence, canopy, slope, elevation, and gate code — and decide whether a pattern is a real finding or an artifact of one pair. Use when a product looks wrong, when asked why the model fails somewhere, or when deciding what to change before the next refit.
---

# Diagnosing a product

This is the **only part of the system with agency**. Training and prediction had
every decision deliberately removed so results stay reproducible; diagnostics is
where the loop, the hypotheses, and the judgment live.

It runs on the **analysis side, never in the path that generates a product.** It
reads artifacts that already exist and writes findings. It does not write rasters,
does not refit, does not touch `models/<id>/`. If a diagnosis implies a change, that
change belongs to **`nisar-snow-train`** and produces a new pinned `model_id` — never
an edit to the current one.

There is no `diagnose.py`. This is an exploratory loop over saved artifacts, which is
correct: freezing it into a module would be freezing the part that should stay
flexible.

## What you have to work with

```python
import json, joblib, pandas as pd, numpy as np, rasterio
d    = "models/mcs-dsd-20260828-0f28ba57"
card = json.load(open(f"{d}/model_card.json"))
rows = pd.read_parquet(f"{d}/training_rows.parquet")   # features + dsd_mean + x/y
est  = joblib.load(f"{d}/model.joblib")
with rasterio.open("products/dsd_077_2026-02-07_<model_id>.tif") as ds:
    dsd, coh, gate = ds.read(1), ds.read(2), ds.read(3)
    tags = ds.tags()
```

`rows` carries the bookkeeping columns as well as the features — `cell_id`, `row`,
`col`, `x_center`, `y_center`, `cc_label`, `mask_water`, `mask_sub_ref`,
`mask_sub_sec`, `pair_id`, `track` — which is what makes spatial and
mask-conditioned residual analysis possible without re-streaming.

Residuals must be **out-of-fold**. `cross_validate` returns `(results, oof)`;
in-sample residuals on a ridge with 12 features will look flat and tell you nothing.

## The axes worth looking at

| Condition on | Looking for | What it would mean |
|---|---|---|
| `coh80`, `coh20_std` | error rising as coherence falls | the cell threshold (0.20) is too permissive |
| `chm_mean` | error under canopy | L-band canopy penetration limits — expected, worth quantifying |
| `slope_deg`, `aspect_sin/cos` | error on steep or lee slopes | geometric distortion, or wind redistribution the features miss |
| `elev_m` | structure across the gradient | the orographic term is doing work the radar should |
| `cc_label` | offset between components | datum leakage — should be impossible at `CC_ALLOW = (1,)` |
| `gate_code` bits | error concentrated in one bit's cells | a gate is admitting cells it should drop |
| `x_center`, `y_center` | spatial clustering of residuals | unmodelled spatial process; also re-check the variogram |
| distance to nodata edge | error on the perimeter | boundary artifact in an ancillary layer |

The perimeter one has bitten before. The valid region is ~50% of the box with a long
irregular perimeter, so any neighbourhood operator is a boundary hazard.

## Rules for this loop

**State the hypothesis before the plot.** With 12 features, ~1,500 rows and a dozen
conditioning axes, something will look structured by chance. Deciding what would
count as a finding first is the only defence.

**`n_eff = 1`.** The residual variogram range is 1480 m over an 8 km AOI. A residual
pattern spanning less than ~1.5 km is one correlated blob, not a population of
observations. Do not compute a p-value on 1,518 cells; do not report "significant."

**One pair is one weather event.** Any pattern found here is a pattern in February
2026 on track 077. It becomes a finding when it survives a second pair, and until
then it is a hypothesis with a date attached. Say so explicitly in any writeup.

**Distinguish the three failure classes** before proposing a fix:

1. *Target error* — the LiDAR interval and the InSAR interval do not coincide
   (`lidar_offset_days` in the card). Snow that moved in the gap is unmodelled error
   in `y`, and no feature change fixes it.
2. *Feature error* — a covariate is wrong or missing. Fixable in `features.py` or
   `ancillary.py`; costs a version bump and a refit.
3. *Model error* — the functional form is wrong. The rarest and the one most often
   blamed first.

**A pattern that only appears in `gate_code`-masked cells is not a model finding** —
those cells have no prediction. Check you are not conditioning on cells the model
declined to speak about.

## Precedent — three defects this loop found

All three looked entirely normal in their own output, which is the point.

1. **Slope fabricated across the nodata boundary.** Found by noticing `slope_deg` was
   finite in 10,494 cells while `elev_m` was finite in 5,336. Interior slope maxes at
   34°; the artifact reached 73°, and *all* 111 cells over 45° were boundary cells.
   They passed the ancillary gate, so fabricated values reached the feature table.
2. **A block sweep that could not change its block size**, printing identical RMSE to
   four decimals across 400–3200 m. A def-time default binding.
3. **A melt gate that measured geometry, not coherence** — the denominator was
   dominated by two site-constant factors, so it refused a healthy pair at 0.154 and
   could not have detected melt. Conditioned correctly it reads 0.896.

The shared signature: a number that is *plausible* and internally consistent. Prefer
checks that compare two quantities which must agree (finite counts across layers,
interior vs boundary maxima, a swept parameter against its output) over eyeballing a
single number for reasonableness.

## Output

A finding is: the axis, the effect size in metres, the holdout severity it survives,
the failure class, and what would falsify it. Route it to `nisar-snow-train` if it
implies a refit, or to `nisar-snow-verify` if it implies an archive fact is stale.

Related: **`nisar-snow-train`**, **`nisar-snow-predict`**, **`nisar-snow-verify`**.

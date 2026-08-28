---
name: nisar-snow-train
description: Fit, evaluate, and freeze a Mores Creek snow-depth-change model — matched InSAR/LiDAR pair selection, target aggregation, the holdout scheme that is actually honest, the feature ablation, the challenger rule, and what must go in the model card before an id is pinned. Use when adding a training pair, refitting after a featurizer or ancillary version bump, changing features, or judging whether a reported score is trustworthy.
---

# Training and freezing a model

Workflow A in CLAUDE.md. Offline, iterative, run once, then **frozen**. Unlike the
prediction path this one has real choices in it, and most of them are choices about
not fooling yourself.

```
matched (InSAR pair, LiDAR flight pair)
  → stream GUNW → build_feature_table → attach_target → apply_row_filters
  → cross_validate + robustness_report → pick estimator → freeze → pin model_id
```

Entry point: `python scripts/run_train.py`. Target aggregation is separable and
slow: `python scripts/build_targets.py dsd` caches it first.

## When to retrain

- A new matched pair becomes usable, or you extend to more of the six.
- `FEATURIZER_VERSION` or `ANCILLARY_VERSION` bumps. `model.load()` will refuse the
  old artifact — that refusal is the design working, not a bug to route around.
- `FEATURE_COLUMNS` changes. It is frozen and ordered; changing it mints a new
  `model_id` by construction.

Never edit a frozen model's card to make it load. Refit and pin a new id.

## Choosing pairs

`C.MATCHED_PAIRS` holds the six 12-day InSAR pairs that land within a week of a
LiDAR flight on both ends. `C.DEFAULT_PAIR_INDEX = 5` is the best match
(20260207→20260219, track 077, offsets 0 / +3).

**Temporal offset is unmodelled error in the target, not bookkeeping.** A ±7 day gap
means the LiDAR interval and the InSAR interval do not coincide — snow accumulated
or settled in between, and that difference lands in `dsd_mean` as if it were signal
the radar should have seen. Either weight matches by `abs(off_ref) + abs(off_sec)`
or restrict to the tight ones, and say which you did in the card.

Three November pairs predate the first flight (20251203) and are unusable. Track 149
has a contiguous run: 20251226 → 20260107 → 20260119 → 20260131 → 20260212.

## Holdout — the decision that determines whether the score means anything

**Hold out whole pairs, not pixels, and not spatial blocks if you can avoid it.**
Random pixel splits leak outright; neighbouring 80 m cells are near-duplicates.

| pairs available | scheme | what it measures |
|---|---|---|
| ≥ 2 | **whole-pair holdout** | transfer across dates — the thing that actually breaks |
| 1 | spatial blocks (fallback) | interpolation across space only |

The current frozen model uses the fallback, because it was scoped to one pair. Its
card says so in `holdout_scheme`, in those words. Any multi-pair refit should switch
to `GroupKFold` on pair id and the card text must change with it — a stale
`holdout_scheme` string is a provenance lie.

### If you are stuck with spatial blocks

The block must be **wider than the residual correlation range** or held-out cells
are near-duplicates of training cells and the score is measuring the leak.

```python
rng_m, _, _ = train.variogram_range(x, y, resid)   # 1480 m on the current pair
n_eff = train.effective_n(len(rows), 80.0, rng_m)  # 1 -- yes, one
```

`BLOCK_CELLS = 10` is 800 m, which is *narrower* than 1480 m. That is why
`robustness_report` sweeps 400–3200 m and adds two half-AOI splits. Report the
**halves** column as the headline. The 800 m number is the most optimistic one in
the table and it is not the answer.

Report fold-level CIs (`train.fold_ci`) and the spatial block bootstrap
(`train.block_bootstrap_rmse`) — never `sd/sqrt(n_cells)`, which with `n_eff = 1`
would be off by a factor of ~39.

`cross_validate(df, block=..., groups=...)` — pass the block through. An earlier
version called `block_groups(df)` bare, so the module default bound at def time and
a block sweep silently re-ran identical folds, printing the same RMSE five times to
four decimals. If a sweep produces suspiciously stable numbers, check that first.

## Ablation is not optional

```python
rob = train.robustness_report(rows, range_m=rng_m)   # block_sweep + ablation
```

Terrain alone reaches R² 0.888 here through the **orographic accumulation
gradient** — snow depth change correlates with elevation whether or not the radar
sees anything. Without `terrain_only` and `elevation_only` in the table, the radar
gets credit for elevation's work and the whole result is unfalsifiable.

The claim the ablation licenses, and the only one: `radar_only` beats `terrain_only`
at every holdout severity, and the gap **widens** as the holdout hardens
(0.0612 vs 0.0621 at 800 m → 0.0953 vs 0.1108 at E/W halves). That argues the InSAR
carries signal terrain does not supply. It does not establish that the relation is
causal — one pair cannot separate "L-band phase responds to snow" from "both follow
the same terrain gradient in February 2026."

## Estimator selection

Ridge is the default and the small-data regime justifies it. HGB is fit as a
challenger on the same folds, alongside `baseline_mean`, `baseline_coh`,
`baseline_phase`.

**The challenger is adopted only if it wins on every fold.** Not most folds, not on
pooled RMSE. HGB won 3 of 5 and was rejected. With `n_eff = 1`, a pooled-RMSE
comparison between two models is noise, and "won the average" is exactly how a more
flexible model gets adopted on a dataset that cannot support it.

`RIDGE_ALPHA = 1.0` is fixed a priori. Five spatial folds cannot support nested CV
for hyperparameter selection; tuning alpha on the same folds you report would be
selection on the holdout.

## Freezing

`model_id` is content-addressed over hyperparameters, the training-table hash and
the code version, with a date prefix. `M.save()` writes `model.joblib`,
`model_card.json`, `training_rows.parquet`, and copies `ancillary.npz` **into the
model directory** — so prediction loads the ancillary the model was fit against, not
whatever is in the cache now.

The card must carry, truthfully: `feature_columns`, `featurizer_version`,
`ancillary_version`, `ancillary_source_dates`, `training_data_version`,
`training_granules`, `training_pairs`, `lidar_offset_days`, `data_maturity`,
`cutoff_policy`, `mask_values_kept`, `holdout_scheme`, `thresholds`, `robustness`,
`n_rows`, `n_eff`, `variogram_range_m`, `cv`, `code_version` + `code_dirty`,
`grid` + `grid_hash`.

`thresholds` is what prediction reads instead of `config.py`. Setting them here is
therefore a *pinning* decision, not a tuning knob — and tuning a gate threshold until
a pair passes converts a refusal into a plausible-looking raster. Don't.

Refuse to fit below ~200 usable rows (`run_train.py` exits). A model fit on fewer
cells than that at this correlation length is fitting one blob.

## Watch for

- **Slope at the nodata boundary.** `ancillary.slope_aspect` is NaN-propagating on
  purpose; a `nanmean` fill once produced 73° slopes on the perimeter against a 34°
  interior maximum, and every cell over 45° was a boundary cell. Costs 415 perimeter
  cells. `tests/test_ancillary_slope.py` pins it.
- **`elev_m` finite in far fewer cells than `slope_deg`** — that asymmetry is the
  signature of the bug above returning.
- **Tier-2 columns.** `iono_*`, `mask_bit24`, `perp_baseline_m`, `tropo_*` ride in
  the table but are **not** in `FEATURE_COLUMNS`. The iono screen is a ~+14.7 rad
  near-constant offset whose own uncertainty (2.20 rad) is 7× its spatial variation —
  too uncertain to subtract from phase. Promote one only if a fold shows it helps.

Related: **`nisar-snow-diagnose`** for reading residuals after a fit,
**`nisar-snow-verify`** for re-checking the archive facts the training set rests on,
**`nisar-data-access`** for granule streaming.

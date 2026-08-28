---
name: nisar-snow-verify
description: Re-check the archive and grid facts the Mores Creek pipeline rests on — GUNW CRS, geotransform, grid alignment, chunk shape, connected-component labels, polarization, data maturity, pair inventory — and update the VERIFIED/INFERRED/OPEN tags in CLAUDE.md and the nisar-data-access skill. Use after a NISAR reprocessing campaign, when a CRID changes, when a granule read behaves unexpectedly, or before trusting any claim marked INFERRED.
---

# Re-verifying the facts underneath

Every number in `config.py` and every VERIFIED claim in `CLAUDE.md` was checked
against the live archive in August 2026. The archive is not static: a full validated
reprocessing of the L0–L3 backlog is targeted for **Q4 2026**, and CRIDs have already
churned `P00407 → X0500x → P05006 → P05012 → P05023`.

This skill is the loop that keeps those claims honest.

## Run the reconnaissance

```bash
python scripts/recon.py            # cached
python scripts/recon.py --nocache  # against the live archive -- do this one
```

It re-derives, against a real granule, the facts in `EXPECT`:

```python
EXPECT = dict(epsg=32611, res=80.0, window=(2888, 2994, 3469, 3568), cells=10494,
              frame=24, track=77, direction="Ascending", cc_labels={0, 1},
              col_edge0=-74, row_edge0=-14)
```

A disagreement means one of two things and you must decide which: the **archive
changed** (reprocessing), or the **code drifted**. Check `git log` on
`nisar_snow/gunw.py` and `nisar_snow/config.py` before concluding it was the archive.

`col_edge0=-74, row_edge0=-14` is the grid-alignment fact and the most valuable line
in that table. The AOI's first coarse cell starts 74 LiDAR pixels left and 14 up of
the block boundary — 37.0 m and 7.0 m, 46% and 9% of a cell. A naive
`.reshape(-1,160,160).mean()` is displaced by exactly that and **looks entirely
normal**. `grid.block_edges` computes cumulative edges from both geotransforms;
`test_naive_reshape_is_wrong` pins it. If that test ever gets "simplified," this is
what breaks.

## The tagging discipline

Three tags, used in `CLAUDE.md` and in **`nisar-data-access`**:

- **VERIFIED** — checked against the live archive or a real file, *method stated*.
- **INFERRED** — a consistent pattern across real granules, not read from a spec.
- **OPEN** / **UNVERIFIED** — documentation only, or not looked at.

**Do not promote a tag without doing the check.** Promotion is the failure mode:
an INFERRED claim quoted twice starts reading as established. Demotion is equally
required — if a reprocessing invalidates a VERIFIED fact, move it back and say when.

Precedent for why: the Science Users' Handbook CONUS row predicts dual-pol HH/HV at
20+5 MHz → 20 m GCOV. At Mores Creek it is 40+5 MHz → **10 m**. An earlier version of
the skill asserted 20 m from that table and was wrong. **Query, don't extrapolate.**

## What to re-check, in priority order

1. **Pair inventory.** `list_acquisitions()` should still return 10 usable ascending
   PROVISIONAL 12-day pairs, tracks 077/149, frame 024. Reprocessing changes granule
   *names*, so a drop to zero usually means CRID churn, not lost data.
2. **Data maturity.** PROVISIONAL currently reaches back to Nov 2025 — inside the
   nominal BETA-only window, i.e. the published maturity windows understate
   availability. Re-check; mixing BETA and PROVISIONAL introduces processing-version
   inconsistency. Note `identification/processingType` reads **"Nominal"** and is
   *not* the maturity; maturity comes from the collection searched.
3. **Grid + alignment** — `recon.py`, above.
4. **Chunk shape.** `(512, 512)`. The AOI is one chunk per layer, ~1 MB from a
   2437 MB granule. If chunking changes to full-row, the ~1000× streaming win
   evaporates and the read pattern needs redesign. Always print `.chunks`.
5. **Connected-component labels.** `{0, 1}` only, 0 being the unwrapping-failure
   label; component 1 covers 4,409 of 10,494 AOI cells. `CC_ALLOW = (1,)` costs no
   datum trade-off *because* there is exactly one real component. If reprocessing
   yields several, invariant 8 becomes a live decision again and the "keep the
   dominant component" trade-off has to be made for real.
6. **Polarization.** `HH` here, from `listOfPolarizations` — a cleaner source than
   walking group children. `SV`/VV GUNW granules do exist in the archive, so "GUNW is
   always HH" is false as a general claim even though it holds at this site.
   Invariant 6: enumerate at runtime, never hardcode.
7. **Mask semantics.** uint32 bitfield, fill 255 — *not* the 3-digit UByte the
   pre-launch spec describes. Bits 0–7 subswath digits, 8–15 secondary anomaly,
   16–23 reference anomaly, 24 ionosphere interpolated.

## Key on acquisition, never on name

Trap worth restating because it is the one that survives every other fix:
**never key on CRID or filename.** The same acquisition reappears under new granule
names each campaign. Key on `(acquisition date, track, frame)` — which is what
`naming.pair_key` does. Hardcoded granule ids in `scripts/run_train.py`,
`scripts/run_predict.py` and `scripts/recon.py` are the exception, and they will
break at Q4 2026 reprocessing. That is acceptable for a pinned training record; it is
not acceptable in library code.

## After a change

- Update `config.py`, then the VERIFIED table in `CLAUDE.md`, then
  **`nisar-data-access`** — all three, or they disagree.
- Record *when* and *how* it was checked, not just the value.
- If a fact a frozen model depends on has changed, the model is not automatically
  invalid — but its card now describes an archive that no longer exists. Note it;
  refit via **`nisar-snow-train`** if the change touches features or the grid.

## Still genuinely open

- **Does this transfer across dates?** Untested and untestable on one pair. The
  single most important unknown in the project.
- **Is the phase→ΔSD relation causal or coincidental at this site?**
- **`NISAR_L2_STATIC`.** `identification/staticLayersDataAccess` points at a matching
  static product that would supply full-resolution incidence angle instead of
  interpolating the ~500 m `radarGrid` cube. Never opened.

Related: **`nisar-data-access`** for the full archive reference and search recipes.

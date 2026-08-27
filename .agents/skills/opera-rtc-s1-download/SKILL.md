---
name: opera-rtc-s1-download
description: Download OPERA L2 RTC-S1 VV Cloud-Optimized GeoTIFFs from ASF via earthaccess. Use when fetching Sentinel-1 RTC backscatter, estimating stack size, or when ASF datapool returns 401 Unauthorized. Prefers ~/.netrc over EARTHDATA_TOKEN, HTTPS _VV.tif URLs only, and a one-file size check before bulk download.
---

# OPERA RTC-S1 VV download

Working example in this repo (pixi):

- Size check: `contributors/ajoros/opera_vv_size_check.py`
- Bulk pull: `contributors/ajoros/download_opera_rtc_vv.py`

AOI numbers and polygons: [references/aois.md](references/aois.md).

## When not to use this

- NISAR GCOV / GSLC / GUNW / SME2 — different product, GB-class files.
- Glacier velocity — GOFF / offsets, not RTC.
- Melt-onset math — `snow_depth_retrieval` / `amplitude` (once those exist).
- Davis Fire 2024 pre/during/post — there is no NISAR; this skill is the right **S1** path.

## Procedure

1. Confirm product: `short_name="OPERA_L2_RTC-S1_V1"`.
2. Search with a tight bbox or closed CCW polygon. Loop calendar years with
   `temporal=(f"{year}-02-01", f"{year}-08-31")` so Sep–Jan is not included.
   `count=-1`.
3. Collect **HTTPS `_VV.tif` only** (`data_links(access="external")`). Prefer
   `asf.alaska.edu`. Do not pass granule objects to `earthaccess.download` —
   that pulls VV + VH + mask + h5.
4. **Size check:** download one VV COG, print bytes, multiply by catalog count.
   CMR often has no file size. Do not start a multi-GB pull until that number exists.
5. Login: `unset EARTHDATA_TOKEN`; `earthaccess.login(strategy="netrc")`;
   `earthaccess.download(urls, provider="ASF")`. Do not use `earthaccess.open()`
   for ASF datapool (Bearer / fsspec HEAD → URS OAuth 401).
6. Write files as `{root}/{site}/{T###}/{yyyy}/OPERA_..._VV.tif`.
   `T###` is Sentinel-1 relative orbit. Do not mix tracks in one melt series.
7. Re-run is safe: skip files ≳ 1 MiB; delete smaller partials and retry.
   Do not commit the stack (`contributors/ajoros/data/` is gitignored).

## Auth

- Token is enough for **CMR search**.
- ASF datapool HTTPS redirects to `urs.earthdata.nasa.gov/oauth/authorize`
  (client for `cumulus.asf.alaska.edu`). That needs username/password cookies
  from `~/.netrc`, not a Bearer token.
- If both token and netrc exist, **drop the token** for download.
- Still 401 after netrc: Earthdata profile → Applications → authorize ASF.
- Never paste Earthdata tokens or passwords into chat, git, or the skill.

## Guardrails

- Default to **one relative orbit** per site unless the user asked for all tracks.
- Do not download Pioneer Fire and MCS together (same orbits; Pioneer bbox is larger).
- Do not use the padded Washoe Valley box for Davis; see references.

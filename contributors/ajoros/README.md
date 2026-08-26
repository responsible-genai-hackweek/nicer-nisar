# Andrew Joros (@ajoros)

Co-lead. Tracking: Davis Fire AOI (coverage done), status-quo agent baseline.

## Setup (local)

- Env: pixi (`pixi install` / `pixi run`). Do not bring back `environment.yml`.
- Earthdata: `earthaccess.login(strategy="environment")` via `EARTHDATA_TOKEN` (not username/password in the hidden prompt). Token lives in the shell, not in git.

## Davis Fire (AOI 1)

- Place: Washoe Valley, NV (Davis Creek / west of I-580)
- Burn: 2024-09-07 to 2024-09-25 (~5,800 acres, 100% contained 2024-09-25)
- Bbox (lonmin, latmin, lonmax, latmax): `-119.92, 39.24, -119.72, 39.40`

NISAR launched **2025-07-30**. There are **no** NISAR granules during the 2024 burn. First science scenes over this bbox: **2025-11-01**. Latest seen in CMR (2026-08-26): **2026-08-20**. This is **post-fire only** (~14 months after containment). Pre/post NISAR for the burn itself is not possible; use another SAR for Sep 2024.

Granule date spans (metadata only, no download): [nisar-coverage-davis.md](nisar-coverage-davis.md).

**Beta vs provisional:** same product family, different processing maturity. Beta is early, not fully calibrated (workflow familiarization). Provisional is later software (CRID P05023+), calibrated and only partly validated — use that for analysis. Do not mix beta and provisional in one time series. After ~Jan 2026 on this AOI you mostly only have provisional. GOFF / RIFG / RUNW / ROFF: none over this box.

## Snow (team, not this folder)

Mores Creek Summit is the snow AOI (Ibrahim / Hp Marshall). Eric Gagliano’s [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset) is a Sentinel-1 C-band global runoff-onset dataset (ESSD 2026) we may use as a baseline to compare or extend with NISAR L-band.

## Still to do here

- Status-quo agent prompt on Davis Fire (write fail cases)

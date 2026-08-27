# Andrew Joros (@ajoros)

Co-lead. Tracking: Davis Fire AOI (coverage done), status-quo agent baseline.

## Setup (local)

- Env: pixi (`pixi install` / `pixi run`). Do not bring back `environment.yml`.
- Earthdata: CMR **search** can use `EARTHDATA_TOKEN`. ASF **datapool download** needs `~/.netrc` (`earthaccess.login(strategy="netrc")`). Unset the token before download or ASF returns 401. Never put tokens in git.

## Davis Fire (AOI 1)

- Place: Winters Creek + Davis Creek basins, Mt Rose / eastern Sierra (Eastern Lake Tahoe). Combined **8.49 km²**. Shapefiles: [aoi/gis/](aoi/gis/) (also Dropbox `IRP_NISAR_AOI_Winters_Davis.zip`).
- Burn: 2024-09-07 to 2024-09-25 (~5,800 acres, 100% contained 2024-09-25)
- Envelope (W,S,E,N): `-119.88496, 39.29819, -119.82518, 39.32630` — use this, not the older padded Washoe Valley box

NISAR launched **2025-07-30**. There are **no** NISAR granules during the 2024 burn. First science scenes over the old padded bbox: **2025-11-01**. Latest seen in CMR (2026-08-26): **2026-08-20**. NISAR is **post-fire only**. Pre/during/post of the burn: **Sentinel-1** (see below).

- NISAR date spans (padded bbox, metadata only): [nisar-coverage-davis.md](nisar-coverage-davis.md)
- Sentinel-1 over the shapefile envelope, Aug–Oct 2024 inventory: [sentinel1-coverage-davis.md](sentinel1-coverage-davis.md). Product: OPERA RTC-S1. Pair: **2024-09-04** (pre) vs **2024-09-28** (post-containment).
- OPERA RTC-S1 **VV** time series (Feb–Aug 2017–2026, Davis + MCS, all tracks): local only under `data/opera-rtc-s1-vv/` (~11 GiB, gitignored). Scripts: [opera_vv_size_check.py](opera_vv_size_check.py), [download_opera_rtc_vv.py](download_opera_rtc_vv.py).

**Beta vs provisional:** same product family, different processing maturity. Beta is early, not fully calibrated (workflow familiarization). Provisional is later software (CRID P05023+), calibrated and only partly validated — use that for analysis. Do not mix beta and provisional in one time series. After ~Jan 2026 on this AOI you mostly only have provisional. GOFF / RIFG / RUNW / ROFF: none over this box.

## Snow (team, not this folder)

Mores Creek Summit is the snow AOI (Ibrahim / Hp Marshall). Eric Gagliano’s [global_snowmelt_runoff_onset](https://github.com/egagli/global_snowmelt_runoff_onset) is a Sentinel-1 C-band global runoff-onset dataset (ESSD 2026) we may use as a baseline to compare or extend with NISAR L-band.

## Still to do here

- Status-quo agent prompt on Davis Fire (write fail cases)

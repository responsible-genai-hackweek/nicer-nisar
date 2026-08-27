#!/usr/bin/env python3
"""One-file size check for OPERA RTC-S1 VV COG. Does not pull the stack.

Requires EARTHDATA_TOKEN in the environment (or ~/.netrc + strategy netrc).

  export EARTHDATA_TOKEN='...'
  pixi run python contributors/ajoros/opera_vv_size_check.py
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import earthaccess

BBOX = (-119.88496, 39.29819, -119.82518, 39.32630)  # Winters+Davis envelope
# Catalog counts: OPERA RTC, Feb 1–Aug 31, 2017–2026
COUNTS = {
    "davis_all_paths": 1200,
    "davis_path_144": 246,
    "davis_path_137": 481,
    "mcs_all_paths": 593,
    "mcs_path_93": 222,
    "mcs_path_71": 371,
}


def main() -> None:
    # ASF datapool uses URS OAuth cookies from username/password, not a Bearer token.
    # If EARTHDATA_TOKEN is still exported, earthaccess.open() 401s on /oauth/authorize.
    if os.environ.get("EARTHDATA_TOKEN"):
        print("warning: ignoring EARTHDATA_TOKEN; ASF download needs netrc password")
        del os.environ["EARTHDATA_TOKEN"]
    earthaccess.login(strategy="netrc")

    granules = earthaccess.search_data(
        short_name="OPERA_L2_RTC-S1_V1",
        bounding_box=BBOX,
        temporal=("2024-02-01", "2024-02-15"),
        count=1,
    )
    if not granules:
        raise SystemExit("No OPERA RTC granule in the sample window.")

    urls: list[str] = []
    try:
        urls = granules[0].data_links(access="external") or granules[0].data_links() or []
    except Exception:
        pass
    if not urls:
        umm = granules[0].get("umm") or {}
        urls = [
            ru.get("URL") or ""
            for ru in umm.get("RelatedUrls") or []
        ]
    vv = [u for u in urls if u.startswith("http") and u.endswith("_VV.tif")]
    if not vv:
        raise SystemExit("No HTTPS _VV.tif link on the granule.")

    url = vv[0]
    tmp = Path(tempfile.mkdtemp(prefix="opera_vv_"))
    downloaded = earthaccess.download([url], local_path=tmp, provider="ASF", threads=1)
    if not downloaded:
        raise SystemExit("download returned no files")
    path = Path(downloaded[0])
    n = path.stat().st_size
    print(f"downloaded {path.name}")

    print(f"VV_bytes={n}  VV_MiB={n / 1024 / 1024:.2f}")
    print(url.rsplit("/", 1)[-1])
    print("--- scaled (this file size × catalog counts, VV only) ---")
    for name, count in COUNTS.items():
        gb = count * n / 1e9
        print(f"{name:22s}  n={count:4d}  ~{gb:.2f} GB")
    both_one = COUNTS["davis_path_144"] + COUNTS["mcs_path_93"]
    both_all = COUNTS["davis_all_paths"] + COUNTS["mcs_all_paths"]
    print(f"{'both_one_path_each':22s}  n={both_one:4d}  ~{both_one * n / 1e9:.2f} GB")
    print(f"{'both_all_paths':22s}  n={both_all:4d}  ~{both_all * n / 1e9:.2f} GB")


if __name__ == "__main__":
    main()

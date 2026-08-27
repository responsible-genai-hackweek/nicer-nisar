#!/usr/bin/env python3
"""Download OPERA RTC-S1 VV COGs for Davis and MCS (Feb–Aug, 2017–2026).

Layout:
  contributors/ajoros/data/opera-rtc-s1-vv/{davis,mcs}/{T137}/{2024}/*.tif

Re-run is safe: existing files >1 MiB are skipped. ASF datapool needs ~/.netrc
(not EARTHDATA_TOKEN).

  pixi run python contributors/ajoros/download_opera_rtc_vv.py
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

import earthaccess

SHORT_NAME = "OPERA_L2_RTC-S1_V1"
YEARS = range(2017, 2027)
ROOT = Path(__file__).resolve().parent / "data" / "opera-rtc-s1-vv"
MIN_BYTES = 1_000_000
NAME_RE = re.compile(r"OPERA_L2_RTC-S1_(T\d+)-\d+-IW\d+_(\d{4})\d{4}T")

# Winters + Davis Creek envelope
DAVIS_BBOX = (-119.88496, 39.29819, -119.82518, 39.32630)

# MCS_survey2 ring from contributors/HPMARSHALL/MCS_domain.kml (CCW, closed)
MCS_POLY = [
    (-115.6424376856718, 43.93758446194689),
    (-115.6832872807049, 43.97480214169399),
    (-115.7304987363249, 43.95571699539472),
    (-115.6857018337183, 43.91364532347756),
    (-115.6424376856718, 43.93758446194689),
]

SITES = {
    "davis": {"bounding_box": DAVIS_BBOX, "expected": 1200},
    "mcs": {"polygon": MCS_POLY, "expected": 593},
}


def _vv_https(granule) -> str | None:
    urls: list[str] = []
    try:
        urls = granule.data_links(access="external") or granule.data_links() or []
    except Exception:
        pass
    if not urls:
        umm = granule.get("umm") or {}
        urls = [ru.get("URL") or "" for ru in umm.get("RelatedUrls") or []]
    https = [
        u
        for u in urls
        if isinstance(u, str) and u.startswith("http") and u.endswith("_VV.tif")
    ]
    asf = [u for u in https if "asf.alaska.edu" in u]
    return (asf or https or [None])[0]


def _dest_for(site: str, url: str) -> Path | None:
    name = url.rsplit("/", 1)[-1]
    m = NAME_RE.search(name)
    if not m:
        return None
    return ROOT / site / m.group(1) / m.group(2) / name


def _collect(site: str, spatial: dict) -> list[str]:
    seen: dict[str, str] = {}  # filename -> url
    for year in YEARS:
        kwargs = dict(
            short_name=SHORT_NAME,
            temporal=(f"{year}-02-01", f"{year}-08-31"),
            count=-1,
            **spatial,
        )
        granules = earthaccess.search_data(**kwargs)
        n_vv = 0
        for g in granules:
            url = _vv_https(g)
            if not url:
                continue
            name = url.rsplit("/", 1)[-1]
            seen[name] = url
            n_vv += 1
        print(f"  {site} {year}: {len(granules)} granules, {n_vv} VV", flush=True)
    return list(seen.values())


def _download_group(dest_dir: Path, urls: list[str]) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        earthaccess.download(
            urls, local_path=dest_dir, provider="ASF", threads=4
        )
        return
    except Exception as e:
        print(f"  batch fail {dest_dir.name}: {e!r}; retry one-by-one", flush=True)
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        dest = dest_dir / name
        if dest.exists() and dest.stat().st_size >= MIN_BYTES:
            continue
        try:
            earthaccess.download(
                [url], local_path=dest_dir, provider="ASF", threads=1
            )
        except Exception as e:
            print(f"  FAIL {name}: {e!r}", flush=True)


def main() -> None:
    if os.environ.get("EARTHDATA_TOKEN"):
        print("warning: ignoring EARTHDATA_TOKEN; ASF download needs netrc")
        del os.environ["EARTHDATA_TOKEN"]
    earthaccess.login(strategy="netrc")
    ROOT.mkdir(parents=True, exist_ok=True)

    by_dir: dict[Path, list[str]] = defaultdict(list)
    skipped = 0
    for site, spatial in SITES.items():
        print(f"search {site} (expect ~{spatial.pop('expected')})", flush=True)
        urls = _collect(site, spatial)
        print(f"  {site} unique VV: {len(urls)}", flush=True)
        for url in urls:
            dest = _dest_for(site, url)
            if dest is None:
                print(f"  skip unparsed {url.rsplit('/', 1)[-1]}", flush=True)
                continue
            if dest.exists() and dest.stat().st_size >= MIN_BYTES:
                skipped += 1
                continue
            if dest.exists():
                dest.unlink()
            by_dir[dest.parent].append(url)

    todo = sum(len(v) for v in by_dir.values())
    print(f"skip existing={skipped}  download={todo}", flush=True)
    for i, (dest_dir, urls) in enumerate(by_dir.items(), 1):
        rel = dest_dir.relative_to(ROOT)
        print(f"[{i}/{len(by_dir)}] {rel}  n={len(urls)}", flush=True)
        _download_group(dest_dir, urls)

    n = len(list(ROOT.rglob("*_VV.tif")))
    bytes_ = sum(p.stat().st_size for p in ROOT.rglob("*_VV.tif"))
    print(f"done: {n} VV files, {bytes_ / 1e9:.2f} GB under {ROOT}", flush=True)


if __name__ == "__main__":
    main()

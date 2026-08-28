"""``python -m nisar_cubes <command>`` — the operational entry points.

    inventory   refresh the granule inventory from CMR (and diff against ASF)
    build       index everything not yet in the repository (resumable, idempotent)
    catalog     rebuild the STAC / GeoParquet catalog from the repository
    append      inventory + build + catalog — the thing to run after each 12-day cycle
    validate    group checks and a random round-trip against h5py
    drift       HEAD every referenced granule and compare with the inventory
    compact     expire old snapshots (keep last N + monthly tags) and collect garbage
    backfill-coords  add granule/coverage/ctr time coordinates to groups built before they existed
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings

from . import config as C


def _settings(a) -> C.Settings:
    kw = dict(region_name=a.region, workers=a.workers, batch_granules=a.batch)
    if a.bucket:
        kw["bucket"] = a.bucket
    if a.prefix:
        kw["prefix"] = a.prefix
    return C.Settings(**kw)


def main(argv=None):
    p = argparse.ArgumentParser(prog="nisar_cubes", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--region", default="wna", choices=sorted(C.REGIONS))
    p.add_argument("--bucket", help="override NISAR_CUBES_BUCKET")
    p.add_argument("--prefix", help="override NISAR_CUBES_PREFIX (root; region name is appended)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--batch", type=int, default=40, help="commit after this many granules")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("inventory").add_argument("--no-asf", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--limit", type=int, help="only the N largest cube keys")
    b.add_argument("--only", nargs="*", help="track-frames, e.g. D172_F065")
    b.add_argument("--bands", nargs="*", default=["freqA", "freqB"])
    b.add_argument("--no-catalog", action="store_true")
    sub.add_parser("catalog").add_argument("--no-upload", action="store_true")
    ap = sub.add_parser("append")
    ap.add_argument("--no-asf", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("-n", type=int, default=10)
    v.add_argument("--schemes", nargs="*", default=["s3"])
    sub.add_parser("drift")
    sub.add_parser("backfill-coords")
    c = sub.add_parser("compact")
    c.add_argument("--keep-last", type=int, default=10)
    c.add_argument("--dry-run", action="store_true")

    a = p.parse_args(argv)
    warnings.filterwarnings("ignore")
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S", stream=sys.stdout,
    )
    for noisy in ("botocore", "urllib3", "s3fs", "fsspec", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    import icechunk

    icechunk.set_logs_filter("error")
    s = _settings(a)
    from . import inventory

    if a.cmd == "inventory":
        inv, rep = inventory.refresh(s, asf=not a.no_asf)
        print(inventory.summary(inv).head(30).to_string())
        print(json.dumps({k: v for k, v in rep.items() if k not in ("asf_only", "cmr_only")}))
        if rep.get("asf_only") or rep.get("cmr_only"):
            print("ASF-only:", rep.get("asf_only"), "\nCMR-only:", rep.get("cmr_only"))
        return 0

    if a.cmd in ("build", "append"):
        from . import build, catalog

        if a.cmd == "append":
            inv, _ = inventory.refresh(s, asf=not a.no_asf)
        else:
            inv = inventory.load(s)
        df = build.build_region(s, inv, bands=tuple(getattr(a, "bands", ["freqA", "freqB"])),
                                limit=getattr(a, "limit", None), only=getattr(a, "only", None))
        if len(df):
            df.to_csv(s.local_dir / "last_build.csv", index=False)
        if not getattr(a, "no_catalog", False):
            catalog.refresh(s, inv)
        return 0 if not (s.local_dir / "build_failures.csv").exists() else 1

    if a.cmd == "catalog":
        from . import catalog

        inv = inventory.load(s) if s.inventory_path.exists() else None
        gdf = catalog.refresh(s, inv, upload=not a.no_upload)
        print(gdf[["group", "n_times", "start", "end", "epsg", "posting_m", "local_overpass"]].head(40).to_string())
        return 0

    if a.cmd == "validate":
        from . import validate

        groups = validate.check_groups(s)
        inv = inventory.load(s)
        rt = validate.round_trip(s, inv, n=a.n, schemes=tuple(a.schemes))
        print(rt.to_string())
        ok = bool(groups["ok"].all()) and bool(rt["identical"].all())
        print("VALIDATION", "PASSED" if ok else "FAILED")
        return 0 if ok else 1

    if a.cmd == "drift":
        from . import ops

        df = ops.drift_check(s, inventory.load(s))
        df.to_csv(s.local_dir / "drift.csv", index=False)
        return 0 if bool(df["ok"].all()) else 1

    if a.cmd == "backfill-coords":
        from . import ops

        print("groups backfilled:", ops.backfill_time_coords(s))
        return 0

    if a.cmd == "compact":
        from . import ops

        print(json.dumps(ops.compact(s, keep_last=a.keep_last, dry_run=a.dry_run), default=str, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

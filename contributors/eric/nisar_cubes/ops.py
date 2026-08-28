"""Operational chores: retention/compaction and source-drift detection."""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from . import auth
from . import config as C

log = logging.getLogger(__name__)


def compact(settings: C.Settings, *, keep_last: int = 10, keep_monthly: bool = True, dry_run: bool = False) -> dict:
    """Expire old snapshots and collect garbage, keeping the last ``keep_last``
    and (as tags) one snapshot per calendar month.

    Every append rewrites a manifest and Icechunk keeps the old one; this is
    the retention rule the README asked for instead of "expire everything".
    """
    repo = auth.open_repo(settings, schemes=())
    hist = list(repo.ancestry(branch="main"))  # newest first
    if len(hist) <= keep_last:
        log.info("%d snapshots, nothing to expire", len(hist))
        return {"snapshots": len(hist), "expired": 0}

    tagged = []
    if keep_monthly:
        existing = set(repo.list_tags())
        seen = set()
        for s in hist:  # newest first → first seen per month is that month's latest
            key = s.written_at.strftime("%Y-%m")
            if key in seen:
                continue
            seen.add(key)
            tag = f"monthly-{key}"
            if tag not in existing and not dry_run:
                repo.create_tag(tag, s.id)
            tagged.append(tag)

    cutoff = hist[keep_last - 1].written_at  # everything strictly older than the Nth newest
    if dry_run:
        n = sum(1 for s in hist if s.written_at < cutoff)
        log.info("dry run: would expire %d snapshots older than %s (tags kept: %s)", n, cutoff, tagged)
        return {"snapshots": len(hist), "would_expire": n, "tags": tagged}
    expired = repo.expire_snapshots(older_than=cutoff)
    summary = repo.garbage_collect(delete_object_older_than=dt.datetime.now(dt.timezone.utc))
    log.info("expired %d snapshots; gc: %s", len(expired), summary)
    return {"snapshots": len(hist), "expired": len(expired), "tags": tagged, "gc": str(summary)}


def drift_check(settings: C.Settings, inv: pd.DataFrame) -> pd.DataFrame:
    """HEAD every referenced granule and compare its size to the inventory.

    Cheap (one request per granule, concurrent) and catches a republished or
    withdrawn granule before a user's read does.  ``last_updated_at`` on the
    virtual references is the per-read backstop.
    """
    import asyncio

    import obstore as obs

    from . import api

    cat = api.load_catalog(settings)
    names = sorted({g for gs in cat["granules"] for g in gs})
    idx = inv.set_index("name")
    store = auth.nisar_s3_store()

    async def head_all():
        sem = asyncio.Semaphore(32)

        async def one(name):
            key = idx.loc[name, "url_s3"].split(f"{C.NISAR_BUCKET}/", 1)[1]
            async with sem:
                try:
                    h = await obs.head_async(store, key)
                    return dict(name=name, exists=True, size=h["size"], last_modified=h["last_modified"])
                except Exception as exc:  # noqa: BLE001
                    return dict(name=name, exists=False, size=None, last_modified=None, error=repr(exc)[:120])

        return await asyncio.gather(*(one(n) for n in names))

    df = pd.DataFrame(asyncio.run(head_all()))
    df["expected_size"] = df["name"].map(idx["size_bytes"])
    df["ok"] = df["exists"] & (df["size"] == df["expected_size"])
    df["in_inventory"] = df["name"].isin(idx.index)
    bad = df[~df["ok"]]
    log.info("drift: %d referenced granules, %d missing/changed", len(df), len(bad))
    for _, r in bad.iterrows():
        log.error("  %s exists=%s size=%s expected=%s", r["name"], r["exists"], r["size"], r["expected_size"])
    return df


def backfill_time_coords(settings: C.Settings, *, commit_every: int = 150) -> int:
    """Add ``granule`` / ``coverage`` / ``ctr`` coordinates to groups built before
    :func:`build.concat_cube` wrote them, and drop the per-granule statistics attrs
    the first granule leaked onto every cube.  Metadata-only commits; idempotent."""
    import numpy as np
    import xarray as xr
    import zarr

    from .build import PER_GRANULE_ATTRS, list_groups, read_group_attrs
    from .naming import parse_granule

    repo = auth.open_repo(settings, schemes=())
    session = repo.writable_session("main")
    done = staged = 0
    for scheme in C.SCHEMES:
        for tf in list_groups(session.store, scheme):
            for mp in list_groups(session.store, f"{scheme}/{tf}"):
                for leaf in list_groups(session.store, f"{scheme}/{tf}/{mp}"):
                    g = f"{scheme}/{tf}/{mp}/{leaf}"
                    zg = zarr.open_group(session.store, path=g, mode="r+")
                    if "granule" in zg:
                        continue
                    names = (read_group_attrs(session.store, g) or {}).get("granules", [])
                    if len(names) != zg["time"].shape[0]:
                        log.error("%s: ledger %d != time %d, skipped", g, len(names), zg["time"].shape[0])
                        continue
                    parsed = [parse_granule(n) for n in names]
                    # xarray's to_zarr(mode="a") REPLACES the group's attributes with the
                    # Dataset's, so carry them through explicitly.
                    group_attrs = dict(zg.attrs)
                    xr.Dataset(
                        {
                            "granule": ("time", np.array(names, dtype=object)),
                            "coverage": ("time", np.array([p.coverage for p in parsed], dtype=object)),
                            "ctr": ("time", np.array([p.ctr for p in parsed], dtype="int16")),
                        },
                        attrs=group_attrs,
                    ).to_zarr(session.store, group=g, mode="a", zarr_format=3, consolidated=False)
                    zarr.open_group(session.store, path=g, mode="r+").attrs.update(group_attrs)
                    for v in C.BACKSCATTER_VARS:
                        if v in zg:
                            arr = zarr.open_array(session.store, path=f"{g}/{v}", mode="r+")
                            keep = {k: val for k, val in arr.attrs.items() if k not in PER_GRANULE_ATTRS}
                            keep["coordinates"] = "granule coverage ctr"
                            arr.attrs.clear()
                            arr.attrs.update(keep)
                    done += 1
                    staged += 1
                    if staged >= commit_every:
                        session.commit(f"backfill time coordinates ({staged} groups)")
                        session = repo.writable_session("main")
                        staged = 0
    if staged:
        session.commit(f"backfill time coordinates ({staged} groups)")
    log.info("backfilled %d groups", done)
    return done


def restore_group_attrs(settings: C.Settings, *, before_message_prefix: str = "backfill time coordinates") -> int:
    """Copy every cube group's attributes from the last snapshot *before* the first
    commit whose message starts with ``before_message_prefix`` onto the current
    ``main``.  Repairs the ledger after an attribute-clobbering write; Icechunk's
    history is the backup."""
    import zarr

    from .build import list_groups

    repo = auth.open_repo(settings, schemes=())
    hist = list(repo.ancestry(branch="main"))  # newest first
    idx = [i for i, sn in enumerate(hist) if sn.message.startswith(before_message_prefix)]
    if not idx:
        log.info("no commits matching %r; nothing to restore", before_message_prefix)
        return 0
    good = hist[max(idx) + 1]  # parent of the earliest matching commit
    src = repo.readonly_session(snapshot_id=good.id).store
    session = repo.writable_session("main")
    n = 0
    for scheme in C.SCHEMES:
        for tf in list_groups(src, scheme):
            for mp in list_groups(src, f"{scheme}/{tf}"):
                for leaf in list_groups(src, f"{scheme}/{tf}/{mp}"):
                    g = f"{scheme}/{tf}/{mp}/{leaf}"
                    attrs = dict(zarr.open_group(src, path=g, mode="r").attrs)
                    if not attrs:
                        continue
                    cur = zarr.open_group(session.store, path=g, mode="r+")
                    if dict(cur.attrs) != attrs:
                        cur.attrs.update(attrs)
                        n += 1
    if n:
        session.commit(f"restore group attributes from snapshot {good.id}")
    log.info("restored attributes on %d groups from %s (%s)", n, good.id, good.message[:60])
    return n

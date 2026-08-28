"""Build and append virtual cubes, one Icechunk group per track-frame and band.

The unit of work is ``build_group``: given the inventory rows of one cube key
and a band, index whatever is not yet in the group and stage it in the session.
``build_region`` walks every cube key, commits every ``batch_granules`` granules
so a killed run loses at most one batch, and treats the repository itself as
the ledger of what is done.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xarray as xr

from . import auth
from . import config as C
from .naming import group_path, parse_granule

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Virtualising granules (process pool; see README "On parallelizing the build")
# ---------------------------------------------------------------------------

_REGISTRY = None


def _pool_init():
    global _REGISTRY
    warnings.filterwarnings("ignore")
    import icechunk

    icechunk.set_logs_filter("error")
    _REGISTRY = auth.nisar_registry()


def _virtualize(args):
    url, hdf_group = args
    global _REGISTRY
    if _REGISTRY is None:
        _pool_init()
    import virtualizarr as vz
    from virtualizarr.parsers import HDFParser

    parser = HDFParser(group=hdf_group, drop_variables=list(C.DENY_VARIABLES))
    last_err = None
    for attempt in range(3):  # transient S3 errors are routine (README)
        try:
            return vz.open_virtual_dataset(url, registry=_REGISTRY, parser=parser)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"virtualize failed for {url}") from last_err


class ManifestBuilder:
    """A persistent process pool, so 442 five-granule track-frames do not each pay for one."""

    def __init__(self, workers: int = 8):
        self.workers = workers
        self._ex = None

    def __enter__(self):
        if self.workers > 1:
            self._ex = ProcessPoolExecutor(self.workers, initializer=_pool_init)
        return self

    def __exit__(self, *exc):
        if self._ex:
            self._ex.shutdown(wait=True, cancel_futures=True)

    def build(self, urls, band: str) -> list[xr.Dataset]:
        args = [(u, C.HDF_GROUPS[band]) for u in urls]
        if self._ex:
            return list(self._ex.map(_virtualize, args))
        return [_virtualize(a) for a in args]


# ---------------------------------------------------------------------------
# Grids and cubes
# ---------------------------------------------------------------------------


def grid_signature(vds: xr.Dataset) -> tuple[int, int, float, float, float]:
    x, y = vds.xCoordinates.values, vds.yCoordinates.values
    return (int(y.size), int(x.size), round(float(x[0]), 3), round(float(y[0]), 3), round(float(x[1] - x[0]), 3))


def grid_id(sig) -> str:
    return hashlib.sha1(json.dumps(sig).encode()).hexdigest()[:6]


def epsg_of(vds: xr.Dataset) -> int:
    return int(vds.projection.attrs["epsg_code"])


#: Per-granule statistics NISAR writes on each raster.  ``compat="override"`` would
#: silently carry the *first* granule's onto the whole cube, so they are dropped.
PER_GRANULE_ATTRS = ("max_value", "mean_value", "min_value", "sample_stddev")


def concat_cube(members: list[tuple[pd.Timestamp, str, xr.Dataset]]) -> xr.Dataset:
    """Stack one grid's ``(time, granule_name, vds)`` members along a new time axis.

    Adds three per-time coordinates — ``granule`` (product name), ``coverage``
    (``F``ull/``P``artial frame) and ``ctr`` (product counter) — so provenance
    travels with the data, not just in the group attributes.
    """
    members = sorted(members, key=lambda m: m[0])
    cube = xr.concat(
        [v for _, _, v in members], dim="time", coords="minimal", compat="override", join="exact",
        combine_attrs="override",
    )
    for v in cube.data_vars:
        for k in PER_GRANULE_ATTRS:
            cube[v].attrs.pop(k, None)
    times = pd.DatetimeIndex([t for t, _, _ in members]).tz_localize(None)
    names = [n for _, n, _ in members]
    parsed = [parse_granule(n) for n in names]
    return cube.assign_coords(
        time=("time", times.values),
        granule=("time", np.array(names, dtype=object)),
        coverage=("time", np.array([g.coverage for g in parsed], dtype=object)),
        ctr=("time", np.array([g.ctr for g in parsed], dtype="int16")),
    )


def _to_https(path: str) -> str:
    return path.replace(C.NISAR_S3_PREFIX, C.NISAR_HTTPS_PREFIX, 1)


# ---------------------------------------------------------------------------
# Reading what is already there
# ---------------------------------------------------------------------------


def read_group_attrs(store, path: str) -> dict | None:
    import zarr

    try:
        return dict(zarr.open_group(store, path=path, mode="r").attrs)
    except Exception:  # noqa: BLE001 — group does not exist
        return None


def list_groups(store, parent: str) -> list[str]:
    import zarr

    try:
        return sorted(zarr.open_group(store, path=parent, mode="r").group_keys())
    except Exception:  # noqa: BLE001
        return []


def resolve_group(store, scheme: str, track_frame: str, mode_pols: str, band: str, sig) -> tuple[str, dict | None]:
    """The group for this grid: an existing one with a matching signature, the
    plain band name if unused, else a hashed sibling."""
    parent = f"{scheme}/{track_frame}/{mode_pols}"
    for leaf in list_groups(store, parent):
        if leaf == band or leaf.startswith(f"{band}_g"):
            attrs = read_group_attrs(store, f"{parent}/{leaf}") or {}
            if tuple(attrs.get("grid_signature", ())) == tuple(sig):
                return f"{parent}/{leaf}", attrs
    plain = group_path(scheme, track_frame, mode_pols, band)
    if read_group_attrs(store, plain) is None:
        return plain, None
    return group_path(scheme, track_frame, mode_pols, band, grid_id(sig)), None


# ---------------------------------------------------------------------------
# One group
# ---------------------------------------------------------------------------


@dataclass
class GroupResult:
    group: str
    band: str
    n_new: int
    n_total: int
    new_grid: bool
    sibling: bool
    seconds: float
    warnings: list[str] = field(default_factory=list)


def build_group(session, rows: pd.DataFrame, band: str, builder: ManifestBuilder) -> list[GroupResult]:
    """Index the granules in ``rows`` (one cube key, ``keep=True``) for one band.

    Returns one result per grid touched (normally exactly one).
    """
    store = session.store
    rows = rows.sort_values("start")
    track_frame, mode_pols = rows["track_frame"].iloc[0], rows["mode_pols"].iloc[0]
    parent = f"s3/{track_frame}/{mode_pols}"

    # ledger: every granule already indexed under any grid of this band
    have: set[str] = set()
    for leaf in list_groups(store, parent):
        if leaf == band or leaf.startswith(f"{band}_g"):
            have |= set((read_group_attrs(store, f"{parent}/{leaf}") or {}).get("granules", []))
    new = rows[~rows["name"].isin(have)]
    if new.empty:
        return []

    t0 = time.perf_counter()
    vdss = builder.build(new["url_s3"].tolist(), band)

    by_grid: dict[tuple, list] = {}
    for (_, r), v in zip(new.iterrows(), vdss):
        by_grid.setdefault(grid_signature(v), []).append((r["start"], r["name"], v))

    results = []
    for sig, members in sorted(by_grid.items(), key=lambda kv: -len(kv[1])):
        gpath, attrs = resolve_group(store, "s3", track_frame, mode_pols, band, sig)
        exists = attrs is not None
        sibling = gpath.rsplit("/", 1)[-1] != band
        cube = concat_cube(members)
        warns = []

        if exists:
            prev_max = pd.Timestamp(max(attrs.get("times", ["1970-01-01"])))
            if pd.Timestamp(cube.time.values[0]) <= prev_max:
                warns.append(f"appending acquisitions older than the cube's last ({prev_max:%Y-%m-%d}); time is no longer sorted")
        if len(set(cube.time.values)) != cube.sizes["time"]:
            raise RuntimeError(f"{gpath}: duplicate timestamps within one batch")

        chans = [c for c in C.BACKSCATTER_VARS if c in cube]
        stamp = dt.datetime.now(dt.timezone.utc)
        for scheme, ds in (("s3", cube), ("https", cube.vz.rename_paths(_to_https))):
            path = gpath if scheme == "s3" else "https" + gpath[len("s3"):]
            ds.vz.to_icechunk(
                store, group=path, append_dim="time" if exists else None, last_updated_at=stamp
            )

        # attrs are the ledger and the catalog's raw material
        x, y = cube.xCoordinates.values, cube.yCoordinates.values
        merged = dict(attrs or {})
        merged.update(
            grid_signature=list(sig), epsg=epsg_of(cube), band=band, channels=chans,
            track_frame=track_frame, mode=mode_pols.split("_")[0], pols=mode_pols.split("_")[1],
            direction=track_frame[0], relative_orbit=int(track_frame[1:4]), frame=int(track_frame[6:9]),
            collection=str(rows["collection"].iloc[0]), crids=sorted(set(merged.get("crids", [])) | set(rows["crid"])),
            posting_m=float(sig[4]),
            bounds=[float(x.min() - sig[4] / 2), float(y.min() - sig[4] / 2), float(x.max() + sig[4] / 2), float(y.max() + sig[4] / 2)],
            granules=list(merged.get("granules", [])) + [n for _, n, _ in sorted(members)],
            times=list(merged.get("times", [])) + [pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%S") for t in cube.time.values],
            time_sorted=bool(merged.get("time_sorted", True) and not warns),
            last_indexed=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            source_urls={"s3": C.NISAR_S3_PREFIX, "https": C.NISAR_HTTPS_PREFIX},
        )
        _set_attrs(store, gpath, merged)
        _set_attrs(store, "https" + gpath[len("s3"):], merged)

        results.append(
            GroupResult(gpath, band, len(members), len(merged["granules"]), not exists, sibling,
                        round(time.perf_counter() - t0, 1), warns)
        )
        if sibling and not exists:
            log.warning("NEW GRID in %s: %s -> sibling group %s", parent, sig, gpath)
    return results


def _set_attrs(store, path, attrs):
    import zarr

    zarr.open_group(store, path=path, mode="a").attrs.update(attrs)


# ---------------------------------------------------------------------------
# The region
# ---------------------------------------------------------------------------


def cube_keys(inv: pd.DataFrame) -> list[tuple]:
    kept = inv[inv["keep"]]
    counts = kept.groupby(["direction", "relative_orbit", "frame", "mode", "pols"]).size()
    return list(counts.sort_values(ascending=False).index)


def _commit(session, staged: list[GroupResult], settings) -> str | None:
    import icechunk

    if not staged:
        return None
    n = sum(r.n_new for r in staged)
    groups = sorted({r.group for r in staged})
    msg = f"index {n} granules into {len(groups)} groups: {', '.join(g.split('/', 1)[1] for g in groups[:6])}" + (
        " …" if len(groups) > 6 else ""
    )
    sid = session.commit(msg, rebase_with=icechunk.ConflictDetector())
    log.info("commit %s — %s", sid, msg)
    return sid


def build_region(
    settings: C.Settings,
    inv: pd.DataFrame,
    *,
    bands=("freqA", "freqB"),
    limit: int | None = None,
    only: list[str] | None = None,
) -> pd.DataFrame:
    """Index everything in ``inv`` (``keep=True``) not already in the repo.

    Returns a frame of per-group results.  Idempotent: a second run is a no-op.
    """
    repo = auth.open_repo(settings, create=True)
    keys = cube_keys(inv)
    if only:
        keys = [k for k in keys if f"{k[0]}{k[1]:03d}_F{k[2]:03d}" in only]
    if limit:
        keys = keys[:limit]
    log.info("%d cube keys to check (%s)", len(keys), settings.repo_url)

    results, failures = [], []
    kept = inv[inv["keep"]]
    t_start = time.perf_counter()
    with ManifestBuilder(settings.workers) as builder:
        session = repo.writable_session("main")
        staged: list[GroupResult] = []
        for i, key in enumerate(keys):
            rows = kept[
                (kept["direction"] == key[0]) & (kept["relative_orbit"] == key[1]) & (kept["frame"] == key[2])
                & (kept["mode"] == key[3]) & (kept["pols"] == key[4])
            ]
            gbands = [b for b in bands if b in _bands_for_mode(key[3])]
            for band in gbands:
                try:
                    res = build_group(session, rows, band, builder)
                except Exception as exc:  # noqa: BLE001 — one bad track-frame must not sink the run
                    log.error("FAILED %s %s: %r", key, band, exc)
                    failures.append(dict(key=key, band=band, error=repr(exc)))
                    # the session may hold half-written arrays for this group; start clean
                    _commit(session, staged, settings)
                    staged = []
                    session = repo.writable_session("main")
                    continue
                staged += res
                results += res
                for r in res:
                    log.info(
                        "[%d/%d] %s +%d (=%d) %.1fs%s", i + 1, len(keys), r.group, r.n_new, r.n_total, r.seconds,
                        "  NEW GRID" if r.sibling and r.new_grid else "",
                    )
            if sum(r.n_new for r in staged) >= settings.batch_granules:
                _commit(session, staged, settings)
                staged = []
                session = repo.writable_session("main")
        _commit(session, staged, settings)

    df = pd.DataFrame([r.__dict__ for r in results])
    n_new = int(df["n_new"].sum()) if len(df) else 0
    log.info(
        "done: %d granule-bands indexed into %d groups in %.0fs; %d failures",
        n_new, df["group"].nunique() if len(df) else 0, time.perf_counter() - t_start, len(failures),
    )
    if failures:
        pd.DataFrame(failures).to_csv(settings.local_dir / "build_failures.csv", index=False)
        log.error("failures written to %s", settings.local_dir / "build_failures.csv")
    return df


def _bands_for_mode(mode: str) -> tuple[str, ...]:
    out = []
    if mode[:2] != "00":
        out.append("freqA")
    if mode[2:] != "00":
        out.append("freqB")
    return tuple(out)

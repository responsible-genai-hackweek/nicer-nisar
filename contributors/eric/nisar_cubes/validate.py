"""Checks that fail loudly where the data model fails silently.

* every group: ``time`` strictly increasing (or flagged), unique, equal in
  length to the granule ledger, and identical between the ``s3`` and ``https`` trees;
* a random sample of (cube, time) windows: pixels read through the cube equal
  the same window read straight from the source ``.h5`` with ``h5py``.
"""

from __future__ import annotations

import logging
import random
import time

import numpy as np
import pandas as pd

from . import auth
from . import config as C
from .build import list_groups, read_group_attrs

log = logging.getLogger(__name__)


def check_groups(settings: C.Settings) -> pd.DataFrame:
    import xarray as xr

    repo = auth.open_repo(settings, schemes=())
    store = repo.readonly_session("main").store
    rows = []
    for tf in list_groups(store, "s3"):
        for mp in list_groups(store, f"s3/{tf}"):
            for leaf in list_groups(store, f"s3/{tf}/{mp}"):
                g = f"{tf}/{mp}/{leaf}"
                a = read_group_attrs(store, f"s3/{g}") or {}
                b = read_group_attrs(store, f"https/{g}")
                problems = []
                if not a.get("granules"):
                    problems.append("group attrs missing (ledger lost)")
                if b is None:
                    problems.append("https twin missing")
                ds = xr.open_zarr(store, group=f"s3/{g}", consolidated=False, zarr_format=3, chunks={})
                t = ds.time.to_index()
                if len(t) != len(a.get("granules", [])):
                    problems.append(f"time len {len(t)} != ledger {len(a.get('granules', []))}")
                if not t.is_unique:
                    problems.append("duplicate timestamps")
                if not t.is_monotonic_increasing and a.get("time_sorted", True):
                    problems.append("time not sorted but flagged sorted")
                if b is not None:
                    ds2 = xr.open_zarr(store, group=f"https/{g}", consolidated=False, zarr_format=3, chunks={})
                    if dict(ds2.sizes) != dict(ds.sizes) or not ds2.time.to_index().equals(t):
                        problems.append("s3/https trees differ")
                rows.append(dict(group=g, n_times=len(t), ok=not problems, problems="; ".join(problems)))
    df = pd.DataFrame(rows)
    bad = df[~df["ok"]] if len(df) else df
    log.info("group checks: %d groups, %d with problems", len(df), len(bad))
    for _, r in bad.iterrows():
        log.error("  %s: %s", r["group"], r["problems"])
    return df


def _direct_window(url: str, hdf_group: str, var: str, ysl: slice, xsl: slice) -> np.ndarray:
    import h5py
    from obspec_utils.readers import BlockStoreReader

    registry = auth.nisar_registry()
    store, path = registry.resolve(url)
    with h5py.File(BlockStoreReader(store, path), "r") as f:
        return f[f"{hdf_group}/{var}"][ysl, xsl]


def round_trip(settings: C.Settings, inv: pd.DataFrame, *, n: int = 10, window: int = 256, seed: int = 0,
               schemes=("s3",)) -> pd.DataFrame:
    """Compare ``n`` random windows: cube vs. direct h5py.  Every row must be byte-identical."""
    from . import api

    cat = api.load_catalog(settings)
    rng = random.Random(seed)
    urls = inv.set_index("name")["url_s3"]
    rows = []
    for _ in range(n):
        r = cat.iloc[rng.randrange(len(cat))]
        ti = rng.randrange(r["n_times"])
        granule = r["granules"][ti]
        ny, nx = r["shape"]
        y0, x0 = rng.randrange(0, ny - window), rng.randrange(0, nx - window)
        ysl, xsl = slice(y0, y0 + window), slice(x0, x0 + window)
        chan = r["channels"][0]
        t0 = time.perf_counter()
        truth = _direct_window(urls[granule], C.HDF_GROUPS[r["band"]], chan, ysl, xsl)
        t_direct = time.perf_counter() - t0
        for scheme in schemes:
            ds = api.open(r, scheme=scheme, sort_time=False, settings=settings)
            t0 = time.perf_counter()
            got = ds[chan].isel(time=ti, y=ysl, x=xsl).values
            t_cube = time.perf_counter() - t0
            same = np.array_equal(truth, got, equal_nan=True)
            rows.append(dict(group=r["group"], scheme=scheme, granule=granule, time_index=ti, window=(y0, x0),
                             identical=same, fill_fraction=float(np.mean(~(np.isfinite(truth) & (truth > 0)))),
                             s_direct=round(t_direct, 2), s_cube=round(t_cube, 2)))
            (log.info if same else log.error)("%s %s t=%d %s: identical=%s (direct %.1fs, cube %.1fs)",
                                              scheme, r["group"], ti, granule[:40], same, t_direct, t_cube)
    return pd.DataFrame(rows)

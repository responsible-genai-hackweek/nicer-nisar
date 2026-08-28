"""What users call: ``find``, ``open``, ``coverage``, ``open_region``."""

from __future__ import annotations

import functools
import json
import logging
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import box, shape
from shapely import wkt

from . import auth
from . import config as C

log = logging.getLogger(__name__)

_LIST_COLS = ("channels", "shape", "grid_signature", "bounds", "crids", "granules")


def _settings(settings: C.Settings | None) -> C.Settings:
    return settings or C.Settings()


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------


def load_catalog(settings: C.Settings | None = None, *, source: str | None = None) -> gpd.GeoDataFrame:
    """The cube catalog as a GeoDataFrame (from S3 unless a local copy exists).

    ``source`` may be a local path or an ``s3://`` URL to ``cubes.parquet``.
    """
    s = _settings(settings)
    src = source or (str(s.catalog_path) if s.catalog_path.exists() else f"{s.catalog_url}/cubes.parquet")
    gdf = gpd.read_parquet(src)
    for col in _LIST_COLS:
        if col in gdf and len(gdf) and isinstance(gdf[col].iloc[0], str):
            gdf[col] = gdf[col].map(json.loads)
    gdf.attrs["source"] = src
    return gdf


def find(
    geometry=None,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    time: str | tuple | None = None,
    band: str | None = "freqA",
    direction: str | None = None,
    mode: str | None = None,
    min_times: int = 1,
    require_data: bool = True,
    catalog: gpd.GeoDataFrame | None = None,
    settings: C.Settings | None = None,
) -> gpd.GeoDataFrame:
    """Cubes whose grid intersects ``geometry`` (shapely or GeoJSON-like) or ``bbox``.

    ``require_data`` also demands that the *imaged footprint* touches the query —
    the grid is a rectangle, the swath inside it is not.  ``time`` is an ISO
    interval ``"2025-11/2026-06"`` or a ``(start, end)`` pair.  Results are
    sorted longest-series first.
    """
    cat = catalog if catalog is not None else load_catalog(settings)
    q = None
    if geometry is not None:
        q = geometry if hasattr(geometry, "geom_type") else shape(geometry)
    elif bbox is not None:
        q = box(*bbox)
    sel = cat
    if q is not None:
        sel = sel[sel.intersects(q)]
        if require_data:
            fp = sel["data_footprint"].map(lambda w: wkt.loads(w) if isinstance(w, str) else None)
            sel = sel[[f is None or f.intersects(q) for f in fp]]
    if band:
        sel = sel[sel["band"] == band]
    if direction:
        sel = sel[sel["direction"] == direction[0].upper()]
    if mode:
        sel = sel[sel["mode"] == mode]
    if time is not None:
        t0, t1 = time.split("/") if isinstance(time, str) else time
        t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
        sel = sel[(sel["end"] >= t0) & (sel["start"] <= t1)]
    sel = sel[sel["n_times"] >= min_times]
    return sel.sort_values("n_times", ascending=False)


# ---------------------------------------------------------------------------
# opening
# ---------------------------------------------------------------------------


def _auto_scheme() -> str:
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return "s3" if region == C.NISAR_REGION else "https"


@functools.lru_cache(maxsize=8)
def _repo(bucket, prefix, region_name, scheme):
    s = C.Settings(bucket=bucket, prefix=prefix, region_name=region_name)
    return auth.open_repo(s, schemes=(scheme,))


def open_repo(settings: C.Settings | None = None, scheme: str = "auto"):
    s = _settings(settings)
    scheme = _auto_scheme() if scheme == "auto" else scheme
    return _repo(s.bucket, s.prefix, s.region_name, scheme)


def _group_of(item) -> str:
    if isinstance(item, str):
        return item.split("#", 1)[-1].split("/", 1)[-1] if item.startswith(("s3/", "https/")) else item
    if isinstance(item, pd.Series):
        return item["group"]
    if isinstance(item, dict):  # STAC item
        return item["properties"]["icechunk:group"]
    if hasattr(item, "properties"):  # pystac.Item
        return item.properties["icechunk:group"]
    if isinstance(item, pd.DataFrame):
        if len(item) != 1:
            raise ValueError("pass one catalog row, not a frame of %d" % len(item))
        return item.iloc[0]["group"]
    raise TypeError(f"cannot get a group from {type(item)}")


def open(item, *, scheme: str = "auto", sort_time: bool = True, settings: C.Settings | None = None, **kw) -> xr.Dataset:  # noqa: A001
    """Open one cube lazily.  ``scheme`` is ``s3`` in us-west-2, ``https`` anywhere."""
    import rioxarray  # noqa: F401 — registers .rio

    s = _settings(settings)
    scheme = _auto_scheme() if scheme == "auto" else scheme
    repo = open_repo(s, scheme)
    store = repo.readonly_session("main").store
    ds = xr.open_zarr(store, group=f"{scheme}/{_group_of(item)}", consolidated=False, zarr_format=3, chunks={}, **kw)
    if sort_time and not ds.time.to_index().is_monotonic_increasing:
        ds = ds.sortby("time")
    return ds.rename({"xCoordinates": "x", "yCoordinates": "y"}).rio.write_crs(int(ds.projection.attrs["epsg_code"]))


def open_region(*, scheme: str = "auto", settings: C.Settings | None = None) -> xr.DataTree:
    """Every cube in the region as one lazy DataTree.

    ~2,000 nodes; opening the whole region takes ~5 minutes because each node's
    metadata is fetched individually.  Pass a ``group`` such as ``"s3/D172_F065"``
    to :func:`xarray.open_datatree` yourself for one track-frame in a second.
    """
    s = _settings(settings)
    scheme = _auto_scheme() if scheme == "auto" else scheme
    store = open_repo(s, scheme).readonly_session("main").store
    return xr.open_datatree(store, engine="zarr", group=scheme, consolidated=False, zarr_format=3, chunks={})


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------


def clip(ds: xr.Dataset | xr.DataArray, geometry, *, buffer_m: float = 0.0, crs="EPSG:4326"):
    """Index-subset a cube to a geometry's bounds, then clip to the geometry."""
    import rioxarray  # noqa: F401 — registers .rio

    g = gpd.GeoSeries([geometry if hasattr(geometry, "geom_type") else shape(geometry)], crs=crs).to_crs(ds.rio.crs)
    x, y = ds.x.values, ds.y.values
    half = abs(float(x[1] - x[0])) / 2
    if g.iloc[0].area == 0:  # a point or line: make it one pixel wide so clip has something to keep
        g = g.buffer(half)
    minx, miny, maxx, maxy = g.total_bounds
    # select by pixel *cell*, not centre, so a geometry smaller than a pixel still hits one
    xs = np.where((x + half >= minx - buffer_m) & (x - half <= maxx + buffer_m))[0]
    ys = np.where((y + half >= miny - buffer_m) & (y - half <= maxy + buffer_m))[0]
    if not len(xs) or not len(ys):
        raise ValueError("geometry does not intersect the cube's grid")
    sub = ds.isel(x=slice(xs[0], xs[-1] + 1), y=slice(ys[0], ys[-1] + 1))
    return sub.rio.clip(g.geometry, all_touched=True, drop=True)


def coverage(item, geometry, *, time=-1, channel: str | None = None, scheme: str = "auto", settings=None) -> float:
    """Fraction of valid (non-fill) pixels over ``geometry`` at one time step.

    Reads only the chunks under the geometry.  ``time=-1`` is the newest scene.
    """
    ds = open(item, scheme=scheme, settings=settings)
    chan = channel or next(c for c in C.BACKSCATTER_VARS if c in ds)
    da = ds[chan].isel(time=time)
    sub = clip(da, geometry)
    vals = sub.values
    valid = np.isfinite(vals) & (vals > 0)
    return float(valid.sum() / vals.size) if vals.size else float("nan")

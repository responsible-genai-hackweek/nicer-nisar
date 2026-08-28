"""nisar_cubes — a catalogued collection of virtual NISAR GCOV cubes.

One Icechunk repository per region, one Zarr group per (track-frame, mode,
polarisation, band), each group a ``(time, y, x)`` virtual cube whose chunks
still live in ASF's original HDF5 files.  See ``PLAN_western_north_america_cube.md``.

Typical use::

    import nisar_cubes as nc
    items = nc.find(bbox=(-121.9, 46.7, -121.6, 46.95))     # cubes that see Rainier
    ds = nc.open(items.iloc[0])                             # lazy xarray.Dataset
    frac = nc.coverage(items.iloc[0], my_polygon)           # valid-pixel fraction
"""

from .api import clip, coverage, find, load_catalog, open, open_region, open_repo  # noqa: A004
from .config import REGIONS, Region, Settings
from .naming import GranuleName, parse_granule

__all__ = [
    "REGIONS",
    "GranuleName",
    "Region",
    "Settings",
    "clip",
    "coverage",
    "find",
    "load_catalog",
    "open",
    "open_region",
    "open_repo",
    "parse_granule",
]

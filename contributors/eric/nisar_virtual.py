"""Helpers for virtualizing NISAR GCOV granules with VirtualiZarr + Icechunk.

Kept out of the notebook so that ``icechunk.s3_refreshable_credentials`` has a
module-level (picklable) callable to refresh NISAR's hourly S3 tokens with.
"""

from __future__ import annotations

import re

import earthaccess

BUCKET = "sds-n-cumulus-prod-nisar-products"
S3_CREDS_ENDPOINT = "https://nisar.asf.earthdatacloud.nasa.gov/s3credentials"
REGION = "us-west-2"

#: Group holding the frequency-A image grids of a GCOV product.
GCOV_GRIDS = "/science/LSAR/GCOV/grids/frequencyA"

#: NISAR L2 GCOV filename fields we care about, e.g.
#: NISAR_L2_PR_GCOV_004_172_D_065_4005_DHDH_A_20251110T031848_...
#:
#: Per the NISAR naming convention (nisar-docs, "Naming Conventions") the
#: fields are CYCLE_REL_P_FRM_MODE_POLE: ``172`` is the *relative orbit*,
#: ``065`` the *frame*, ``4005`` the *bandwidth mode* (40 MHz + 5 MHz).
#: Earlier versions of this module mislabelled them (``relorb`` for the frame,
#: ``frame`` for the mode), which grouped granules by frame across *all*
#: relative orbits — the real cause of README failure #2.  The group names below
#: are correct; ``relorb``/``frame`` are kept as aliases for the notebooks.
GRANULE_RX = re.compile(
    r"NISAR_L2_\w\w_GCOV_(?P<cycle>\d+)_(?P<relative_orbit>\d+)_(?P<direction>[AD])_"
    r"(?P<frame>\d+)_(?P<mode>\d+)_(?P<pols>\w+)_\w_"
    r"(?P<start>\d{8}T\d{6})_(?P<end>\d{8}T\d{6})_"
)

#: Trailing product-version field, e.g. ``..._J_001.h5``. The archive can hold
#: more than one version of the same acquisition; without this we would index
#: the same date twice.
VERSION_RX = re.compile(r"_(?P<version>\d{3})\.h5$")


def nisar_s3_credentials() -> dict:
    """Fetch temporary NISAR S3 credentials (valid ~1 hour) via Earthdata Login."""
    auth = earthaccess.login(strategy="netrc")
    return auth.get_s3_credentials(endpoint=S3_CREDS_ENDPOINT)


def icechunk_credentials():
    """Refresh callback for ``icechunk.s3_refreshable_credentials``.

    Must be importable (not defined in a notebook cell) so icechunk can pickle
    it into the repository config.
    """
    import datetime

    import icechunk

    c = nisar_s3_credentials()
    expires = c["expiration"]
    if isinstance(expires, str):
        # earthaccess hands back an ISO-8601 string; icechunk wants a datetime.
        expires = datetime.datetime.fromisoformat(expires)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=datetime.timezone.utc)
    return icechunk.S3StaticCredentials(
        access_key_id=c["accessKeyId"],
        secret_access_key=c["secretAccessKey"],
        session_token=c["sessionToken"],
        expires_after=expires,
    )


def obstore_registry():
    """An ObjectStoreRegistry wired to the NISAR products bucket."""
    from obspec_utils.registry import ObjectStoreRegistry
    from obstore.store import S3Store

    c = nisar_s3_credentials()
    store = S3Store(
        BUCKET,
        region=REGION,
        access_key_id=c["accessKeyId"],
        secret_access_key=c["secretAccessKey"],
        session_token=c["sessionToken"],
    )
    return ObjectStoreRegistry({f"s3://{BUCKET}": store})


def find_track(bbox, short_name="NISAR_L2_GCOV_PROVISIONAL_V1", count=200):
    """Group GCOV granules over ``bbox`` by (direction, relative orbit, frame, pols).

    Returns ``{key: [(start_datetime, s3_url), ...]}`` sorted by acquisition time,
    with **one granule per acquisition**: where the archive holds several product
    versions of the same take (``..._001.h5`` and ``..._002.h5``), the highest is
    kept. Leaving both in produces a duplicated time step in the cube.

    The key is a true *track-frame* (relative orbit **and** frame). One
    track-frame is one output grid in every case audited so far; ``group_by_grid``
    remains the check that makes it so rather than an assumption.  (Before
    2026-08-28 this keyed on frame and bandwidth mode, mislabelled as relative
    orbit and frame, which merged different tracks — see the README erratum.)
    """
    from collections import defaultdict

    results = earthaccess.search_data(
        short_name=short_name, bounding_box=bbox, count=count
    )
    # key -> start -> (version, url), so a later version displaces an earlier one
    groups: dict[tuple, dict[str, tuple[int, str]]] = defaultdict(dict)
    for g in results:
        for url in g.data_links(access="direct"):
            if not url.endswith(".h5"):
                continue
            name = url.rsplit("/", 1)[-1]
            if not (m := GRANULE_RX.search(name)):
                continue
            key = (m["direction"], m["relative_orbit"], m["frame"], m["pols"])
            v = VERSION_RX.search(name)
            version = int(v["version"]) if v else 0
            start = m["start"]
            if version >= groups[key].get(start, (-1, ""))[0]:
                groups[key][start] = (version, url)
    return {
        k: [(s, u) for s, (_, u) in sorted(v.items())]
        for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    }


# ---------------------------------------------------------------------------
# Building manifests
# ---------------------------------------------------------------------------

#: The frequencyA variables worth indexing for a backscatter time series. The
#: group holds 14; the other 9 are per-granule masks and scalars that triple the
#: reference count without being used downstream. Dropping them roughly halves
#: the build time (see README, "Parallelizing the build").
DEFAULT_KEEP = ("HHHH", "HVHV", "VVVV", "VHVH", "xCoordinates", "yCoordinates", "projection")

_REGISTRY = None  # per-process cache, set by _pool_init


def drop_outside(all_vars, keep=DEFAULT_KEEP):
    """The ``drop_variables`` deny-list that keeps only ``keep``.

    ``HDFParser`` takes a deny-list, so the variables present in the file have to
    be known first — open one granule, then reuse this for the rest.
    """
    return [v for v in all_vars if v not in keep]


def _pool_init():
    global _REGISTRY
    # Worker processes start clean, so warning filters set in the parent do not
    # apply; without this, zarr's unstable-dtype warnings are written straight to
    # the parent's stderr from every child.
    import warnings

    warnings.filterwarnings("ignore")
    _REGISTRY = obstore_registry()


def _pool_build(args):
    url, group, drop = args
    import virtualizarr as vz
    from virtualizarr.parsers import HDFParser

    return vz.open_virtual_dataset(
        url, registry=_REGISTRY, parser=HDFParser(group=group, drop_variables=drop)
    )


def build_manifests(urls, registry=None, group=GCOV_GRIDS, drop_variables=None, workers=1):
    """Open virtual datasets for ``urls``.

    ``workers > 1`` uses *processes*, not threads: roughly half of the build is
    pure-Python URI validation running once per chunk reference, so threads are
    GIL-bound and gain almost nothing. Processes give ~1.4x at 8 workers — the
    manifests have to be pickled back to the parent, which eats most of the win.
    """
    import virtualizarr as vz
    from virtualizarr.parsers import HDFParser

    urls = list(urls)
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(workers, initializer=_pool_init) as ex:
            return list(ex.map(_pool_build, [(u, group, drop_variables) for u in urls]))

    registry = registry or obstore_registry()
    parser = HDFParser(group=group, drop_variables=drop_variables)
    return [vz.open_virtual_dataset(u, registry=registry, parser=parser) for u in urls]


def grid_signature(vds):
    """The identity of a NISAR output grid: shape plus origin.

    Track and frame are *not* sufficient — the archive contains granules with
    the same relative orbit and frame posted to different grids. Group on this.
    """
    return (
        vds.sizes["yCoordinates"],
        vds.sizes["xCoordinates"],
        round(float(vds.xCoordinates[0]), 3),
        round(float(vds.yCoordinates[0]), 3),
    )


def group_by_grid(items, vdss):
    """Split ``(time, url)`` items and their virtual datasets by output grid.

    Returns ``{signature: [(start, url, vds), ...]}``, largest group first.
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for (start, url), v in zip(items, vdss):
        groups[grid_signature(v)].append((start, url, v))
    return dict(sorted(groups.items(), key=lambda kv: -len(kv[1])))


def concat_cube(members):
    """Concatenate one grid's ``(start, url, vds)`` members along a time axis."""
    import pandas as pd
    import xarray as xr

    members = sorted(members)
    times = pd.to_datetime([s for s, _, _ in members], format="%Y%m%dT%H%M%S")
    cube = xr.concat(
        [v for _, _, v in members],
        dim="time",
        coords="minimal",
        compat="override",
        join="exact",
    )
    return cube.assign_coords(time=("time", times))


# ---------------------------------------------------------------------------
# Icechunk repository
# ---------------------------------------------------------------------------


def open_repo(path, create=False):
    """Open (or create) an Icechunk repo authorized to read the NISAR bucket.

    The virtual chunk container is wired to a *refreshable* credential callback,
    because EDL S3 tokens last an hour and a static token makes the cube stop
    reading mid-session.
    """
    import icechunk

    prefix = f"s3://{BUCKET}/"
    cfg = icechunk.RepositoryConfig.default()
    cfg.set_virtual_chunk_container(
        icechunk.VirtualChunkContainer(prefix, icechunk.s3_store(region=REGION))
    )
    auth = {
        prefix: icechunk.Credentials.S3(
            icechunk.s3_refreshable_credentials(icechunk_credentials)
        )
    }
    storage = icechunk.local_filesystem_storage(str(path))
    fn = icechunk.Repository.create if create else icechunk.Repository.open
    return fn(storage=storage, config=cfg, authorize_virtual_chunk_access=auth)


def open_cube(repo, branch="main"):
    """Open the persisted virtual cube as a lazy xarray Dataset."""
    import xarray as xr

    return xr.open_zarr(
        repo.readonly_session(branch).store, consolidated=False, zarr_format=3, chunks={}
    )


def indexed_times(repo, branch="main"):
    """Acquisition times already in the cube, as a pandas DatetimeIndex.

    Returns an empty index if the branch has no cube yet.
    """
    import pandas as pd

    try:
        return open_cube(repo, branch).time.to_index()
    except Exception:
        return pd.DatetimeIndex([])


def append_new(repo, items, registry=None, group=GCOV_GRIDS, drop_variables=None,
               workers=1, branch="main"):
    """Index any of ``items`` not already in the cube and append them.

    ``items`` is ``[(start_string, url), ...]`` as returned by ``find_track``.
    New acquisitions arrive at the end of the archive, so this is the operation
    you run on a schedule: it is idempotent, and skips granules already indexed.

    Returns ``(snapshot_id_or_None, appended_times)``.
    """
    import pandas as pd

    have = indexed_times(repo, branch)
    new = [
        (s, u)
        for s, u in sorted(items)
        if pd.to_datetime(s, format="%Y%m%dT%H%M%S") not in have
    ]
    if not new:
        return None, pd.DatetimeIndex([])

    vdss = build_manifests(
        [u for _, u in new], registry=registry, group=group,
        drop_variables=drop_variables, workers=workers,
    )
    if len(have):
        # Only granules on the cube's existing grid can be appended.
        cube0 = open_cube(repo, branch)
        want = (
            cube0.sizes["yCoordinates"], cube0.sizes["xCoordinates"],
            round(float(cube0.xCoordinates[0]), 3), round(float(cube0.yCoordinates[0]), 3),
        )
        keep = [(s, u, v) for (s, u), v in zip(new, vdss) if grid_signature(v) == want]
    else:
        keep = max(group_by_grid(new, vdss).values(), key=len)

    if not keep:
        return None, pd.DatetimeIndex([])

    cube = concat_cube(keep)
    session = repo.writable_session(branch)
    cube.vz.to_icechunk(session.store, **({"append_dim": "time"} if len(have) else {}))
    times = cube.time.to_index()
    msg = (
        f"{'append' if len(have) else 'create'} {len(times)} acquisitions "
        f"({times[0]:%Y-%m-%d}..{times[-1]:%Y-%m-%d})"
    )
    return session.commit(msg), times


def compact(repo):
    """Reclaim space from superseded manifests left behind by appends.

    Every append rewrites the array's chunk manifest, and Icechunk keeps the old
    one so you can time-travel to it — ~10 MB per append here. Expiring the old
    snapshots and collecting garbage brings the repo back to the size of a single
    from-scratch build, at the price of the history.
    """
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    expired = repo.expire_snapshots(older_than=now)
    summary = repo.garbage_collect(delete_object_older_than=now)
    return expired, summary

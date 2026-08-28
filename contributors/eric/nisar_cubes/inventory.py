"""Granule inventory: what CMR knows, deduplicated, as a GeoDataFrame.

One row per *file*.  ``keep`` marks the one file per acquisition we index — the
highest product counter (``_001`` < ``_002``) — so the duplicates the archive
holds never become a duplicated time step (README failure #3).  ``asf_search``
is consulted as a second opinion and the disagreement is reported, not merged
(failure #9).
"""

from __future__ import annotations

import logging
import time

import geopandas as gpd
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon

from . import config as C
from .naming import parse_granule

log = logging.getLogger(__name__)

COLUMNS = [
    "name", "collection", "url_s3", "url_https", "size_bytes",
    "cycle", "relative_orbit", "direction", "frame", "mode", "pols",
    "start", "end", "crid", "accuracy", "coverage", "ctr",
    "track_frame", "mode_pols", "keep", "superseded_by",
]


def _footprint(umm: dict):
    try:
        polys = umm["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"]
    except KeyError:
        return None
    shells = [
        Polygon([(p["Longitude"], p["Latitude"]) for p in g["Boundary"]["Points"]])
        for g in polys
    ]
    return shells[0] if len(shells) == 1 else MultiPolygon(shells)


def search_cmr(region: C.Region) -> gpd.GeoDataFrame:
    import earthaccess

    rows = []
    for collection in region.collections:
        t0 = time.perf_counter()
        results = earthaccess.search_data(short_name=collection, bounding_box=region.bbox, count=-1)
        log.info("CMR %s: %d granules in %.1fs", collection, len(results), time.perf_counter() - t0)
        for g in results:
            s3 = [u for u in g.data_links(access="direct") if u.endswith(".h5")]
            https = [u for u in g.data_links(access="external") if u.endswith(".h5")]
            if not s3:
                continue
            gn = parse_granule(s3[0])
            url_https = https[0] if https else s3[0].replace(C.NISAR_S3_PREFIX, C.NISAR_HTTPS_PREFIX)
            if url_https != s3[0].replace(C.NISAR_S3_PREFIX, C.NISAR_HTTPS_PREFIX):
                log.warning("HTTPS link does not follow the S3 key for %s", gn.name)
            rows.append(
                dict(
                    name=gn.name, collection=collection, url_s3=s3[0], url_https=url_https,
                    size_bytes=int(float(g["umm"].get("DataGranule", {}).get("ArchiveAndDistributionInformation", [{}])[0].get("SizeInBytes", 0)) or g.size() * 1e6),
                    cycle=gn.cycle, relative_orbit=gn.relative_orbit, direction=gn.direction,
                    frame=gn.frame, mode=gn.mode, pols=gn.pols,
                    start=pd.Timestamp(gn.start).tz_convert(None), end=pd.Timestamp(gn.end).tz_convert(None),
                    crid=gn.crid, accuracy=gn.accuracy, coverage=gn.coverage, ctr=gn.ctr,
                    track_frame=gn.track_frame, mode_pols=gn.mode_pols,
                    geometry=_footprint(g["umm"]),
                )
            )
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return dedup(gdf)


def dedup(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Mark one file per acquisition (highest ``ctr``) with ``keep=True``."""
    key = ["collection", "direction", "relative_orbit", "frame", "mode", "pols", "start"]
    gdf = gdf.sort_values(key + ["ctr"]).reset_index(drop=True)
    last = gdf.groupby(key, sort=False)["ctr"].transform("max")
    gdf["keep"] = gdf["ctr"] == last
    winners = gdf[gdf["keep"]].set_index(key)["name"]
    gdf["superseded_by"] = [
        None if k else winners.loc[tuple(r[c] for c in key)]
        for k, (_, r) in zip(gdf["keep"], gdf.iterrows())
    ]
    n_dup = int((~gdf["keep"]).sum())
    if n_dup:
        log.info("%d superseded product versions marked keep=False", n_dup)
    return gdf[COLUMNS + ["geometry"]]


def asf_diff(region: C.Region, gdf: gpd.GeoDataFrame) -> dict:
    """Compare acquisition sets from CMR and ASF.  Never raises; reports."""
    try:
        import asf_search as asf
        from shapely.geometry import box

        t0 = time.perf_counter()
        hits = asf.search(
            intersectsWith=box(*region.bbox).wkt, dataset=["NISAR"], processingLevel=["GCOV"], maxResults=50_000
        )
        names = []
        for h in hits:
            n = h.properties.get("fileID") or h.properties.get("sceneName")
            try:
                names.append(parse_granule(n))
            except ValueError:
                continue
        asf_keys = {g.acquisition_key for g in names if g.crid.startswith("P")}
        cmr_keys = {
            parse_granule(n).acquisition_key for n in gdf.loc[gdf["collection"].str.contains("PROVISIONAL"), "name"]
        }
        rep = dict(
            asf_seconds=round(time.perf_counter() - t0, 1),
            asf_files=len(hits), asf_acquisitions=len(asf_keys), cmr_acquisitions=len(cmr_keys),
            asf_only=sorted(str(k) for k in asf_keys - cmr_keys),
            cmr_only=sorted(str(k) for k in cmr_keys - asf_keys),
        )
        log.info(
            "ASF vs CMR (provisional): %d vs %d acquisitions; %d ASF-only, %d CMR-only",
            rep["asf_acquisitions"], rep["cmr_acquisitions"], len(rep["asf_only"]), len(rep["cmr_only"]),
        )
        return rep
    except Exception as exc:  # noqa: BLE001 — a second opinion must never block the build
        log.warning("asf_search comparison skipped: %r", exc)
        return {"error": repr(exc)}


def load(settings: C.Settings) -> gpd.GeoDataFrame:
    return gpd.read_parquet(settings.inventory_path)


def save(gdf: gpd.GeoDataFrame, settings: C.Settings) -> None:
    gdf.to_parquet(settings.inventory_path)
    log.info("inventory: %d files, %d kept -> %s", len(gdf), int(gdf["keep"].sum()), settings.inventory_path)


def refresh(settings: C.Settings, *, asf: bool = True) -> tuple[gpd.GeoDataFrame, dict]:
    gdf = search_cmr(settings.region)
    report = asf_diff(settings.region, gdf) if asf else {}
    save(gdf, settings)
    return gdf, report


def summary(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """One row per cube key: how many acquisitions, when, which bands."""
    kept = gdf[gdf["keep"]]
    agg = kept.groupby(["direction", "relative_orbit", "frame", "mode", "pols"], sort=False).agg(
        n=("name", "size"), first=("start", "min"), last=("start", "max"), gb=("size_bytes", lambda s: s.sum() / 1e9)
    )
    return agg.sort_values("n", ascending=False)

"""The catalog: one row / STAC Item per cube group, built from the repository.

Group attributes written by :mod:`build` are the source of truth; the inventory
adds the CMR footprints so an item carries both the *grid* it covers (a
rectangle in the cube's UTM zone) and the *data footprint* inside it — a grid
can contain your AOI and still hold only fill (README failure #8).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Polygon, box, mapping
from shapely.ops import unary_union

from . import auth
from . import config as C
from .build import list_groups, read_group_attrs

log = logging.getLogger(__name__)


def _grid_polygon_lonlat(bounds, epsg: int) -> Polygon:
    """The grid rectangle, edges densified so it survives the projection."""
    w, s, e, n = bounds
    tr = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    xs = np.linspace(w, e, 25)
    ys = np.linspace(s, n, 25)
    ring = (
        [(x, s) for x in xs] + [(e, y) for y in ys] + [(x, n) for x in xs[::-1]] + [(w, y) for y in ys[::-1]]
    )
    return Polygon([tr.transform(x, y) for x, y in ring])


def _local_overpass(times: list[str], lon: float) -> str:
    """Circular mean local solar time of the acquisitions, ``HH:MM``."""
    t = pd.to_datetime(times)
    hours = (np.asarray(t.hour) + np.asarray(t.minute) / 60 + lon / 15) % 24
    ang = hours / 24 * 2 * np.pi
    mean = np.arctan2(np.sin(ang).mean(), np.cos(ang).mean()) % (2 * np.pi) / (2 * np.pi) * 24
    return f"{int(mean):02d}:{int(round((mean % 1) * 60)) % 60:02d}"


def scan_repo(settings: C.Settings, inv: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    repo = auth.open_repo(settings, schemes=())
    session = repo.readonly_session("main")
    store = session.store
    snapshot = session.snapshot_id
    foot = inv.set_index("name")["geometry"] if inv is not None else None

    rows = []
    for tf in list_groups(store, "s3"):
        for mp in list_groups(store, f"s3/{tf}"):
            for leaf in list_groups(store, f"s3/{tf}/{mp}"):
                path = f"s3/{tf}/{mp}/{leaf}"
                a = read_group_attrs(store, path) or {}
                if "grid_signature" not in a:
                    continue
                geom = _grid_polygon_lonlat(a["bounds"], a["epsg"])
                data_fp = None
                if foot is not None:
                    fps = [foot[g] for g in a["granules"] if g in foot.index and foot[g] is not None]
                    data_fp = unary_union(fps) if fps else None
                c = geom.centroid
                rows.append(
                    dict(
                        id=path[len("s3/"):].replace("/", "__"),
                        group=path[len("s3/"):],
                        track_frame=tf, mode_pols=mp, band=a["band"],
                        direction=a["direction"], relative_orbit=a["relative_orbit"], frame=a["frame"],
                        mode=a["mode"], pols=a["pols"], channels=a["channels"],
                        epsg=a["epsg"], posting_m=a["posting_m"], shape=[a["grid_signature"][0], a["grid_signature"][1]],
                        grid_signature=a["grid_signature"], bounds=a["bounds"],
                        n_times=len(a["times"]), start=pd.Timestamp(min(a["times"])), end=pd.Timestamp(max(a["times"])),
                        time_sorted=a.get("time_sorted", True),
                        local_overpass=_local_overpass(a["times"], c.x),
                        collection=a["collection"], crids=a.get("crids", []),
                        granules=a["granules"], last_indexed=a.get("last_indexed"),
                        snapshot=snapshot,
                        data_footprint=data_fp.wkt if data_fp is not None else None,
                        geometry=geom,
                    )
                )
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    log.info("catalog: %d cubes, %d acquisitions", len(gdf), int(gdf["n_times"].sum()) if len(gdf) else 0)
    return gdf


# ---------------------------------------------------------------------------
# STAC
# ---------------------------------------------------------------------------


def to_stac(gdf: gpd.GeoDataFrame, settings: C.Settings) -> dict:
    """A static STAC Collection + Items as plain dicts (``{"collection": …, "items": […]}``)."""
    items = []
    for _, r in gdf.iterrows():
        props = {
            "start_datetime": r["start"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_datetime": r["end"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sat:orbit_state": "ascending" if r["direction"] == "A" else "descending",
            "sat:relative_orbit": int(r["relative_orbit"]),
            "sar:polarizations": [c[:2] for c in r["channels"]],
            "sar:frequency_band": "L",
            "sar:product_type": "GCOV",
            "proj:epsg": int(r["epsg"]),
            "proj:shape": list(map(int, r["shape"])),
            "proj:bbox": list(map(float, r["bounds"])),
            "nisar:frame": int(r["frame"]),
            "nisar:mode": r["mode"],
            "nisar:pols": r["pols"],
            "nisar:band": r["band"],
            "nisar:channels": list(r["channels"]),
            "nisar:posting_m": float(r["posting_m"]),
            "nisar:grid_signature": list(r["grid_signature"]),
            "nisar:n_times": int(r["n_times"]),
            "nisar:time_sorted": bool(r["time_sorted"]),
            "nisar:local_overpass_time": r["local_overpass"],
            "nisar:collection": r["collection"],
            "nisar:crids": list(r["crids"]),
            "nisar:granules": list(r["granules"]),
            "nisar:data_footprint": r["data_footprint"],
            "icechunk:repo": settings.repo_url,
            "icechunk:group": r["group"],
            "icechunk:snapshot": r["snapshot"],
        }
        items.append(
            {
                "type": "Feature", "stac_version": "1.0.0", "stac_extensions": [], "id": r["id"],
                "geometry": mapping(r["geometry"]), "bbox": list(r["geometry"].bounds),
                "properties": props, "collection": f"nisar-gcov-virtual-{settings.region_name}",
                "links": [], "assets": {
                    "s3": {"href": f"{settings.repo_url}#s3/{r['group']}", "type": "application/vnd+zarr",
                           "roles": ["data"], "title": "Icechunk group, s3:// chunk references (us-west-2)"},
                    "https": {"href": f"{settings.repo_url}#https/{r['group']}", "type": "application/vnd+zarr",
                              "roles": ["data"], "title": "Icechunk group, https:// chunk references (anywhere)"},
                },
            }
        )
    union = unary_union(list(gdf.geometry)) if len(gdf) else box(*settings.region.bbox)
    collection = {
        "type": "Collection", "stac_version": "1.0.0", "id": f"nisar-gcov-virtual-{settings.region_name}",
        "description": f"Virtual (VirtualiZarr + Icechunk) cubes of NISAR L2 GCOV over {settings.region.description}",
        "license": "other", "extent": {
            "spatial": {"bbox": [list(union.bounds)]},
            "temporal": {"interval": [[
                gdf["start"].min().strftime("%Y-%m-%dT%H:%M:%SZ") if len(gdf) else None,
                gdf["end"].max().strftime("%Y-%m-%dT%H:%M:%SZ") if len(gdf) else None,
            ]]},
        },
        "links": [], "summaries": {"nisar:n_cubes": len(gdf), "nisar:n_acquisitions": int(gdf["n_times"].sum()) if len(gdf) else 0},
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return {"collection": collection, "items": items}


# ---------------------------------------------------------------------------
# Persisting
# ---------------------------------------------------------------------------


def _fs():
    import s3fs

    return s3fs.S3FileSystem()


def _parquet_ready(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    for col in ("channels", "shape", "grid_signature", "bounds", "crids", "granules"):
        out[col] = out[col].map(json.dumps)
    return out


def write(gdf: gpd.GeoDataFrame, settings: C.Settings, *, upload: bool = True) -> None:
    local = settings.local_dir / "catalog"
    local.mkdir(exist_ok=True)
    (local / "items").mkdir(exist_ok=True)
    _parquet_ready(gdf).to_parquet(settings.catalog_path)
    stac = to_stac(gdf, settings)
    (local / "collection.json").write_text(json.dumps(stac["collection"], indent=1))
    for it in stac["items"]:
        (local / "items" / f"{it['id']}.json").write_text(json.dumps(it))
    log.info("catalog written to %s (%d items)", local, len(stac["items"]))
    if upload:
        fs = _fs()
        fs.put(str(settings.catalog_path), f"{settings.catalog_url}/cubes.parquet")
        fs.put(str(local), settings.catalog_url, recursive=True)
        log.info("catalog uploaded to %s", settings.catalog_url)


def refresh(settings: C.Settings, inv: gpd.GeoDataFrame | None = None, *, upload: bool = True) -> gpd.GeoDataFrame:
    gdf = scan_repo(settings, inv)
    write(gdf, settings, upload=upload)
    return gdf

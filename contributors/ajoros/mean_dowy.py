#!/usr/bin/env python3
"""Mean snowmelt-runoff-onset DOWY inside a polygon.

Uses Gagliano et al. (ESSD 2026) v1.1.0 on Zenodo (kerchunk, no 56 GB download).

  pixi run python contributors/ajoros/mean_dowy.py              # davis + mcs
  pixi run python contributors/ajoros/mean_dowy.py davis
  pixi run python contributors/ajoros/mean_dowy.py mcs
  pixi run python contributors/ajoros/mean_dowy.py path/to.shp
  pixi run python contributors/ajoros/mean_dowy.py --self-check  # no network
"""

from __future__ import annotations

import argparse
import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import rioxarray  # noqa: F401  (registers .rio)
import xarray as xr
from pyproj import CRS
from pyproj.transformer import TransformerGroup

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REF_JSON_URL = (
    "https://zenodo.org/records/19618062/files/"
    "global_snowmelt_runoff_onset.zarr.tar.refs.json"
)
# Documented Winters+Davis envelope (W,S,E,N), from sentinel1-coverage-davis.md
DAVIS_ENVELOPE = (-119.88496, 39.29819, -119.82518, 39.32630)
SITES = {
    "davis": [
        HERE / "aoi/gis/davisckboundary.shp",
        HERE / "aoi/gis/wintersckboundary.shp",
    ],
    "mcs": [REPO / "contributors/HPMARSHALL/MCS_domain.kml"],
}


def _signed_area(ring: list[tuple[float, float]]) -> float:
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    s = 0.0
    n = len(pts)
    for i, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _rings_to_geojson(rings: list[list[tuple[float, float]]]) -> dict:
    # ponytail: ESRI shapefile winding only (clockwise outer). No Z/M. Upgrade: geopandas.
    polygons: list[list[list[tuple[float, float]]]] = []
    current: list[list[tuple[float, float]]] | None = None
    for ring in rings:
        if _signed_area(ring) <= 0 or current is None:
            if current:
                polygons.append(current)
            current = [ring]
        else:
            current.append(ring)
    if current:
        polygons.append(current)
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _to_4326(src: CRS):
    """Local NAD83→WGS84 (no CDN grid). from_crs() can return inf here."""
    tg = TransformerGroup(src, 4326, always_xy=True)
    if not tg.transformers:
        raise ValueError(f"no transform {src.to_string()} -> EPSG:4326")
    return tg.transformers[0]


def _transform_geom(geom: dict, transformer) -> dict:
    def xf(ring):
        return [transformer.transform(x, y) for x, y in ring]

    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [xf(r) for r in geom["coordinates"]]}
    return {
        "type": "MultiPolygon",
        "coordinates": [[xf(r) for r in poly] for poly in geom["coordinates"]],
    }


def _read_shp(path: Path) -> list[dict]:
    data = path.read_bytes()
    geoms: list[dict] = []
    offset = 100
    while offset + 8 <= len(data):
        _rec_num, rec_len = struct.unpack(">2i", data[offset : offset + 8])
        offset += 8
        rec = data[offset : offset + rec_len * 2]
        offset += rec_len * 2
        shape_type = struct.unpack("<i", rec[:4])[0]
        if shape_type == 0:
            continue
        if shape_type != 5:
            raise ValueError(f"{path.name}: unsupported shape type {shape_type}")
        nparts, npoints = struct.unpack("<2i", rec[36:44])
        parts = struct.unpack(f"<{nparts}i", rec[44 : 44 + 4 * nparts])
        pts = struct.unpack(
            f"<{npoints * 2}d",
            rec[44 + 4 * nparts : 44 + 4 * nparts + 16 * npoints],
        )
        xy = list(zip(pts[0::2], pts[1::2], strict=True))
        rings = []
        for i, start in enumerate(parts):
            end = parts[i + 1] if i + 1 < nparts else npoints
            ring = xy[start:end]
            if ring[0] != ring[-1]:
                ring = ring + [ring[0]]
            rings.append(ring)
        geoms.append(_rings_to_geojson(rings))
    prj = path.with_suffix(".prj")
    if prj.exists():
        src = CRS.from_user_input(prj.read_text())
        if src.to_epsg() != 4326:
            t = _to_4326(src)
            geoms = [_transform_geom(g, t) for g in geoms]
    return geoms


def _read_kml(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    elems = root.findall(".//{http://www.opengis.net/kml/2.2}coordinates")
    if not elems:
        elems = root.findall(".//coordinates")
    if not elems:
        raise ValueError(f"no coordinates in {path}")
    geoms = []
    for elem in elems:
        ring = []
        for pair in (elem.text or "").split():
            lon, lat, *_rest = pair.split(",")
            ring.append((float(lon), float(lat)))
        if len(ring) < 3:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        geoms.append({"type": "Polygon", "coordinates": [ring]})
    return geoms


def _read_geojson(path: Path) -> list[dict]:
    obj = json.loads(path.read_text())
    geoms = []

    def walk(g):
        if not g:
            return
        t = g.get("type")
        if t in ("Polygon", "MultiPolygon"):
            geoms.append(g)
        elif t == "GeometryCollection":
            for c in g.get("geometries", []):
                walk(c)
        elif t == "Feature":
            walk(g.get("geometry"))
        elif t == "FeatureCollection":
            for f in g.get("features", []):
                walk(f)

    walk(obj)
    return geoms


def load_geoms(path: Path) -> list[dict]:
    suf = path.suffix.lower()
    if suf == ".shp":
        return _read_shp(path)
    if suf == ".kml":
        return _read_kml(path)
    if suf in {".geojson", ".json"}:
        return _read_geojson(path)
    raise ValueError(f"unsupported polygon file: {path}")


def bounds(geoms: list[dict]) -> tuple[float, float, float, float]:
    xs, ys = [], []

    def walk_ring(ring):
        for x, y in ring:
            xs.append(x)
            ys.append(y)

    for g in geoms:
        if g["type"] == "Polygon":
            for ring in g["coordinates"]:
                walk_ring(ring)
        else:
            for poly in g["coordinates"]:
                for ring in poly:
                    walk_ring(ring)
    return min(xs), min(ys), max(xs), max(ys)


def _open_onset() -> xr.Dataset:
    import fsspec

    # zarr 3 wants an async fsspec store; reference FS needs the inner HTTP fs async too.
    fs = fsspec.filesystem(
        "reference",
        fo=REF_JSON_URL,
        remote_protocol="https",
        remote_options={"asynchronous": True},
        asynchronous=True,
    )
    return xr.open_zarr(fs.get_mapper(""), consolidated=False, decode_coords="all")


def mean_dowy(
    geoms: list[dict],
    *,
    max_res: float | None = None,
    ds: xr.Dataset | None = None,
) -> dict:
    """Clip onset rasters to geoms; return 10-year mean + annual means."""
    if ds is None:
        ds = _open_onset()
    minx, miny, maxx, maxy = bounds(geoms)
    pad = 0.002
    box = ds[
        ["runoff_onset", "runoff_onset_median", "temporal_resolution"]
    ].rio.clip_box(minx - pad, miny - pad, maxx + pad, maxy + pad, crs="EPSG:4326")
    box = box.compute()
    clipped = box.rio.clip(geoms, crs="EPSG:4326", all_touched=False)

    med = clipped["runoff_onset_median"]
    annual = clipped["runoff_onset"]
    tres = clipped["temporal_resolution"]
    if max_res is not None:
        good = tres < max_res
        annual = annual.where(good)
        med = med.where(good.any("water_year"))

    years = {}
    for wy in annual.water_year.values:
        sl = annual.sel(water_year=wy)
        res = tres.sel(water_year=wy)
        years[int(wy)] = {
            "mean_dowy": float(sl.mean(skipna=True)),
            "n_valid": int(sl.count()),
            "mean_res_days": float(res.mean(skipna=True)),
        }
    return {
        "bounds": bounds(geoms),
        "n_in_poly": int(annual.isel(water_year=0).size),
        "median_mean_dowy": float(med.mean(skipna=True)),
        "median_n_valid": int(med.count()),
        "years": years,
    }


def _resolve(name: str) -> tuple[str, list[dict]]:
    key = name.lower()
    if key in SITES:
        geoms: list[dict] = []
        for p in SITES[key]:
            geoms.extend(load_geoms(p))
        return key, geoms
    path = Path(name)
    if not path.exists():
        raise SystemExit(f"unknown site or missing file: {name}")
    return path.stem, load_geoms(path)


def _print_result(label: str, result: dict) -> None:
    b = result["bounds"]
    print(f"{label}")
    print(f"  envelope W,S,E,N: {b[0]:.5f}, {b[1]:.5f}, {b[2]:.5f}, {b[3]:.5f}")
    print(
        f"  10-year median DOWY  mean={result['median_mean_dowy']:.1f}"
        f"  n_valid={result['median_n_valid']}  (clip window {result['n_in_poly']} cells)"
    )
    print("  water_year  mean_dowy  n_valid  mean_res_d")
    for wy, row in result["years"].items():
        print(
            f"  {wy:10d}  {row['mean_dowy']:9.1f}  {row['n_valid']:7d}"
            f"  {row['mean_res_days']:10.1f}"
        )


def self_check() -> None:
    label, geoms = _resolve("davis")
    assert label == "davis" and geoms
    w, s, e, n = bounds(geoms)
    dw, ds_, de, dn = DAVIS_ENVELOPE
    # envelope should match the documented bbox within ~200 m
    for got, exp, name in ((w, dw, "W"), (s, ds_, "S"), (e, de, "E"), (n, dn, "N")):
        assert abs(got - exp) < 0.005, f"davis {name}: {got} vs {exp}"
    _, mcs = _resolve("mcs")
    assert len(mcs) == 1 and mcs[0]["type"] == "Polygon"
    ring = mcs[0]["coordinates"][0]
    assert abs(ring[0][0] - (-115.6424376856718)) < 1e-8
    print("self-check ok")
    print(f"  davis envelope {w:.5f}, {s:.5f}, {e:.5f}, {n:.5f}")
    print(f"  mcs vertices {len(ring)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "polygons",
        nargs="*",
        default=["davis", "mcs"],
        help="site name (davis|mcs) or polygon path (.shp/.kml/.geojson)",
    )
    p.add_argument(
        "--max-res",
        type=float,
        default=None,
        help="drop pixels with temporal_resolution >= this (days); paper uses 14",
    )
    p.add_argument("--self-check", action="store_true", help="parse AOIs only, no Zenodo")
    args = p.parse_args()
    if args.self_check:
        self_check()
        return

    ds = _open_onset()
    for name in args.polygons:
        label, geoms = _resolve(name)
        result = mean_dowy(geoms, max_res=args.max_res, ds=ds)
        _print_result(label, result)
        print()


if __name__ == "__main__":
    main()

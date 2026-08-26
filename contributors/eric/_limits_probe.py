"""Pin down what VirtualiZarr cannot do with NISAR: metadata group, RSLC, GSLC."""
import sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore", category=UserWarning)

import earthaccess, h5py, numpy as np
import virtualizarr as vz
from obspec_utils.readers import BlockStoreReader
from virtualizarr.parsers import HDFParser
import nisar_virtual as nv

BBOX = (-121.932, 46.754, -121.5707, 46.964)
registry = nv.obstore_registry()

def first_url(short_name):
    r = earthaccess.search_data(short_name=short_name, bounding_box=BBOX, count=5)
    for g in r:
        for u in g.data_links(access="direct"):
            if u.endswith(".h5"):
                return u
    return None

# --- 1. what exactly breaks the root parse? -----------------------------
print("### 1. the complex-valued attribute that breaks a root-level parse")
url = first_url("NISAR_L2_GCOV_PROVISIONAL_V1")
store, path = registry.resolve(url)
with h5py.File(BlockStoreReader(store, path), "r") as f:
    hits = []
    def visit(name, obj):
        for k, v in obj.attrs.items():
            if np.iscomplexobj(np.asarray(v)):
                hits.append((name, k, np.asarray(v).ravel()[0]))
    f.visititems(visit)
    for name, k, v in hits[:6]:
        print(f"   /{name}  attr {k!r} = {v!r}")
    print(f"   ({len(hits)} complex-valued attributes in the file)")

# --- 2. can the metadata group be virtualized at all? -------------------
print("\n### 2. HDFParser on the GCOV metadata group")
for grp in ("/science/LSAR/GCOV/metadata",
            "/science/LSAR/GCOV/metadata/sourceData",
            "/science/LSAR/identification"):
    try:
        vds = vz.open_virtual_dataset(url, registry=registry, parser=HDFParser(group=grp))
        print(f"   {grp}: OK, {len(vds.variables)} variables")
    except Exception as e:
        print(f"   {grp}: {type(e).__name__}: {str(e)[:150]}")

# --- 3. other product levels -------------------------------------------
print("\n### 3. other NISAR product levels")
CANDIDATES = [
    ("NISAR_L2_GSLC_PROVISIONAL_V1", "/science/LSAR/GSLC/grids/frequencyA"),
    ("NISAR_L1_RSLC_PROVISIONAL_V1", "/science/LSAR/RSLC/swaths/frequencyA"),
    ("NISAR_L2_GUNW_PROVISIONAL_V1", None),
]
for short_name, grp in CANDIDATES:
    u = first_url(short_name)
    if u is None:
        print(f"   {short_name}: no granules over this AOI")
        continue
    print(f"\n   {short_name}")
    store, path = registry.resolve(u)
    if grp is None:  # discover a grids/swaths group
        with h5py.File(BlockStoreReader(store, path), "r") as f:
            found = []
            f.visititems(lambda n, o: found.append(n)
                         if isinstance(o, h5py.Group) and n.count("/") == 4 else None)
            print("     groups:", found[:8])
            continue
    # what dtypes does it actually store?
    with h5py.File(BlockStoreReader(store, path), "r") as f:
        g = f[grp]
        for k in list(g.keys())[:12]:
            d = g[k]
            if isinstance(d, h5py.Dataset) and d.ndim == 2:
                print(f"     {k}: dtype={d.dtype} chunks={d.chunks} shape={d.shape}")
    try:
        vds = vz.open_virtual_dataset(u, registry=registry, parser=HDFParser(group=grp))
        print(f"     -> HDFParser OK: {list(vds.data_vars)[:6]}")
    except Exception as e:
        print(f"     -> {type(e).__name__}: {str(e)[:300]}")

import sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

import earthaccess, h5py
import virtualizarr as vz
from obspec_utils.readers import BlockStoreReader
from virtualizarr.parsers import HDFParser
import nisar_virtual as nv

BBOX = (-121.932, 46.754, -121.5707, 46.964)
registry = nv.obstore_registry()

def first_url(sn):
    for g in earthaccess.search_data(short_name=sn, bounding_box=BBOX, count=5):
        for u in g.data_links(access="direct"):
            if u.endswith(".h5"):
                return u

# Root cause: do the image rasters have HDF5 dimension scales attached?
print("### dimension scales attached to the main raster")
for sn, grp, var in (
    ("NISAR_L2_GCOV_PROVISIONAL_V1", "/science/LSAR/GCOV/grids/frequencyA", "HHHH"),
    ("NISAR_L2_GSLC_PROVISIONAL_V1", "/science/LSAR/GSLC/grids/frequencyA", "HH"),
    ("NISAR_L1_RSLC_PROVISIONAL_V1", "/science/LSAR/RSLC/swaths/frequencyA", "HH"),
):
    u = first_url(sn)
    store, path = registry.resolve(u)
    with h5py.File(BlockStoreReader(store, path), "r") as f:
        d = f[f"{grp}/{var}"]
        scales = [[sc.name for sc in d.dims[i].values()] for i in range(d.ndim)]
    print(f"  {sn.split('_')[2]:5s} {var}: {scales}")

# Practical recipe for RSLC: keep only the 2-D rasters.
print("\n### RSLC keeping only the 2-D rasters")
u = first_url("NISAR_L1_RSLC_PROVISIONAL_V1")
grp = "/science/LSAR/RSLC/swaths/frequencyA"
store, path = registry.resolve(u)
with h5py.File(BlockStoreReader(store, path), "r") as f:
    keep = {k for k, v in f[grp].items()
            if isinstance(v, h5py.Dataset) and v.ndim == 2 and v.shape[1] != 2}
    drop = [k for k, v in f[grp].items()
            if isinstance(v, h5py.Dataset) and k not in keep]
print(f"  keep={sorted(keep)}")
try:
    vds = vz.open_virtual_dataset(
        u, registry=registry, parser=HDFParser(group=grp, drop_variables=drop))
    print(vds)
    hh = vds["HH"].data
    print("\n  HH dtype :", hh.metadata.data_type)
    print("  HH chunks:", hh.metadata.chunks)
    print("  HH codecs:", hh.metadata.codecs)
    print("  HH nchunks:", len(hh.manifest))
except Exception as e:
    print(f"  {type(e).__name__}: {str(e)[:300]}")

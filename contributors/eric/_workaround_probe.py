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

# --- RSLC: does dropping the 1-D "listOf*" vars resolve the dim clash? ---
url = first_url("NISAR_L1_RSLC_PROVISIONAL_V1")
grp = "/science/LSAR/RSLC/swaths/frequencyA"
store, path = registry.resolve(url)
with h5py.File(BlockStoreReader(store, path), "r") as f:
    ds = {k: (v.shape, v.dtype) for k, v in f[grp].items() if isinstance(v, h5py.Dataset)}
print("RSLC frequencyA datasets:")
for k, (s, d) in ds.items():
    print(f"   {k:28s} {str(s):18s} {d}")

drop = [k for k, (s, d) in ds.items() if len(s) == 1 and k.startswith("listOf")]
print(f"\nretry with drop_variables={drop}")
try:
    vds = vz.open_virtual_dataset(
        url, registry=registry, parser=HDFParser(group=grp, drop_variables=drop)
    )
    print(vds)
    hh = vds["HH"].data
    print("\n   HH dtype :", hh.metadata.data_type)
    print("   HH chunks:", hh.metadata.chunks)
    print("   HH codecs:", hh.metadata.codecs)
    print("   HH nchunks:", len(hh.manifest))
except Exception as e:
    print(f"   {type(e).__name__}: {str(e)[:300]}")

# --- identification group with the offending var dropped ------------------
print("\nidentification group, dropping listOfObservationModes:")
try:
    vds = vz.open_virtual_dataset(
        first_url("NISAR_L2_GCOV_PROVISIONAL_V1"), registry=registry,
        parser=HDFParser(group="/science/LSAR/identification",
                         drop_variables=["listOfObservationModes"]))
    print("   OK:", len(vds.variables), "variables")
    for k in list(vds.variables)[:10]:
        print("     ", k, vds[k].shape, vds[k].dtype)
except Exception as e:
    print(f"   {type(e).__name__}: {str(e)[:200]}")

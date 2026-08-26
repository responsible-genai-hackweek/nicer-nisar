import sys, warnings
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
warnings.filterwarnings("ignore")

import numpy as np, h5py
from obspec_utils.readers import BlockStoreReader
import nisar_virtual as nv

BBOX = (-121.932, 46.754, -121.5707, 46.964)
track = nv.find_track(BBOX)
key, items = next(iter(track.items()))
registry = nv.obstore_registry()
print(f"track {key}: {len(items)} granules\n")

grids = defaultdict(list)
for start, url in items:
    store, path = registry.resolve(url)
    with h5py.File(BlockStoreReader(store, path), "r") as f:
        g = f[nv.GCOV_GRIDS]
        x, y = g["xCoordinates"], g["yCoordinates"]
        sig = (x.shape[0], y.shape[0], float(x[0]), float(y[0]),
               float(x[-1]), float(y[-1]), int(np.asarray(g["projection"])))
        epsg = sig[6]
    grids[sig].append(start)

print(f"{len(grids)} distinct grids across {len(items)} granules:\n")
for sig, dates in sorted(grids.items(), key=lambda kv: -len(kv[1])):
    nx, ny, x0, y0, x1, y1, epsg = sig
    print(f"  n={len(dates):2d}  EPSG:{epsg}  {ny} x {nx}  "
          f"x[{x0:.0f}..{x1:.0f}] y[{y0:.0f}..{y1:.0f}]")
    print(f"        {', '.join(d[:8] for d in sorted(dates))}")

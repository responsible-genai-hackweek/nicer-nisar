import asf_search as asf

wkt = 'POLYGON((-122.5 37.0,-121.5 37.0,-121.5 38.0,-122.5 38.0,-122.5 37.0))'

results = asf.search(
    dataset='NISAR',
    processingLevel='GCOV',        # e.g. RSLC, GSLC, GCOV, GUNW, RUNW...
    intersectsWith=wkt,
    start='2025-08-01',
    end='2026-01-01',
    dataMaturity='PROVISIONAL',    # calibrated; use 'BETA' for pre-calibration
    maxResults=50,
)

for r in results:
    sizes = r.properties.get('bytes', {})
    h5_entry = next((v for v in sizes.values() if v['format'] == 'HDF5'), None)
    if h5_entry:
        print(f"{r.properties['sceneName']}: {h5_entry['bytes']/1e6:.1f} MB (main file)")

import os
os.makedirs('./nisar_data', exist_ok=True)
session = asf.ASFSession()          # picks up ~/.netrc automatically
results[:1].download(path='./nisar_data', session=session)

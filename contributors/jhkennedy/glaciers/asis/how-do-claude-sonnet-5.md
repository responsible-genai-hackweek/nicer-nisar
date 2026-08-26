# Chat Session: Getting Glacier Velocity Estimates from NISAR

claude --resume 1a7504ee-fdbe-40f2-8fc2-cdc3b8c01487

## User Question
How do I get glacier velocity estimates from NISAR?

## Response

Here's the practical path to get glacier velocity from NISAR:

### 1. Two ways to get there

**A. Use pre-made velocity products (easiest, once available)**
- NASA's **ITS_LIVE** project ([registry.opendata.aws/its-live-data](https://registry.opendata.aws/its-live-data/)) plans to ingest NISAR into its standard velocity mosaics/time series, using the same autoRIFT pipeline it runs for Landsat/Sentinel-1/2. Check there first — if NISAR pairs are already processed, you get ready-to-use vx/vy velocity GeoTIFFs/NetCDFs with no offset-tracking work on your end.

**B. Derive velocity yourself from NISAR offset-tracking products**
NISAR has dedicated cryosphere products built for exactly this:

| Product | Level | Notes |
|---|---|---|
| **ROFF** (Range-Doppler Pixel Offsets) | L1 | Radar coordinates, 90 m pixel spacing |
| **GOFF** (Geocoded Pixel Offsets) | L2 | Map-projected (UTM/polar stereographic), 80 m posting — this is the one you want for glacier work |

Both are generated specifically "for acquisitions over Antarctica, Greenland, and selected mountain glaciers" and contain dense range/azimuth pixel offsets (plus SNR/quality layers) from speckle tracking between a reference and secondary RSLC pair — conceptually the same autoRIFT-style offset tracking used for Sentinel-1/Landsat velocity products, just done natively by the NISAR pipeline.

Important caveat straight from the product docs: **GOFF/ROFF layers are raw** — "distributed without performing any conventional post-processing... layers might contain offset outliers and are not low pass filtered." So you'll need to do your own outlier filtering/masking before treating them as velocity.

### 2. Getting the data

Search/download via `asf_search` (Python):
```python
import asf_search as asf

results = asf.search(dataset='NISAR', processingLevel='GOFF')
session = asf.ASFSession().auth_with_creds('username', 'password')  # Earthdata Login
results.download(path='./data', session=session)
```
You can also browse interactively via ASF **Vertex** or use **earthaccess**. Requires a NASA Earthdata Login. Note that as of now only **provisional** products exist for acquisitions from mid-2026 onward (earlier data was "beta" with known issues) — so real GOFF coverage is still limited/early.

### 3. Converting offsets → velocity

Once you have GOFF:
1. Read range and azimuth offset layers + their SNR/quality layers.
2. Mask low-SNR / outlier pixels (recommended since NISAR doesn't do this for you).
3. Convert pixel offsets to ground displacement using the pixel spacing (range/azimuth → ground distance, accounting for look geometry).
4. Divide displacement by the time separation between the reference and secondary acquisitions to get velocity (m/day or m/year).
5. Optionally apply your own low-pass filtering, similar to what ITS_LIVE/autoRIFT do post-hoc.

If you tell me whether you want to do this in Python (e.g., with `autoRIFT`, `rasterio`, `h5py` for the HDF5 GOFF files) I can help write the actual processing script.

### Sources

- [Geocoded Pixel Offsets (GOFF) - NISAR Data User Guide](https://nisar-docs.asf.alaska.edu/goff/)
- [NISAR Data Products - NISAR Data User Guide](https://nisar-docs.asf.alaska.edu/products-overview/)
- [Finding NISAR Data with ASF Search - NISAR Data User Guide](https://nisar-docs.asf.alaska.edu/asf-search/)
- [asf-search · PyPI](https://pypi.org/project/asf-search/)
- [Inter-mission Time Series of Land Ice Velocity and Elevation (ITS_LIVE) - Registry of Open Data on AWS](https://registry.opendata.aws/its-live-data/)
- [NISAR Provisional Geocoded Pixel Offsets (Version 1) | NASA Earthdata](https://www.earthdata.nasa.gov/data/catalog/asf-nisar-l2-goff-provisional-v1-1)
- [Cryosphere - NASA Science](https://science.nasa.gov/mission/nisar/cryosphere/)

## User Follow-up
Can you save this entire chat session to `../nicer-nisar/contributors/jhkennedy/glaciers/asis/how-do-claude-sonnet-5.md`

(this file)

# Chat Session: Getting Glacier Velocity Estimates from NISAR

claude --resume acc3c64d-ec08-4be4-962c-5955ed659fa0

## User Question
How do I get glacier velocity estimates from NISAR?

## Response

NISAR (NASA-ISRO Synthetic Aperture Radar) glacier velocity data is processed through the **ITS_LIVE** (Interagency Time Series of Land Ice Velocity and Elevation) system. Here's how to access it:

### Direct Access

1. **ITS_LIVE Portal**: Visit https://its-live.jpl.nasa.gov/ — this is the primary, login-free interface for accessing all velocity data, including NISAR-derived estimates once available.

2. **Data Discovery**: Search by glacier region or download velocity maps directly from the portal.

### NISAR Data Processing Pipeline

- NISAR scenes are ingested by the **Alaska Satellite Facility (ASF) DAAC** immediately after acquisition
- Velocity estimates are typically available **within 2 hours** of scene cataloguing
- Feature tracking is performed on 20,000+ image pairs daily using InSAR techniques

### Real-Time Notifications

Set up near-real-time alerts for new NISAR scenes:
- Use NASA's **Common Metadata Repository (CMR)** to subscribe to NISAR collection notifications
- Subscribe via AWS SQS to receive messages when new scenes are ingested

### Alternative Data Sources

For historical glacier velocity data (pre-NISAR), explore:
- [MEaSUREs Greenland Ice Velocity datasets](https://nsidc.org/data/nsidc-0481/versions/4) at NSIDC
- [ITS_LIVE regional velocity products](https://nsidc.org/sites/default/files/documents/user-guide/nsidc-0776-v002-userguide.pdf)

The velocity estimates come from InSAR processing, which measures glacier surface displacement between radar acquisitions, providing sub-meter accuracy.

### Sources

- [ITS_LIVE global glacier velocity data in near-real time](https://tc.copernicus.org/articles/19/3517/2025/tc-19-3517-2025.pdf)
- [Alaska Satellite Facility Distributed Active Archive Center](https://www.earthdata.nasa.gov/centers/asf-daac)
- [MEaSUREs Greenland Ice Velocity datasets](https://nsidc.org/data/nsidc-0481/versions/4)

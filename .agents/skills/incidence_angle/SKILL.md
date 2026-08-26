---
name: incidence_angle  
description: calculate local incidence angle for NISAR pixels within a GCOV product
whenToUse: when local incidence angles are needed for either phase-based or amplitude-based InSAR analysis
---

This skill is used to calculate local incidence angle, stores by default in ./incidence_angle_output.
    Inputs required: local path to NISAR GCOV HDF5 file, kml file for subdomain of interest, and optional DEM.

DEM is not required but can be provided.  If not available, function will download Copernicus 30m DEM.

Two examples are also in this directory for not providing DEM (run_incidence_angle_MCS.py) and when a 0.5m lidar DEM is provided (run_incidence_angle_MCS_lidar.py) for the Mores Creek Summit domain (/contributors/HPMARSHALL/MCS_domain.kml) 

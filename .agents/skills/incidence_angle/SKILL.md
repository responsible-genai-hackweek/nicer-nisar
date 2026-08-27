---
name: incidence_angle  
description: calculate local incidence angle for NISAR pixels within a GCOV product
whenToUse: when local incidence angles are needed for either phase-based or amplitude-based InSAR analysis
---

This skill is used to calculate local incidence angle, stores by default in ./incidence_angle_output.
    Inputs required: local path to NISAR GCOV HDF5 file, kml file for subdomain of interest, and optional DEM.

If you don't have a DEM, see this example: run_incidence_angle_MCS.py
If you have a specific DEM, see this example: run_incidence_angle_MCS_lidar.py


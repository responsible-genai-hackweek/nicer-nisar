#!/usr/bin/env python3
"""
Download NISAR data for the MCS survey domain.

This script searches for and downloads NISAR data products (GCOV and GUNW)
that intersect the polygon defined in MCS_domain.kml, for ascending passes
during February 1-25, 2026.

The script first shows available data (counts, sizes, product details),
downloads a single test file for verification, then leaves the full batch
download for deliberate user action.
"""

from nisar_downloader import download_nisar_data

# Define the MCS domain KML file and date range
kml_file = './MCS_domain.kml'
start_date = '2026-02-01'
end_date = '2026-02-25'
output_dir = './nisar_data'

print("=" * 140)
print("NISAR Data Download for MCS Survey Domain")
print("=" * 140)
print()

# Call the download function with test_only=True to verify before bulk download
results = download_nisar_data(
    kml_file=kml_file,
    start_date=start_date,
    end_date=end_date,
    test_only=True,
    output_dir=output_dir
)

print()
print("To download all scenes, modify this script to call:")
print("  download_nisar_data(kml_file, start_date, end_date, test_only=False, output_dir)")
print()
print("Or run the function directly in Python with test_only=False")

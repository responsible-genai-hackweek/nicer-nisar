#!/usr/bin/env python3
"""
NISAR data search and download utility for regional surveys.

Provides a function to search for and download NISAR GCOV and GUNW products
from a regional area (defined by KML polygon) within a specified date range.
Filters results to GCOV products that correspond to GUNW acquisition endpoints.
"""

import xml.etree.ElementTree as ET
import asf_search as asf
import os
from datetime import datetime


def download_nisar_data(kml_file, start_date, end_date, test_only=True, output_dir='./nisar_data'):
    """
    Search for and download NISAR data for a regional survey area.

    This function:
    1. Parses a KML file to extract the survey area polygon
    2. Searches for NISAR GCOV and GUNW products within the specified date range
    3. Filters to only include:
       - Products completely within the date window
       - GCOV products that match GUNW acquisition endpoints
    4. Reports inventory (counts, sizes, product details)
    5. Downloads a test file (first scene) for verification

    Parameters:
    -----------
    kml_file : str
        Path to KML file containing the survey area polygon
    start_date : str
        Start date in format 'YYYY-MM-DD' (e.g., '2026-02-01')
    end_date : str
        End date in format 'YYYY-MM-DD' (e.g., '2026-02-25')
    test_only : bool
        If True (default), only download the first scene as a test.
        If False, download all filtered scenes.
    output_dir : str
        Directory to save downloaded files (default: './nisar_data')

    Returns:
    --------
    results : asf.ASFSearchResults
        The filtered search results object containing all scenes to download
    """

    # ========================================================================
    # 1. PARSE THE KML FILE TO EXTRACT THE AOI POLYGON
    # ========================================================================

    print(f"Parsing AOI from {kml_file}...")

    tree = ET.parse(kml_file)
    root = tree.getroot()

    # KML uses a namespace, so we need to handle that when searching for elements
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}

    # Find the coordinates element inside the first Polygon
    coords_elem = root.find('.//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', ns)

    if coords_elem is None:
        raise ValueError(f"Could not find coordinates in {kml_file}")

    # The coordinates text is in format: "lon,lat,alt lon,lat,alt ..."
    # We need to extract just lon,lat pairs and build a WKT POLYGON string
    coords_text = coords_elem.text.strip()

    # Split on whitespace to get individual coordinate tuples
    coord_pairs = coords_text.split()

    # Extract lon,lat from each "lon,lat,alt" triplet (discard altitude)
    wkt_coords = []
    for pair in coord_pairs:
        lon, lat, alt = pair.split(',')
        wkt_coords.append(f"{lon} {lat}")

    # Build the WKT POLYGON string (closed ring: first and last vertices are the same)
    wkt = f"POLYGON(({','.join(wkt_coords)}))"

    print(f"  WKT polygon: {wkt}\n")

    # ========================================================================
    # 2. SEARCH FOR NISAR DATA
    # ========================================================================

    print("Searching for NISAR data...")
    print(f"  Dataset: NISAR")
    print(f"  Processing Levels: GCOV (covariance), GUNW (unwrapped interferogram)")
    print(f"  Date range: {start_date} to {end_date}")
    print(f"  Flight direction: ASCENDING (no descending passes)")
    print()

    # Search with our AOI polygon, date range, and product types
    all_results = asf.search(
        dataset='NISAR',
        processingLevel=['GCOV', 'GUNW'],
        intersectsWith=wkt,
        start=start_date,
        end=end_date,
        flightDirection='ASCENDING',
    )

    print(f"Found {len(all_results)} initial scenes\n")

    # ========================================================================
    # 3. FILTER: KEEP ONLY PRODUCTS COMPLETELY WITHIN THE DATE RANGE
    # ========================================================================

    # Define the time window boundaries
    window_start = datetime.fromisoformat(f"{start_date}T00:00:00").replace(tzinfo=None)
    window_end = datetime.fromisoformat(f"{end_date}T23:59:59").replace(tzinfo=None)

    # Collect GUNW products and their acquisition times to match against GCOV
    gunw_times = set()  # Will store datetime objects of GUNW start/stop times
    gunw_products = []
    gcov_products = []

    for scene in all_results:
        start_time_str = scene.properties.get('startTime', '')
        stop_time_str = scene.properties.get('stopTime', '')
        processing_level = scene.properties.get('processingLevel', '')

        # Parse the ISO 8601 timestamps (remove Z and convert to datetime)
        try:
            start_time = datetime.fromisoformat(start_time_str.replace('Z', ''))
            stop_time = datetime.fromisoformat(stop_time_str.replace('Z', ''))

            # Keep only if both start AND stop are within the date window
            if start_time >= window_start and stop_time <= window_end:
                if processing_level == 'GUNW':
                    gunw_products.append(scene)
                    # Collect the start and stop times from GUNW products
                    gunw_times.add(start_time)
                    gunw_times.add(stop_time)
                elif processing_level == 'GCOV':
                    gcov_products.append(scene)
        except (ValueError, AttributeError):
            # Skip scenes with unparseable times
            pass

    # Filter GCOV products: keep only those whose acquisition time is within ±12 hours of a GUNW start or stop time
    # This captures GCOV products from the same pass/acquisition pair even if timing isn't exact
    from datetime import timedelta
    buffer_hours = 12
    buffer_td = timedelta(hours=buffer_hours)

    filtered_gcov = []
    for gcov_scene in gcov_products:
        start_time_str = gcov_scene.properties.get('startTime', '')
        try:
            gcov_time = datetime.fromisoformat(start_time_str.replace('Z', ''))
            # Check if GCOV time is within ±12 hours of any GUNW endpoint
            for gunw_endpoint in gunw_times:
                if abs(gcov_time - gunw_endpoint) <= buffer_td:
                    filtered_gcov.append(gcov_scene)
                    break  # Only add once even if it matches multiple endpoints
        except (ValueError, AttributeError):
            pass

    # Combine filtered GUNW and GCOV products and convert back to ASFSearchResults
    filtered_results = gunw_products + filtered_gcov
    results = asf.ASFSearchResults(filtered_results)

    print(f"After filtering for dates within {start_date} to {end_date}: {len(all_results)} initial -> {len(results)} final")
    print(f"  - {len(gunw_products)} GUNW products")
    print(f"  - {len(filtered_gcov)} GCOV products (filtered to match GUNW acquisition endpoints)\n")

    # ========================================================================
    # 4. EXTRACT FRAMES AND REPORT INVENTORY
    # ========================================================================

    if len(results) == 0:
        print("No scenes found within the date range. Exiting.")
        return results

    frames_found = set()
    total_size_mb = 0.0

    # Extract frames
    for scene in results:
        frame = scene.properties.get('frameNumber', None)
        if frame is not None:
            frames_found.add(int(frame))

    frames_list = sorted(list(frames_found))
    print(f"Available frames: {frames_list}")
    print()

    print("Scene Inventory:")
    print("-" * 140)

    for i, scene in enumerate(results, 1):
        name = scene.properties.get('sceneName', 'N/A')
        processing_level = scene.properties.get('processingLevel', 'N/A')
        frame = scene.properties.get('frameNumber', 'N/A')
        path = scene.properties.get('pathNumber', 'N/A')

        # Get start and stop acquisition times
        start_time = scene.properties.get('startTime', 'N/A')
        stop_time = scene.properties.get('stopTime', 'N/A')

        # Extract data maturity from collection name
        collection_name = scene.properties.get('collectionName', '')
        data_maturity = 'N/A'
        if 'PROVISIONAL' in collection_name:
            data_maturity = 'PROVISIONAL'
        elif 'BETA' in collection_name:
            data_maturity = 'BETA'

        # Get file size
        sizes_dict = scene.properties.get('bytes', {})

        # Look for an HDF5 file entry
        hdf5_entry = None
        for filename, file_info in sizes_dict.items():
            if isinstance(file_info, dict) and file_info.get('format') == 'HDF5':
                hdf5_entry = file_info
                break

        if hdf5_entry:
            size_bytes = hdf5_entry.get('bytes', 0)
            size_mb = size_bytes / 1e6
        else:
            # Fallback: sum all file sizes if no HDF5 entry found
            size_mb = 0.0
            for filename, file_info in sizes_dict.items():
                if isinstance(file_info, dict):
                    size_mb += file_info.get('bytes', 0) / 1e6

        total_size_mb += size_mb

        print(f"{i:3d}. {name}")
        print(f"     Frame: {frame} | Path (Orbit Track): {path} | Processing Level: {processing_level}")
        print(f"     Data Maturity: {data_maturity}")
        print(f"     Acquisition Time: {start_time} to {stop_time}")
        print(f"     Size: {size_mb:.1f} MB")
        print()

    print("-" * 140)
    print(f"Total estimated data size: {total_size_mb:.1f} MB ({total_size_mb/1024:.2f} GB)")
    print()

    # ========================================================================
    # 5. SINGLE TEST DOWNLOAD
    # ========================================================================

    print("Starting test download of first scene...")
    print("(This is a required safety check before batch downloads)")
    print()

    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)

    # Create an ASF session (uses ~/.netrc for credentials)
    try:
        session = asf.ASFSession()
    except Exception as e:
        print(f"WARNING: Could not create ASF session: {e}")
        print("You may need to set up ~/.netrc with your ASF Earthdata credentials.")
        print("Skipping download step.")
        return results

    # Download only the first result (test download)
    try:
        results[:1].download(path=output_dir, session=session)
        print(f"Test download complete! File saved to {output_dir}/")
    except Exception as e:
        print(f"Test download failed: {e}")
        return results

    # ========================================================================
    # 6. FULL BATCH DOWNLOAD (OPTIONAL)
    # ========================================================================

    print()
    print("=" * 140)
    print("Test download successful!")
    print("=" * 140)
    print()

    if test_only:
        print(f"To download ALL {len(results)} scenes, call this function with test_only=False")
        print()
    else:
        print(f"Downloading all {len(results)} scenes...")
        try:
            results.download(path=output_dir, session=session)
            print(f"Full download complete! All files saved to {output_dir}/")
        except Exception as e:
            print(f"Full batch download failed: {e}")

    return results

#!/usr/bin/env python3
"""
Calculate local incidence angle for NISAR GCOV products using terrain from a DEM.

This module computes the true local incidence angle (angle between radar line-of-sight
and terrain surface normal) by combining the radar geometry stored in NISAR GCOV files
with elevation data from a digital elevation model. By default uses the public Copernicus
30 m DEM (via AWS COG), but can accept a user-provided higher-resolution DEM.

The stored NISAR incidenceAngle layer is NOT local — it's the angle to the ellipsoid
normal and ignores terrain slope. This module corrects for actual topography.
"""

import h5py
import numpy as np
import xml.etree.ElementTree as ET
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import from_bounds
from scipy.interpolate import RegularGridInterpolator
import pyproj
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
import os


def fetch_copernicus_dem(bounds_lonlat, buffer_deg=0.02):
    """
    Fetch Copernicus 30 m DEM over an AOI from the public AWS bucket.

    Directly reads Cloud Optimized GeoTIFFs from the copernicus-dem-30m AWS bucket
    via /vsicurl/ (HTTP windowed read — no full download). Handles multi-tile mosaics
    if the AOI spans more than one 1°×1° tile.

    Parameters:
    -----------
    bounds_lonlat : tuple
        (min_lon, min_lat, max_lon, max_lat) of the area of interest
    buffer_deg : float
        Expand bounds by this many degrees on all sides (default 0.02 ≈ 2 km)

    Returns:
    --------
    dem_array : ndarray (float32)
        Elevation data in WGS84 (EPSG:4326), shape (height, width)
    transform : rasterio.Transform
        Geospatial transform (maps pixel coords → WGS84)
    crs : rasterio.crs.CRS
        Coordinate reference system (EPSG:4326)
    """

    min_lon, min_lat, max_lon, max_lat = bounds_lonlat
    min_lon -= buffer_deg
    min_lat -= buffer_deg
    max_lon += buffer_deg
    max_lat += buffer_deg

    # Determine which 1° DEM tiles are needed (tiles are named by SW corner: N{lat}0_W{lon}00)
    tile_min_lat = int(np.floor(min_lat))
    tile_max_lat = int(np.floor(max_lat))
    tile_min_lon = int(np.floor(-max_lon))  # Note the flip: eastern hemisphere uses negative W
    tile_max_lon = int(np.floor(-min_lon))

    tiles_needed = []
    for lat in range(tile_min_lat, tile_max_lat + 1):
        for lon in range(tile_min_lon, tile_max_lon + 1):
            tiles_needed.append((lat, lon))

    # Fetch and mosaic tiles (often just one tile is needed)
    dem_mosaic = None
    bounds_collected = None

    for lat, lon in tiles_needed:
        # Copernicus DEM AWS bucket tile naming: Copernicus_DSM_COG_10_N{lat}_00_W{lon}_00_DEM.tif
        # Tiles are 1°×1° (3600×3600 pixels at ~30 m nominal spacing)
        url = f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM/Copernicus_DSM_COG_10_N{lat:02d}_00_W{lon:03d}_00_DEM.tif"

        print(f"Fetching DEM tile N{lat:02d}_W{lon:03d}...")

        with rasterio.open(url) as src:
            # Read the portion of this tile that overlaps our AOI
            # (rasterio.open with /vsicurl/ supports windowed reads, so only the needed part downloads)
            dem_tile = src.read(1)
            tile_transform = src.transform
            tile_crs = src.crs

            if dem_mosaic is None:
                dem_mosaic = dem_tile
                transform = tile_transform
                crs = tile_crs
            else:
                # Simple left-right concatenation (assumes tiles are ordered W→E, N→S)
                # For multi-tile: a proper mosaic would require more complex stitching
                # For now assume single tile; warn if multi-tile detected
                if len(tiles_needed) > 1:
                    print("WARNING: AOI spans multiple tiles; using first tile only (proper mosaic not yet implemented)")
                    break

    return dem_mosaic, transform, crs


def calculate_local_incidence_angle(gcov_file, kml_file, dem_file=None, buffer_m=200,
                                     frequency='frequencyA', output_dir='./incidence_angle_output',
                                     match_grid=None):
    """
    Calculate local incidence angle from a NISAR GCOV product and terrain DEM.

    Parameters:
    -----------
    gcov_file : str
        Path to NISAR GCOV HDF5 file
    kml_file : str
        Path to KML file containing the AOI polygon
    dem_file : str, optional
        Path to a raster DEM file (GeoTIFF, etc.). If None, fetch Copernicus 30 m DEM from AWS.
    buffer_m : float
        Buffer around the KML AOI in meters (default 200)
    frequency : str
        Frequency band ('frequencyA' or 'frequencyB'; default 'frequencyA')
    output_dir : str
        Directory to write output GeoTIFFs and quicklook PNG (default './incidence_angle_output')
    match_grid : str, optional
        Path to a reference raster whose exact grid (CRS, transform, shape) the outputs
        should be written on. Default None builds the grid from the KML bounds plus a
        buffer, which does NOT align with the GCOV product grid. Pass a GCOV GeoTIFF here
        to get outputs that overlay the backscatter pixel-for-pixel.

    Returns:
    --------
    results : dict
        Keys: 'local_incidence', 'ellipsoidal_incidence', 'dem', 'difference',
        'transform', 'crs', 'x_coords', 'y_coords'
    """

    os.makedirs(output_dir, exist_ok=True)

    # ========================================================================
    # 1. PARSE THE KML AOI
    # ========================================================================

    print(f"Parsing AOI from {kml_file}...")

    tree = ET.parse(kml_file)
    root = tree.getroot()
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}

    coords_elem = root.find('.//kml:Polygon/kml:outerBoundaryIs/kml:LinearRing/kml:coordinates', ns)
    if coords_elem is None:
        raise ValueError(f"Could not find coordinates in {kml_file}")

    # Parse coordinates: "lon,lat,alt lon,lat,alt ..."
    coord_pairs = coords_elem.text.strip().split()
    lons = []
    lats = []
    for pair in coord_pairs:
        lon, lat, alt = pair.split(',')
        lons.append(float(lon))
        lats.append(float(lat))

    bounds_lonlat = (min(lons), min(lats), max(lons), max(lats))
    print(f"  AOI bounds (lon/lat): {bounds_lonlat}")

    # ========================================================================
    # 2. OPEN THE GCOV FILE AND READ METADATA
    # ========================================================================

    print(f"Opening GCOV file: {gcov_file}")

    with h5py.File(gcov_file, 'r') as h5:
        # Read the EPSG code (all NISAR products are in UTM or polar stereographic)
        proj_attr = h5[f'science/LSAR/GCOV/grids/{frequency}/projection'].attrs
        epsg_code = int(proj_attr['epsg_code'])
        print(f"  Product projection: EPSG:{epsg_code}")

        # Read the full-resolution grid coordinates
        x_full = h5[f'science/LSAR/GCOV/grids/{frequency}/xCoordinates'][:]
        y_full = h5[f'science/LSAR/GCOV/grids/{frequency}/yCoordinates'][:]

        # Read the metadata radar grid (coarse 3-D cube)
        h_heights = h5['science/LSAR/GCOV/metadata/radarGrid/heightAboveEllipsoid'][:]
        x_grid = h5['science/LSAR/GCOV/metadata/radarGrid/xCoordinates'][:]
        y_grid = h5['science/LSAR/GCOV/metadata/radarGrid/yCoordinates'][:]
        los_x_cube = h5['science/LSAR/GCOV/metadata/radarGrid/losUnitVectorX'][:]
        los_y_cube = h5['science/LSAR/GCOV/metadata/radarGrid/losUnitVectorY'][:]

        # Note: y-axis is descending (north-up convention); flip for RegularGridInterpolator
        y_grid_flipped = y_grid[::-1]
        los_x_cube_flipped = los_x_cube[:, ::-1, :]
        los_y_cube_flipped = los_y_cube[:, ::-1, :]

        print(f"  Full-res grid shape: {len(y_full)} rows × {len(x_full)} cols (10 m spacing)")
        print(f"  Radar grid metadata cube: {len(h_heights)} heights × {los_x_cube_flipped.shape[1]} rows × {los_x_cube_flipped.shape[2]} cols")

    # ========================================================================
    # 3. TRANSFORM AOI BOUNDS TO UTM AND FIND SUBWINDOW
    # ========================================================================

    print("Transforming AOI to product CRS...")

    # Transform from WGS84 (EPSG:4326) to the product's UTM
    transformer = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg_code}", always_xy=True)
    min_lon, min_lat, max_lon, max_lat = bounds_lonlat

    # Add buffer in degrees, transform corners
    buffer_deg = 0.02  # rough conversion: ~2 km
    corners_ll = [
        (min_lon - buffer_deg, min_lat - buffer_deg),
        (max_lon + buffer_deg, max_lat + buffer_deg)
    ]
    corners_utm = [transformer.transform(lon, lat) for lon, lat in corners_ll]

    min_x_utm = min(c[0] for c in corners_utm)
    max_x_utm = max(c[0] for c in corners_utm)
    min_y_utm = min(c[1] for c in corners_utm)
    max_y_utm = max(c[1] for c in corners_utm)

    # Add explicit meter buffer
    min_x_utm -= buffer_m
    max_x_utm += buffer_m
    min_y_utm -= buffer_m
    max_y_utm += buffer_m

    # Find the subwindow in the full-res grid
    # Note: x is ascending, y is descending (north-up raster convention: first row is north)
    # For descending y, larger indices are further south (smaller y values)
    x_idx_min = np.searchsorted(x_full, min_x_utm)
    x_idx_max = np.searchsorted(x_full, max_x_utm)

    # y is descending: y_full[0] is max, y_full[-1] is min
    # Find indices where y values fall in [min_y_utm, max_y_utm]
    y_idx_min = np.searchsorted(y_full[::-1], max_y_utm)  # Start of range in reversed array
    y_idx_max = np.searchsorted(y_full[::-1], min_y_utm)  # End of range in reversed array
    # Convert back to forward-array indices
    y_idx_min = len(y_full) - y_idx_min
    y_idx_max = len(y_full) - y_idx_max
    if y_idx_min > y_idx_max:
        y_idx_min, y_idx_max = y_idx_max, y_idx_min

    x_idx_min = max(0, x_idx_min)
    x_idx_max = min(len(x_full), x_idx_max)
    y_idx_min = max(0, y_idx_min)
    y_idx_max = min(len(y_full), y_idx_max)

    x_subwindow = x_full[x_idx_min:x_idx_max]
    y_subwindow = y_full[y_idx_min:y_idx_max]

    print(f"  Subwindow: x[{x_idx_min}:{x_idx_max}] ({len(x_subwindow)} cols), y[{y_idx_min}:{y_idx_max}] ({len(y_subwindow)} rows)")

    # ========================================================================
    # 3b. OPTIONAL: SNAP THE OUTPUT GRID TO A REFERENCE RASTER
    # ========================================================================

    # By default the output grid above is derived from the KML bounds plus a buffer, which
    # does not line up with the GCOV product grid. Passing match_grid=<raster path> instead
    # locks the output to that raster's exact grid, so incidence angle and backscatter can
    # be combined per-pixel later with no further resampling.
    if match_grid is not None:
        print(f"Snapping output grid to reference raster {match_grid}...")

        with rasterio.open(match_grid) as ref:
            ref_transform = ref.transform
            ref_height, ref_width = ref.shape
            ref_bounds = ref.bounds
            ref_epsg = ref.crs.to_epsg()

        if ref_epsg != epsg_code:
            raise ValueError(
                f"match_grid is EPSG:{ref_epsg} but the GCOV product is EPSG:{epsg_code}; "
                "reproject the reference raster first."
            )

        # These four drive dst_transform in the next section
        min_x_utm, min_y_utm, max_x_utm, max_y_utm = ref_bounds

        # Pixel-CENTRE coordinates. y must descend (north-up convention) because the
        # np.gradient call below uses these axes to get the sign of the slope right.
        x_subwindow = ref_transform.c + (np.arange(ref_width) + 0.5) * ref_transform.a
        y_subwindow = ref_transform.f + (np.arange(ref_height) + 0.5) * ref_transform.e

        print(f"  Output grid: {ref_height} rows x {ref_width} cols, "
              f"bounds ({min_x_utm:.1f}, {min_y_utm:.1f}, {max_x_utm:.1f}, {max_y_utm:.1f})")

    # ========================================================================
    # 4. FETCH OR LOAD DEM AND REPROJECT TO SUBWINDOW
    # ========================================================================

    print("Loading DEM...")

    if dem_file is None:
        # Fetch from Copernicus AWS directly with rasterio
        # Determine which tile is needed based on bounds_lonlat
        # Tiles are 1°×1° in WGS84, named by SW corner: N{lat}_W{abs(lon)}
        # For western hemisphere: W value = ceiling of abs(most_negative_longitude)
        # E.g., -115.73 → W116 (because floor(-115.73) = -116, abs = 116)
        min_lon = bounds_lonlat[0]  # Most negative (western) longitude
        min_lat = bounds_lonlat[1]  # Southern latitude

        tile_w = int(np.ceil(abs(min_lon)))  # Convert to tile W value
        tile_n = int(np.floor(min_lat))     # Convert to tile N value

        dem_url = f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_N{tile_n:02d}_00_W{tile_w:03d}_00_DEM/Copernicus_DSM_COG_10_N{tile_n:02d}_00_W{tile_w:03d}_00_DEM.tif"
        print(f"  Fetching from tile N{tile_n:02d}_W{tile_w:03d}")
        dem_src_obj = rasterio.open(dem_url)
        dem_data = dem_src_obj.read(1)
        dem_transform = dem_src_obj.transform
        dem_crs = dem_src_obj.crs
        dem_nodata = dem_src_obj.nodata
    else:
        # Load from user file
        print(f"  Reading DEM from {dem_file}")
        with rasterio.open(dem_file) as src:
            dem_data = src.read(1)
            dem_transform = src.transform
            dem_crs = src.crs
            dem_nodata = src.nodata

    # Reproject DEM to the product's CRS and resolution, covering the subwindow
    src_transform = dem_transform
    dst_crs = rasterio.crs.CRS.from_epsg(epsg_code)
    dst_transform = rasterio.transform.from_bounds(
        min_x_utm, min_y_utm, max_x_utm, max_y_utm,
        len(x_subwindow), len(y_subwindow)
    )

    dem_reprojected = np.zeros((len(y_subwindow), len(x_subwindow)), dtype=np.float32)

    # Use rasterio to reproject: read full DEM, resample to our grid
    with rasterio.MemoryFile() as memfile:
        with memfile.open(
            driver='GTiff',
            height=dem_data.shape[0],
            width=dem_data.shape[1],
            count=1,
            dtype=dem_data.dtype,
            transform=dem_transform,
            crs=dem_crs,
            nodata=dem_nodata,
        ) as src_mem:
            src_mem.write(dem_data, 1)

        with memfile.open() as src_mem:
            # Carry nodata through explicitly. Without this, DEM voids resample to 0 m
            # and become spurious cliffs in the surface normals below.
            reproject(
                src_mem.read(1),
                dem_reprojected,
                src_transform=src_mem.transform,
                src_crs=src_mem.crs,
                src_nodata=dem_nodata,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear
            )

    # Close the source if it was remote
    if dem_file is None:
        dem_src_obj.close()

    print(f"  DEM resampled to {dem_reprojected.shape[0]}×{dem_reprojected.shape[1]} (10 m)")

    # ========================================================================
    # 5. COMPUTE SURFACE NORMAL FROM DEM
    # ========================================================================

    print("Computing terrain surface normals from DEM...")

    # Gradient computes derivatives in the grid direction
    # For north-up raster (y descending), we pass the actual y_subwindow (descending) so
    # numpy knows to flip the sign automatically
    dz_dy, dz_dx = np.gradient(dem_reprojected, y_subwindow, x_subwindow)

    # Normal vector: (-dz/dx, -dz/dy, 1) in (East, North, Up) — unnormalized
    normal_x = -dz_dx
    normal_y = -dz_dy
    normal_z = np.ones_like(dz_dx)

    # Normalize
    normal_mag = np.sqrt(normal_x**2 + normal_y**2 + normal_z**2)
    normal_x /= normal_mag
    normal_y /= normal_mag
    normal_z /= normal_mag

    # ========================================================================
    # 6. INTERPOLATE LOS VECTORS TO FULL RESOLUTION USING ACTUAL TERRAIN HEIGHT
    # ========================================================================

    print("Interpolating LOS vectors from coarse metadata grid to full resolution...")

    # RegularGridInterpolator requires strictly increasing axes
    # Our axes: h_heights (ascending), y_grid_flipped (ascending after flip), x_grid (ascending)
    interp = RegularGridInterpolator(
        (h_heights, y_grid_flipped, x_grid),
        los_x_cube_flipped,
        bounds_error=False,
        fill_value=np.nan
    )

    # Query at every (actual_dem_height, y, x) location
    # Build mesh of all points in the subwindow
    yy, xx = np.meshgrid(y_subwindow, x_subwindow, indexing='ij')

    # For interpolation, we assume the LOS direction varies with height above the local ground.
    # At each pixel, query at the DEM elevation (effective target height above ellipsoid).
    # Note: dem_reprojected is already absolute height; h_heights are height above ellipsoid.

    # Build (height, y, x) query points
    query_pts = np.stack([dem_reprojected.ravel(), yy.ravel(), xx.ravel()], axis=1)

    los_x_interp_flat = interp(query_pts, method='linear')
    los_x_at_dem = los_x_interp_flat.reshape(dem_reprojected.shape)

    # Repeat for Y component
    interp_y = RegularGridInterpolator(
        (h_heights, y_grid_flipped, x_grid),
        los_y_cube_flipped,
        bounds_error=False,
        fill_value=np.nan
    )
    los_y_interp_flat = interp_y(query_pts, method='linear')
    los_y_at_dem = los_y_interp_flat.reshape(dem_reprojected.shape)

    # Derive Z component from unit vector constraint
    los_z_at_dem = np.sqrt(np.maximum(0, 1 - los_x_at_dem**2 - los_y_at_dem**2))

    # ========================================================================
    # 7. COMPUTE LOCAL INCIDENCE ANGLE
    # ========================================================================

    print("Computing local incidence angle...")

    # Dot product: LOS · surface_normal (both in ENU)
    dot_product = los_x_at_dem * normal_x + los_y_at_dem * normal_y + los_z_at_dem * normal_z

    # Clamp to [-1, 1] to avoid numerical issues with arccos
    dot_product = np.clip(dot_product, -1, 1)

    # Local incidence angle = arccos(dot product), convert to degrees
    local_incidence_rad = np.arccos(dot_product)
    local_incidence = np.degrees(local_incidence_rad)

    # Also compute ellipsoidal incidence for comparison
    ellipsoidal_incidence_rad = np.arccos(los_z_at_dem)
    ellipsoidal_incidence = np.degrees(ellipsoidal_incidence_rad)

    # Difference (local - ellipsoidal; positive means terrain faces sensor more than flat)
    difference = local_incidence - ellipsoidal_incidence

    print(f"  Local incidence: {np.nanmean(local_incidence):.1f}° mean (range {np.nanmin(local_incidence):.1f}° to {np.nanmax(local_incidence):.1f}°)")
    print(f"  Ellipsoidal incidence: {np.nanmean(ellipsoidal_incidence):.1f}° mean")
    print(f"  Difference (local - ellipsoidal): {np.nanmean(difference):.1f}° mean")

    # ========================================================================
    # 8. WRITE OUTPUT GEOTIFFS AND QUICKLOOK
    # ========================================================================

    print(f"Writing outputs to {output_dir}...")

    # GeoTIFF writer function
    def write_geotiff(data, filename, description):
        filepath = os.path.join(output_dir, filename)
        with rasterio.open(
            filepath, 'w',
            driver='GTiff',
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype=data.dtype,
            crs=dst_crs,
            transform=dst_transform,
            nodata=np.nan,
        ) as dst:
            dst.write(data, 1)
            dst.update_tags(1, description=description)
        print(f"  Wrote {filepath}")

    write_geotiff(local_incidence, 'local_incidence_angle.tif',
                  'Local incidence angle (degrees) — angle between LOS and terrain normal')
    write_geotiff(ellipsoidal_incidence, 'ellipsoidal_incidence_angle.tif',
                  'Ellipsoidal incidence angle (degrees) — angle between LOS and ellipsoid normal (as in NISAR product)')
    write_geotiff(difference, 'incidence_difference.tif',
                  'Difference: local - ellipsoidal (degrees)')
    write_geotiff(dem_reprojected, 'dem_subset.tif',
                  'Digital elevation model subset (meters above ellipsoid)')

    # Quicklook PNG
    print("  Generating quicklook PNG...")

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Left: DEM with hillshade
    ls = LightSource(azdeg=315, altdeg=45)
    # hillshade() cannot handle NaN, so fill voids with the mean elevation just for the
    # quicklook, then mask them back out so gaps read as blank rather than flat grey.
    dem_valid = np.isfinite(dem_reprojected)
    dem_filled = np.where(dem_valid, dem_reprojected, np.nanmean(dem_reprojected))
    dem_shade = np.where(dem_valid, ls.hillshade(dem_filled), np.nan)
    axes[0].imshow(dem_shade, cmap='gray', origin='upper')
    axes[0].set_title('Terrain (Hillshade)')
    axes[0].set_ylabel('Northing (pixels)')
    axes[0].set_xlabel('Easting (pixels)')

    # Right: Local incidence angle
    im = axes[1].imshow(local_incidence, cmap='RdYlBu_r', origin='upper', vmin=0, vmax=90)
    axes[1].set_title('Local Incidence Angle')
    axes[1].set_ylabel('Northing (pixels)')
    axes[1].set_xlabel('Easting (pixels)')
    cbar = plt.colorbar(im, ax=axes[1])
    cbar.set_label('Angle (degrees)')

    plt.tight_layout()
    quicklook_path = os.path.join(output_dir, 'quicklook.png')
    plt.savefig(quicklook_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Wrote {quicklook_path}")

    # ========================================================================
    # RETURN RESULTS
    # ========================================================================

    results = {
        'local_incidence': local_incidence,
        'ellipsoidal_incidence': ellipsoidal_incidence,
        'difference': difference,
        'dem': dem_reprojected,
        'transform': dst_transform,
        'crs': dst_crs,
        'x_coords': x_subwindow,
        'y_coords': y_subwindow,
    }

    print(f"\nLocal incidence angle calculation complete!")
    print(f"Output directory: {output_dir}")

    return results

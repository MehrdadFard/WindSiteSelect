# SPDX-License-Identifier: GPL-2.0-or-later
"""
Helper functions for CRS checking and reprojection before rasterization.
This addresses the issue where geographic CRS (EPSG:4326) causes invalid raster dimensions
when using metric pixel sizes (10x10 meters).
"""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsRectangle,
    QgsProcessingException
)
from qgis.PyQt.QtCore import QCoreApplication


def is_geographic_crs(crs):
    """
    Check if a CRS is geographic (uses degrees, not meters).
    
    Args:
        crs: QgsCoordinateReferenceSystem object
        
    Returns:
        bool: True if CRS is geographic, False if projected
    """
    if not crs.isValid():
        return False
    
    # Check if CRS is geographic (uses angular units like degrees)
    return crs.isGeographic()


def get_utm_crs_for_extent(extent, source_crs):
    """
    Determine an appropriate UTM CRS based on the layer's extent.
    
    Args:
        extent: QgsRectangle of the layer extent
        source_crs: QgsCoordinateReferenceSystem of the source layer
        
    Returns:
        QgsCoordinateReferenceSystem: Appropriate UTM CRS
    """
    # Get the center longitude of the extent
    # If source CRS is geographic, use extent directly
    # Otherwise, transform to geographic first
    if source_crs.isGeographic():
        center_lon = (extent.xMinimum() + extent.xMaximum()) / 2.0
        center_lat = (extent.yMinimum() + extent.yMaximum()) / 2.0
    else:
        # Transform extent to geographic to get center coordinates
        geo_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source_crs, geo_crs, QgsProject.instance())
        geo_extent = transform.transformBoundingBox(extent)
        center_lon = (geo_extent.xMinimum() + geo_extent.xMaximum()) / 2.0
        center_lat = (geo_extent.yMinimum() + geo_extent.yMaximum()) / 2.0
    
    # Determine UTM zone (1-60)
    utm_zone = int((center_lon + 180) / 6) + 1
    
    # Determine hemisphere (N or S)
    hemisphere = 'N' if center_lat >= 0 else 'S'
    
    # Calculate EPSG code
    # UTM North: EPSG:32601 to EPSG:32660
    # UTM South: EPSG:32701 to EPSG:32760
    if hemisphere == 'N':
        epsg_code = 32600 + utm_zone
    else:
        epsg_code = 32700 + utm_zone
    
    utm_crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")
    
    if not utm_crs.isValid():
        # Fallback: ETRS89 UTM 32N for Germany / central Europe
        utm_crs = QgsCoordinateReferenceSystem("EPSG:25832")
    
    return utm_crs





# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Analysis CRS selection from AOI geometry (global use — not limited to a single fixed EPSG).
"""
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

from .aoi_tools import normalize_polygon_aoi_geometry


# Approximate Europe extent suitable for ETRS89 / LAEA Europe (EPSG:3035) — INSPIRE-style
EUROPE_LON_MIN = -25.0
EUROPE_LON_MAX = 45.0
EUROPE_LAT_MIN = 34.0
EUROPE_LAT_MAX = 72.0


def get_analysis_crs_for_geometry(geometry: QgsGeometry, source_crs: QgsCoordinateReferenceSystem):
    """
    Choose a projected CRS for metric analysis from the AOI geometry.

    * AOI centroid in WGS84 inside Europe bounds → EPSG:3035 (ETRS89 LAEA Europe).
    * Otherwise → WGS 84 / UTM zone by centroid longitude and hemisphere.

    Does not use map canvas CRS.

    Args:
        geometry: QgsGeometry in source_crs (polygon or multipolygon).
        source_crs: CRS of the geometry.

    Returns:
        QgsCoordinateReferenceSystem (projected, valid).

    Raises:
        ValueError: if geometry or CRS is unusable.
    """
    if not geometry or geometry.isEmpty():
        raise ValueError("AOI geometry is empty.")
    if not source_crs or not source_crs.isValid():
        raise ValueError("Invalid source CRS for AOI.")

    g = normalize_polygon_aoi_geometry(QgsGeometry(geometry))
    if g.isEmpty():
        raise ValueError("AOI geometry is empty after makeValid().")

    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    g_wgs = QgsGeometry(g)
    if source_crs.authid() != wgs84.authid():
        tr = QgsCoordinateTransform(source_crs, wgs84, QgsProject.instance())
        try:
            g_wgs.transform(tr)
        except Exception as e:
            raise ValueError(f"Could not reproject AOI to WGS 84 for CRS choice: {e}") from e

    c = g_wgs.centroid()
    if c is None or c.isEmpty():
        b = g_wgs.boundingBox()
        lon = (b.xMinimum() + b.xMaximum()) / 2.0
        lat = (b.yMinimum() + b.yMaximum()) / 2.0
    else:
        pt = c.asPoint()
        lon, lat = float(pt.x()), float(pt.y())

    if EUROPE_LON_MIN <= lon <= EUROPE_LON_MAX and EUROPE_LAT_MIN <= lat <= EUROPE_LAT_MAX:
        crs = QgsCoordinateReferenceSystem("EPSG:3035")
        if crs.isValid():
            return crs

    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    epsg_code = 32600 + zone if lat >= 0.0 else 32700 + zone
    crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")
    if crs.isValid():
        return crs

    fallback = QgsCoordinateReferenceSystem("EPSG:3035")
    if fallback.isValid():
        return fallback
    raise ValueError("Could not determine a valid projected analysis CRS.")


def get_analysis_crs(aoi_geometry: QgsGeometry, source_crs: QgsCoordinateReferenceSystem):
    """Alias for :func:`get_analysis_crs_for_geometry` (same signature as the public API name)."""
    return get_analysis_crs_for_geometry(aoi_geometry, source_crs)

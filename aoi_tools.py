# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
AOI map tools and vector file helpers for Wind Site Select.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsGeometry,
    QgsPointXY,
    QgsProviderRegistry,
    QgsVectorLayer,
    QgsWkbTypes,
)
try:
    from qgis.core import Qgis
except ImportError:
    Qgis = None
from qgis.gui import QgsMapTool, QgsRubberBand

AOI_MIN_POLYGON_VERTICES = 3


def _qt_enum(group_name, member_name, fallback_attr=None):
    """Resolve Qt enums for PyQt5 (Qt.Member) and PyQt6 (Qt.Group.Member)."""
    fallback_attr = fallback_attr or member_name
    group = getattr(Qt, group_name, None)
    if group is not None and hasattr(group, member_name):
        return getattr(group, member_name)
    return getattr(Qt, fallback_attr)


QT_CROSS_CURSOR = _qt_enum("CursorShape", "CrossCursor", "CrossCursor")
QT_LEFT_BUTTON = _qt_enum("MouseButton", "LeftButton", "LeftButton")
QT_RIGHT_BUTTON = _qt_enum("MouseButton", "RightButton", "RightButton")
QT_KEY_ESCAPE = _qt_enum("Key", "Key_Escape", "Key_Escape")
QT_KEY_BACKSPACE = _qt_enum("Key", "Key_Backspace", "Key_Backspace")
QT_KEY_DELETE = _qt_enum("Key", "Key_Delete", "Key_Delete")
QT_KEY_Z = _qt_enum("Key", "Key_Z", "Key_Z")
QT_CONTROL_MODIFIER = _qt_enum("KeyboardModifier", "ControlModifier", "ControlModifier")


def _geometry_is_polygonal(g):
    """True if QgsGeometry is polygon/multipolygon (not point/line/collection-only)."""
    if not g or g.isEmpty():
        return False
    try:
        t = g.type()
        if t == QgsWkbTypes.PolygonGeometry or (Qgis is not None and t == Qgis.GeometryType.Polygon):
            return True
    except Exception:
        pass
    try:
        gt = QgsWkbTypes.geometryType(g.wkbType())
        if gt == QgsWkbTypes.PolygonGeometry or (Qgis is not None and gt == Qgis.GeometryType.Polygon):
            return True
        if hasattr(QgsWkbTypes, "GeometryType") and gt == QgsWkbTypes.GeometryType.Polygon:
            return True
    except Exception:
        pass
    return False


def is_polygonal_aoi_geometry(g):
    """Public check for polygon AOI (after normalize); use in create_aoi_layer_from_geometry."""
    return _geometry_is_polygonal(g)


def _collect_polygon_parts(geom):
    """Collect polygon QgsGeometry parts from a geometry (handles collections / multiparts)."""
    out = []
    g = QgsGeometry(geom)
    if g.isEmpty():
        return out
    if _geometry_is_polygonal(g):
        return [QgsGeometry(g)]
    try:
        for part in g.parts():
            pg = QgsGeometry(part)
            if _geometry_is_polygonal(pg) and not pg.isEmpty():
                out.append(pg)
    except Exception:
        pass
    return out


def normalize_polygon_aoi_geometry(geom):
    """
    Run makeValid(); if GEOS returns a GeometryCollection, merge polygon parts or buffer(0).
    """
    g = QgsGeometry(geom)
    if g.isEmpty():
        return g
    g = g.makeValid()
    if g.isEmpty():
        return g
    if _geometry_is_polygonal(g):
        return g
    u = QgsGeometry.unaryUnion([g])
    if not u.isEmpty() and _geometry_is_polygonal(u):
        return u
    polys = _collect_polygon_parts(u if not u.isEmpty() else g)
    if polys:
        merged = QgsGeometry.unaryUnion(polys)
        if not merged.isEmpty() and _geometry_is_polygonal(merged):
            return merged
        if len(polys) == 1:
            return polys[0]
    try:
        buf = u.buffer(0.0, 8) if not u.isEmpty() else g.buffer(0.0, 8)
        if not buf.isEmpty() and _geometry_is_polygonal(buf):
            return buf
    except Exception:
        pass
    try:
        src = u if not u.isEmpty() else g
        if not _geometry_is_polygonal(src) and not src.isEmpty():
            e = src.boundingBox()
            if e.isValid():
                pad = max(abs(e.width()), abs(e.height()), 1e-18) * 1e-6 + 1e-12
                buf2 = src.buffer(pad, 8)
                if not buf2.isEmpty() and _geometry_is_polygonal(buf2):
                    return buf2
    except Exception:
        pass
    try:
        e = g.boundingBox()
        if e.isValid() and e.width() > 0 and e.height() > 0:
            br = QgsGeometry.fromRect(e)
            if not br.isEmpty() and _geometry_is_polygonal(br):
                return br
    except Exception:
        pass
    return g


VECTOR_FILE_FILTER = (
    "Vector files (*.shp *.SHP *.gpkg *.GPKG *.geojson *.GEOJSON *.json *.JSON);;"
    "All files (*.*)"
)


def iter_vector_layers_from_path(path: str):
    """
    Yield valid QgsVectorLayer instances for the given path (handles multi-layer containers).
    """
    if not path:
        return
    vl = QgsVectorLayer(path, "aoi_import", "ogr")
    if vl.isValid():
        yield vl
        return
    try:
        registry = QgsProviderRegistry.instance()
        subs = registry.querySublayers(path)
    except (AttributeError, Exception):
        subs = []
    for sub in subs:
        try:
            uri = sub.uri()
            name = sub.name() or "layer"
            provider = sub.providerKey() or "ogr"
        except Exception:
            continue
        if not uri:
            continue
        layer = QgsVectorLayer(uri, name, provider)
        if layer.isValid():
            yield layer


def collect_polygon_geometries_from_layer(layer: QgsVectorLayer):
    """Collect polygon geometries from a vector layer (skips empty / non-polygon)."""
    geoms = []
    if not layer or not layer.isValid():
        return geoms
    for feat in layer.getFeatures():
        g = feat.geometry()
        if g is None or g.isEmpty():
            continue
        if g.type() != QgsWkbTypes.PolygonGeometry:
            continue
        geoms.append(QgsGeometry(g))
    return geoms


def merge_polygon_geometries(geoms):
    """Merge polygon geometries with unaryUnion; returns single QgsGeometry or None."""
    if not geoms:
        return None
    if len(geoms) == 1:
        return QgsGeometry(geoms[0])
    return QgsGeometry.unaryUnion(geoms)


def load_polygon_geometry_from_vector_file(path: str):
    """
    Load and merge all polygon features from supported vector files.

    Returns:
        tuple: (QgsGeometry, QgsCoordinateReferenceSystem)

    Raises:
        ValueError: with a user-facing message on failure.
    """
    if not path or not path.strip():
        raise ValueError("No file path provided.")
    layers = list(iter_vector_layers_from_path(path))
    if not layers:
        raise ValueError(
            "Could not open the file as a vector layer.\n\n"
            "Check that the path is valid and the format is supported (.shp, .gpkg, .geojson)."
        )
    all_geoms = []
    crs = None
    for layer in layers:
        if crs is None and layer.crs().isValid():
            crs = layer.crs()
        all_geoms.extend(collect_polygon_geometries_from_layer(layer))
    if not all_geoms:
        raise ValueError(
            "No polygon or multipolygon features were found in the file.\n\n"
            "Use a layer that contains at least one polygon feature."
        )
    merged = merge_polygon_geometries(all_geoms)
    if merged is None or merged.isEmpty():
        raise ValueError("Merged AOI geometry is empty.")
    merged = normalize_polygon_aoi_geometry(merged)
    if merged.isEmpty():
        raise ValueError("AOI geometry is empty after makeValid().")
    if not is_polygonal_aoi_geometry(merged):
        raise ValueError("AOI must be polygon or multipolygon geometry.")
    if crs is None or not crs.isValid():
        raise ValueError("The layer has no valid CRS. Please define CRS on the file or use another source.")
    return merged, crs


class PolygonMapTool(QgsMapTool):
    """
    Digitize a polygon AOI: left-click vertices, move shows preview,
    right-click or double-click to finish, Esc to cancel,
    Backspace / Ctrl+Z to undo last vertex.
    """

    def __init__(self, canvas, on_finished, on_cancelled=None, parent=None):
        super().__init__(canvas)
        self.canvas = canvas
        self._on_finished = on_finished
        self._on_cancelled = on_cancelled
        self._parent = parent
        self._msg_parent = None
        self.points = []
        self._cursor_point = None
        self._rubber_band = None
        self.setCursor(QT_CROSS_CURSOR)

    def _message_parent(self):
        if self._msg_parent is None:
            try:
                w = self.canvas.window()
                self._msg_parent = w if w is not None else self._parent
            except Exception:
                self._msg_parent = self._parent
        return self._msg_parent

    def _qt(self):
        try:
            return self._parent.get_qt_constants() if self._parent else None
        except Exception:
            return None

    def _make_rubber(self):
        self._cleanup_rubber()
        qt = self._qt()
        red = qt.get("red", 0xFF0000) if qt else 0xFF0000
        rb = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        rb.setColor(QColor(red))
        rb.setFillColor(QColor(0, 0, 0, 0))
        rb.setWidth(2)
        self._rubber_band = rb

    def _cleanup_rubber(self):
        if self._rubber_band is not None:
            try:
                self._rubber_band.reset(QgsWkbTypes.PolygonGeometry)
                if self.canvas and self.canvas.scene():
                    self.canvas.scene().removeItem(self._rubber_band)
            except Exception:
                pass
            self._rubber_band = None

    def _redraw_rubber(self):
        if self._rubber_band is None:
            self._make_rubber()
        rb = self._rubber_band
        rb.reset(QgsWkbTypes.PolygonGeometry)
        if len(self.points) == 0:
            return
        ring = []
        for p in self.points:
            ring.append(p)
        if self._cursor_point is not None:
            ring.append(self._cursor_point)
        if len(ring) < 2:
            for p in ring:
                rb.addPoint(p)
            return
        if len(ring) >= 3:
            closed = list(ring)
            closed.append(self.points[0])
            poly = QgsGeometry.fromPolygonXY([closed])
            rb.setToGeometry(poly, None)
        else:
            ls = QgsGeometry.fromPolylineXY(ring)
            rb.setToGeometry(ls, None)

    def canvasMoveEvent(self, event):
        self._cursor_point = self.toMapCoordinates(event.pos())
        self._redraw_rubber()

    def canvasReleaseEvent(self, event):
        if event.button() == QT_RIGHT_BUTTON:
            self._cursor_point = None
            self._try_finish()
            event.accept()
            return
        if event.button() == QT_LEFT_BUTTON:
            self._cursor_point = None
            p = self.toMapCoordinates(event.pos())
            self.points.append(QgsPointXY(p))
            self._redraw_rubber()
            event.accept()
            return
        super().canvasReleaseEvent(event)

    def canvasDoubleClickEvent(self, event):
        """Finish digitizing (two-click finish gesture; may add one extra vertex — use Undo)."""
        self._cursor_point = None
        self._try_finish()
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key == QT_KEY_ESCAPE:
            self._cancel()
            event.accept()
            return
        if key == QT_KEY_BACKSPACE or key == QT_KEY_DELETE:
            self._undo_vertex()
            event.accept()
            return
        if key == QT_KEY_Z and (mods & QT_CONTROL_MODIFIER):
            self._undo_vertex()
            event.accept()
            return
        super().keyPressEvent(event)

    def _undo_vertex(self):
        if self.points:
            self.points.pop()
            self._redraw_rubber()

    def _cancel(self):
        self.points = []
        self._cursor_point = None
        self._cleanup_rubber()
        if self._on_cancelled:
            try:
                self._on_cancelled()
            except Exception:
                pass
        self.canvas.unsetMapTool(self)

    def _try_finish(self):
        self._cursor_point = None
        if len(self.points) < AOI_MIN_POLYGON_VERTICES:
            QMessageBox.warning(
                self._parent.dlg if self._parent and hasattr(self._parent, "dlg") else None,
                "AOI Polygon",
                f"At least {AOI_MIN_POLYGON_VERTICES} vertices are required to close the polygon.",
            )
            self._redraw_rubber()
            return
        ring = [QgsPointXY(p) for p in self.points]
        ring.append(ring[0])
        geom = QgsGeometry.fromPolygonXY([ring])
        geom = normalize_polygon_aoi_geometry(geom)
        if geom.isEmpty():
            QMessageBox.critical(
                self._message_parent(),
                "Invalid AOI",
                "The polygon geometry is empty after repair.\n\n"
                "Try again with a simpler shape.",
            )
            return
        if hasattr(geom, "isGeosValid") and not geom.isGeosValid():
            QMessageBox.critical(
                self._message_parent(),
                "Invalid AOI",
                "The polygon geometry is invalid even after repair.\n\n"
                "Try again with a simpler shape or more spacing between vertices.",
            )
            return
        self._cleanup_rubber()
        self.canvas.unsetMapTool(self)
        if self._on_finished:
            try:
                self._on_finished(geom)
            except Exception as e:
                QMessageBox.critical(
                    self._message_parent(),
                    "AOI Error",
                    str(e),
                )

    def activate(self):
        self.points = []
        self._cursor_point = None
        self._make_rubber()
        super().activate()

    def deactivate(self):
        self._cleanup_rubber()
        super().deactivate()

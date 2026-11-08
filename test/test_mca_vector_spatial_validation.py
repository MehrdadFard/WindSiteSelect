# -*- coding: utf-8 -*-
"""
Regression: pre-rasterization spatial intersection must not false-negative on
large layers where only late features intersect the analysis grid.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_QGIS = False
_qgis_err = None
_plugin_mod = None
_app = None


def _bootstrap():
    global _QGIS, _qgis_err, _plugin_mod, _app
    if _QGIS:
        return True
    try:
        qgis_prefix = r"C:\Program Files\QGIS 4.0.3"
        qgis_python = os.path.join(qgis_prefix, r"apps\qgis\python")
        for p in (qgis_python, os.path.join(qgis_python, "plugins")):
            if p not in sys.path:
                sys.path.insert(0, p)
        os.environ["PATH"] = (
            os.path.join(qgis_prefix, "bin")
            + os.pathsep
            + os.path.join(qgis_prefix, r"apps\Qt6\bin")
            + os.pathsep
            + os.environ.get("PATH", "")
        )
        os.environ["QGIS_PREFIX_PATH"] = qgis_prefix
        os.environ["GDAL_DATA"] = os.path.join(qgis_prefix, r"apps\gdal\share\gdal")
        os.environ["PROJ_LIB"] = os.path.join(qgis_prefix, r"share\proj")
        os.environ["PROJ_DATA"] = os.path.join(qgis_prefix, r"share\proj")

        from qgis.core import QgsApplication
        from qgis.PyQt.QtWidgets import QMessageBox
        from qgis.analysis import QgsNativeAlgorithms
        from processing.core.Processing import Processing
        import importlib.util

        QgsApplication.setPrefixPath(qgis_prefix, True)
        _app = QgsApplication([], False)
        _app.initQgis()
        Processing.initialize()
        reg = QgsApplication.processingRegistry()
        if reg.providerById("native") is None:
            reg.addProvider(QgsNativeAlgorithms())
        QMessageBox.warning = staticmethod(lambda *a, **k: 1)
        QMessageBox.critical = staticmethod(lambda *a, **k: 1)
        QMessageBox.information = staticmethod(lambda *a, **k: 1)
        _yes = getattr(getattr(QMessageBox, "StandardButton", QMessageBox), "Yes", 1)
        QMessageBox.question = staticmethod(lambda *a, **k: _yes)

        init_path = os.path.join(ROOT, "__init__.py")
        spec = importlib.util.spec_from_file_location(
            "wind_site_select", init_path, submodule_search_locations=[ROOT]
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["wind_site_select"] = mod
        spec.loader.exec_module(mod)
        _plugin_mod = mod
        _QGIS = True
        return True
    except Exception as exc:
        _qgis_err = exc
        return False


def _write_byte_raster(path, ox=4500000.0, oy=3200000.0, px=100.0, n=10):
    from osgeo import gdal, osr
    import numpy as np

    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3035)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(np.ones((n, n), dtype=np.uint8))
    band.SetNoDataValue(255)
    ds = None


def _write_lines_gpkg(path, coords_list, epsg=3035):
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsFields,
        QgsGeometry,
        QgsPointXY,
        QgsVectorFileWriter,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QVariant

    crs = QgsCoordinateReferenceSystem("EPSG:{}".format(epsg))
    fields = QgsFields()
    fields.append(QgsField("id", QVariant.Int))
    writer = QgsVectorFileWriter(path, "UTF-8", fields, QgsWkbTypes.LineString, crs, "GPKG")
    for i, pts in enumerate(coords_list, start=1):
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts]))
        feat.setAttributes([i])
        writer.addFeature(feat)
    del writer


def _write_poly_gpkg(path, xmin, ymin, xmax, ymax, epsg=3035):
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsFeature,
        QgsField,
        QgsFields,
        QgsGeometry,
        QgsRectangle,
        QgsVectorFileWriter,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QVariant

    crs = QgsCoordinateReferenceSystem("EPSG:{}".format(epsg))
    fields = QgsFields()
    fields.append(QgsField("id", QVariant.Int))
    writer = QgsVectorFileWriter(path, "UTF-8", fields, QgsWkbTypes.Polygon, crs, "GPKG")
    feat = QgsFeature(fields)
    feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax)))
    feat.setAttributes([1])
    writer.addFeature(feat)
    del writer


class _FakeCanvas:
    def mapSettings(self):
        from qgis.core import QgsCoordinateReferenceSystem

        class MS:
            def destinationCrs(self):
                return QgsCoordinateReferenceSystem("EPSG:3035")

        return MS()

    def mapTool(self):
        return None

    def unsetMapTool(self, *a, **k):
        pass

    def setMapTool(self, *a, **k):
        pass

    def setExtent(self, *a, **k):
        pass

    def scene(self):
        return None

    def refresh(self):
        pass


class _FakeIface:
    def __init__(self):
        self._canvas = _FakeCanvas()

    def mainWindow(self):
        return None

    def mapCanvas(self):
        return self._canvas

    def addPluginToMenu(self, *a, **k):
        pass

    def addToolBarIcon(self, *a, **k):
        pass

    def removePluginMenu(self, *a, **k):
        pass

    def removeToolBarIcon(self, *a, **k):
        pass

    def messageBar(self):
        class MB:
            def pushMessage(self, *a, **k):
                pass

            def pushWarning(self, *a, **k):
                pass

            def pushSuccess(self, *a, **k):
                pass

        return MB()

    def layerTreeView(self):
        return None


def _set_aoi(plugin, path):
    from qgis.core import QgsProject, QgsVectorLayer

    lyr = QgsVectorLayer(path, "Wind Site Select AOI", "ogr")
    assert lyr.isValid() and lyr.featureCount() > 0
    lyr.setCustomProperty("wind_plugin_user_aoi", True)
    QgsProject.instance().addMapLayer(lyr)
    plugin.user_aoi_layer = lyr
    plugin.user_aoi_layer_id = lyr.id()
    return lyr


@unittest.skipUnless(_bootstrap(), "QGIS unavailable: {}".format(_qgis_err))
class VectorSpatialValidationTests(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QSettings

        QgsProject.instance().clear()
        self.workdir = tempfile.mkdtemp(prefix="wss_vec_spatial_")
        self.results = os.path.join(self.workdir, "results")
        os.makedirs(self.results, exist_ok=True)
        self.spatial = os.path.join(self.results, "spatial_filtered.tif")
        _write_byte_raster(self.spatial)
        QSettings().setValue("wind_site_select/last_results_root", self.results)

        self.plugin = _plugin_mod.classFactory(_FakeIface())
        self.plugin.initGui()
        self.plugin.run()
        self.plugin.results_dir = self.results
        self.plugin.output_dir = self.workdir
        self.plugin.temp_dir = os.path.join(self.workdir, "temp")
        os.makedirs(self.plugin.temp_dir, exist_ok=True)
        self.plugin.spatial_filter_result_path = self.spatial
        self.plugin._remember_results_root()

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _master_layer(self):
        from qgis.core import QgsRasterLayer

        lyr = QgsRasterLayer(self.spatial, "MasterGrid", "gdal")
        self.assertTrue(lyr.isValid())
        return lyr

    def test_01_intersecting_feature_after_first_100_passes(self):
        """First 100 features miss the raster; feature 101 intersects — must pass."""
        from qgis.core import QgsVectorLayer, QgsCoordinateReferenceSystem

        coords = []
        # Distant cluster far SW of the 10x10 master at 4500000,3200000
        for i in range(100):
            x0 = 4000000.0 + i * 10.0
            coords.append([(x0, 2700000.0), (x0 + 50.0, 2700100.0)])
        # Feature 101 intersects master extent [4500000..4501000, 3199000..3200000]
        coords.append([(4500400.0, 3199400.0), (4500600.0, 3199600.0)])

        path = os.path.join(self.workdir, "late_hit.gpkg")
        _write_lines_gpkg(path, coords)
        layer = QgsVectorLayer(path, "LateHit", "ogr")
        self.assertTrue(layer.isValid())
        self.assertGreaterEqual(layer.featureCount(), 101)

        master = self._master_layer()
        # Direct helper + validate_vector_for_rasterization
        ok, info = self.plugin._vector_intersects_raster_extent(
            layer, master.extent(), master.crs()
        )
        self.assertTrue(ok, info)
        self.plugin.validate_vector_for_rasterization(
            layer, master.extent(), QgsCoordinateReferenceSystem("EPSG:3035")
        )

        out = os.path.join(self.workdir, "late_hit_bin.tif")
        raster, err = self.plugin.rasterize_vector_against_mca_reference(
            layer, out, reference_raster=master, clip_to_aoi=False
        )
        self.assertIsNotNone(raster, err)
        self.assertTrue(os.path.isfile(out))

    def test_02_bbox_overlap_without_geometry_intersection_fails(self):
        """Overall extent overlaps raster bbox, but no geometry actually intersects."""
        from qgis.core import QgsVectorLayer

        # Lines that surround the master bbox without crossing into it.
        coords = [
            [(4499000.0, 3198000.0), (4499500.0, 3198500.0)],  # SW outside
            [(4501500.0, 3200500.0), (4502000.0, 3201000.0)],  # NE outside
            [(4499000.0, 3200500.0), (4499500.0, 3201000.0)],  # NW outside
            [(4501500.0, 3198000.0), (4502000.0, 3198500.0)],  # SE outside
        ]
        path = os.path.join(self.workdir, "bbox_only.gpkg")
        _write_lines_gpkg(path, coords)
        layer = QgsVectorLayer(path, "BBoxOnly", "ogr")
        self.assertTrue(layer.isValid())
        master = self._master_layer()
        # Layer extent may intersect raster extent as envelopes, but geometries do not.
        ok, err = self.plugin._vector_intersects_raster_extent(
            layer, master.extent(), master.crs()
        )
        self.assertFalse(ok)
        self.assertIn("No spatial intersection", err)

        with self.assertRaises(RuntimeError) as ctx:
            self.plugin.validate_vector_for_rasterization(
                layer, master.extent(), master.crs()
            )
        self.assertIn("No spatial intersection", str(ctx.exception))

    def test_03_different_crs_intersects_after_transform(self):
        """Vector in EPSG:4326 intersects master EPSG:3035 after transform."""
        from qgis.core import QgsVectorLayer, QgsCoordinateTransform, QgsProject, QgsPointXY

        from qgis.core import QgsCoordinateReferenceSystem

        master = self._master_layer()
        # Transform a point inside the master grid to WGS84 for the line endpoints.
        to_wgs = QgsCoordinateTransform(
            master.crs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext(),
        )
        p1 = to_wgs.transform(QgsPointXY(4500400.0, 3199400.0))
        p2 = to_wgs.transform(QgsPointXY(4500600.0, 3199600.0))
        path = os.path.join(self.workdir, "wgs_line.gpkg")
        _write_lines_gpkg(path, [[(p1.x(), p1.y()), (p2.x(), p2.y())]], epsg=4326)
        layer = QgsVectorLayer(path, "WgsLine", "ogr")
        self.assertTrue(layer.isValid())
        self.assertEqual(layer.crs().authid(), "EPSG:4326")

        ok, info = self.plugin._vector_intersects_raster_extent(
            layer, master.extent(), master.crs()
        )
        self.assertTrue(ok, info)

    def test_04_invalid_crs_reports_crs_error(self):
        from qgis.core import QgsVectorLayer, QgsCoordinateReferenceSystem

        path = os.path.join(self.workdir, "no_crs.gpkg")
        _write_lines_gpkg(path, [[(4500400.0, 3199400.0), (4500600.0, 3199600.0)]])
        layer = QgsVectorLayer(path, "NoCrs", "ogr")
        self.assertTrue(layer.isValid())
        # Force invalid CRS on the layer object
        layer.setCrs(QgsCoordinateReferenceSystem())
        self.assertFalse(layer.crs().isValid())

        master = self._master_layer()
        ok, err = self.plugin._vector_intersects_raster_extent(
            layer, master.extent(), master.crs()
        )
        self.assertFalse(ok)
        self.assertIn("CRS", err)

        with self.assertRaises(RuntimeError) as ctx:
            self.plugin.validate_vector_for_rasterization(
                layer, master.extent(), master.crs()
            )
        self.assertIn("CRS", str(ctx.exception))

    def test_05_features_outside_aoi_inside_master_retained_for_proximity(self):
        from qgis.core import QgsProject, QgsVectorLayer
        import numpy as np
        from osgeo import gdal

        # AOI covers only the SE half of the master; line is in the NW half (outside AOI, inside master).
        aoi = os.path.join(self.workdir, "aoi_se.gpkg")
        _write_poly_gpkg(aoi, 4500500.0, 3199000.0, 4501000.0, 3199500.0)
        _set_aoi(self.plugin, aoi)

        line = os.path.join(self.workdir, "outside_aoi_line.gpkg")
        _write_lines_gpkg(line, [[(4500100.0, 3199700.0), (4500200.0, 3199800.0)]])
        layer = QgsVectorLayer(line, "OutsideAoiPower", "ogr")
        QgsProject.instance().addMapLayer(layer)
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "proximity"
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(len(self.plugin.decision_making_layers), 1)
        path = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        self.assertTrue(os.path.isfile(path))
        ds = gdal.Open(path)
        arr = ds.GetRasterBand(1).ReadAsArray().astype(float)
        nd = ds.GetRasterBand(1).GetNoDataValue()
        finite = arr[np.isfinite(arr) & (np.abs(arr - nd) > 1e-6)]
        self.assertGreater(finite.size, 0)

    def test_06_large_layer_spatial_filter_not_first_100_sample(self):
        """~114502 features: first 100 miss; one late feature hits. Must succeed efficiently."""
        from qgis.core import QgsVectorLayer
        from osgeo import ogr, osr

        path = os.path.join(self.workdir, "large_power.gpkg")
        driver = ogr.GetDriverByName("GPKG")
        ds = driver.CreateDataSource(path)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3035)
        lyr = ds.CreateLayer("lines", srs, ogr.wkbLineString)
        lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
        # 114502 distant features (FID order), then one intersecting feature last.
        n_distant = 114502
        for i in range(n_distant):
            feat = ogr.Feature(lyr.GetLayerDefn())
            feat.SetField("id", i + 1)
            x0 = 4000000.0 + (i % 5000) * 5.0
            y0 = 2700000.0 + (i // 5000) * 5.0
            line = ogr.Geometry(ogr.wkbLineString)
            line.AddPoint_2D(x0, y0)
            line.AddPoint_2D(x0 + 20.0, y0 + 20.0)
            feat.SetGeometry(line)
            lyr.CreateFeature(feat)
            feat = None
        hit = ogr.Feature(lyr.GetLayerDefn())
        hit.SetField("id", n_distant + 1)
        line = ogr.Geometry(ogr.wkbLineString)
        line.AddPoint_2D(4500400.0, 3199400.0)
        line.AddPoint_2D(4500600.0, 3199600.0)
        hit.SetGeometry(line)
        lyr.CreateFeature(hit)
        hit = None
        ds = None

        layer = QgsVectorLayer(path, "LargePower", "ogr")
        self.assertTrue(layer.isValid())
        self.assertGreaterEqual(layer.featureCount(), 114503)

        master = self._master_layer()
        ok, info = self.plugin._vector_intersects_raster_extent(
            layer, master.extent(), master.crs()
        )
        self.assertTrue(ok, info)
        self.assertTrue(isinstance(info, dict))
        # Must not rely on scanning only the first 100 provider features.
        self.assertNotEqual(info.get("candidates_checked"), 100)

        # Full rasterize path used by Proximity (clip_to_aoi=False)
        out = os.path.join(self.workdir, "large_bin.tif")
        raster, err = self.plugin.rasterize_vector_against_mca_reference(
            layer, out, reference_raster=master, clip_to_aoi=False
        )
        self.assertIsNotNone(raster, err)


if __name__ == "__main__":
    unittest.main()

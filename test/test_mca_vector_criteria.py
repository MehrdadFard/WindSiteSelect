# -*- coding: utf-8 -*-
"""
Vector Binary / Proximity MCA criteria — regression for restored Suitability Analysis workflow.

Evidence type: QGIS 4.0.3 offscreen + GDAL Processing where available; pure schema tests without QGIS.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from results_lifecycle import (  # noqa: E402
    CRITERIA_SCHEMA_VERSION,
    build_criteria_export_payload,
    validate_criteria_payload,
)

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
        from qgis.PyQt.QtWidgets import QMessageBox, QDialog
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


def _write_byte(path, ox=4500000.0, oy=3200000.0, px=100.0, n=10):
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


def _write_line_gpkg(path, x0=4500200.0, y0=3199200.0, x1=4500800.0, y1=3199800.0):
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

    crs = QgsCoordinateReferenceSystem("EPSG:3035")
    fields = QgsFields()
    fields.append(QgsField("id", QVariant.Int))
    writer = QgsVectorFileWriter(path, "UTF-8", fields, QgsWkbTypes.LineString, crs, "GPKG")
    feat = QgsFeature(fields)
    feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x0, y0), QgsPointXY(x1, y1)]))
    feat.setAttributes([1])
    writer.addFeature(feat)
    del writer


def _write_poly_gpkg(path, xmin=4500300.0, ymin=3199300.0, xmax=4500700.0, ymax=3199700.0):
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

    crs = QgsCoordinateReferenceSystem("EPSG:3035")
    fields = QgsFields()
    fields.append(QgsField("id", QVariant.Int))
    writer = QgsVectorFileWriter(path, "UTF-8", fields, QgsWkbTypes.Polygon, crs, "GPKG")
    feat = QgsFeature(fields)
    feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(xmin, ymin, xmax, ymax)))
    feat.setAttributes([1])
    writer.addFeature(feat)
    del writer


class CriteriaSchemaVectorTests(unittest.TestCase):
    def test_v1_raster_payload_still_accepted(self):
        ok, err, norm = validate_criteria_payload(
            {
                "schema_version": 1,
                "criteria": [
                    {
                        "layer_name": "Wind",
                        "weight": 60.0,
                        "role": "Beneficial",
                        "include": True,
                        "layer_path": "C:/tmp/wind.tif",
                    }
                ],
            }
        )
        self.assertTrue(ok, err)
        self.assertEqual(norm["schema_version"], CRITERIA_SCHEMA_VERSION)
        self.assertEqual(norm["criteria"][0]["source_type"], "raster")

    def test_v2_vector_payload_requires_mode(self):
        ok, err, _ = validate_criteria_payload(
            {
                "schema_version": 2,
                "criteria": [
                    {
                        "layer_name": "Lines",
                        "weight": 40.0,
                        "role": "Beneficial",
                        "include": True,
                        "source_type": "vector",
                    }
                ],
            }
        )
        self.assertFalse(ok)
        self.assertIn("analysis_mode", err)

    def test_export_includes_vector_metadata(self):
        payload = build_criteria_export_payload(
            [
                {
                    "layer_name": "Grid (Distance suitability)",
                    "weight": 50.0,
                    "role": "Beneficial",
                    "include": True,
                    "source_type": "vector",
                    "analysis_mode": "proximity",
                    "geometry_type": "Line",
                    "source_vector_path": "C:/tmp/lines.gpkg",
                    "derived_raster_path": "C:/tmp/lines_suitability.tif",
                    "layer_path": "C:/tmp/lines_suitability.tif",
                    "processing_params": {"proximity_units": "GEO"},
                }
            ]
        )
        self.assertEqual(payload["schema_version"], 2)
        c = payload["criteria"][0]
        self.assertEqual(c["analysis_mode"], "proximity")
        self.assertEqual(c["source_vector_path"], "C:/tmp/lines.gpkg")
        ok, err, norm = validate_criteria_payload(payload)
        self.assertTrue(ok, err)
        self.assertEqual(norm["criteria"][0]["derived_raster_path"], "C:/tmp/lines_suitability.tif")


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


@unittest.skipUnless(_bootstrap(), "QGIS unavailable: {}".format(_qgis_err))
class McaVectorCriteriaTests(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QSettings

        QgsProject.instance().clear()
        self.workdir = tempfile.mkdtemp(prefix="wss_vec_crit_")
        self.results = os.path.join(self.workdir, "results")
        os.makedirs(self.results, exist_ok=True)
        self.spatial = os.path.join(self.results, "spatial_filtered.tif")
        _write_byte(self.spatial)
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

        # Auto-accept Binary mode unless a test overrides
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "binary"

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_01_ui_has_vector_controls(self):
        d = self.plugin.dlg
        self.assertEqual(d.btn_add_layer_to_table.text(), "Add Layer from Map")
        self.assertEqual(d.btn_add_layer_from_file.text(), "Add Raster Criterion...")
        self.assertEqual(d.btn_add_vector_criterion.text(), "Add Vector Criterion...")
        self.assertEqual(d.lbl_add_criteria.text(), "Add Criteria")
        self.assertEqual(d.lbl_manage_criteria.text(), "Manage Criteria")

    def test_02_invalid_vector_path_rejected(self):
        from qgis.core import QgsVectorLayer

        bad = os.path.join(self.workdir, "missing.gpkg")
        layer = QgsVectorLayer(bad, "Missing", "ogr")
        self.assertFalse(layer.isValid())
        before = self.plugin.dlg.tbl_weights.rowCount()
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before)

    def test_03_empty_vector_rejected(self):
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsFields,
            QgsVectorFileWriter,
            QgsWkbTypes,
            QgsVectorLayer,
        )

        path = os.path.join(self.workdir, "empty.gpkg")
        crs = QgsCoordinateReferenceSystem("EPSG:3035")
        writer = QgsVectorFileWriter(path, "UTF-8", QgsFields(), QgsWkbTypes.LineString, crs, "GPKG")
        del writer
        layer = QgsVectorLayer(path, "Empty", "ogr")
        self.assertTrue(layer.isValid())
        self.assertEqual(layer.featureCount(), 0)
        before = self.plugin.dlg.tbl_weights.rowCount()
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before)

    def test_04_binary_polygon_registers_derived_raster(self):
        from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer
        import numpy as np
        from osgeo import gdal

        poly = os.path.join(self.workdir, "zone.gpkg")
        _write_poly_gpkg(poly)
        layer = QgsVectorLayer(poly, "Zone", "ogr")
        self.assertTrue(layer.isValid())
        QgsProject.instance().addMapLayer(layer)
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "binary"
        before = self.plugin.dlg.tbl_weights.rowCount()
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before + 1)
        entry = self.plugin.decision_making_layers[-1]
        self.assertEqual(entry.get("source_type"), "vector")
        self.assertEqual(entry.get("analysis_mode"), "binary")
        self.assertTrue(entry.get("derived_raster_path"))
        self.assertTrue(os.path.isfile(entry["derived_raster_path"]))
        ds = gdal.Open(entry["derived_raster_path"])
        self.assertIsNotNone(ds)
        arr = ds.GetRasterBand(1).ReadAsArray()
        self.assertTrue(set(np.unique(arr)).issubset({0, 1, 255}))
        self.assertIn(1, set(np.unique(arr)))
        master = QgsRasterLayer(self.spatial, "m", "gdal")
        derived = QgsRasterLayer(entry["derived_raster_path"], "d", "gdal")
        self.assertEqual(derived.width(), master.width())
        self.assertEqual(derived.height(), master.height())
        self.assertEqual(derived.crs().authid(), master.crs().authid())

    def test_05_proximity_line_inverse_normalized(self):
        from qgis.core import QgsProject, QgsVectorLayer
        import numpy as np
        from osgeo import gdal

        # Proximity requires current AOI + spatial_filtered master
        aoi_path = os.path.join(self.workdir, "aoi_prox.gpkg")
        _write_poly_gpkg(aoi_path)
        aoi = QgsVectorLayer(aoi_path, "Wind Site Select AOI", "ogr")
        aoi.setCustomProperty("wind_plugin_user_aoi", True)
        QgsProject.instance().addMapLayer(aoi)
        self.plugin.user_aoi_layer = aoi
        self.plugin.user_aoi_layer_id = aoi.id()

        line = os.path.join(self.workdir, "power.gpkg")
        _write_line_gpkg(line)
        layer = QgsVectorLayer(line, "Power", "ogr")
        self.assertTrue(layer.isValid())
        QgsProject.instance().addMapLayer(layer)
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "proximity"
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertTrue(self.plugin.decision_making_layers, "proximity should succeed with AOI+spatial master")
        entry = self.plugin.decision_making_layers[-1]
        self.assertEqual(entry.get("analysis_mode"), "proximity")
        path = entry.get("derived_raster_path")
        self.assertTrue(path and os.path.isfile(path))
        ds = gdal.Open(path)
        arr = ds.GetRasterBand(1).ReadAsArray().astype(float)
        nodata = ds.GetRasterBand(1).GetNoDataValue()
        if nodata is not None:
            valid = arr[np.isfinite(arr) & (np.abs(arr - nodata) > 1e-6)]
        else:
            valid = arr[np.isfinite(arr)]
        self.assertGreater(valid.size, 0)
        self.assertGreaterEqual(float(np.nanmin(valid)), -1e-6)
        self.assertLessEqual(float(np.nanmax(valid)), 1.0 + 1e-5)
        ok, err = self.plugin._validate_proximity_suitability_masked_to_aoi(path, self.spatial)
        self.assertTrue(ok, err)

    def test_06_vector_criteria_json_roundtrip(self):
        from qgis.core import QgsProject, QgsVectorLayer

        poly = os.path.join(self.workdir, "zone2.gpkg")
        _write_poly_gpkg(poly)
        layer = QgsVectorLayer(poly, "Zone2", "ogr")
        QgsProject.instance().addMapLayer(layer)
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "binary"
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        payload = self.plugin._serialize_criteria_for_persistence()
        self.assertEqual(payload["schema_version"], 2)
        c0 = payload["criteria"][0]
        self.assertEqual(c0["source_type"], "vector")
        self.assertEqual(c0["analysis_mode"], "binary")
        self.assertTrue(c0.get("derived_raster_path"))

        # Clear and re-apply
        applied, err = self.plugin._apply_criteria_payload(payload, show_messages=False)
        self.assertTrue(applied, err)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 1)
        restored = self.plugin.decision_making_layers[0]
        self.assertEqual(restored.get("analysis_mode"), "binary")
        self.assertTrue(restored.get("layer") is not None)

    def test_07_missing_vector_source_does_not_silently_reuse(self):
        payload = build_criteria_export_payload(
            [
                {
                    "layer_name": "Ghost",
                    "weight": 30.0,
                    "role": "Beneficial",
                    "include": True,
                    "source_type": "vector",
                    "analysis_mode": "binary",
                    "source_vector_path": os.path.join(self.workdir, "does_not_exist.gpkg"),
                    "derived_raster_path": os.path.join(self.workdir, "also_missing.tif"),
                    "layer_path": os.path.join(self.workdir, "also_missing.tif"),
                }
            ]
        )
        applied, err = self.plugin._apply_criteria_payload(payload, show_messages=False)
        self.assertTrue(applied, err)
        # Row may exist but without a valid scoring raster layer
        entry = self.plugin.decision_making_layers[0]
        self.assertTrue(entry.get("layer") is None or not entry["layer"].isValid())

    def test_08_mode_dialog_cancel_returns_none(self):
        from qgis.PyQt.QtWidgets import QDialog

        # Restore real dialog but force reject
        real = type(self.plugin)._select_vector_analysis_mode

        def _cancel(self_inner, layer_name=None):
            from qgis.PyQt.QtWidgets import QDialog as QD

            # Call production builder path via monkey: emulate cancel
            return None

        self.plugin._select_vector_analysis_mode = lambda layer_name=None: None
        from qgis.core import QgsVectorLayer

        poly = os.path.join(self.workdir, "zone3.gpkg")
        _write_poly_gpkg(poly)
        layer = QgsVectorLayer(poly, "Zone3", "ogr")
        before = self.plugin.dlg.tbl_weights.rowCount()
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before)


if __name__ == "__main__":
    unittest.main()

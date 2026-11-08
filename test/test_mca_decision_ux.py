# -*- coding: utf-8 -*-
"""
Decision Making UX / criteria-setup semantics tests.

Evidence type: Production-helper integration under QGIS 4.0.3 (offscreen).
Not a live GUI click-through — exercises real helpers (append, apply payload,
export/import, New MCA confirmation, MCA prerequisites).
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

_QGIS = False
_qgis_err = None
_plugin = None
_app = None


def _mount_public_plugin():
    import importlib.util

    init_path = os.path.join(ROOT, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "wind_site_select",
        init_path,
        submodule_search_locations=[ROOT],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wind_site_select"] = mod
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_qgis():
    global _QGIS, _qgis_err, _plugin, _app
    if _QGIS:
        return True
    try:
        qgis_prefix = r"C:\Program Files\QGIS 4.0.3"
        qgis_python = os.path.join(qgis_prefix, r"apps\qgis\python")
        qgis_py_plugins = os.path.join(qgis_python, "plugins")
        env_path = os.environ.get("PATH", "")
        os.environ["PATH"] = (
            os.path.join(qgis_prefix, "bin")
            + os.pathsep
            + os.path.join(qgis_prefix, r"apps\Qt6\bin")
            + os.pathsep
            + os.path.join(qgis_prefix, r"apps\Python312")
            + os.pathsep
            + env_path
        )
        os.environ["QGIS_PREFIX_PATH"] = qgis_prefix
        os.environ["GDAL_DATA"] = os.path.join(qgis_prefix, r"apps\gdal\share\gdal")
        os.environ["PROJ_LIB"] = os.path.join(qgis_prefix, r"share\proj")
        os.environ["PROJ_DATA"] = os.path.join(qgis_prefix, r"share\proj")
        for p in (qgis_python, qgis_py_plugins):
            if p not in sys.path:
                sys.path.insert(0, p)

        from qgis.core import QgsApplication
        from qgis.PyQt.QtWidgets import QMessageBox
        from qgis.analysis import QgsNativeAlgorithms
        from processing.core.Processing import Processing

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
        yes = getattr(getattr(QMessageBox, "StandardButton", QMessageBox), "Yes", 1)
        QMessageBox.question = staticmethod(lambda *a, **k: yes)

        _plugin = _mount_public_plugin()
        _QGIS = True
        return True
    except Exception as exc:
        _qgis_err = exc
        _QGIS = False
        return False


def _write_float_tif(path, arr, ox=4500000.0, oy=3200000.0, px=100.0):
    from osgeo import gdal, osr
    import numpy as np

    gdal.UseExceptions()
    h, w = arr.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3035)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(arr.astype(np.float32))
    band.SetNoDataValue(-9999.0)
    ds = None


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


@unittest.skipUnless(_bootstrap_qgis(), "QGIS 4.0.3 unavailable: {}".format(_qgis_err))
class McaDecisionUxTests(unittest.TestCase):
    """Add Raster Criterion vs Load Criteria Setup and related UX safeguards."""

    @classmethod
    def setUpClass(cls):
        import numpy as np
        from qgis.core import QgsProject

        cls.workdir = tempfile.mkdtemp(prefix="wss_mca_ux_")
        cls.wind_path = os.path.join(cls.workdir, "WindSpeed.tif")
        cls.slope_path = os.path.join(cls.workdir, "Slope.tif")
        cls.extra_path = os.path.join(cls.workdir, "ExtraCrit.tif")
        yy, xx = np.mgrid[0:10, 0:10]
        _write_float_tif(cls.wind_path, (8.0 + 0.1 * xx).astype(float))
        _write_float_tif(cls.slope_path, (2.0 + 0.05 * yy).astype(float))
        _write_float_tif(cls.extra_path, (5.0 + xx).astype(float))
        QgsProject.instance().clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtWidgets import QMessageBox

        QgsProject.instance().clear()
        self.plugin = _plugin.classFactory(_FakeIface())
        self.plugin.initGui()
        self.plugin.run()
        self.plugin.get_canonical_results_root = lambda: self.workdir
        self.plugin.get_plugin_results_dir = lambda: self.workdir
        # Default confirmations answer Yes unless a test overrides
        yes = getattr(getattr(QMessageBox, "StandardButton", QMessageBox), "Yes", 1)
        QMessageBox.question = staticmethod(lambda *a, **k: yes)
        self.plugin._configure_decision_making_ux()

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass

    def _payload(self, items):
        from results_lifecycle import build_criteria_export_payload

        return build_criteria_export_payload(items)

    def _two_criteria_payload(self):
        return self._payload(
            [
                {
                    "layer_name": "WindSpeed",
                    "weight": 60.0,
                    "role": "Beneficial",
                    "include": True,
                    "layer_path": self.wind_path,
                },
                {
                    "layer_name": "Slope",
                    "weight": 40.0,
                    "role": "Penalizing",
                    "include": True,
                    "layer_path": self.slope_path,
                },
            ]
        )

    def test_01_button_labels_and_tooltips(self):
        d = self.plugin.dlg
        self.assertEqual(d.btn_add_layer_to_table.text(), "Add Layer")
        self.assertEqual(d.btn_add_layer_from_file.text(), "Add Raster Criterion...")
        self.assertEqual(d.btn_export_criteria.text(), "Save Criteria Setup...")
        self.assertEqual(d.btn_import_criteria.text(), "Load Criteria Setup...")
        self.assertEqual(d.btn_new_mca_analysis.text(), "New MCA Analysis")
        self.assertIn("loaded in the current QGIS project", d.btn_add_layer_to_table.toolTip())
        self.assertIn("Browse for a raster file", d.btn_add_layer_from_file.toolTip())
        self.assertIn("JSON file", d.btn_export_criteria.toolTip())
        self.assertIn("previously saved", d.btn_import_criteria.toolTip())
        hint = getattr(d, "lbl_mca_workflow_hint", None)
        self.assertIsNotNone(hint)
        self.assertIn("Prospect Analysis and Spatial Filtering", hint.text())

    def test_02_add_raster_appends_without_clearing(self):
        from qgis.core import QgsProject, QgsRasterLayer

        applied, err = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied, err)
        before = self.plugin.dlg.tbl_weights.rowCount()
        self.assertEqual(before, 2)

        rl = QgsRasterLayer(self.extra_path, "ExtraCrit", "gdal")
        self.assertTrue(rl.isValid())
        QgsProject.instance().addMapLayer(rl)
        # Production Add Raster Criterion path ends in add_layer_to_weights_table(from_file_layer=...)
        self.plugin.add_layer_to_weights_table(from_file_layer=rl)

        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before + 1)
        names = [self.plugin.dlg.tbl_weights.item(r, 1).text() for r in range(before + 1)]
        self.assertEqual(names[0], "WindSpeed")
        self.assertEqual(names[1], "Slope")
        self.assertIn("ExtraCrit", names[2])
        # Distinct from Load Criteria Setup (which replaces the whole table)
        for i, ent in enumerate(self.plugin.decision_making_layers):
            self.assertEqual(ent.get("row"), i)

    def test_03_json_round_trip_preserves_settings(self):
        applied, err = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied, err)
        exported = self.plugin._serialize_criteria_for_persistence()
        path = os.path.join(self.workdir, "setup_roundtrip.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(exported, fh)

        from results_lifecycle import load_and_validate_criteria_file

        ok, load_err, loaded = load_and_validate_criteria_file(path)
        self.assertTrue(ok, load_err)
        # Clear then reload via production apply helper
        self.plugin.start_new_mca_analysis()
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 0)
        applied2, err2 = self.plugin._apply_criteria_payload(loaded, show_messages=False)
        self.assertTrue(applied2, err2)
        criteria = self.plugin.extract_criteria_data()
        self.assertEqual(len(criteria), 2)
        self.assertEqual(criteria[0]["layer_name"], "WindSpeed")
        self.assertEqual(criteria[0]["weight"], 60.0)
        self.assertTrue(str(criteria[0]["role"]).lower().startswith("b"))
        self.assertTrue(criteria[0]["include"])
        self.assertEqual(criteria[1]["layer_name"], "Slope")
        self.assertEqual(criteria[1]["weight"], 40.0)
        self.assertTrue(criteria[1]["include"])

    def test_04_invalid_json_preserves_existing(self):
        applied, err = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied, err)
        before_names = [
            self.plugin.dlg.tbl_weights.item(r, 1).text()
            for r in range(self.plugin.dlg.tbl_weights.rowCount())
        ]
        bad = {
            "schema_version": 1,
            "criteria": [{"layer_name": "X", "weight": float("nan"), "role": "Beneficial"}],
        }
        applied_bad, _ = self.plugin._apply_criteria_payload(bad, show_messages=False)
        self.assertFalse(applied_bad)
        after_names = [
            self.plugin.dlg.tbl_weights.item(r, 1).text()
            for r in range(self.plugin.dlg.tbl_weights.rowCount())
        ]
        self.assertEqual(after_names, before_names)

    def test_05_remove_preserves_row_mappings(self):
        applied, err = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied, err)
        self.plugin.dlg.tbl_weights.selectRow(0)
        self.plugin.remove_layer_from_weights_table()
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 1)
        self.assertEqual(self.plugin.decision_making_layers[0]["row"], 0)
        self.assertEqual(self.plugin.decision_making_layers[0]["layer_name"], "Slope")
        criteria = self.plugin.extract_criteria_data()
        self.assertEqual(len(criteria), 1)
        self.assertEqual(criteria[0]["layer_name"], "Slope")

    def test_06_new_mca_cancel_preserves_settings(self):
        from qgis.PyQt.QtWidgets import QMessageBox

        applied, err = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied, err)
        before = self.plugin.dlg.tbl_weights.rowCount()
        no = getattr(getattr(QMessageBox, "StandardButton", QMessageBox), "No", 0)
        QMessageBox.question = staticmethod(lambda *a, **k: no)
        result = self.plugin.start_new_mca_analysis()
        self.assertFalse(result)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before)
        self.assertEqual(len(self.plugin.decision_making_layers), 2)

    def test_07_master_raster_missing_message_is_actionable(self):
        self.plugin.wind_master_path = None
        self.plugin.wind_result_path = None
        self.plugin.spatial_filter_result_path = None
        self.plugin.prospect_result_path = None
        # Fake a grid so the master-missing branch is reached (not the grid-missing branch)
        from qgis.core import QgsVectorLayer

        vl = QgsVectorLayer("Polygon?crs=EPSG:3035", "fake_grid", "memory")
        self.plugin.mca_grid_layer = vl
        ok, msg = self.plugin._validate_mca_run_prerequisites()
        self.assertFalse(ok)
        self.assertIn("Complete Spatial Filtering first", msg)
        self.assertIn("generate the MCA grid", msg)

        # prepare_mca_data_matrix uses the same wording when master is missing
        self.plugin.decision_making_layers = []
        applied, _ = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied)
        matrix, err = self.plugin.prepare_mca_data_matrix()
        self.assertIsNone(matrix)
        self.assertIsNotNone(err)
        self.assertIn("Complete Spatial Filtering first", err)

    def test_08_prerequisites_ok_after_spatial_paths(self):
        from osgeo import gdal, osr
        import numpy as np
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsFeature,
            QgsField,
            QgsFields,
            QgsGeometry,
            QgsRectangle,
            QgsVectorFileWriter,
            QgsVectorLayer,
            QgsWkbTypes,
        )
        from qgis.PyQt.QtCore import QVariant

        mask = os.path.join(self.workdir, "spatial_filtered.tif")
        poly = os.path.join(self.workdir, "spatial_final_polygons.gpkg")
        master = os.path.join(self.workdir, "wind_master.tif")
        arr = np.ones((10, 10), dtype=np.uint8)
        ds = gdal.GetDriverByName("GTiff").Create(mask, 10, 10, 1, gdal.GDT_Byte)
        ds.SetGeoTransform((4500000.0, 100.0, 0, 3200000.0, 0, -100.0))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3035)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(arr)
        ds.GetRasterBand(1).SetNoDataValue(255)
        ds = None
        shutil.copyfile(self.wind_path, master)

        crs = QgsCoordinateReferenceSystem("EPSG:3035")
        fields = QgsFields()
        fields.append(QgsField("VALUE", QVariant.Int))
        writer = QgsVectorFileWriter(poly, "UTF-8", fields, QgsWkbTypes.Polygon, crs, "GPKG")
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(4500100, 3199100, 4500900, 3199900)))
        feat.setAttributes([1])
        writer.addFeature(feat)
        del writer

        applied, err = self.plugin._apply_criteria_payload(self._two_criteria_payload(), show_messages=False)
        self.assertTrue(applied, err)
        self.plugin.wind_master_path = master
        self.plugin.spatial_filter_result_path = mask
        self.plugin.spatial_filter_polygons_path = poly

        # Minimal valid memory grid with grid_id so prerequisite check can pass grid alive test
        grid = QgsVectorLayer("Polygon?crs=EPSG:3035&field=grid_id:integer", "mca_grid", "memory")
        pr = grid.dataProvider()
        gfeat = QgsFeature(grid.fields())
        gfeat.setGeometry(QgsGeometry.fromRect(QgsRectangle(4500200, 3199200, 4500400, 3199400)))
        gfeat.setAttributes([1])
        pr.addFeatures([gfeat])
        grid.updateExtents()
        self.plugin.mca_grid_layer = grid

        ok, msg = self.plugin._validate_mca_run_prerequisites()
        self.assertTrue(ok, msg)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""
MCA criteria restore/import row-mapping regression tests.

Evidence type: Production-helper integration tests under QGIS 4.0.3 (offscreen).
Not a live GUI click-through test — exercises _apply_criteria_payload /
extract_criteria_data / remove pathways without manually injecting a 'row' key.
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
    """Load WindSiteSelect-Public as package wind_site_select."""
    import importlib.util

    init_path = os.path.join(ROOT, "__init__.py")
    spec = importlib.util.spec_from_file_location(
        "wind_site_select",
        init_path,
        submodule_search_locations=[ROOT],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wind_site_select"] = mod
    # Ensure sibling imports resolve for already-loaded absolute helpers
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


@unittest.skipUnless(_bootstrap_qgis(), "QGIS 4.0.3 environment unavailable: {}".format(_qgis_err))
class McaCriteriaRowMappingTests(unittest.TestCase):
    """Required restore/import/remove row-mapping scenarios."""

    @classmethod
    def setUpClass(cls):
        import numpy as np
        from qgis.core import QgsProject

        cls.workdir = tempfile.mkdtemp(prefix="wss_mca_row_")
        cls.wind_path = os.path.join(cls.workdir, "WindSpeed.tif")
        cls.slope_path = os.path.join(cls.workdir, "Slope.tif")
        yy, xx = np.mgrid[0:12, 0:12]
        _write_float_tif(cls.wind_path, (8.0 + 0.1 * xx).astype(float))
        _write_float_tif(cls.slope_path, (2.0 + 0.05 * yy).astype(float))
        QgsProject.instance().clear()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtWidgets import QMessageBox

        # Re-assert Yes enum after other test modules may have patched question→int(1)
        yes = getattr(getattr(QMessageBox, "StandardButton", QMessageBox), "Yes", 1)
        QMessageBox.warning = staticmethod(lambda *a, **k: 1)
        QMessageBox.critical = staticmethod(lambda *a, **k: 1)
        QMessageBox.information = staticmethod(lambda *a, **k: 1)
        QMessageBox.question = staticmethod(lambda *a, **k: yes)

        QgsProject.instance().clear()
        self.plugin = _plugin.classFactory(_FakeIface())
        self.plugin.initGui()
        self.plugin.run()
        self.plugin.get_canonical_results_root = lambda: self.workdir
        self.plugin.get_plugin_results_dir = lambda: self.workdir

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass

    def _payload(self, wind_w=60.0, slope_w=40.0):
        from results_lifecycle import build_criteria_export_payload

        return build_criteria_export_payload(
            [
                {
                    "layer_name": "WindSpeed",
                    "weight": wind_w,
                    "role": "Beneficial",
                    "include": True,
                    "save": True,
                    "layer_path": self.wind_path,
                },
                {
                    "layer_name": "Slope",
                    "weight": slope_w,
                    "role": "Penalizing",
                    "include": True,
                    "save": True,
                    "layer_path": self.slope_path,
                },
            ]
        )

    def _assert_row_mapping(self, expected_names):
        dml = self.plugin.decision_making_layers
        self.assertEqual(len(dml), len(expected_names))
        for i, name in enumerate(expected_names):
            self.assertIn("row", dml[i], msg="decision_making_layers[{}] missing row".format(i))
            self.assertEqual(dml[i]["row"], i)
            self.assertEqual(dml[i].get("layer_name"), name)
            self.assertIsNotNone(dml[i].get("layer"))

        # Real extract path — no manual row injection after helpers ran
        criteria = self.plugin.extract_criteria_data()
        self.assertEqual(len(criteria), len(expected_names))
        for i, name in enumerate(expected_names):
            self.assertEqual(criteria[i]["layer_name"], name)
            self.assertEqual(criteria[i]["row_index"], i)
            self.assertIsNotNone(criteria[i]["layer"])
            self.assertTrue(criteria[i]["layer"].isValid())

        ok = self.plugin.validate_criteria(show_messages=False)
        self.assertTrue(ok, "restored/imported criteria must pass MCA validation")

    def test_01_apply_payload_populates_row_mapping(self):
        payload = self._payload()
        applied, err = self.plugin._apply_criteria_payload(payload, show_messages=False)
        self.assertTrue(applied, err)
        # Guard: helpers themselves must have written row (not a post-hoc patch)
        self.assertTrue(all("row" in e for e in self.plugin.decision_making_layers))
        self._assert_row_mapping(["WindSpeed", "Slope"])

    def test_02_json_import_path(self):
        payload = self._payload()
        json_path = os.path.join(self.workdir, "criteria_import.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

        from results_lifecycle import load_and_validate_criteria_file

        ok, err, loaded = load_and_validate_criteria_file(json_path)
        self.assertTrue(ok, err)
        applied, apply_err = self.plugin._apply_criteria_payload(loaded, show_messages=False)
        self.assertTrue(applied, apply_err)
        self._assert_row_mapping(["WindSpeed", "Slope"])

    def test_03_remove_criterion_reindexes_rows(self):
        applied, err = self.plugin._apply_criteria_payload(self._payload(), show_messages=False)
        self.assertTrue(applied, err)

        table = self.plugin.dlg.tbl_weights
        table.selectRow(0)
        self.plugin.remove_layer_from_weights_table()

        self._assert_row_mapping(["Slope"])
        self.assertEqual(self.plugin.decision_making_layers[0]["row"], 0)

    def test_04_restore_after_dialog_reset(self):
        payload = self._payload()
        applied, err = self.plugin._apply_criteria_payload(payload, show_messages=False)
        self.assertTrue(applied, err)
        snapshot = self.plugin._serialize_criteria_for_persistence()

        # Simulate New MCA Analysis / dialog clear
        self.plugin.start_new_mca_analysis()
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 0)
        self.assertEqual(self.plugin.decision_making_layers, [])

        applied2, err2 = self.plugin._apply_criteria_payload(snapshot, show_messages=False)
        self.assertTrue(applied2, err2)
        self._assert_row_mapping(["WindSpeed", "Slope"])

    def test_05_invalid_import_leaves_existing_unchanged(self):
        applied, err = self.plugin._apply_criteria_payload(self._payload(), show_messages=False)
        self.assertTrue(applied, err)
        before_names = [e.get("layer_name") for e in self.plugin.decision_making_layers]
        before_rows = [e.get("row") for e in self.plugin.decision_making_layers]
        before_count = self.plugin.dlg.tbl_weights.rowCount()

        bad = {
            "schema_version": 1,
            "criteria": [
                {"layer_name": "Bad", "weight": float("nan"), "role": "Beneficial", "include": True}
            ],
        }
        applied_bad, bad_err = self.plugin._apply_criteria_payload(bad, show_messages=False)
        self.assertFalse(applied_bad)
        self.assertTrue(bad_err)

        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before_count)
        self.assertEqual(
            [e.get("layer_name") for e in self.plugin.decision_making_layers], before_names
        )
        self.assertEqual([e.get("row") for e in self.plugin.decision_making_layers], before_rows)
        # Still extractable without KeyError
        criteria = self.plugin.extract_criteria_data()
        self.assertEqual(len(criteria), 2)


if __name__ == "__main__":
    unittest.main()

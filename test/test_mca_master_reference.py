# -*- coding: utf-8 -*-
"""
Regression: MCA master reference after Spatial Filtering / session reset.

Evidence type: Production-helper integration under QGIS 4.0.3 (offscreen).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)

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
        QMessageBox.question = staticmethod(lambda *a, **k: 1)

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


def _write_byte(path, ox=4500000.0, oy=3200000.0, px=100.0, n=8):
    from osgeo import gdal, osr
    import numpy as np

    gdal.UseExceptions()
    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3035)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(np.ones((n, n), dtype=np.uint8))
    band.SetNoDataValue(255)
    ds = None


def _write_float(path, ox=4500000.0, oy=3200000.0, px=100.0, n=8):
    from osgeo import gdal, osr
    import numpy as np

    gdal.UseExceptions()
    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3035)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray((np.arange(n * n, dtype=np.float32).reshape(n, n) + 1.0))
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


@unittest.skipUnless(_bootstrap(), "QGIS unavailable: {}".format(_qgis_err))
class McaMasterReferenceTests(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QSettings

        QgsProject.instance().clear()
        self.workdir = tempfile.mkdtemp(prefix="wss_master_ref_")
        self.results = os.path.join(self.workdir, "results")
        os.makedirs(self.results, exist_ok=True)
        self.spatial = os.path.join(self.results, "spatial_filtered.tif")
        self.wind = os.path.join(self.workdir, "wind_master.tif")
        self.prospect = os.path.join(self.workdir, "prospect.tif")
        _write_byte(self.spatial)
        _write_float(self.wind)
        _write_float(self.prospect)
        QSettings().setValue("wind_site_select/last_results_root", self.results)

        self.plugin = _plugin_mod.classFactory(_FakeIface())
        self.plugin.initGui()
        self.plugin.run()
        self.plugin.output_dir = self.workdir
        self.plugin.results_dir = self.results
        self.plugin._remember_results_root()

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_01_prefers_spatial_filtered_over_wind(self):
        self.plugin.wind_master_path = self.wind
        self.plugin.spatial_filter_result_path = self.spatial
        layer, path, name = self.plugin.get_master_reference_raster_for_decision_making()
        self.assertIsNotNone(layer)
        self.assertEqual(os.path.normcase(path), os.path.normcase(self.spatial))
        self.assertEqual(name, "spatial_filtered.tif")

    def test_02_session_spatial_found_after_results_dir_cleared(self):
        """GUI failure mode: reset clears results_dir; remembered root + session/alias still resolve."""
        self.plugin.spatial_filter_result_path = self.spatial
        self.plugin.wind_master_path = None
        self.plugin.wind_result_path = None
        self.plugin.prospect_result_path = None
        # Simulate dialog reset clearing durable dirs
        self.plugin.results_dir = None
        self.plugin.output_dir = None
        layer, path, name = self.plugin.get_master_reference_raster_for_decision_making()
        self.assertIsNotNone(layer, "master must resolve via session spatial path")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.normcase(path), os.path.normcase(self.spatial))

    def test_03_manifest_restore_recovers_spatial_and_master(self):
        import results_lifecycle as _rl

        run_id = "run_test_spatial"
        run_spatial = os.path.join(self.results, "runs", run_id, "spatial")
        os.makedirs(run_spatial, exist_ok=True)
        durable = os.path.join(run_spatial, "spatial_filtered.tif")
        shutil.copyfile(self.spatial, durable)
        poly = os.path.join(run_spatial, "spatial_final_polygons.gpkg")
        # minimal empty-ish gpkg not required for master raster test; skip polygons
        section = _rl.build_spatial_section(
            self.results,
            run_id,
            durable,
            durable,  # placeholder path; file may not be gpkg — only raster restore matters
            input_refs={
                "wind_master": self.wind,
                "prospect": self.prospect,
            },
        )
        # Fix polygons_output to None-like by editing section
        section["polygons_output"] = None
        man = _rl.update_manifest_after_spatial(None, self.results, section)
        ok, err = _rl.save_manifest_atomic(os.path.join(self.results, "current_run.json"), man)
        self.assertTrue(ok, err)

        self.plugin.spatial_filter_result_path = None
        self.plugin.wind_master_path = None
        self.plugin.results_dir = None
        self.plugin.output_dir = None
        applied, msg = self.plugin._apply_manifest_paths_to_session()
        self.assertTrue(applied, msg)
        self.assertTrue(os.path.isfile(self.plugin.spatial_filter_result_path or ""))
        layer, path, name = self.plugin.get_master_reference_raster_for_decision_making()
        self.assertIsNotNone(layer)
        self.assertEqual(os.path.normcase(path), os.path.normcase(self.plugin.spatial_filter_result_path))

    def test_04_missing_spatial_actionable_error(self):
        self.plugin.spatial_filter_result_path = None
        self.plugin.wind_master_path = None
        self.plugin.wind_result_path = None
        self.plugin.prospect_result_path = None
        # Point results at empty dir so alias also missing
        empty = os.path.join(self.workdir, "empty_results")
        os.makedirs(empty, exist_ok=True)
        self.plugin.results_dir = empty
        self.plugin.output_dir = self.workdir
        # Remove alias if present
        alias = os.path.join(empty, "spatial_filtered.tif")
        if os.path.isfile(alias):
            os.remove(alias)
        layer, path, name = self.plugin.get_master_reference_raster_for_decision_making()
        self.assertIsNone(layer)
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_analysis_master_grid_path()
        self.assertIn("Complete Spatial Filtering first", str(ctx.exception))

    def test_05_analysis_master_used_not_raw_wind_lineedit(self):
        """Raw wind input line edit must not become the MCA master when spatial exists."""
        raw_input = os.path.join(self.workdir, "raw_unclipped_wind.tif")
        _write_float(raw_input)
        if hasattr(self.plugin.dlg, "lineEditWindPath"):
            self.plugin.dlg.lineEditWindPath.setText(raw_input)
        self.plugin.wind_master_path = None
        self.plugin.wind_result_path = None
        self.plugin.spatial_filter_result_path = self.spatial
        layer, path, name = self.plugin.get_master_reference_raster_for_decision_making()
        self.assertEqual(os.path.normcase(path), os.path.normcase(self.spatial))
        self.assertNotEqual(os.path.normcase(path), os.path.normcase(raw_input))


class ResolveAuthoritativeSessionWithoutRootTests(unittest.TestCase):
    """Pure helper: session raster resolves even when results_root is empty."""

    def test_session_raster_without_root(self):
        import results_lifecycle as _rl

        td = tempfile.mkdtemp(prefix="wss_sess_")
        try:
            raster = os.path.join(td, "spatial_filtered.tif")
            open(raster, "wb").write(b"x")
            out = _rl.resolve_authoritative_spatial_paths(
                "",
                session_raster=raster,
                session_polygons=None,
                manifest=None,
            )
            self.assertEqual(os.path.normcase(out["raster"]), os.path.normcase(raster))
            self.assertEqual(out["source"], "session")
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

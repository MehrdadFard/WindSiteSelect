# -*- coding: utf-8 -*-
"""AOI vs Spatial Filtering master-grid overlap / lifecycle regression."""
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


def _write_byte_raster(path, ox=4500000.0, oy=3200000.0, px=100.0, n=10, epsg=3035):
    from osgeo import gdal, osr
    import numpy as np

    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(np.ones((n, n), dtype=np.uint8))
    band.SetNoDataValue(255)
    ds = None


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
class AoiMasterOverlapTests(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QSettings

        QgsProject.instance().clear()
        self.workdir = tempfile.mkdtemp(prefix="wss_aoi_master_")
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

    def _master(self):
        from qgis.core import QgsRasterLayer

        lyr = QgsRasterLayer(self.spatial, "MasterGrid", "gdal")
        self.assertTrue(lyr.isValid())
        return lyr

    def _write_manifest(self, aoi_identity, run_id="run_test_1"):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": now,
            "updated_at": now,
            "spatial_filter": {
                "run_id": run_id,
                "raster_output": "spatial_filtered.tif",
                "polygons_output": None,
                "input_refs": {"aoi_identity": aoi_identity},
            },
            "mca": None,
        }
        path = os.path.join(self.results, "current_run.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)

    def test_01_valid_aoi_and_master_same_run_ok(self):
        aoi = os.path.join(self.workdir, "aoi_ok.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4500800.0, 3199700.0)
        lyr = _set_aoi(self.plugin, aoi)
        token = self.plugin._aoi_identity_token(lyr)
        self._write_manifest(token)
        master = self._master()
        diag = self.plugin._diagnose_aoi_master_overlap(master, aoi_layer=lyr)
        self.assertEqual(diag["status"], "ok", diag)
        ref, path, aoi_out = self.plugin._require_proximity_analysis_context()
        self.assertTrue(ref.isValid())
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(aoi_out.id(), lyr.id())

    def test_02_aoi_changed_after_spatial_rejected(self):
        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4500800.0, 3199700.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        self._write_manifest(self.plugin._aoi_identity_token(lyr_a))

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 4500400.0, 3199300.0, 4500900.0, 3199800.0)
        lyr_b = _set_aoi(self.plugin, aoi_b)
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        msg = str(ctx.exception)
        self.assertIn("Area of Interest has changed", msg)

    def test_03_previous_run_master_association_rejected_on_aoi_change(self):
        # Same as test_02 but with explicit previous run_id in manifest.
        aoi_old = os.path.join(self.workdir, "aoi_old.gpkg")
        _write_poly_gpkg(aoi_old, 4500200.0, 3199100.0, 4500700.0, 3199600.0)
        lyr_old = _set_aoi(self.plugin, aoi_old)
        self._write_manifest(self.plugin._aoi_identity_token(lyr_old), run_id="run_previous")
        aoi_new = os.path.join(self.workdir, "aoi_new.gpkg")
        _write_poly_gpkg(aoi_new, 4500500.0, 3199400.0, 4501000.0, 3199900.0)
        _set_aoi(self.plugin, aoi_new)
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        msg = str(ctx.exception)
        self.assertTrue(
            "Area of Interest has changed" in msg
            or "does not match the AOI" in msg
            or "same analysis run" in msg
        )

    def test_04_different_crs_overlap_after_transform(self):
        from qgis.core import QgsCoordinateTransform, QgsProject, QgsPointXY, QgsCoordinateReferenceSystem

        master = self._master()
        to_wgs = QgsCoordinateTransform(
            master.crs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance().transformContext(),
        )
        # Corners of a box inside the master grid, expressed in WGS84.
        p1 = to_wgs.transform(QgsPointXY(4500400.0, 3199400.0))
        p2 = to_wgs.transform(QgsPointXY(4500600.0, 3199600.0))
        aoi = os.path.join(self.workdir, "aoi_wgs.gpkg")
        _write_poly_gpkg(aoi, min(p1.x(), p2.x()), min(p1.y(), p2.y()), max(p1.x(), p2.x()), max(p1.y(), p2.y()), epsg=4326)
        lyr = _set_aoi(self.plugin, aoi)
        self.assertEqual(lyr.crs().authid(), "EPSG:4326")
        diag = self.plugin._diagnose_aoi_master_overlap(master, aoi_layer=lyr)
        self.assertEqual(diag["status"], "ok", diag)

    def test_05_genuine_non_overlap_rejected(self):
        aoi = os.path.join(self.workdir, "aoi_far.gpkg")
        _write_poly_gpkg(aoi, 4000000.0, 2700000.0, 4001000.0, 2701000.0)
        lyr = _set_aoi(self.plugin, aoi)
        self._write_manifest(self.plugin._aoi_identity_token(lyr))
        master = self._master()
        diag = self.plugin._diagnose_aoi_master_overlap(master, aoi_layer=lyr)
        self.assertEqual(diag["status"], "no_overlap", diag)
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        msg = str(ctx.exception)
        self.assertTrue(
            "does not overlap" in msg
            or "does not intersect" in msg
            or "different analysis area" in msg
            or "Area of Interest has changed" in msg
            or "analysis reference grid are required" in msg,
            msg,
        )

    def test_06_invalid_empty_aoi_rejected(self):
        self.plugin.user_aoi_layer = None
        self.plugin.user_aoi_layer_id = None
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        self.assertIn("AOI", str(ctx.exception))

    def test_07_session_restore_does_not_reuse_unrelated_aoi_token(self):
        aoi = os.path.join(self.workdir, "aoi_sess.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4500800.0, 3199700.0)
        lyr = _set_aoi(self.plugin, aoi)
        self._write_manifest(self.plugin._aoi_identity_token(lyr))
        # Clear in-memory spatial pointer; restore from settings/manifest must still validate.
        self.plugin.spatial_filter_result_path = None
        self.plugin.results_dir = None
        restored = self.plugin._restore_results_root_from_settings()
        self.assertTrue(restored)
        ref, path, _aoi = self.plugin._require_proximity_analysis_context()
        self.assertTrue(os.path.isfile(path))

    def test_08_repeated_results_runs_paths_coerced(self):
        nested = os.path.join(
            self.workdir, "results", "runs", "run_x", "results", "runs", "run_y", "results"
        )
        os.makedirs(nested, exist_ok=True)
        coerced = self.plugin._coerce_canonical_results_root(nested)
        self.assertEqual(os.path.normcase(coerced), os.path.normcase(self.results))
        # ensure_output_dirs from nested path must not deepen nesting
        self.plugin.ensure_output_dirs(nested)
        self.assertEqual(os.path.normcase(self.plugin.results_dir), os.path.normcase(self.results))
        self.assertNotIn(
            os.path.normcase(os.path.join("runs", "results")),
            os.path.normcase(self.plugin.results_dir),
        )


if __name__ == "__main__":
    unittest.main()

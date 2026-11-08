# -*- coding: utf-8 -*-
"""
Proximity Analysis AOI gates and masking regression (EPSG:3035 synthetic).

Evidence type: QGIS 4.0.3 offscreen + GDAL Processing.
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

from results_lifecycle import build_criteria_export_payload  # noqa: E402

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


def _write_line_gpkg(path, coords):
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
    for i, pts in enumerate(coords, start=1):
        feat = QgsFeature(fields)
        feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts]))
        feat.setAttributes([i])
        writer.addFeature(feat)
    del writer


def _write_poly_gpkg(path, xmin, ymin, xmax, ymax):
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
class ProximityAoiGateTests(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QSettings

        QgsProject.instance().clear()
        self.workdir = tempfile.mkdtemp(prefix="wss_prox_aoi_")
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
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "proximity"

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _tif_snapshot(self):
        found = set()
        for root, _, files in os.walk(self.workdir):
            for f in files:
                if f.lower().endswith(".tif"):
                    found.add(os.path.normcase(os.path.join(root, f)))
        return found

    def _project_raster_paths(self):
        from qgis.core import QgsProject, QgsRasterLayer

        paths = set()
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsRasterLayer) and lyr.isValid():
                src = (lyr.source() or "").split("|")[0].strip().strip('"')
                if src:
                    paths.add(os.path.normcase(src))
        return paths

    def _clear_aoi(self):
        from qgis.core import QgsProject

        self.plugin.user_aoi_layer = None
        self.plugin.user_aoi_layer_id = None
        for lyr in list(QgsProject.instance().mapLayers().values()):
            try:
                prop = lyr.customProperty("wind_plugin_user_aoi")
            except Exception:
                prop = None
            name = lyr.name() if hasattr(lyr, "name") else ""
            if prop is True or prop == "true" or prop == "True" or name == "Wind Site Select AOI":
                QgsProject.instance().removeMapLayer(lyr.id())

    def test_A_missing_aoi_refuses_proximity_no_output(self):
        from qgis.core import QgsProject, QgsVectorLayer

        # Stale spatial master is present; AOI is intentionally absent.
        self._clear_aoi()

        line = os.path.join(self.workdir, "power.gpkg")
        _write_line_gpkg(line, [[(4500300.0, 3199200.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "Power", "ogr")
        QgsProject.instance().addMapLayer(layer)

        before_rows = self.plugin.dlg.tbl_weights.rowCount()
        before_files = self._tif_snapshot()
        before_rasters = self._project_raster_paths()

        self.plugin.add_layer_to_weights_table(from_file_layer=layer)

        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before_rows)
        self.assertFalse(self.plugin.decision_making_layers)
        self.assertIsNone(getattr(self.plugin, "_pending_vector_criterion_meta", None))
        # No new GeoTIFF products at all (including converted/distance/suitability)
        self.assertEqual(self._tif_snapshot(), before_files)
        self.assertEqual(self._project_raster_paths(), before_rasters)
        self.assertTrue(os.path.isfile(self.spatial))

    def test_A2_add_layer_from_map_entry_refuses_without_aoi(self):
        """GUI entry: Add Layer from Map → Proximity (QInputDialog path)."""
        from qgis.core import QgsProject, QgsVectorLayer
        from qgis.PyQt.QtWidgets import QInputDialog

        self._clear_aoi()
        line = os.path.join(self.workdir, "power_map.gpkg")
        _write_line_gpkg(line, [[(4500300.0, 3199200.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "PowerMap", "ogr")
        QgsProject.instance().addMapLayer(layer)

        display = "{} (Vector - will convert to raster)".format(layer.name())
        real_get_item = QInputDialog.getItem
        QInputDialog.getItem = staticmethod(lambda *a, **k: (display, True))
        before_files = self._tif_snapshot()
        before_rows = self.plugin.dlg.tbl_weights.rowCount()
        try:
            self.plugin.add_layer_to_weights_table()  # map/project picker entry point
        finally:
            QInputDialog.getItem = real_get_item

        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before_rows)
        self.assertFalse(self.plugin.decision_making_layers)
        self.assertEqual(self._tif_snapshot(), before_files)

    def test_A3_add_vector_criterion_file_entry_refuses_without_aoi(self):
        """GUI entry: Add Vector Criterion... → Proximity (file dialog path)."""
        from qgis.PyQt.QtWidgets import QFileDialog

        self._clear_aoi()
        line = os.path.join(self.workdir, "power_file.gpkg")
        _write_line_gpkg(line, [[(4500300.0, 3199200.0), (4500700.0, 3199600.0)]])

        real_open = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (line, "GeoPackage (*.gpkg)"))
        before_files = self._tif_snapshot()
        before_rows = self.plugin.dlg.tbl_weights.rowCount()
        try:
            self.plugin.add_vector_criterion_from_file()
        finally:
            QFileDialog.getOpenFileName = real_open

        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), before_rows)
        self.assertFalse(self.plugin.decision_making_layers)
        self.assertEqual(self._tif_snapshot(), before_files)

    def test_A4_stale_session_remembered_spatial_without_aoi(self):
        """results_dir cleared but last_results_root still points at spatial_filtered — still refuse."""
        from qgis.core import QgsProject, QgsVectorLayer
        from qgis.PyQt.QtCore import QSettings

        self._clear_aoi()
        self.plugin.results_dir = None
        self.plugin.spatial_filter_result_path = None
        QSettings().setValue("wind_site_select/last_results_root", self.results)
        self.assertTrue(os.path.isfile(self.spatial))

        line = os.path.join(self.workdir, "power_stale.gpkg")
        _write_line_gpkg(line, [[(4500300.0, 3199200.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "PowerStale", "ogr")
        QgsProject.instance().addMapLayer(layer)

        before_files = self._tif_snapshot()
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        self.assertIn("AOI", str(ctx.exception))

        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 0)
        self.assertEqual(self._tif_snapshot(), before_files)

    def test_A5_cleared_aoi_after_success_refuses_and_preserves_prior(self):
        """After a successful proximity run, clearing AOI must block a new run and keep the old file."""
        from qgis.core import QgsProject, QgsVectorLayer

        aoi = os.path.join(self.workdir, "aoi_ok.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4500800.0, 3199700.0)
        _set_aoi(self.plugin, aoi)
        line = os.path.join(self.workdir, "power_ok.gpkg")
        _write_line_gpkg(line, [[(4500400.0, 3199300.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "PowerOk", "ogr")
        QgsProject.instance().addMapLayer(layer)
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(len(self.plugin.decision_making_layers), 1)
        prior = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        prior_bytes = open(prior, "rb").read()

        self.plugin.dlg.tbl_weights.setRowCount(0)
        self.plugin.decision_making_layers = []
        self._clear_aoi()
        before_files = self._tif_snapshot()

        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 0)
        self.assertTrue(os.path.isfile(prior))
        self.assertEqual(open(prior, "rb").read(), prior_bytes)
        # No additional proximity products beyond the preserved prior run
        new_prox = {
            p for p in (self._tif_snapshot() - before_files)
            if ("suitability" in os.path.basename(p).lower() or "distance" in os.path.basename(p).lower()
                or "converted" in os.path.basename(p).lower())
        }
        self.assertEqual(new_prox, set())

    def test_A6_regenerate_and_payload_refuse_without_aoi(self):
        """Regenerate / criteria restore must not create proximity outputs without AOI."""
        from qgis.core import QgsProject, QgsVectorLayer

        self._clear_aoi()
        line = os.path.join(self.workdir, "power_regen.gpkg")
        _write_line_gpkg(line, [[(4500300.0, 3199200.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "PowerRegen", "ogr")
        QgsProject.instance().addMapLayer(layer)

        item = {
            "layer_name": "PowerRegen",
            "source_type": "vector",
            "analysis_mode": "proximity",
            "source_vector_path": line,
            "source_vector_name": "PowerRegen",
            "weight": 50.0,
            "role": "Beneficial",
            "include": True,
        }
        before_files = self._tif_snapshot()
        derived, err = self.plugin._regenerate_vector_criterion_raster(item)
        self.assertIsNone(derived)
        self.assertTrue(err)
        self.assertIn("AOI", err)
        self.assertEqual(self._tif_snapshot(), before_files)

        payload = build_criteria_export_payload(
            [
                {
                    "layer_name": "PowerRegen",
                    "weight": 50.0,
                    "role": "Beneficial",
                    "include": True,
                    "source_type": "vector",
                    "analysis_mode": "proximity",
                    "source_vector_path": line,
                    "derived_raster_path": os.path.join(self.workdir, "missing_prox.tif"),
                    "layer_path": os.path.join(self.workdir, "missing_prox.tif"),
                }
            ]
        )
        before_files = self._tif_snapshot()
        applied, apply_err = self.plugin._apply_criteria_payload(payload, show_messages=False)
        self.assertTrue(applied, apply_err)
        self.assertEqual(self._tif_snapshot(), before_files)
        # Row may exist without a valid scoring raster
        if self.plugin.decision_making_layers:
            entry = self.plugin.decision_making_layers[0]
            lyr = entry.get("layer")
            self.assertTrue(lyr is None or not lyr.isValid())

    def test_A7_compute_proximity_raster_defense_gate(self):
        """Low-level proximity writer must refuse without AOI before creating output_path."""
        from qgis.core import QgsRasterLayer

        self._clear_aoi()
        out = os.path.join(self.workdir, "must_not_create_distance.tif")
        ref = QgsRasterLayer(self.spatial, "m", "gdal")
        self.assertTrue(ref.isValid())
        ok, err = self.plugin._compute_proximity_raster(self.spatial, out, reference_raster=ref)
        self.assertFalse(ok)
        self.assertIn("AOI", err or "")
        self.assertFalse(os.path.isfile(out))

    def test_B_aoi_mask_no_valid_outside(self):
        from qgis.core import QgsProject, QgsVectorLayer, QgsRasterLayer
        import numpy as np
        from osgeo import gdal

        aoi = os.path.join(self.workdir, "aoi.gpkg")
        # Irregular relative to full 10x10 master: only SE quadrant-ish
        _write_poly_gpkg(aoi, 4500500.0, 3199000.0, 4501000.0, 3199500.0)
        _set_aoi(self.plugin, aoi)

        line = os.path.join(self.workdir, "power.gpkg")
        _write_line_gpkg(
            line,
            [
                [(4500600.0, 3199100.0), (4500900.0, 3199400.0)],
                [(4500200.0, 3199600.0), (4500400.0, 3199800.0)],  # outside AOI, inside master
            ],
        )
        layer = QgsVectorLayer(line, "Power", "ogr")
        QgsProject.instance().addMapLayer(layer)
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 1)
        path = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        master = QgsRasterLayer(self.spatial, "m", "gdal")
        der = QgsRasterLayer(path, "d", "gdal")
        self.assertEqual(der.width(), master.width())
        self.assertEqual(der.height(), master.height())
        self.assertEqual(der.crs().authid(), "EPSG:3035")

        ok, err = self.plugin._validate_proximity_suitability_masked_to_aoi(path, self.spatial)
        self.assertTrue(ok, err)

        # Direct check NoData outside AOI
        info = self.plugin._get_reference_raster_info(self.spatial)
        mask_path = os.path.join(self.workdir, "mask_check.tif")
        self.assertTrue(self.plugin._rasterize_user_aoi_binary_mask(self.spatial, mask_path, ref_info=info))
        ds_s = gdal.Open(path)
        ds_m = gdal.Open(mask_path)
        S = ds_s.GetRasterBand(1).ReadAsArray().astype(float)
        M = ds_m.GetRasterBand(1).ReadAsArray()
        nd = ds_s.GetRasterBand(1).GetNoDataValue()
        outside = S[M <= 0]
        self.assertTrue(np.all(~np.isfinite(outside) | (np.abs(outside - nd) < 1e-6)))
        inside = S[M > 0]
        finite = inside[np.isfinite(inside) & (np.abs(inside - nd) > 1e-6)]
        self.assertGreater(finite.size, 0)

    def test_C_external_nearest_line_contributes(self):
        from qgis.core import QgsProject, QgsVectorLayer
        import numpy as np
        from osgeo import gdal

        aoi = os.path.join(self.workdir, "aoi2.gpkg")
        _write_poly_gpkg(aoi, 4500400.0, 3199200.0, 4500800.0, 3199600.0)
        _set_aoi(self.plugin, aoi)

        # Only line is just west of AOI (outside polygon, still on master grid)
        line = os.path.join(self.workdir, "outside_line.gpkg")
        _write_line_gpkg(line, [[(4500200.0, 3199300.0), (4500200.0, 3199500.0)]])
        layer = QgsVectorLayer(line, "OutsidePower", "ogr")
        QgsProject.instance().addMapLayer(layer)
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        self.assertEqual(len(self.plugin.decision_making_layers), 1)
        path = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        ds = gdal.Open(path)
        arr = ds.GetRasterBand(1).ReadAsArray().astype(float)
        nd = ds.GetRasterBand(1).GetNoDataValue()
        finite = arr[np.isfinite(arr) & (np.abs(arr - nd) > 1e-6)]
        self.assertGreater(finite.size, 0)
        # Suitability in [0,1]
        self.assertGreaterEqual(float(np.min(finite)), -1e-6)
        self.assertLessEqual(float(np.max(finite)), 1.0 + 1e-5)

    def test_D_different_aois_distinct_outputs(self):
        from qgis.core import QgsProject, QgsVectorLayer

        line = os.path.join(self.workdir, "power3.gpkg")
        _write_line_gpkg(line, [[(4500300.0, 3199100.0), (4500900.0, 3199700.0)]])
        layer = QgsVectorLayer(line, "Power3", "ogr")
        QgsProject.instance().addMapLayer(layer)

        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500200.0, 3199200.0, 4500600.0, 3199600.0)
        _set_aoi(self.plugin, aoi_a)
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        path_a = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        self.assertTrue(os.path.isfile(path_a))

        # Clear table for second run (simulate new analysis)
        self.plugin.dlg.tbl_weights.setRowCount(0)
        self.plugin.decision_making_layers = []

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 4500500.0, 3199000.0, 4501000.0, 3199500.0)
        _set_aoi(self.plugin, aoi_b)
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        path_b = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        self.assertTrue(os.path.isfile(path_b))
        self.assertNotEqual(os.path.normcase(path_a), os.path.normcase(path_b))
        self.assertTrue(os.path.isfile(path_a))  # previous preserved

    def test_E_validation_failure_preserves_previous(self):
        from qgis.core import QgsProject, QgsVectorLayer

        aoi = os.path.join(self.workdir, "aoi_e.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4500800.0, 3199700.0)
        _set_aoi(self.plugin, aoi)
        line = os.path.join(self.workdir, "power_e.gpkg")
        _write_line_gpkg(line, [[(4500400.0, 3199300.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "PowerE", "ogr")
        QgsProject.instance().addMapLayer(layer)
        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        path_ok = self.plugin.decision_making_layers[-1]["derived_raster_path"]
        sha_before = open(path_ok, "rb").read()

        # Inject validation failure on next attempt
        self.plugin.dlg.tbl_weights.setRowCount(0)
        self.plugin.decision_making_layers = []
        real_validate = self.plugin._validate_proximity_suitability_masked_to_aoi
        self.plugin._validate_proximity_suitability_masked_to_aoi = lambda *a, **k: (False, "injected failure")
        try:
            self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        finally:
            self.plugin._validate_proximity_suitability_masked_to_aoi = real_validate

        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 0)
        self.assertTrue(os.path.isfile(path_ok))
        self.assertEqual(open(path_ok, "rb").read(), sha_before)


if __name__ == "__main__":
    unittest.main()

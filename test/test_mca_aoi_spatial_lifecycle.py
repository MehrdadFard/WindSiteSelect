# -*- coding: utf-8 -*-
"""
AOI / Spatial Filtering / Proximity output lifecycle regressions.

Covers AOI change invalidation, master-grid binding, incomplete-output
prevention, and run-specific path isolation (EPSG:3035 synthetic).
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


def _write_byte_raster(path, ox=4500000.0, oy=3200000.0, px=100.0, n=10, epsg=3035, fill=1):
    from osgeo import gdal, osr
    import numpy as np

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(np.full((n, n), fill, dtype=np.uint8))
    band.SetNoDataValue(255)
    ds = None


def _write_float_suitability(path, ox, oy, px, n, values, epsg=3035, nodata=-9999.0):
    from osgeo import gdal, osr
    import numpy as np

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    arr = np.asarray(values, dtype=np.float32)
    assert arr.shape == (n, n)
    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((ox, px, 0, oy, 0, -px))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(arr)
    band.SetNoDataValue(nodata)
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


def _raster_shape(path):
    from osgeo import gdal

    ds = gdal.Open(path)
    assert ds is not None
    w, h = ds.RasterXSize, ds.RasterYSize
    gt = ds.GetGeoTransform()
    ds = None
    return w, h, gt


@unittest.skipUnless(_bootstrap(), "QGIS unavailable: {}".format(_qgis_err))
class AoiSpatialLifecycleTests(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject
        from qgis.PyQt.QtCore import QSettings

        QgsProject.instance().clear()
        self.workdir = tempfile.mkdtemp(prefix="wss_aoi_life_")
        self.results = os.path.join(self.workdir, "results")
        os.makedirs(self.results, exist_ok=True)
        QSettings().setValue("wind_site_select/last_results_root", self.results)

        self.plugin = _plugin_mod.classFactory(_FakeIface())
        self.plugin.initGui()
        self.plugin.run()
        self.plugin.results_dir = self.results
        self.plugin.output_dir = self.workdir
        self.plugin.temp_dir = os.path.join(self.workdir, "temp")
        os.makedirs(self.plugin.temp_dir, exist_ok=True)
        self.plugin._remember_results_root()
        self.plugin._select_vector_analysis_mode = lambda layer_name=None: "proximity"
        self.plugin._spatial_stale_after_aoi_change = False

    def tearDown(self):
        try:
            self.plugin.unload()
        except Exception:
            pass
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _publish_master(self, ox, oy, n=20, px=100.0, run_id="run_a", aoi_layer=None, alias=True):
        """Simulate Spatial Filtering publish: run-specific master + optional flat alias."""
        spatial_dir = os.path.join(self.results, "runs", run_id, "spatial_filtering")
        os.makedirs(spatial_dir, exist_ok=True)
        durable = os.path.join(spatial_dir, "spatial_filtered.tif")
        _write_byte_raster(durable, ox=ox, oy=oy, px=px, n=n)
        if alias:
            alias_path = os.path.join(self.results, "spatial_filtered.tif")
            _write_byte_raster(alias_path, ox=ox, oy=oy, px=px, n=n)
        token = self.plugin._aoi_identity_token(aoi_layer) if aoi_layer else None
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        rel = os.path.relpath(durable, self.results).replace("\\", "/")
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": now,
            "updated_at": now,
            "spatial_filter": {
                "run_id": run_id,
                "raster_output": rel,
                "polygons_output": None,
                "input_refs": {"aoi_identity": token},
            },
            "mca": None,
        }
        with open(os.path.join(self.results, "current_run.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        self.plugin.spatial_filter_result_path = durable
        self.plugin._current_spatial_run_id = run_id
        self.plugin._spatial_stale_after_aoi_change = False
        return durable

    # --- Test 1: AOI A → Spatial → Proximity context OK ---
    def test_01_aoi_a_spatial_proximity_aligned(self):
        aoi = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr = _set_aoi(self.plugin, aoi)
        master = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr)
        ref, path, aoi_out = self.plugin._require_proximity_analysis_context()
        self.assertTrue(ref.isValid())
        self.assertEqual(os.path.normcase(path), os.path.normcase(master))
        self.assertEqual(aoi_out.id(), lyr.id())
        w, h, _gt = _raster_shape(path)
        self.assertEqual((w, h), (20, 20))

    # --- Test 2: AOI A → Spatial → switch AOI B → Proximity blocked ---
    def test_02_aoi_change_blocks_proximity_without_respatial(self):
        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        # Same CRS, disjoint geography (~40 km west)
        _write_poly_gpkg(aoi_b, 4000000.0, 3100000.0, 4010000.0, 3110000.0)
        _set_aoi(self.plugin, aoi_b)
        self.plugin._invalidate_spatial_outputs_for_aoi_change(reason="test_switch")

        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        self.assertIn("Area of Interest has changed", str(ctx.exception))

    # --- Test 3: AOI B Spatial re-run → Proximity OK with master B ---
    def test_03_respatial_for_aoi_b_then_proximity_ok(self):
        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        master_a = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 4000300.0, 3100200.0, 4001500.0, 3098500.0)
        lyr_b = _set_aoi(self.plugin, aoi_b)
        self.plugin._invalidate_spatial_outputs_for_aoi_change(reason="switch_b")
        master_b = self._publish_master(4000000.0, 3101000.0, n=20, run_id="run_b", aoi_layer=lyr_b)

        ref, path, _ = self.plugin._require_proximity_analysis_context()
        self.assertEqual(os.path.normcase(path), os.path.normcase(master_b))
        self.assertNotEqual(os.path.normcase(path), os.path.normcase(master_a))
        self.assertTrue(os.path.isfile(master_a))  # old run preserved on disk

    # --- Test 4: same CRS, different locations — no master reuse ---
    def test_04_same_crs_different_geography_no_reuse(self):
        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 3986909.0, 3080019.0, 4186856.0, 3250207.0)
        lyr_b = _set_aoi(self.plugin, aoi_b)
        # Leave stale flat alias from AOI A in place (simulate user bug report)
        self.plugin.spatial_filter_result_path = os.path.join(self.results, "spatial_filtered.tif")
        self.plugin._spatial_stale_after_aoi_change = False
        # Manifest still points at AOI A identity
        belongs = self.plugin._spatial_raster_belongs_to_current_aoi(
            self.plugin.spatial_filter_result_path, aoi_layer=lyr_b
        )
        self.assertFalse(belongs)
        resolved = self.plugin._resolve_current_spatial_outputs()
        self.assertIsNone(resolved.get("raster"))

    # --- Test 5: edit geometry in same AOI layer invalidates ---
    def test_05_geometry_edit_invalidates_master(self):
        from qgis.core import QgsGeometry, QgsRectangle, QgsFeatureRequest

        aoi = os.path.join(self.workdir, "aoi_edit.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr = _set_aoi(self.plugin, aoi)
        token_before = self.plugin._aoi_identity_token(lyr)
        self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_edit", aoi_layer=lyr)

        # Mutate geometry in-layer
        feat = next(lyr.getFeatures())
        lyr.startEditing()
        lyr.changeGeometry(
            feat.id(),
            QgsGeometry.fromRect(QgsRectangle(4500400.0, 3199100.0, 4501600.0, 3198400.0)),
        )
        lyr.commitChanges()
        token_after = self.plugin._aoi_identity_token(lyr)
        self.assertNotEqual(token_before, token_after)
        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        self.assertIn("Area of Interest has changed", str(ctx.exception))

    # --- Test 6: remove map layers; stale refs not treated as current ---
    def test_06_remove_map_layers_does_not_revive_stale_master(self):
        from qgis.core import QgsProject

        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)

        # Remove all map layers (user clears legend) but keep results files
        QgsProject.instance().removeAllMapLayers()
        self.plugin.user_aoi_layer = None
        self.plugin.user_aoi_layer_id = None

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 4000300.0, 3100200.0, 4001500.0, 3098500.0)
        _set_aoi(self.plugin, aoi_b)
        # Session still has old path; resolve must reject
        self.plugin.spatial_filter_result_path = os.path.join(
            self.results, "runs", "run_a", "spatial_filtering", "spatial_filtered.tif"
        )
        resolved = self.plugin._resolve_current_spatial_outputs()
        self.assertIsNone(resolved.get("raster"))
        with self.assertRaises(RuntimeError):
            self.plugin._require_proximity_analysis_context()

    # --- Test 7: session restore / criteria payload keeps or marks stale ---
    def test_07_manifest_restore_marks_stale_on_aoi_mismatch(self):
        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 4000300.0, 3100200.0, 4001500.0, 3098500.0)
        _set_aoi(self.plugin, aoi_b)
        self.plugin.spatial_filter_result_path = None
        ok, _err = self.plugin._apply_manifest_paths_to_session()
        self.assertTrue(ok)
        self.assertTrue(self.plugin._spatial_stale_after_aoi_change)
        self.assertIsNone(self.plugin.spatial_filter_result_path)

    # --- Test 8: proximity output extent/dims must match master ---
    def test_08_output_extent_must_match_master_not_vector_crop(self):
        import numpy as np

        aoi = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr = _set_aoi(self.plugin, aoi)
        master = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr)

        # Fake cropped suitability (5x5) — must fail grid match
        cropped = os.path.join(self.workdir, "cropped_suit.tif")
        _write_float_suitability(
            cropped,
            ox=4500500.0,
            oy=3199500.0,
            px=100.0,
            n=5,
            values=np.full((5, 5), 0.5, dtype=np.float32),
        )
        ok, err = self.plugin._validate_proximity_suitability_masked_to_aoi(cropped, master)
        self.assertFalse(ok)
        self.assertIn("master grid", err.lower())

        # Full-grid suitability matching master: NoData everywhere, then mask-apply path
        full = os.path.join(self.workdir, "full_suit.tif")
        vals = np.full((20, 20), 0.7, dtype=np.float32)
        _write_float_suitability(full, ox=4500000.0, oy=3200000.0, px=100.0, n=20, values=vals)
        masked = os.path.join(self.workdir, "full_suit_masked.tif")
        self.assertTrue(
            self.plugin._multiply_float_raster_by_aoi_mask(
                full, master, masked, ref_info=self.plugin._get_reference_raster_info(master)
            )
        )
        ok2, err2 = self.plugin._validate_proximity_suitability_masked_to_aoi(masked, master)
        self.assertTrue(ok2, err2)

    # --- Test 9: AOI masking / NoData outside ---
    def test_09_aoi_mask_nodata_outside(self):
        import numpy as np

        aoi = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr = _set_aoi(self.plugin, aoi)
        master = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr)

        leaky = os.path.join(self.workdir, "leaky.tif")
        vals = np.full((20, 20), 0.8, dtype=np.float32)  # valid everywhere — bad
        _write_float_suitability(leaky, ox=4500000.0, oy=3200000.0, px=100.0, n=20, values=vals)
        ok, err = self.plugin._validate_proximity_suitability_masked_to_aoi(leaky, master)
        self.assertFalse(ok)
        self.assertIn("outside the AOI", err)

    # --- Test 10: lines outside AOI but inside master remain eligible (sanitize clip off) ---
    def test_10_lines_outside_aoi_inside_master_not_clipped(self):
        from qgis.core import QgsVectorLayer, QgsProject

        aoi = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi, 4500500.0, 3199500.0, 4501000.0, 3199000.0)
        lyr = _set_aoi(self.plugin, aoi)
        master = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr)

        # Line entirely outside AOI polygon but inside master extent
        line = os.path.join(self.workdir, "outside_line.gpkg")
        _write_line_gpkg(line, [[(4500100.0, 3199900.0), (4500200.0, 3199800.0)]])
        vlayer = QgsVectorLayer(line, "OutsideLine", "ogr")
        QgsProject.instance().addMapLayer(vlayer)
        from qgis.core import QgsRasterLayer

        ref = QgsRasterLayer(master, "Master", "gdal")
        path, ok, err = self.plugin.sanitize_vector_for_rasterization(
            vlayer, ref, clip_to_aoi=False
        )
        self.assertTrue(ok, err)
        self.assertTrue(path and os.path.isfile(path), err)
        sanitized = QgsVectorLayer(path, "SanitizedOutside", "ogr")
        self.assertTrue(sanitized.isValid())
        self.assertGreaterEqual(sanitized.featureCount(), 1)

    # --- Test 11: large vector spatial candidate filtering retained ---
    def test_11_large_vector_spatial_filter_request(self):
        from qgis.core import (
            QgsCoordinateReferenceSystem,
            QgsFeature,
            QgsField,
            QgsFields,
            QgsGeometry,
            QgsPointXY,
            QgsVectorFileWriter,
            QgsVectorLayer,
            QgsWkbTypes,
            QgsProject,
            QgsRasterLayer,
        )
        from qgis.PyQt.QtCore import QVariant

        aoi = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr = _set_aoi(self.plugin, aoi)
        master = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr)

        # Create many features; one inside master extent, rest far away
        big = os.path.join(self.workdir, "big_lines.gpkg")
        crs = QgsCoordinateReferenceSystem("EPSG:3035")
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        writer = QgsVectorFileWriter(big, "UTF-8", fields, QgsWkbTypes.LineString, crs, "GPKG")
        # Put a hit early AND late so first-100 sampling would miss if filter broken
        for i in range(500):
            feat = QgsFeature(fields)
            if i == 250:
                pts = [QgsPointXY(4500400.0, 3199300.0), QgsPointXY(4500600.0, 3199500.0)]
            else:
                # Far west — outside master
                pts = [QgsPointXY(3000000.0 + i, 2000000.0), QgsPointXY(3000001.0 + i, 2000001.0)]
            feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
            feat.setAttributes([i])
            writer.addFeature(feat)
        del writer

        vlayer = QgsVectorLayer(big, "BigLines", "ogr")
        QgsProject.instance().addMapLayer(vlayer)
        self.assertEqual(vlayer.featureCount(), 500)
        ref = QgsRasterLayer(master, "Master", "gdal")
        path, ok, err = self.plugin.sanitize_vector_for_rasterization(
            vlayer, ref, clip_to_aoi=False
        )
        self.assertTrue(ok, err)
        self.assertTrue(path and os.path.isfile(path), err)
        sanitized = QgsVectorLayer(path, "SanitizedBig", "ogr")
        self.assertTrue(sanitized.isValid())
        # Must keep the in-extent feature (not falsely empty via first-100)
        self.assertGreaterEqual(sanitized.featureCount(), 1)

    # --- Test 12: no AOI + Proximity — no side effects ---
    def test_12_no_aoi_blocks_before_side_effects(self):
        from qgis.core import QgsProject, QgsVectorLayer

        master = os.path.join(self.results, "spatial_filtered.tif")
        _write_byte_raster(master, ox=4500000.0, oy=3200000.0, n=20)
        self.plugin.spatial_filter_result_path = master
        self.plugin.user_aoi_layer = None
        self.plugin.user_aoi_layer_id = None

        line = os.path.join(self.workdir, "power.gpkg")
        _write_line_gpkg(line, [[(4500400.0, 3199300.0), (4500700.0, 3199600.0)]])
        layer = QgsVectorLayer(line, "Power", "ogr")
        QgsProject.instance().addMapLayer(layer)

        before = set()
        for root, _, files in os.walk(self.workdir):
            for f in files:
                if f.lower().endswith(".tif"):
                    before.add(os.path.normcase(os.path.join(root, f)))

        with self.assertRaises(RuntimeError) as ctx:
            self.plugin._require_proximity_analysis_context()
        self.assertIn("AOI", str(ctx.exception))

        self.plugin.add_layer_to_weights_table(from_file_layer=layer)
        after = set()
        for root, _, files in os.walk(self.workdir):
            for f in files:
                if f.lower().endswith(".tif"):
                    after.add(os.path.normcase(os.path.join(root, f)))
        self.assertEqual(before, after)
        self.assertEqual(self.plugin.dlg.tbl_weights.rowCount(), 0)

    # --- Test 13: repeated AOIs use distinct run paths ---
    def test_13_run_specific_paths_do_not_overwrite(self):
        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        master_a = self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)

        aoi_b = os.path.join(self.workdir, "aoi_b.gpkg")
        _write_poly_gpkg(aoi_b, 4000300.0, 3100200.0, 4001500.0, 3098500.0)
        lyr_b = _set_aoi(self.plugin, aoi_b)
        master_b = self._publish_master(4000000.0, 3101000.0, n=20, run_id="run_b", aoi_layer=lyr_b)

        self.assertTrue(os.path.isfile(master_a))
        self.assertTrue(os.path.isfile(master_b))
        self.assertNotEqual(os.path.normcase(master_a), os.path.normcase(master_b))
        wa, ha, gta = _raster_shape(master_a)
        wb, hb, gtb = _raster_shape(master_b)
        self.assertEqual((wa, ha), (20, 20))
        self.assertEqual((wb, hb), (20, 20))
        self.assertNotEqual(gta[0], gtb[0])  # different origin X

    def test_14_finalize_aoi_invalidates_session_master(self):
        from qgis.core import QgsGeometry, QgsRectangle, QgsCoordinateReferenceSystem

        aoi_a = os.path.join(self.workdir, "aoi_a.gpkg")
        _write_poly_gpkg(aoi_a, 4500300.0, 3199200.0, 4501500.0, 3198500.0)
        lyr_a = _set_aoi(self.plugin, aoi_a)
        self._publish_master(4500000.0, 3200000.0, n=20, run_id="run_a", aoi_layer=lyr_a)
        self.assertIsNotNone(self.plugin.spatial_filter_result_path)

        geom = QgsGeometry.fromRect(QgsRectangle(4000300.0, 3100200.0, 4001500.0, 3098500.0))
        crs = QgsCoordinateReferenceSystem("EPSG:3035")
        self.plugin._finalize_aoi_from_geometry(geom, crs)
        self.assertTrue(self.plugin._spatial_stale_after_aoi_change)
        self.assertIsNone(self.plugin.spatial_filter_result_path)


if __name__ == "__main__":
    unittest.main()

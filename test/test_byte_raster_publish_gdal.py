# -*- coding: utf-8 -*-
"""
Standalone GDAL smoke test: Byte NoData=255 suitability raster publication.

Evidence type: Standalone GDAL tests (no QGIS Processing / no plugin UI).
Requires GDAL Python bindings (osgeo).
"""
import hashlib
import os
import shutil
import tempfile
import unittest

try:
    from osgeo import gdal, osr
    gdal.UseExceptions()
    _GDAL = True
except Exception:
    _GDAL = False

from results_lifecycle import publish_file_atomic

BINARY_BYTE_NODATA = 255


@unittest.skipUnless(_GDAL, "GDAL Python bindings not available")
class ByteRasterPublishGdalTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ws_gdal_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _make_byte_tif(self, path, value=1):
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(path, 4, 4, 1, gdal.GDT_Byte, ["COMPRESS=LZW"])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(3035)
        ds.SetProjection(srs.ExportToWkt())
        ds.SetGeoTransform((4000000.0, 100.0, 0.0, 3000000.0, 0.0, -100.0))
        band = ds.GetRasterBand(1)
        import numpy as np
        arr = np.full((4, 4), value, dtype=np.uint8)
        arr[0, 0] = BINARY_BYTE_NODATA
        band.WriteArray(arr)
        band.SetNoDataValue(BINARY_BYTE_NODATA)
        ds.FlushCache()
        ds = None

    def _sha(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            h.update(fh.read())
        return h.hexdigest()

    def _nodata(self, path):
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        nd = ds.GetRasterBand(1).GetNoDataValue()
        dt = ds.GetRasterBand(1).DataType
        ds = None
        return nd, dt

    def test_successful_publish_preserves_nodata_255(self):
        final = os.path.join(self.root, "spatial_filtered.tif")
        staging = os.path.join(self.root, "stage.tif")
        self._make_byte_tif(final, value=0)
        sha_old = self._sha(final)
        self._make_byte_tif(staging, value=1)

        def _validate(p):
            nd, dt = self._nodata(p)
            if dt != gdal.GDT_Byte:
                return False, "not byte"
            if int(nd) != BINARY_BYTE_NODATA:
                return False, "bad nodata"
            return True, ""

        ok, err = publish_file_atomic(staging, final, validate_fn=_validate)
        self.assertTrue(ok, err)
        self.assertNotEqual(self._sha(final), sha_old)
        nd, dt = self._nodata(final)
        self.assertEqual(dt, gdal.GDT_Byte)
        self.assertEqual(int(nd), BINARY_BYTE_NODATA)

    def test_failed_validation_leaves_previous(self):
        final = os.path.join(self.root, "spatial_filtered.tif")
        staging = os.path.join(self.root, "stage.tif")
        self._make_byte_tif(final, value=1)
        sha = self._sha(final)
        self._make_byte_tif(staging, value=0)
        ok, err = publish_file_atomic(staging, final, validate_fn=lambda p: (False, "reject"))
        self.assertFalse(ok)
        self.assertEqual(self._sha(final), sha)


if __name__ == "__main__":
    unittest.main()

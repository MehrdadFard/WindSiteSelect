# -*- coding: utf-8 -*-
"""
Phase 1.4.3 unit tests for results_lifecycle helpers.

Evidence type: Mocked/unit tests (no QGIS app, no Processing, no Germany data).
"""
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from results_lifecycle import (
    MANIFEST_SCHEMA_VERSION,
    build_criteria_export_payload,
    build_mca_section,
    build_spatial_section,
    create_run_directories,
    create_staging_directory,
    empty_manifest,
    ensure_results_layout,
    load_and_validate_criteria_file,
    load_manifest,
    manifest_paths_exist,
    publish_file_atomic,
    publish_gpkg_atomic,
    referenced_paths_from_manifest,
    safe_remove_tree,
    save_manifest_atomic,
    update_manifest_after_mca,
    update_manifest_after_spatial,
    validate_criteria_payload,
    validate_manifest_structure,
)


class ResultsLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ws_rl_")
        self.results = os.path.join(self.root, "results")
        os.makedirs(self.results, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_bytes(self, path, data=b"ok"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def _sha(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            h.update(fh.read())
        return h.hexdigest()

    def test_ensure_layout_and_run_dirs(self):
        layout = ensure_results_layout(self.results)
        self.assertTrue(os.path.isdir(layout["runs_dir"]))
        self.assertTrue(os.path.isdir(layout["staging_dir"]))
        dirs = create_run_directories(self.results)
        self.assertTrue(os.path.isdir(dirs["spatial_dir"]))
        self.assertTrue(os.path.isdir(dirs["mca_dir"]))
        self.assertNotEqual(dirs["run_id"], "")

    def test_manifest_atomic_write_and_failed_run_preserves(self):
        layout = ensure_results_layout(self.results)
        man_path = layout["manifest_path"]
        m1 = empty_manifest("runA")
        ok, err = save_manifest_atomic(man_path, m1)
        self.assertTrue(ok, err)
        loaded, err = load_manifest(man_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["run_id"], "runA")
        sha_before = self._sha(man_path)

        # Invalid structure must not replace
        bad = {"schema_version": 999, "run_id": "x"}
        ok, err = save_manifest_atomic(man_path, bad)
        self.assertFalse(ok)
        self.assertEqual(self._sha(man_path), sha_before)

    def test_spatial_success_invalidates_mca(self):
        dirs = create_run_directories(self.results)
        raster = os.path.join(dirs["spatial_dir"], "spatial_filtered.tif")
        polys = os.path.join(dirs["spatial_dir"], "spatial_final_polygons.gpkg")
        self._write_bytes(raster, b"RASTER1")
        self._write_bytes(polys, b"GPKG1")
        spatial = build_spatial_section(self.results, dirs["run_id"], raster, polys)
        existing = empty_manifest("old")
        existing["mca"] = {"run_id": "old_mca"}
        updated = update_manifest_after_spatial(existing, self.results, spatial)
        self.assertIsNone(updated["mca"])
        self.assertEqual(updated["spatial_filter"]["run_id"], dirs["run_id"])
        ok, err = save_manifest_atomic(dirs["manifest_path"], updated)
        self.assertTrue(ok, err)

        # MCA linked to spatial
        mca_grid = os.path.join(dirs["mca_dir"], "mca_grid_with_scores.gpkg")
        self._write_bytes(mca_grid, b"GRID")
        mca = build_mca_section(self.results, "mca1", dirs["run_id"], grid_scores=mca_grid)
        with_mca = update_manifest_after_mca(updated, mca)
        self.assertEqual(with_mca["mca"]["spatial_run_id"], dirs["run_id"])
        ok, err = save_manifest_atomic(dirs["manifest_path"], with_mca)
        self.assertTrue(ok, err)

        # New spatial invalidates MCA again
        dirs2 = create_run_directories(self.results)
        raster2 = os.path.join(dirs2["spatial_dir"], "spatial_filtered.tif")
        polys2 = os.path.join(dirs2["spatial_dir"], "spatial_final_polygons.gpkg")
        self._write_bytes(raster2, b"RASTER2")
        self._write_bytes(polys2, b"GPKG2")
        spatial2 = build_spatial_section(self.results, dirs2["run_id"], raster2, polys2)
        loaded, _ = load_manifest(dirs["manifest_path"])
        updated2 = update_manifest_after_spatial(loaded, self.results, spatial2)
        self.assertIsNone(updated2["mca"])
        # Previous run dir still intact
        self.assertTrue(os.path.isfile(raster))
        self.assertTrue(os.path.isfile(mca_grid))

    def test_publish_file_preserves_previous_on_validation_failure(self):
        final = os.path.join(self.results, "out.bin")
        self._write_bytes(final, b"GOOD")
        sha = self._sha(final)
        staging = os.path.join(self.results, "stage.bin")
        self._write_bytes(staging, b"BAD!")

        def _fail(_p):
            return False, "validation failed"

        ok, err = publish_file_atomic(staging, final, validate_fn=_fail)
        self.assertFalse(ok)
        self.assertEqual(self._sha(final), sha)
        self.assertEqual(open(final, "rb").read(), b"GOOD")

    def test_publish_file_success_and_same_path_rerun(self):
        final = os.path.join(self.results, "out.bin")
        self._write_bytes(final, b"OLD")
        staging = os.path.join(self.results, "stage.bin")
        self._write_bytes(staging, b"NEWDATA")
        ok, err = publish_file_atomic(staging, final)
        self.assertTrue(ok, err)
        self.assertEqual(open(final, "rb").read(), b"NEWDATA")
        # Same-path re-run with new staging
        staging2 = os.path.join(self.results, "stage2.bin")
        self._write_bytes(staging2, b"NEWER")
        ok, err = publish_file_atomic(staging2, final)
        self.assertTrue(ok, err)
        self.assertEqual(open(final, "rb").read(), b"NEWER")

    def test_publish_gpkg_atomic(self):
        import sqlite3

        def _mk_gpkg(path, tag):
            if os.path.isfile(path):
                os.remove(path)
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    "CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, identifier TEXT)"
                )
                conn.execute(
                    "INSERT INTO gpkg_contents VALUES ('layer', 'features', ?)", (tag,)
                )
                conn.execute("CREATE TABLE layer (id INTEGER PRIMARY KEY, VALUE INTEGER)")
                conn.execute("INSERT INTO layer (VALUE) VALUES (1)")
                conn.commit()
            finally:
                conn.close()

        final = os.path.join(self.results, "layer.gpkg")
        _mk_gpkg(final, "OLD")
        sha = self._sha(final)
        staging = os.path.join(self.results, "layer_stage.gpkg")
        _mk_gpkg(staging, "NEW")
        ok, err = publish_gpkg_atomic(staging, final)
        self.assertTrue(ok, err)
        self.assertNotEqual(self._sha(final), sha)
        # Failure leaves previous
        staging2 = os.path.join(self.results, "bad.gpkg")
        self._write_bytes(staging2, b"X")
        ok, err = publish_gpkg_atomic(staging2, final, validate_fn=lambda p: (False, "nope"))
        self.assertFalse(ok)
        # Previous successful publish content unchanged by failed second attempt
        self.assertNotEqual(self._sha(final), sha)

    def test_safe_remove_tree_protects_manifest_paths(self):
        dirs = create_run_directories(self.results)
        protected_file = os.path.join(dirs["spatial_dir"], "spatial_filtered.tif")
        self._write_bytes(protected_file, b"KEEP")
        staging = create_staging_directory(self.results, kind="tmp")
        self._write_bytes(os.path.join(staging, "x.bin"), b"tmp")
        ok, msg = safe_remove_tree(dirs["run_root"], protected_paths=[protected_file])
        self.assertFalse(ok)
        self.assertTrue(os.path.isfile(protected_file))
        ok, msg = safe_remove_tree(staging, protected_paths=[protected_file])
        self.assertTrue(ok, msg)
        self.assertFalse(os.path.isdir(staging))

    def test_manifest_missing_referenced_file(self):
        dirs = create_run_directories(self.results)
        raster = os.path.join(dirs["spatial_dir"], "spatial_filtered.tif")
        polys = os.path.join(dirs["spatial_dir"], "spatial_final_polygons.gpkg")
        self._write_bytes(raster, b"R")
        # polys intentionally missing
        spatial = build_spatial_section(self.results, dirs["run_id"], raster, polys)
        man = update_manifest_after_spatial(None, self.results, spatial)
        ok, missing = manifest_paths_exist(man, self.results)
        self.assertFalse(ok)
        self.assertTrue(any("spatial_final" in str(m) or m.endswith(".gpkg") for m in missing))

    def test_invalid_manifest_json(self):
        path = os.path.join(self.results, "current_run.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        data, err = load_manifest(path)
        self.assertIsNone(data)
        self.assertIn("JSON", err)

    def test_criteria_export_import_validation(self):
        payload = build_criteria_export_payload([
            {"layer_name": "Wind", "weight": 40.0, "role": "Beneficial", "include": True, "layer_path": None},
            {"layer_name": "Depth", "weight": 60.0, "role": "Penalizing", "include": True, "layer_path": None},
        ])
        ok, err, norm = validate_criteria_payload(payload)
        self.assertTrue(ok, err)
        path = os.path.join(self.results, "criteria.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(norm, fh)
        ok, err, loaded = load_and_validate_criteria_file(path)
        self.assertTrue(ok, err)
        self.assertEqual(len(loaded["criteria"]), 2)

        # Malformed
        bad = os.path.join(self.results, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("[]")
        ok, err, _ = load_and_validate_criteria_file(bad)
        self.assertFalse(ok)

        # Unsupported schema
        ok, err, _ = validate_criteria_payload({"schema_version": 99, "criteria": [{"layer_name": "A", "weight": 1}]})
        self.assertFalse(ok)

        # Non-finite weight
        ok, err, _ = validate_criteria_payload({
            "schema_version": 1,
            "criteria": [{"layer_name": "A", "weight": float("nan"), "role": "Beneficial"}],
        })
        self.assertFalse(ok)

    def test_referenced_paths_never_cleaned(self):
        dirs = create_run_directories(self.results)
        raster = os.path.join(dirs["spatial_dir"], "spatial_filtered.tif")
        polys = os.path.join(dirs["spatial_dir"], "spatial_final_polygons.gpkg")
        self._write_bytes(raster, b"R")
        self._write_bytes(polys, b"P")
        spatial = build_spatial_section(self.results, dirs["run_id"], raster, polys)
        man = update_manifest_after_spatial(None, self.results, spatial)
        refs = referenced_paths_from_manifest(man, self.results)
        self.assertTrue(any(os.path.normcase(r) == os.path.normcase(raster) for r in refs))


if __name__ == "__main__":
    unittest.main()

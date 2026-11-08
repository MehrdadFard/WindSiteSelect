# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Phase 1.4.3 – durable results root, current-run manifest, and safe publication helpers.

Pure-Python helpers (no QGIS imports) so unit tests can run without a QGIS app.
Plugin code in wind_suitability.py wraps these with GDAL/QGIS validation.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

CURRENT_RUN_MANIFEST_NAME = "current_run.json"
MANIFEST_SCHEMA_VERSION = 1
CRITERIA_SCHEMA_VERSION = 1
RUNS_SUBDIR = "runs"
SPATIAL_SUBDIR = "spatial"
MCA_SUBDIR = "mca"
TEMP_SUBDIR = "temp"
STAGING_SUBDIR = "staging"

SPATIAL_FILTERED_TIF = "spatial_filtered.tif"
SPATIAL_POLYGONS_GPKG = "spatial_final_polygons.gpkg"
MERGED_EXCLUDE_MASK_TIF = "merged_exclude_mask.tif"
INCLUDE_MASK_TIF = "include_mask.tif"
MCA_GRID_SCORES_FILENAME = "mca_grid_with_scores.gpkg"
MCA_SUITABILITY_MAP_FILENAME = "mca_suitability_map.gpkg"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "{}_{}_{}".format(prefix, stamp, uuid.uuid4().hex[:8])


def normalize_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return os.path.normpath(os.path.abspath(str(path).replace("/", os.sep)))


def path_is_under_root(root: str, path: Optional[str]) -> bool:
    """True when normalized path is the root or a descendant (case-aware on Windows)."""
    root_n = normalize_path(root)
    path_n = normalize_path(path)
    if not root_n or not path_n:
        return False
    root_case = os.path.normcase(root_n)
    path_case = os.path.normcase(path_n)
    if path_case == root_case:
        return True
    prefix = root_case if root_case.endswith(os.sep) else root_case + os.sep
    return path_case.startswith(prefix)


def path_rel_to_root(root: str, path: Optional[str]) -> Optional[str]:
    """
    Store path relative to results root when contained; otherwise None.
    Does not embed absolute external paths into manifests.
    """
    if not path:
        return None
    root_n = normalize_path(root)
    path_n = normalize_path(path)
    if not root_n or not path_n:
        return None
    if not path_is_under_root(root_n, path_n):
        return None
    try:
        rel = os.path.relpath(path_n, root_n)
        if rel.startswith("..") or os.path.isabs(rel):
            return None
        return rel.replace("\\", "/")
    except Exception:
        return None


def path_abs_from_root(
    root: str,
    path: Optional[str],
    *,
    confine: bool = True,
) -> Optional[str]:
    """
    Resolve a manifest-owned path under results root.

    When confine=True (default for manifest paths):
    - Reject absolute paths outside the results root.
    - Reject relative paths that escape via '..' or similar.
    When confine=False, absolute paths are returned normalized (for rare non-manifest uses).
    """
    if not path:
        return None
    root_n = normalize_path(root)
    if not root_n:
        return None

    raw = str(path).replace("/", os.sep)
    if os.path.isabs(path) or (len(raw) >= 2 and raw[1] == ":"):
        abs_p = normalize_path(path)
        if confine and not path_is_under_root(root_n, abs_p):
            return None
        return abs_p

    # Reject explicit traversal segments before join
    parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        if confine:
            return None

    joined = normalize_path(os.path.join(root_n, raw))
    if confine and not path_is_under_root(root_n, joined):
        return None
    return joined


def empty_manifest(run_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id or "",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "spatial_filter": None,
        "mca": None,
    }


def validate_manifest_structure(data: Any) -> Tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Manifest root must be an object"
    version = data.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION:
        return False, "Unsupported manifest schema_version: {!r}".format(version)
    if "run_id" not in data:
        return False, "Manifest missing run_id"
    sf = data.get("spatial_filter")
    if sf is not None and not isinstance(sf, dict):
        return False, "spatial_filter must be an object or null"
    mca = data.get("mca")
    if mca is not None and not isinstance(mca, dict):
        return False, "mca must be an object or null"
    return True, ""


def load_manifest(path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    path_n = normalize_path(path)
    if not path_n or not os.path.isfile(path_n):
        return None, "Manifest file missing"
    try:
        with open(path_n, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return None, "Cannot read manifest JSON: {}".format(exc)
    ok, err = validate_manifest_structure(data)
    if not ok:
        return None, err
    return data, ""


def write_json_atomic(path: str, data: Any) -> Tuple[bool, str]:
    """Write JSON via sibling temp file + os.replace. Does not delete destination first."""
    path_n = normalize_path(path)
    if not path_n:
        return False, "Destination path is empty"
    dest_dir = os.path.dirname(path_n)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as exc:
        return False, "Cannot create directory {}: {}".format(dest_dir, exc)

    fd, tmp_path = tempfile.mkstemp(
        prefix=".ws_manifest_",
        suffix=".json.tmp",
        dir=dest_dir,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        # Validate staging JSON before replace
        with open(tmp_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        ok, err = validate_manifest_structure(loaded) if isinstance(data, dict) and "schema_version" in data else (True, "")
        if not ok:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False, err
        os.replace(tmp_path, path_n)
        return True, ""
    except Exception as exc:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False, "Atomic JSON write failed: {}".format(exc)


def save_manifest_atomic(path: str, data: Dict[str, Any]) -> Tuple[bool, str]:
    ok, err = validate_manifest_structure(data)
    if not ok:
        return False, err
    payload = dict(data)
    payload["updated_at"] = utc_now_iso()
    return write_json_atomic(path, payload)


def ensure_results_layout(results_root: str) -> Dict[str, str]:
    """
    Ensure durable layout under the plugin results directory:
      results/
        current_run.json
        runs/
        staging/
        (legacy flat files may still exist)
    Parent output_dir/temp remains the intermediate temp root.
    """
    root = normalize_path(results_root)
    if not root:
        raise ValueError("results_root is empty")
    runs = os.path.join(root, RUNS_SUBDIR)
    staging = os.path.join(root, STAGING_SUBDIR)
    os.makedirs(runs, exist_ok=True)
    os.makedirs(staging, exist_ok=True)
    return {
        "results_root": root,
        "runs_dir": normalize_path(runs),
        "staging_dir": normalize_path(staging),
        "manifest_path": normalize_path(os.path.join(root, CURRENT_RUN_MANIFEST_NAME)),
    }


def create_run_directories(results_root: str, run_id: Optional[str] = None) -> Dict[str, str]:
    layout = ensure_results_layout(results_root)
    rid = run_id or new_run_id()
    run_root = os.path.join(layout["runs_dir"], rid)
    spatial = os.path.join(run_root, SPATIAL_SUBDIR)
    mca = os.path.join(run_root, MCA_SUBDIR)
    os.makedirs(spatial, exist_ok=True)
    os.makedirs(mca, exist_ok=True)
    return {
        "run_id": rid,
        "run_root": normalize_path(run_root),
        "spatial_dir": normalize_path(spatial),
        "mca_dir": normalize_path(mca),
        "manifest_path": layout["manifest_path"],
        "results_root": layout["results_root"],
        "staging_dir": layout["staging_dir"],
    }


def create_staging_directory(results_root: str, kind: str = "run") -> str:
    layout = ensure_results_layout(results_root)
    path = os.path.join(layout["staging_dir"], "{}_{}".format(kind, uuid.uuid4().hex[:12]))
    os.makedirs(path, exist_ok=True)
    return normalize_path(path)


def safe_remove_tree(path: Optional[str], protected_paths: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Remove a directory tree only if it does not contain any protected paths.
    Never raises; returns (ok, message).
    """
    path_n = normalize_path(path)
    if not path_n or not os.path.isdir(path_n):
        return True, ""
    protected = [normalize_path(p) for p in (protected_paths or []) if p]
    path_case = os.path.normcase(path_n)
    for prot in protected:
        if not prot:
            continue
        prot_case = os.path.normcase(prot)
        if prot_case == path_case or prot_case.startswith(path_case + os.sep):
            return False, "Refusing to delete directory containing protected path: {}".format(prot)
    try:
        shutil.rmtree(path_n)
        return True, ""
    except Exception as exc:
        return False, "Could not remove staging directory (left for later cleanup): {}".format(exc)


def gpkg_sidecar_paths(gpkg_path: str) -> List[str]:
    base = normalize_path(gpkg_path) or ""
    return [base + suffix for suffix in ("-wal", "-shm", "-journal")]


def close_path_handles_best_effort(path: Optional[str]) -> None:
    """Placeholder for plugin to override via GDAL/QGIS handle release before replace."""
    return None


def publish_file_atomic(
    staging_path: str,
    final_path: str,
    validate_fn: Optional[Callable[[str], Tuple[bool, str]]] = None,
) -> Tuple[bool, str]:
    """
    Validate staging file, then os.replace onto final_path.
    Does not delete final_path before a successful replace.
    Cross-volume: copy to sibling staging then replace.
    """
    src = normalize_path(staging_path)
    dst = normalize_path(final_path)
    if not src or not os.path.isfile(src):
        return False, "Staging file missing: {}".format(staging_path)
    if not dst:
        return False, "Final path is empty"
    try:
        if os.path.getsize(src) <= 0:
            return False, "Staging file is empty: {}".format(src)
    except OSError as exc:
        return False, "Cannot stat staging file: {}".format(exc)

    if validate_fn is not None:
        ok, err = validate_fn(src)
        if not ok:
            return False, err or "Staging validation failed"

    dest_dir = os.path.dirname(dst)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as exc:
        return False, "Cannot create destination directory: {}".format(exc)

    abs_src = os.path.normcase(os.path.abspath(src))
    abs_dst = os.path.normcase(os.path.abspath(dst))
    if abs_src == abs_dst:
        return True, ""

    replace_src = src
    staging_copy = None
    try:
        # Prefer same-directory staging for atomic replace across volumes
        same_dir = os.path.normcase(os.path.dirname(abs_src)) == os.path.normcase(os.path.dirname(abs_dst))
        if not same_dir:
            staging_copy = normalize_path(
                os.path.join(dest_dir, ".ws_pub_{}{}".format(uuid.uuid4().hex[:8], os.path.splitext(dst)[1]))
            )
            shutil.copy2(src, staging_copy)
            if validate_fn is not None:
                ok, err = validate_fn(staging_copy)
                if not ok:
                    try:
                        os.remove(staging_copy)
                    except OSError:
                        pass
                    return False, err or "Copied staging validation failed"
            replace_src = staging_copy

        os.replace(replace_src, dst)
        staging_copy = None  # consumed by replace
        return True, ""
    except PermissionError as exc:
        return False, (
            "Destination locked (close the layer/file and retry). "
            "Previous output left unchanged: {}\n{}"
        ).format(dst, exc)
    except Exception as exc:
        return False, "Publication failed (previous output left unchanged): {}".format(exc)
    finally:
        if staging_copy and os.path.isfile(staging_copy):
            try:
                os.remove(staging_copy)
            except OSError:
                pass


def gpkg_destination_sidecars_present(gpkg_path: str) -> List[str]:
    """Return existing destination SQLite sidecars (-wal/-shm/-journal)."""
    found = []
    for side in gpkg_sidecar_paths(gpkg_path):
        if side and os.path.isfile(side):
            found.append(side)
    return found


def checkpoint_sqlite_wal(db_path: str) -> Tuple[bool, str]:
    """
    Checkpoint and truncate WAL for a SQLite/GPKG file after writers are closed.
    Does not delete -wal/-shm blindly while connections may be open.
    """
    path_n = normalize_path(db_path)
    if not path_n or not os.path.isfile(path_n):
        return False, "Database missing for WAL checkpoint"
    try:
        import sqlite3
    except ImportError:
        return False, "sqlite3 module unavailable"
    try:
        conn = sqlite3.connect(path_n, timeout=5.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.commit()
        finally:
            conn.close()
        # After truncate, sidecars should be gone or empty; do not force-delete if still present
        remaining = gpkg_destination_sidecars_present(path_n)
        if remaining:
            return False, "WAL sidecars remain after checkpoint: {}".format(
                ", ".join(remaining)
            )
        return True, ""
    except Exception as exc:
        return False, "SQLite WAL checkpoint failed: {}".format(exc)


def validate_gpkg_sqlite(
    path: str,
    expected_layers: Optional[List[str]] = None,
    min_features: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Validate a GeoPackage via sqlite3 (readable + integrity + optional layer names).
    Does not require QGIS. expected_layers match gpkg_contents.table_name when provided.
    """
    path_n = normalize_path(path)
    if not path_n or not os.path.isfile(path_n):
        return False, "GPKG missing: {}".format(path)
    try:
        if os.path.getsize(path_n) <= 0:
            return False, "GPKG empty: {}".format(path_n)
    except OSError as exc:
        return False, str(exc)

    # Refuse to treat an uncheckpointed WAL-only state as a complete staging product
    wal = path_n + "-wal"
    if os.path.isfile(wal):
        ok_cp, err_cp = checkpoint_sqlite_wal(path_n)
        if not ok_cp:
            return False, "Staged GPKG has unresolved WAL: {}".format(err_cp)

    try:
        import sqlite3
        conn = sqlite3.connect(path_n, timeout=5.0)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                return False, "SQLite integrity_check failed: {}".format(row)
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            if "gpkg_contents" not in tables:
                return False, "Not a GeoPackage (missing gpkg_contents)"
            contents = [
                r[0]
                for r in conn.execute("SELECT table_name FROM gpkg_contents").fetchall()
            ]
            if expected_layers:
                missing = [n for n in expected_layers if n not in contents]
                if missing:
                    return False, "Missing gpkg_contents layers: {}".format(
                        ", ".join(missing)
                    )
            if min_features is not None and contents:
                # Count features from first expected layer or first contents table
                layer = (expected_layers[0] if expected_layers else contents[0])
                if layer in tables:
                    cnt = conn.execute(
                        'SELECT COUNT(*) FROM "{}"'.format(layer.replace('"', '""'))
                    ).fetchone()[0]
                    if int(cnt) < int(min_features):
                        return False, "Layer {} feature count {} < {}".format(
                            layer, cnt, min_features
                        )
        finally:
            conn.close()
    except Exception as exc:
        return False, "GPKG sqlite validation failed: {}".format(exc)
    return True, ""


def publish_gpkg_atomic(
    staging_path: str,
    final_path: str,
    validate_fn: Optional[Callable[[str], Tuple[bool, str]]] = None,
    expected_layers: Optional[List[str]] = None,
    min_features: Optional[int] = None,
    allow_destination_sidecars: bool = False,
) -> Tuple[bool, str]:
    """
    Publish a GPKG after WAL checkpoint + sqlite validation of staging.

    Never deletes the destination before a successful os.replace.
    Never deletes destination -wal/-shm. If destination sidecars exist and
    allow_destination_sidecars is False, abort (previous main + sidecars preserved).
    """
    staging = normalize_path(staging_path)
    final = normalize_path(final_path)
    if not staging or not final:
        return False, "GPKG publish paths are empty"

    # Checkpoint / validate staging (do not blindly delete staging WAL)
    ok_cp, err_cp = checkpoint_sqlite_wal(staging)
    if not ok_cp and os.path.isfile(staging + "-wal"):
        return False, err_cp
    # Even without WAL, run structural validation
    ok_v, err_v = validate_gpkg_sqlite(
        staging, expected_layers=expected_layers, min_features=min_features
    )
    if not ok_v:
        return False, err_v
    if validate_fn is not None:
        ok_u, err_u = validate_fn(staging)
        if not ok_u:
            return False, err_u or "Staged GPKG user validation failed"

    if os.path.isfile(final) and not allow_destination_sidecars:
        dest_sides = gpkg_destination_sidecars_present(final)
        if dest_sides:
            return False, (
                "Destination GPKG has unresolved SQLite sidecars "
                "(close layers/connections and retry; previous output left unchanged):\n{}"
            ).format("\n".join(dest_sides))

    ok, err = publish_file_atomic(staging, final, validate_fn=None)
    if not ok:
        return ok, err

    # Only remove staging sidecars after main file was consumed/replaced
    for side in gpkg_sidecar_paths(staging):
        try:
            if os.path.isfile(side):
                os.remove(side)
        except OSError:
            pass
    return True, ""


def resolve_authoritative_spatial_paths(
    results_root: str,
    session_raster: Optional[str] = None,
    session_polygons: Optional[str] = None,
    manifest: Optional[Dict[str, Any]] = None,
    alias_raster_name: str = SPATIAL_FILTERED_TIF,
    alias_polygons_name: str = SPATIAL_POLYGONS_GPKG,
) -> Dict[str, Any]:
    """
    Pure resolution of current spatial raster/polygons (no QGIS).

    Order: valid session file → confined manifest path → logged alias fallback.
    Never returns a prospect-directory candidate.
    Rejects mixing a canonical runs/ raster with a flat alias polygon.
    """
    root = normalize_path(results_root)
    out: Dict[str, Any] = {
        "run_id": None,
        "raster": None,
        "polygons": None,
        "source": None,
        "alias_used": False,
        "rejected_stale_alias_polygons": False,
        "notes": [],
    }
    if not root:
        return out

    sr = normalize_path(session_raster) if session_raster else None
    sp = normalize_path(session_polygons) if session_polygons else None
    if sr and os.path.isfile(sr):
        out["raster"] = sr
        out["source"] = "session"
    if sp and os.path.isfile(sp):
        out["polygons"] = sp
        out["source"] = out["source"] or "session"

    sf = (manifest or {}).get("spatial_filter") if isinstance(manifest, dict) else None
    if isinstance(sf, dict):
        out["run_id"] = sf.get("run_id") or (manifest or {}).get("run_id")
        mr = path_abs_from_root(root, sf.get("raster_output"), confine=True)
        mp = path_abs_from_root(root, sf.get("polygons_output"), confine=True)
        if mr and os.path.isfile(mr):
            if not out["raster"]:
                out["raster"] = mr
                out["source"] = "manifest"
        if mp and os.path.isfile(mp):
            if not out["polygons"]:
                out["polygons"] = mp
                out["source"] = out["source"] or "manifest"
            elif out["raster"] and mr:
                if os.path.normcase(os.path.dirname(out["raster"])) == os.path.normcase(
                    os.path.dirname(mr)
                ):
                    out["polygons"] = mp

    def _under_runs(path: Optional[str]) -> bool:
        if not path:
            return False
        return (os.sep + "runs" + os.sep) in (os.path.normcase(path) + os.sep)

    alias_r = normalize_path(os.path.join(root, alias_raster_name))
    alias_p = normalize_path(os.path.join(root, alias_polygons_name))
    if not out["raster"] and alias_r and os.path.isfile(alias_r):
        out["raster"] = alias_r
        out["source"] = "alias"
        out["alias_used"] = True
        out["notes"].append("alias_raster")
    if not out["polygons"] and alias_p and os.path.isfile(alias_p):
        if _under_runs(out.get("raster")):
            # Never pair a canonical runs/ raster with a flat alias polygon.
            out["rejected_stale_alias_polygons"] = True
            out["notes"].append("rejected_stale_alias_polygons")
        else:
            out["polygons"] = alias_p
            out["alias_used"] = True
            out["notes"].append("alias_polygons")
            out["source"] = out["source"] or "alias"

    # Final same-directory consistency: drop polygons that don't match runs/ raster dir
    if out["raster"] and out["polygons"]:
        rdir = os.path.normcase(os.path.dirname(out["raster"]))
        pdir = os.path.normcase(os.path.dirname(out["polygons"]))
        if rdir != pdir and _under_runs(out["raster"]) and not _under_runs(out["polygons"]):
            out["polygons"] = None
            out["rejected_stale_alias_polygons"] = True
            out["notes"].append("rejected_mismatched_polygons")

    return out


def referenced_paths_from_manifest(manifest: Dict[str, Any], results_root: str) -> List[str]:
    """Absolute paths referenced by the current manifest (must never be cleaned as temp)."""
    out: List[str] = []
    sf = manifest.get("spatial_filter") or {}
    mca = manifest.get("mca") or {}
    for key in ("raster_output", "polygons_output", "exclude_mask", "include_mask"):
        p = path_abs_from_root(results_root, sf.get(key))
        if p:
            out.append(p)
    for key in ("grid_scores", "suitability_map", "score_raster", "clipped_polygons"):
        p = path_abs_from_root(results_root, mca.get(key))
        if p:
            out.append(p)
    for extra in mca.get("extra_outputs") or []:
        p = path_abs_from_root(results_root, extra)
        if p:
            out.append(p)
    return out


def build_spatial_section(
    results_root: str,
    run_id: str,
    raster_path: str,
    polygons_path: str,
    exclude_mask: Optional[str] = None,
    include_mask: Optional[str] = None,
    input_refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "input_refs": input_refs or {},
        "raster_output": path_rel_to_root(results_root, raster_path),
        "polygons_output": path_rel_to_root(results_root, polygons_path),
        "exclude_mask": path_rel_to_root(results_root, exclude_mask) if exclude_mask else None,
        "include_mask": path_rel_to_root(results_root, include_mask) if include_mask else None,
    }


def build_mca_section(
    results_root: str,
    run_id: str,
    spatial_run_id: Optional[str],
    grid_scores: Optional[str] = None,
    suitability_map: Optional[str] = None,
    criteria_ref: Optional[str] = None,
    extra_outputs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": utc_now_iso(),
        "spatial_run_id": spatial_run_id,
        "grid_scores": path_rel_to_root(results_root, grid_scores) if grid_scores else None,
        "suitability_map": path_rel_to_root(results_root, suitability_map) if suitability_map else None,
        "criteria_configuration": criteria_ref,
        "extra_outputs": [
            path_rel_to_root(results_root, p) for p in (extra_outputs or []) if p
        ],
    }


def update_manifest_after_spatial(
    existing: Optional[Dict[str, Any]],
    results_root: str,
    spatial_section: Dict[str, Any],
) -> Dict[str, Any]:
    """Successful spatial run becomes current; MCA is invalidated as current."""
    base = dict(existing) if existing else empty_manifest(spatial_section.get("run_id"))
    base["schema_version"] = MANIFEST_SCHEMA_VERSION
    base["run_id"] = spatial_section.get("run_id") or base.get("run_id") or ""
    if not base.get("created_at"):
        base["created_at"] = utc_now_iso()
    base["spatial_filter"] = spatial_section
    base["mca"] = None  # invalidate previous MCA as current
    return base


def update_manifest_after_mca(
    existing: Optional[Dict[str, Any]],
    mca_section: Dict[str, Any],
) -> Dict[str, Any]:
    base = dict(existing) if existing else empty_manifest(mca_section.get("run_id"))
    base["schema_version"] = MANIFEST_SCHEMA_VERSION
    if not base.get("run_id"):
        base["run_id"] = mca_section.get("spatial_run_id") or mca_section.get("run_id") or ""
    if not base.get("created_at"):
        base["created_at"] = utc_now_iso()
    base["mca"] = mca_section
    return base


def manifest_paths_exist(manifest: Dict[str, Any], results_root: str) -> Tuple[bool, List[str]]:
    """Return (all_required_exist, missing_list) for current spatial (+ MCA if present)."""
    missing: List[str] = []
    sf = manifest.get("spatial_filter")
    if isinstance(sf, dict):
        for key in ("raster_output", "polygons_output"):
            rel = sf.get(key)
            if not rel:
                missing.append(key)
                continue
            abs_p = path_abs_from_root(results_root, rel)
            if not abs_p or not os.path.exists(abs_p):
                missing.append(abs_p or key)
    mca = manifest.get("mca")
    if isinstance(mca, dict):
        for key in ("grid_scores", "suitability_map"):
            rel = mca.get(key)
            if not rel:
                continue
            abs_p = path_abs_from_root(results_root, rel)
            if abs_p and not os.path.exists(abs_p):
                missing.append(abs_p)
    return (len(missing) == 0), missing


# ---------------------------------------------------------------------------
# MCA criteria JSON (export/import)
# ---------------------------------------------------------------------------

def build_criteria_export_payload(criteria: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    clean_criteria = []
    for c in criteria:
        item = {
            "layer_name": c.get("layer_name"),
            "weight": c.get("weight"),
            "role": c.get("role"),
            "include": c.get("include"),
            "save": c.get("save", True),
            "layer_id": c.get("layer_id"),
            "layer_path": c.get("layer_path"),
        }
        if c.get("crs"):
            item["crs"] = c["crs"]
        clean_criteria.append(item)
    return {
        "schema_version": CRITERIA_SCHEMA_VERSION,
        "metadata": metadata or {
            "export_timestamp": utc_now_iso(),
            "total_criteria": len(clean_criteria),
            "plugin_version": "Phase 1.4.3",
        },
        "settings": {
            "apply_on_prospect_only": False,
            "use_continuous_criteria": False,
        },
        "criteria": clean_criteria,
    }


def validate_criteria_payload(data: Any) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Validate imported criteria JSON without mutating UI state.
    Returns (ok, error, normalized_payload).
    """
    if not isinstance(data, dict):
        return False, "Criteria JSON root must be an object", None
    version = data.get("schema_version", 1)  # accept legacy exports without version as v1
    try:
        version = int(version)
    except (TypeError, ValueError):
        return False, "Invalid schema_version", None
    if version != CRITERIA_SCHEMA_VERSION:
        return False, "Unsupported criteria schema_version: {}".format(version), None
    criteria = data.get("criteria")
    if not isinstance(criteria, list):
        return False, "criteria must be a list", None
    if not criteria:
        return False, "criteria list is empty", None

    normalized = []
    for i, c in enumerate(criteria):
        if not isinstance(c, dict):
            return False, "criteria[{}] must be an object".format(i), None
        name = c.get("layer_name")
        if not name or not isinstance(name, str):
            return False, "criteria[{}] missing layer_name".format(i), None
        try:
            weight = float(c.get("weight"))
        except (TypeError, ValueError):
            return False, "criteria[{}] has invalid weight".format(i), None
        if not (weight == weight) or weight in (float("inf"), float("-inf")):  # NaN/inf
            return False, "criteria[{}] weight must be a finite number".format(i), None
        if weight < 0:
            return False, "criteria[{}] weight must be >= 0".format(i), None
        role = c.get("role", "Beneficial")
        if not isinstance(role, str) or not role.strip():
            return False, "criteria[{}] has invalid role".format(i), None
        # Accept Beneficial/Penalizing and legacy Benefit/Cost aliases
        role_l = role.lower()
        if not (
            role_l.startswith("b")
            or role_l.startswith("p")
            or role_l.startswith("c")
            or "benefit" in role_l
            or "penal" in role_l
            or "cost" in role_l
        ):
            return False, "criteria[{}] has unsupported role {!r}".format(i, role), None
        include = c.get("include", True)
        if not isinstance(include, bool):
            include = bool(include)
        layer_path = c.get("layer_path")
        if layer_path is not None and not isinstance(layer_path, str):
            return False, "criteria[{}] layer_path must be a string".format(i), None
        item = {
            "layer_name": name,
            "weight": weight,
            "role": role,
            "include": include,
            "save": bool(c.get("save", True)),
            "layer_id": c.get("layer_id"),
            "layer_path": layer_path,
        }
        if isinstance(c.get("crs"), dict):
            item["crs"] = c["crs"]
        normalized.append(item)

    payload = {
        "schema_version": CRITERIA_SCHEMA_VERSION,
        "metadata": data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
        "settings": data.get("settings") if isinstance(data.get("settings"), dict) else {},
        "criteria": normalized,
    }
    return True, "", payload


def load_and_validate_criteria_file(path: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    path_n = normalize_path(path)
    if not path_n or not os.path.isfile(path_n):
        return False, "Criteria file not found", None
    try:
        with open(path_n, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return False, "Malformed JSON: {}".format(exc), None
    return validate_criteria_payload(data)


def project_settings_key(project_path: Optional[str]) -> Optional[str]:
    """Stable QSettings suffix from a saved QGIS project path, or None if unsaved."""
    if not project_path:
        return None
    norm = normalize_path(project_path)
    if not norm or not norm.lower().endswith(".qgs") and not norm.lower().endswith(".qgz"):
        # Still allow any non-empty saved path
        if not norm:
            return None
    try:
        digest = uuid.uuid5(uuid.NAMESPACE_URL, os.path.normcase(norm)).hex
        return digest
    except Exception:
        return None

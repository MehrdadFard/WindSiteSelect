#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Build a QGIS Plugin Repository candidate ZIP for Wind Site Select.

Produces:
  dist/Wind_Site_Select_<version>.zip
  dist/Wind_Site_Select_<version>.zip.sha256
  dist/Wind_Site_Select_<version>_manifest.txt

The ZIP contains exactly one top-level directory: wind_site_select/

This script is NOT included inside the plugin package.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PACKAGE_ID = "wind_site_select"
DISPLAY_NAME = "Wind Site Select"
REQUIRED_LICENSE = "LICENSE"
REQUIRED_LICENSE_SPDX = "GPL-2.0-or-later"

# Explicit runtime inclusion list (relative to repo root).
RUNTIME_FILES = [
    "__init__.py",
    "metadata.txt",
    "README.md",
    "LICENSE",
    "icon.png",
    "wind_suitability.py",
    "wind_suitability_dialog.py",
    "wind_suitability_dialog_base.ui",
    "results_lifecycle.py",
    "aoi_tools.py",
    "analysis_crs.py",
    "crs_reprojection_helper.py",
    "scoring_raster_helper.py",
    "resources.py",
]

REQUIRED_IN_PACKAGE = [
    "__init__.py",
    "metadata.txt",
    "README.md",
    "LICENSE",
    "wind_suitability.py",
    "wind_suitability_dialog.py",
    "wind_suitability_dialog_base.ui",
    "results_lifecycle.py",
    "resources.py",
    "icon.png",
]

FORBIDDEN_NAME_FRAGMENTS = (
    "__pycache__",
    ".pyc",
    ".pyo",
    ".git",
    "DIFFERENCE_OPERATION_FIX",
    "germany_windspeed",
    "germany_bathymetry",
    "WindSpeed_100m",
    "test_",
    "/test/",
    "\\test\\",
)

QGIS_PLUGIN_SIZE_LIMIT_BYTES = 25 * 1024 * 1024


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_metadata_field(metadata_path: Path, key: str) -> str:
    text = metadata_path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^{}=(.*)$".format(re.escape(key)), text)
    if not match:
        raise SystemExit("metadata.txt: missing {}=".format(key))
    return match.group(1).strip()


def read_metadata_version(metadata_path: Path) -> str:
    version = read_metadata_field(metadata_path, "version")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(
            "metadata.txt version must be MAJOR.MINOR.PATCH (found {!r})".format(version)
        )
    return version


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_source_tree(root: Path) -> list[str]:
    problems: list[str] = []
    for rel in REQUIRED_IN_PACKAGE:
        if not (root / rel).is_file():
            problems.append("Missing required runtime file: {}".format(rel))
    for rel in RUNTIME_FILES:
        if not (root / rel).is_file():
            problems.append("Missing listed runtime file: {}".format(rel))

    license_path = root / REQUIRED_LICENSE
    if not license_path.is_file():
        problems.append("LICENSE is mandatory and was not found at repository root")
    else:
        text = license_path.read_text(encoding="utf-8", errors="replace")
        if "GNU GENERAL PUBLIC LICENSE" not in text or "Version 2, June 1991" not in text:
            problems.append("LICENSE does not appear to contain GPL Version 2 text")

    metadata_path = root / "metadata.txt"
    if metadata_path.is_file():
        try:
            license_meta = read_metadata_field(metadata_path, "license")
            if license_meta != REQUIRED_LICENSE_SPDX:
                problems.append(
                    "metadata.txt license={!r} (expected {!r})".format(
                        license_meta, REQUIRED_LICENSE_SPDX
                    )
                )
            name = read_metadata_field(metadata_path, "name")
            if name != DISPLAY_NAME:
                problems.append(
                    "metadata.txt name={!r} (expected {!r})".format(name, DISPLAY_NAME)
                )
        except SystemExit as exc:
            problems.append(str(exc))
    return problems


def stage_package(root: Path, staging_pkg: Path) -> list[str]:
    if staging_pkg.exists():
        shutil.rmtree(staging_pkg)
    staging_pkg.mkdir(parents=True)

    included: list[str] = []
    for rel in RUNTIME_FILES:
        src = root / rel
        if not src.is_file():
            raise SystemExit("Cannot stage missing required file: {}".format(rel))
        dst = staging_pkg / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        included.append(rel.replace("\\", "/"))
    return sorted(set(included))


def validate_staged(staging_root: Path, staging_pkg: Path, included: list[str]) -> list[str]:
    problems: list[str] = []
    children = [p for p in staging_root.iterdir()]
    if len(children) != 1 or children[0].name != PACKAGE_ID or not children[0].is_dir():
        problems.append(
            "Staging root must contain exactly one directory named {!r}".format(PACKAGE_ID)
        )

    for rel in REQUIRED_IN_PACKAGE:
        if not (staging_pkg / rel).is_file():
            problems.append("Staged package missing required file: {}".format(rel))

    for rel in included:
        lowered = "/" + rel.lower().replace("\\", "/")
        for frag in FORBIDDEN_NAME_FRAGMENTS:
            if frag.lower() in lowered:
                problems.append("Forbidden content included: {}".format(rel))
                break
        if rel.startswith("test/") or rel.startswith("test\\"):
            problems.append("Test path included: {}".format(rel))

    for path in staging_pkg.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(staging_pkg).as_posix()
        if rel.endswith(".pyc") or "__pycache__" in rel.split("/"):
            problems.append("Bytecode/cache included: {}".format(rel))
        if "germany" in rel.lower() or rel.endswith(".tif"):
            problems.append("Unexpected raster/data file included: {}".format(rel))

    return problems


def write_zip(staging_root: Path, zip_path: Path) -> list[str]:
    if zip_path.exists():
        zip_path.unlink()
    archived: list[str] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staging_root.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(staging_root).as_posix()
            zf.write(path, arcname)
            archived.append(arcname)
    return archived


def validate_zip(zip_path: Path, root_license: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if not names:
            return ["ZIP is empty"]
        tops = sorted({n.split("/")[0] for n in names if n})
        if tops != [PACKAGE_ID]:
            problems.append(
                "ZIP top-level entries must be exactly {!r}, found {}".format(
                    PACKAGE_ID, tops
                )
            )
        required = {"{}/{}".format(PACKAGE_ID, r) for r in REQUIRED_IN_PACKAGE}
        missing = sorted(required - set(names))
        if missing:
            problems.append("ZIP missing required members: {}".format(", ".join(missing)))

        license_member = "{}/LICENSE".format(PACKAGE_ID)
        if license_member in names:
            archived_bytes = zf.read(license_member)
            root_bytes = root_license.read_bytes()
            if archived_bytes != root_bytes:
                problems.append("Archived LICENSE is not byte-identical to root LICENSE")
        else:
            problems.append("ZIP missing LICENSE")

        for n in names:
            low = n.lower()
            if "test/" in low or low.endswith(".pyc") or "__pycache__" in low:
                problems.append("ZIP contains forbidden member: {}".format(n))
            if "germany" in low or low.endswith(".tif"):
                problems.append("ZIP contains unexpected data member: {}".format(n))
            if n.startswith("tools/") or "/tools/" in n:
                problems.append("ZIP must not include release builder: {}".format(n))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Wind Site Select release ZIP")
    parser.add_argument(
        "--dist",
        default=None,
        help="Output directory (default: <repo>/dist)",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    dist = Path(args.dist) if args.dist else root / "dist"
    dist.mkdir(parents=True, exist_ok=True)

    metadata_path = root / "metadata.txt"
    version = read_metadata_version(metadata_path)
    print("Building {} {} ({})".format(DISPLAY_NAME, version, PACKAGE_ID))

    problems = validate_source_tree(root)
    if problems:
        print("VALIDATION FAILED:")
        for p in problems:
            print("  - {}".format(p))
        return 1

    staging_root = dist / "_staging_{}".format(PACKAGE_ID)
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_root.mkdir(parents=True)
    staging_pkg = staging_root / PACKAGE_ID

    try:
        included = stage_package(root, staging_pkg)
        problems.extend(validate_staged(staging_root, staging_pkg, included))
        if problems:
            print("VALIDATION FAILED:")
            for p in problems:
                print("  - {}".format(p))
            return 1

        zip_name = "Wind_Site_Select_{}.zip".format(version)
        zip_path = dist / zip_name
        archived = write_zip(staging_root, zip_path)
        zip_problems = validate_zip(zip_path, root / REQUIRED_LICENSE)
        if zip_problems:
            print("ZIP VALIDATION FAILED:")
            for p in zip_problems:
                print("  - {}".format(p))
            return 1

        digest = sha256_file(zip_path)
        size = zip_path.stat().st_size
        sha_path = Path(str(zip_path) + ".sha256")
        sha_path.write_text("{}  {}\n".format(digest, zip_name), encoding="utf-8")

        manifest_path = dist / "Wind_Site_Select_{}_manifest.txt".format(version)
        lines = [
            "Product: {}".format(DISPLAY_NAME),
            "Package-Id: {}".format(PACKAGE_ID),
            "Version: {}".format(version),
            "License: {}".format(REQUIRED_LICENSE_SPDX),
            "Built-UTC: {}".format(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            "Zip: {}".format(zip_name),
            "Size-Bytes: {}".format(size),
            "SHA256: {}".format(digest),
            "License-File-Present: yes",
            "File-Count: {}".format(len(archived)),
            "",
            "Included members:",
        ]
        lines.extend(archived)
        lines.append("")
        manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        print("ZIP: {}".format(zip_path))
        print("Size: {} bytes ({:.2f} MB)".format(size, size / (1024 * 1024)))
        print("SHA256: {}".format(digest))
        print("Files: {}".format(len(archived)))
        print("Manifest: {}".format(manifest_path))
        if size > QGIS_PLUGIN_SIZE_LIMIT_BYTES:
            print(
                "ERROR: ZIP exceeds QGIS plugin size limit of 25 MB "
                "({} bytes)".format(QGIS_PLUGIN_SIZE_LIMIT_BYTES)
            )
            return 2
        print("OK")
        return 0
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

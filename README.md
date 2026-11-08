# Wind Site Select

**GIS-based Wind Energy Site Selection**

A QGIS plugin for wind energy site suitability assessment, spatial filtering, and multi-criteria decision analysis.

Wind Site Select is intended for professional GIS users working on onshore and offshore wind energy site screening. It is a **GIS-based site screening and suitability tool**. It does **not** perform bankable energy-yield calculations, and it does **not** replace detailed engineering, environmental, grid-connection, or permitting studies.

Users must provide appropriate source datasets wherever required. **No Germany raster dataset (or any other regional sample) is automatically selected as a fallback.**

---

## 1. Product overview

Wind Site Select helps analysts:

- Define an area of interest (AOI)
- Screen wind and depth/bathymetry criteria to derive a prospect area
- Apply spatial filters (exclusion / inclusion constraints)
- Run multi-criteria analysis (MCA) with user-defined criteria and weights
- Produce raster and vector suitability outputs and optional tabular reports

Package identifier (QGIS plugin directory / ZIP root): `wind_site_select`
Public display name: **Wind Site Select**

---

## 2. Main capabilities

| Capability | Description |
|---|---|
| AOI definition | Draw or select AOI geometries for analysis |
| Wind screening | Clip / threshold user-supplied wind rasters |
| Depth / bathymetry | Clip / threshold user-supplied DEM or bathymetry rasters |
| Prospect area | Combine wind and depth screens into a prospect mask / polygon |
| Spatial filtering | Exclude and include layers with buffering; produce final suitable mask and polygons |
| MCA | Weighted multi-criteria scoring over a grid within suitable areas |
| Criteria management | Add/remove criteria, edit weights/roles, export/import JSON, project-scoped persistence |
| Outputs | Suitability rasters, polygons (GeoPackage), optional Excel/CSV reports |
| Results lifecycle | Run-scoped outputs under a project `results/` tree with a `current_run.json` manifest |

---

## 3. Installation

### From a release ZIP (recommended)

1. In QGIS: **Plugins → Manage and Install Plugins → Install from ZIP**
2. Select `Wind_Site_Select_<version>.zip`
3. Enable **Wind Site Select** in the Plugin Manager
4. Open via the Plugins menu or toolbar action **Wind Site Select**

The ZIP contains a single top-level folder `wind_site_select/`.

### From source (developers)

Copy or symlink the plugin package directory into your QGIS profile:

`profiles/<profile>/python/plugins/wind_site_select/`

Do not overwrite an existing production installation with a development copy without a backup.

---

## 4. Data requirements

You must supply project-appropriate datasets, for example:

- Wind speed (or related) raster
- DEM / bathymetry raster (where depth screening is used)
- Vector layers for exclusion / inclusion constraints (protected areas, infrastructure, etc.)
- Optional MCA criterion rasters

Supported inputs follow normal QGIS/GDAL raster and vector formats. CRS handling follows the plugin’s analysis-CRS helpers; mismatched CRS layers may be reprojected or rejected depending on the workflow step.

**Important:** empty wind/DEM path fields do **not** load bundled sample Germany rasters. Analysis stops until a valid user path or map layer is provided.

---

## 5. Typical workflow

1. **Create / open a QGIS project** and save it (recommended for MCA criteria persistence).
2. **Define AOI** using the AOI tools in the dialog.
3. **Wind analysis** — select a wind raster, set thresholds, run screening.
4. **Depth analysis** (as needed) — select DEM/bathymetry, set thresholds, run screening.
5. **Prospect area** — combine screens; optionally polygonize.
6. **Spatial filter** — add exclude/include layers, run spatial filtering to obtain the final suitable mask and polygons.
7. **Decision Making** — add raster criteria (Add Layer / Add Raster Criterion), or Load Criteria Setup; set weights and roles. Optionally Save Criteria Setup for reuse.
8. **MCA Evaluation** — generate the analysis grid, then Run MCA Analysis (requires Spatial Filtering outputs).
9. **Review outputs** — rasters, polygons, and optional Excel/CSV report in a user-chosen folder.
10. **Iterate** — re-run spatial or MCA steps as inputs change; the plugin tracks the current run via `results/current_run.json`.

---

## 6. Multi-criteria analysis (MCA)

MCA scores candidate locations using user-defined raster criteria and weights.

### Required order

1. Complete **Prospect Analysis** and **Spatial Filtering** (authoritative suitable mask / polygons for the current run).
2. On **Decision Making**, add criteria and set weights/roles.
3. On **MCA Evaluation**, **generate the analysis grid**, then **Run MCA Analysis**.

If Spatial Filtering has not been completed, MCA will stop with an actionable error asking you to finish Spatial Filtering before aligning criteria and running the analysis. The plugin does not silently substitute an unrelated old raster.

### Adding criteria

| Action | Meaning |
|---|---|
| **Add Layer** | Add a raster already loaded in the current QGIS project as one MCA criterion. |
| **Add Raster Criterion...** | Browse for a raster file and **append** it as a new criterion (does not replace existing rows). |
| **Remove Layer** / **Normalize Weights** | Manage the current table rows. |

### Saving and loading a criteria setup

| Action | Meaning |
|---|---|
| **Save Criteria Setup...** | Write the current criteria names, weights, roles, and Include flags to a JSON file. |
| **Load Criteria Setup...** | Replace the table with a previously saved JSON configuration (validated first). Invalid JSON leaves the current configuration unchanged. |
| **New MCA Analysis** | Clears the current criteria configuration after confirmation. Cancel leaves settings unchanged. |

These are **not** duplicates of Add Raster Criterion: file-add appends one raster; load restores a full saved setup.

Additional notes:

- Criteria can be marked beneficial or penalizing and included/excluded from a run.
- Weights are user-controlled; an explicit normalize action is available (weights are **not** silently rewritten on restore).
- For **saved projects**, criteria/weights are also persisted in QSettings under a project-scoped key (legacy internal namespace retained for compatibility).
- Computed score matrices are **not** restored from settings; re-run MCA to recompute scores.
- MCA operates on the authoritative spatial suitability outputs for the current run (session → manifest → logged legacy alias fallback). Mixing a new-run raster with stale flat alias polygons is rejected.

Optional Excel export (`mca_report.xlsx`) uses **openpyxl** when available; CSV fallback may be used when enabled if Excel writing fails.

---

## 7. Outputs

Typical outputs (names may vary by run layout):

| Output | Role |
|---|---|
| Prospect / spatial filter rasters | Byte masks of screened or final suitable areas |
| `spatial_final_polygons.gpkg` | Vector polygons of suitable areas |
| MCA score / suitability rasters | Continuous or classified suitability surfaces |
| MCA suitability map (GeoPackage) | Vector/grid-related MCA results |
| `mca_report.xlsx` / CSV | Tabular summary when reporting is requested |
| `results/current_run.json` | Manifest of the authoritative current run |

Canonical durable outputs live under the project’s `results/runs/<run_id>/` tree. Flat `results/` alias files may exist for compatibility but are not authoritative when a valid manifest/session path exists.

---

## 8. Dependencies

| Dependency | Role | Provided by |
|---|---|---|
| Python 3 (QGIS-bundled) | Runtime | QGIS |
| PyQGIS / PyQt | UI and GIS API | QGIS |
| GDAL/OGR | Raster/vector I/O | QGIS |
| NumPy | Array processing where used | Typically bundled with QGIS |
| QGIS Processing | Geoprocessing algorithms | QGIS |
| **openpyxl** (optional) | Writes `mca_report.xlsx` (Summary / Detailed / Metadata sheets) | Not bundled with this plugin; not guaranteed in every QGIS install |

**openpyxl** is optional and used only for Excel MCA reporting. If it is not installed in the QGIS Python environment, Excel export fails gracefully and does not prevent plugin load or MCA computation. When CSV export is enabled, a CSV report may still be written. To enable Excel reports, install openpyxl into the same Python environment that QGIS uses (for example via the OSGeo4W / QGIS Python shell: `python -m pip install openpyxl`).

No separate pip install is required for core functionality on a standard QGIS desktop install.

---

## 9. Supported and tested QGIS versions

| Environment | Status |
|---|---|
| Windows + QGIS **4.0.3** | **Verified** (Stable 0.3.1) |
| QGIS 3.44 LTR / other QGIS 3.x | **Not supported** by this Stable release |
| Linux | **Not verified** |
| macOS | **Not verified** |

`metadata.txt` declares `qgisMinimumVersion=4.0` and `qgisMaximumVersion=4.99`. QGIS 3.44 LTR users should not treat 0.3.1 as compatible until a separately verified build exists. Impact: LTR 3.x deployments cannot install this Stable build under the declared minimum without overriding metadata.

---

## 10. Current limitations

- Stable **0.3.1** is verified on **Windows QGIS 4.0.3** only.
- Optional Excel reporting depends on **openpyxl** (not bundled; install into the QGIS Python environment if Excel export is required).
- Interactive workflows assume a desktop QGIS session (not QGIS Server).
- Large rasters and complex MCA grids can be memory- and disk-intensive.
- Legacy internal identifiers (module/class names, QSettings namespace, Qt resource prefix) remain for compatibility and are not the public product name.

---

## 11. Troubleshooting

| Issue | What to check |
|---|---|
| Plugin does not appear | Confirm ZIP top-level folder is `wind_site_select/` and Plugin Manager refresh |
| Import / load error | Check the Python error log; ensure QGIS provides GDAL and Processing |
| Empty wind/DEM path | Provide a valid file or map layer — no automatic sample raster is used |
| MCA criteria not restored | Save the QGIS project first; unsaved projects cannot use project-scoped persistence |
| Stale spatial polygons | Prefer re-running spatial filter; check `results/current_run.json` |
| Excel report missing | Install openpyxl into the QGIS Python environment, or use CSV export |
| Destination GPKG locked | Close layers using the file and retry; previous output is left unchanged |

---

## 12. Issues and support

For bugs and public feature requests, please open a GitHub Issue:

https://github.com/MehrdadFard/WindSiteSelect/issues

When reporting a bug, include:

- QGIS version and OS
- Plugin version from Plugin Manager / `metadata.txt`
- Steps to reproduce
- Relevant Log Messages panel entries (category may still show the legacy tag `WindSuitability`)

Do not send confidential project data unless you intend to share it.

---

## 13. Contact

**Contact:** greensite.ai@gmail.com

You can use this email for:

- General inquiries
- Collaboration proposals
- Custom GIS development requests
- Professional services

For bugs and public feature requests, prefer [GitHub Issues](https://github.com/MehrdadFard/WindSiteSelect/issues) so that discussions remain visible to other users.

Repository: https://github.com/MehrdadFard/WindSiteSelect

---

## 14. Release history

### 0.3.1 – First Stable (2026-03)

- First Stable release (`experimental=False`).
- MCA criteria restore and row-mapping corrections so Decision Making table rows stay aligned after add/remove/load.
- Improved Decision Making workflow: Add Raster Criterion vs Save/Load Criteria Setup, New MCA Analysis confirmation, clearer labels/tooltips.
- Spatial Filtering current-run master reference for MCA; durable `results/` root restore after session/dialog reset so MCA finds `spatial_filtered.tif` from the current spatial run.
- Verified on Windows with QGIS **4.0.3** only. QGIS 3.x (including 3.44 LTR), Linux, and macOS are not claimed as supported.

### 0.3.0 – Public release candidate

- First public packaging as Wind Site Select under package id `wind_site_select`.
- Spatial results lifecycle with authoritative run manifests, MCA criteria persistence, GPKG WAL-safe publication, GPL-2.0-or-later licensing.

---

## 15. License

**License:** [GPL-2.0-or-later](LICENSE) (GNU General Public License version 2 or any later version).

The full license text is in the repository file [`LICENSE`](LICENSE). Wind Site Select is free software: you may redistribute and/or modify it under the terms of the GPL. There is no warranty. See the license text for permissions, conditions, and the disclaimer of warranty.

This open-source license is compatible with the QGIS Official Plugin Repository requirement for GPLv2 or later.

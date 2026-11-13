# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Professional controls

Added:

- **IDW interpolation** (`qgis:idwinterpolation`), next to TIN linear and
  Clough-Toucher. The only extra control is the IDW power (distance
  coefficient), default 2.
- **Extent modes** for point input:
  - bounding box of the usable points;
  - convex hull;
  - convex hull plus a buffer, in the layer's units, with a warning for
    geographic CRSs;
  - boundary polygon;
  - custom extent (`QgsExtentWidget`).

  When part of the area lies outside the points' convex hull, the plugin
  warns. For IDW that warning is marked **IMPORTANT**, because IDW
  extrapolates there.
- **Boundary clipping**:
  - applies to both point and raster input;
  - uses all polygons or only the selected ones;
  - handles multipart polygons;
  - transforms between CRSs with the project's transform context;
  - repairs invalid polygons with `makeValid`, and reports that.

  Contour lines are clipped **exactly** with `native:clip`. Raster input is
  first cropped to the boundary's bounding box (`gdal:cliprasterbyextent`).
  A selected-only boundary with nothing selected is a validation error.
- **Duplicate locations:**
  - equal values only get a warning;
  - materially different values (more than 1e-6 of the value range) get an
    **IMPORTANT** warning with examples;
  - explicit choice: keep the first value (default), average, or stop.
- **Smoothing** with `native:smoothgeometry`:
  - Light (1 iteration, offset 0.25);
  - Medium (2 iterations, 0.25);
  - Custom (1–5 iterations, offset 0.05–0.5);
  - an option to also keep an unsmoothed copy.

  Smoothed layers have "smoothed" in their default name, and the metadata
  records it.
- **Major/minor contours:**
  - "Major contour every N intervals" sets the `is_major` field (1/0);
  - a categorized style draws minor contours thin and major contours thick.
- **Labels** with native QGIS labeling:
  - off, major only (rule-based), or all;
  - decimals 0–6, curved placement on the line, white text buffer;
  - a warning when the decimals cannot show every level.
- **Style presets:** Neutral (black), Topographic (brown), Groundwater (blue).
  These are ordinary QGIS symbology.
- **Output:**
  - contours: a temporary layer (default), or saved to a GeoPackage. Existing
    layers are never overwritten; conflicts get a safe `_2` name and a
    warning. The style is stored in the GeoPackage.
  - surface: not added, a temporary raster, or a GeoTIFF. An existing file
    gets a safe new name.
- **Output attributes:** `value`, `is_major`. Everything else is stored at layer
  level:
  - the metadata abstract;
  - JSON in the `contour_generator/metadata` custom property.

  This includes the input, field, feature mode, method, IDW power, cell size,
  extent mode, boundary, interval and its mode, major frequency, smoothing,
  labels, style, plugin and QGIS versions, warnings and a professional-review
  disclaimer.
- **Summary** section:
  - points: usable/skipped counts, range, method, cell size and extent;
  - raster: band and range;
  - both: interval and approximate level count;
  - errors and warnings are highlighted.

  It is computed by the same planning step the run uses. It refreshes
  automatically for inputs up to 100,000 features or 50 million cells,
  otherwise on request.
- **Progress:** an application-modal progress dialog shows each stage
  (e.g. "Interpolating (IDW) 1/6"), with progress from the Processing
  algorithms and a working **Cancel** button.
- **Error handling:**
  - covers unavailable algorithms, failed steps, invalid or non-overlapping
    boundaries, CRS transformation failures, unwritable or invalid paths,
    name conflicts, invalid smoothing values and unsupported rasters;
  - files and GeoPackage layers written by a failed or cancelled run are removed;
  - the cursor and dialog state are always restored.
- **UI:**
  - reorganised into Input, Interpolation, Extent, Boundary, Contours, Output
    and Summary, inside a scroll area;
  - irrelevant controls are hidden or disabled (interpolation and extent in
    raster mode, IDW power only for IDW, buffer only for the buffered hull,
    custom smoothing values only for Custom, file pickers only when saving).
- New modules: `core/options.py` and `core/report.py` (pure), plus
  `core/extent.py` and `core/output.py`. `clipping`, `smoothing` and
  `styling` are now implemented.
- Tests: 111 unit tests (plain Python).

Changed:

- Automatic intervals for point input are now based on the **data** value
  range, so the summary and the run agree. Linear TIN and IDW never exceed
  that range.
- The output fields are now `value` and `is_major` (the GDAL `ID` field was dropped).

### Core contour engine

Added:

- **Contour generation.** The Generate Contours button now runs the full workflow
  (`core/workflow.py`):
  - **Point input:** read the values (the source layer is only read) → data
    checks → temporary point layer → `qgis:tininterpolation` (linear or
    Clough-Toucher) → `gdal:contour`.
  - **Raster input:** raster checks → `gdal:contour` on the chosen band.
- **Intervals** (`core/intervals.py`):
  - automatic: a 1/2/2.5/5 x 10^n interval aiming for an approximate contour
    count, 10 by default;
  - fixed: any positive interval;
  - levels are multiples of the interval;
  - limit of 1000 levels.
- **Cell size** (`core/grid.py`): automatic (about 500 cells along the longer
  side of the points' extent) or user-set. Limit of 25 million cells.
- **Data checks** (`core/input_validation.py`):
  - **Errors** stop the run:
    - fewer than 3 distinct point locations with values;
    - all points on one line;
    - all values equal;
    - a raster band with no valid cells or one flat value;
    - a raster that isn't file-based;
    - a missing band;
    - an interval giving no levels or too many;
    - a grid that is too large.
  - **Warnings** let it continue:
    - NULL or non-finite values skipped;
    - empty geometries skipped;
    - duplicate locations, keeping the first value and counting conflicts;
    - a geographic or missing CRS;
    - a boundary selected but not applied;
    - no lines produced.
- **Editable output:** contours are copied into a temporary in-memory line
  layer with fields `ID` and `value`. It can be edited and then saved, e.g.
  with *Make Permanent*. The method, parameters and warnings are written to
  the layer's metadata abstract and to the plugin's log tab.
- **Dialog:**
  - interpolation method and cell size (Point input);
  - band (Raster input, a `QgsRasterBandComboBox`);
  - a Contours group (interval mode, approximate count, fixed interval);
  - an Output group (layer name; optionally also add the temporary
    interpolated surface).
- `core.ContourError` for user-facing problems.
- `utils.qgis_helpers.run_algorithm()`: runs a Processing algorithm with a
  clear error if it is unavailable or fails.
- Unit tests for intervals, grid sizing and data checks (69 tests in total, plain Python).

Not included: IDW, clipping, smoothing, styling, groundwater presets, background processing.

### Phase 2: input selection and live validation

Added:

- **Input source** radio buttons, Point layer / Raster. Only the group for the
  selected mode is enabled.
- **Point input**:
  - `QgsMapLayerComboBox`, filtered to point layers;
  - `QgsFieldComboBox`, filtered to numeric fields (Int, LongLong, Double) and
    following the selected layer;
  - a feature-use choice, "All features" / "Selected features only";
  - a live "selected of total" count.
- **Raster input**: `QgsMapLayerComboBox`, filtered to raster layers.
- **Boundary (optional)**: `QgsMapLayerComboBox`, filtered to polygon layers,
  with a "None" entry selected by default. The choice is only remembered.
  No clipping happens.
- **Generate Contours** button with a short status line explaining why it is
  disabled. When enabled and clicked, it runs no processing and shows
  "Inputs are valid. Contour processing will be added in a later phase."
  in a message bar inside the dialog.
- Live re-validation when:
  - the mode, layer, field or feature-use option changes;
  - the selection changes, or features are added or deleted, on the current point layer;
  - a layer is added or removed;
  - the dialog is shown;
  - Generate Contours is clicked.
- `core/input_validation.py`: `is_numeric_field()`, `usable_feature_count()`,
  `point_input_problem()` and `raster_input_problem()`. The last three are plain
  Python with no QGIS import.
- `tests/test_input_validation.py`: 15 unit tests, run with plain Python.
- `ContourDialog.cleanup()`: disconnects from the point layer's signals. The
  plugin calls it before deleting the dialog on unload or reload.

Changed:

- The dialog's placeholder sections were replaced by the real input groups.
  The disabled "Contour settings" placeholder was removed.
- Build status text is now "Phase 2 development build".

Not included: no interpolation, contouring, clipping, smoothing, styling or Processing calls.

### Phase 1: plugin shell

Added:

- One `QAction` ("Contour Generator"), shared by a Plugins-toolbar button and a
  **Plugins ▸ Contour Generator** menu entry.
- Temporary original SVG icon, `contour_generator/icons/contour.svg`.
- Modeless main dialog, laid out in `ui/contour_dialog.ui` and loaded at runtime
  with `qgis.PyQt.uic.loadUiType`. It shows:
  - an introductory line;
  - diagnostics: the running QGIS version (from `Qgis.version()`), the plugin
    version (read from `metadata.txt`) and the build status;
  - disabled placeholder sections "Input source" and "Contour settings";
  - a Close button.
- Single dialog instance. Triggering the action again brings the open dialog to the front.
- `unload()` closes and deletes the dialog, removes the menu entry and toolbar
  button, disconnects the action's signal and deletes the action.
- A dialog-creation failure is reported in the QGIS message bar, with the full
  traceback in the Log Messages panel under a "Contour Generator" tab.
- `utils/qgis_helpers.py`: `PLUGIN_NAME`, `log_message()` and `plugin_version()`.

Changed:

- `metadata.txt` `about` and `changelog` text now describe the development build. The version is still 0.0.1.

Not included: no layer selectors, contouring, interpolation or Processing calls.

### Phase 0: repository setup

Added:

- Repository structure with the QGIS plugin in its own `contour_generator/` package.
- Draft `metadata.txt` (version 0.0.1, experimental, QGIS 3.44–4.99, placeholder author and URLs).
- Minimal `classFactory()` and empty plugin class, so the development install can be verified.
- Placeholder modules (docstrings only) for UI, validation, interpolation, contouring,
  clipping, smoothing, styling, interval calculation and QGIS helpers.
- Empty placeholder Qt Designer dialog (`ui/contour_dialog.ui`), not yet used.
- Documentation: README, ARCHITECTURE, DEVELOPMENT, TESTING, CHANGELOG.
- GPL-2.0-or-later license.

Not included: no contour generation, interpolation, Processing calls, GUI actions or tests.

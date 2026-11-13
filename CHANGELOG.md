# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-11-13 (first release candidate)

First public release candidate of **Contour Flow**: point or raster data in,
editable contour lines out. Experimental. Tested on QGIS 3.44.15 LTR.

### Release notes

- **Point contouring:** contours from any numeric field of a point layer
  (all or selected features). Data checks cover NULLs, duplicate locations
  (with an explicit choice for conflicting values), too few or collinear
  points, and the CRS.
- **Raster contouring:** contours from any band of a file-based raster/DEM.
- **Interpolation methods:** QGIS's own TIN Linear, TIN Clough–Tocher and IDW
  (with power), automatic or manual cell size, and extent modes. A warning
  appears when values are extrapolated outside the points' convex hull.
- **Intervals:** an automatic "nice" interval for an approximate contour
  count, or a fixed interval. Automatic major contours on round numbers.
- **Clipping:** exact clipping of contour lines to a boundary polygon in any
  CRS (all or selected polygons; multipart; invalid polygons repaired).
- **Smoothing:** optional Light/Medium/Custom smoothing that never touches the
  source values, with an optional unsmoothed copy.
- **Labels and styles:** native QGIS labels (off, major only, all) and three
  style presets (Neutral, Topographic, Groundwater), all editable.
- **Editable outputs:** temporary layers or GeoPackage layers (never
  overwritten), with fields `value` and `is_major`. Optional interpolated
  surface as a temporary raster or GeoTIFF. All settings are stored in the
  layer metadata.
- **Usability:** a simple default dialog with a collapsed Advanced section,
  plain-language messages, a live summary, progress with Cancel, and cleanup
  of partial outputs.
- **Supported QGIS version:** 3.44 LTR (`qgisMinimumVersion=3.44`,
  `qgisMaximumVersion=3.99`). QGIS 4 is not yet tested.
- **Quality:**
  - 119 unit tests;
  - 20 real-QGIS integration tests;
  - an isolated install test of the release ZIP;
  - fictional sample data with a ready-made project.

Known limitation: processing runs in the QGIS main thread, behind a progress
dialog with Cancel.

### Release readiness: simpler UI, sample data, docs

Changed:

- **Simplified dialog.** The default view shows only Input (source, layer,
  value field, features), Boundary, Contours (interval, count or fixed
  value, labels, style), Output (temporary or GeoPackage), Summary and
  **Generate Contours**. Everything technical moved to a collapsed
  **Advanced settings** section: interpolation method, IDW power, cell size,
  extent, hull buffer, custom extent, duplicate handling, boundary features,
  major frequency, label decimals, smoothing and surface output.
- **Cell size:** an *Automatic cell size* checkbox. The number field is
  editable only when the box is unticked, and starts from the automatic value.
- **Major contours:** *Automatic major contours* (default) puts majors on
  round numbers: every 4 for interval 0.25, every 2 for 0.5, every 5 for 1 or 2.
- **Plain-language guidance:**
  - "Add a point layer with a numeric elevation field, or add an elevation raster."
  - "The selected point layer has no numeric fields available for contouring."
  - "Select one or more point features in QGIS, or switch to All features."

  With only rasters in the project, the dialog starts in Raster mode. The band
  row appears only for multi-band rasters.
- **Concise summary:** usable points, range, method, cell size with units,
  contour interval and estimated levels. Only applicable lines are shown.
- **Tooltips** on technical controls: methods, cell size, extent, smoothing,
  automatic interval.
- Display names: "TIN Linear", "TIN Clough–Tocher" (the spelling was
  previously wrong), "IDW"; labels Off / Major only / All; styles Neutral /
  Topographic / Groundwater.
- **New plugin icon** `icons/contour_flow.svg`, plus a 64 px PNG for
  `metadata.txt`.

Added:

- `sample_data/`: fictional `contour_flow_sample.gpkg` (`sample_wells` with
  `gw_elev`, `ground_elev`, `bedrock_elev`; `site_boundary`),
  `sample_dem.tif`, a ready-made project `contour_flow_sample.qgz`, and a
  README with three tests. `scripts/make_sample_data.py` regenerates it all.
- `docs/images/`: README screenshots rendered by real QGIS
  (`scripts/capture_screenshots.py`).
- `scripts/run_with_qgis.bat`: runs any script with QGIS's Python.
- Integration tests:
  - the dialog's first-run messages, Advanced collapse and dependent controls;
  - the sample-data README tests;
  - a desktop "contour, then reopen project" regression;

  20 in total.

Fixed (found by the new tests):

- **Crash after contouring (desktop-relevant):** algorithms were run through
  `QgsProcessingMultiStepFeedback`. On QGIS 3.44.15 this led to an access
  violation on the next event-loop pass, or when layers were deleted, e.g.
  when opening another project after contouring a DEM. Algorithms now get
  the caller's feedback directly, and the dialog computes overall progress
  itself.
- Fixtures and scripts no longer call `gdal.UseExceptions()`, which crashed
  the QGIS test process.

### Real-QGIS integration testing (QGIS 3.44.15, GDAL 3.13.3)

Added:

- `tests/integration/`: an automated suite that runs the real plugin code
  against real QGIS Processing and GDAL algorithms, headless.
  - `fixtures.py` generates fictional points (on a known plane), WGS84 and
    multipart/invalid boundaries, and a gradient GeoTIFF.
  - `run_qgis_integration_tests.py` holds 17 tests and prints a PASS/FAIL report.
  - `run_qgis_integration_tests.bat` finds QGIS automatically.
- Verified on this installation: all algorithm IDs and parameter names the
  plugin uses (`qgis:tininterpolation`, `qgis:idwinterpolation`,
  `gdal:contour`, `native:clip`, `native:smoothgeometry`,
  `gdal:cliprasterbyextent`, `gdal:cliprasterbymasklayer`). No ID changes were
  needed.
- TESTING.md: three test levels (unit, real-QGIS, short visual smoke test).

Fixed (found by the real-QGIS tests):

- **Cleanup after a failed or cancelled run could leave files behind on
  Windows.** Output files were opened as layers before later steps ran, and
  an open layer locks the file. Now the surface GeoTIFF is opened only at the
  end, styling runs on the in-memory layers, and GeoPackage layers are loaded
  only after every write has succeeded.
- **Contours next to a clip boundary could be missing.** Contours are traced
  between cell centres, so an extent cropped exactly to the boundary lost
  levels in the outer half cell (e.g. level 51 at x = 10.5 m). Interpolation
  grids and raster crops are now padded by two cells around the clip
  polygon, and the exact vector clip removes the padding.
- **GeoPackage output printed a GDAL error** ("unable to open database file")
  after the style was stored in a new file. The loaded layer is now reloaded
  after saving the style.
- GeoPackage styles are saved with `saveStyleToDatabaseV2` when available
  (present in 3.44.15), avoiding a deprecated call.
- A spurious PyQGIS 3.44 deprecation warning from `bandStatistics()` (it
  appears even with the recommended `Qgis.RasterBandStatistic` flags) is
  silenced at that one call.

Confirmed on real QGIS (no code change needed): with only Min/Max requested,
the GDAL provider reports a valid-cell count of 0. The range check already
relied on min/max, so this was handled.

### Renamed to Contour Flow (version 0.0.2)

- The plugin was previously developed as "Contour Generator". It is now
  **Contour Flow**, with Python package and plugin folder `contour_flow`.
  The visible name, menu, toolbar, log tab, dialog title, metadata strings
  and the layer custom-property key (`contour_flow/metadata`) were renamed.
- `ContourGeneratorPlugin` was renamed to `ContourFlowPlugin`, and the main
  module `contour_generator.py` to `contour_flow.py`.
- Version bumped to 0.0.2 (still experimental).
- Suggested repository name: `Contour-Flow-QGIS`. The local folder was not renamed.

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
  - JSON in the `contour_flow/metadata` custom property.

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

- One `QAction` ("Contour Flow"), shared by a Plugins-toolbar button and a
  **Plugins ▸ Contour Flow** menu entry.
- Temporary original SVG icon, `contour_flow/icons/contour.svg`.
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
  traceback in the Log Messages panel under a "Contour Flow" tab.
- `utils/qgis_helpers.py`: `PLUGIN_NAME`, `log_message()` and `plugin_version()`.

Changed:

- `metadata.txt` `about` and `changelog` text now describe the development build. The version is still 0.0.1.

Not included: no layer selectors, contouring, interpolation or Processing calls.

### Phase 0: repository setup

Added:

- Repository structure with the QGIS plugin in its own `contour_flow/` package.
- Draft `metadata.txt` (version 0.0.1, experimental, QGIS 3.44–4.99, placeholder author and URLs).
- Minimal `classFactory()` and empty plugin class, so the development install can be verified.
- Placeholder modules (docstrings only) for UI, validation, interpolation, contouring,
  clipping, smoothing, styling, interval calculation and QGIS helpers.
- Empty placeholder Qt Designer dialog (`ui/contour_dialog.ui`), not yet used.
- Documentation: README, ARCHITECTURE, DEVELOPMENT, TESTING, CHANGELOG.
- GPL-2.0-or-later license.

Not included: no contour generation, interpolation, Processing calls, GUI actions or tests.

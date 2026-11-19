# Architecture

This document describes how Contour Flow is organised and the rules that
keep it maintainable. As of the *Professional controls* milestone, every
module is implemented.

## Repository layout

```
GIS Contour Plugin/                 <- git repository root (suggested repo name: Contour-Flow-QGIS)
├── contour_flow/              <- THE QGIS PLUGIN (only this folder ships to users)
│   ├── __init__.py                 classFactory(): QGIS entry point
│   ├── metadata.txt                plugin metadata read by QGIS and plugins.qgis.org
│   ├── LICENSE                     copy of the GPLv2 text (required inside the plugin ZIP)
│   ├── contour_flow.py        plugin lifecycle: initGui() / unload()
│   ├── icons/contour_flow.svg/.png plugin icon (original artwork; PNG for metadata.txt)
│   ├── ui/
│   │   ├── contour_dialog.py       dialog behaviour: visibility, live checks, summary, run
│   │   └── contour_dialog.ui       Qt Designer layout
│   ├── core/
│   │   ├── __init__.py             ContourError, ContourCancelled
│   │   ├── workflow.py             plan_contours() + run_contour_workflow(): the UI's entry points
│   │   ├── options.py         (P)  option constants, labels, validators, naming helpers
│   │   ├── input_validation.py(P)  live checks, point data checks, duplicate handling
│   │   ├── intervals.py       (P)  nice/fixed intervals, level counts, major classification
│   │   ├── grid.py            (P)  automatic cell size, grid size limit
│   │   ├── report.py          (P)  metadata text/JSON serialization, disclaimer
│   │   ├── groundwater.py     (P)  Groundwater Mode: value parsing, heads, QA checks, flow-vector maths
│   │   ├── flow.py                 GW Flow Direction arrows from the interpolated surface
│   │   ├── interpolation.py        read points, temporary point layer, TIN/IDW
│   │   ├── extent.py               extent modes, hull, buffer, boundary union + CRS transform
│   │   ├── contouring.py           GDAL contour, editable copy with value/is_major
│   │   ├── clipping.py             exact line clip, raster crop, surface mask
│   │   ├── smoothing.py            QGIS Smooth (Chaikin); GW: simplify + densify + Chaikin, validated
│   │   ├── styling.py              major/minor renderer, labels, presets
│   │   └── output.py               GeoPackage writing, existing names, rollback
│   └── utils/
│       └── qgis_helpers.py         plugin name, logging, version, run_algorithm(), result layers
├── tests/                          never shipped
│   ├── test_*.py                   level 1: plain-Python unit tests for the (P) modules
│   └── integration/                level 2: real-QGIS tests (fixtures.py, run_qgis_integration_tests.py/.bat)
├── sample_data/                    fictional sample wells, boundary, DEM and QGIS project
├── scripts/                        sample data, icon, screenshots, packaging (run with QGIS Python)
├── docs/images/                    README screenshots rendered by QGIS
├── README.md, ARCHITECTURE.md, DEVELOPMENT.md, TESTING.md, CHANGELOG.md
├── LICENSE                         GPLv2 text (for GitHub and source distribution)
└── .gitignore
```

**(P)** marks *pure Python*: no `qgis` import, so these modules are
unit-tested with ordinary Python outside QGIS.

### Why the plugin lives in a subfolder

1. **QGIS loads the folder as a Python package.** The folder name becomes the
   import name, so it must be a valid identifier (`contour_flow`).
2. **Clean development link.** Only `contour_flow/` is linked into QGIS,
   so `.git/`, `tests/` and the docs never appear in the QGIS profile.
3. **Clean ZIP.** The release ZIP must contain one top-level plugin folder
   and no development or generated files.

`LICENSE` exists twice, because GitHub expects it at the root and
plugins.qgis.org inside the package.

## Layers and responsibilities

```
QGIS ── classFactory(iface)
 ▼
contour_flow.py   lifecycle: one QAction (toolbar + Plugins menu), single dialog instance
 ▼
ui/contour_dialog.py   widgets -> ContourRequest; visibility; live checks; summary; progress
 ▼
core/workflow.py       plan_contours(request)  -> ContourPlan  (checks, extent, cell, interval)
                       run_contour_workflow()  -> ContourResult (layers, warnings, metadata)
 ▼
core step modules      interpolation / extent / contouring / clipping / smoothing / styling / output
 ▼
QGIS + GDAL Processing algorithms (the actual GIS work)
```

Dependencies point **downwards** only. `core` never imports `ui`. The
workflow never adds layers to the project; the dialog does, so the engine
can also be used from the Python console or a future Processing provider.

### Plugin lifecycle: `contour_flow.py`

`initGui()` creates one action, added to the Plugins toolbar and to
**Plugins ▸ Contour Flow**. `show_dialog()` creates the dialog once and
re-raises it afterwards. `unload()` undoes everything: it calls
`dialog.cleanup()`, closes and deletes the dialog, removes the menu entry and
toolbar icon, disconnects the action and deletes it.

### UI: `ui/`

- `contour_dialog.ui` holds the layout in a scroll area. The **default view**
  has Input, Boundary, Contours and Output. A collapsed **Advanced settings**
  group (`QgsCollapsibleGroupBox`) holds interpolation, extent, duplicates,
  boundary features, contour lines and surface output. Then come Summary, the
  Generate row and diagnostics. QGIS widgets are custom widgets with header
  `qgis.gui`.
- `contour_dialog.py`:
  - **visibility:** point-only Advanced sections are hidden for raster input,
    the band row only for multi-band rasters, the count or fixed interval
    according to the interval mode, and the GeoPackage picker only when
    saving. Dependent controls are *disabled* (not hidden) until they apply:
    IDW power, manual cell size, hull buffer, custom extent, custom smoothing,
    major frequency and boundary features;
  - **first run:** plain-language messages when the project has no suitable
    layers, when a layer has no numeric field, or when "selected only" is
    chosen with nothing selected. With only rasters present, the dialog
    starts in Raster mode;
  - **live checks:** cheap checks only (layers, fields, selections, option
    values, output paths). They enable *Generate Contours*;
  - **summary:** a debounced (600 ms) call to `plan_contours`, automatic only
    for small inputs;
  - **run:** an application-modal `QProgressDialog` linked to a
    `QgsProcessingFeedback` (progress and Cancel). The cursor and dialog state
    are restored in a `finally` block.
- **No layer caching.** The current layers are always read from the widgets.
  The dialog connects only to the current point and boundary layers'
  selection and feature signals, and releases them in `cleanup()`.

### Planning and execution: `core/workflow.py`

`plan_contours(request)` collects **errors** and **warnings** and never
raises for user problems. The summary shows them, and the run refuses to
start while there are errors. It:

1. validates options (IDW power, extent mode, boundary selection, smoothing,
   major frequency, label precision, output paths);
2. reads the point samples (read-only), handles duplicates, and runs the
   data checks (minimum 3 distinct points, collinearity, flat values, CRS);
3. builds the boundary union in the processing CRS, works out the extent
   rectangle and clip polygon, and warns about any area outside the points'
   hull;
4. picks the cell size and interval, and counts the levels.

For point input the interval comes from the **data** range. Linear TIN and
IDW cannot exceed it, so the summary equals the run. For raster input it
comes from the band statistics.

`run_contour_workflow(request, feedback, on_stage)` re-plans, then executes
the stages, passing the caller's feedback straight to each algorithm (see
DEVELOPMENT.md on why `QgsProcessingMultiStepFeedback` is not used):

```
points: interpolate (TIN/IDW over extent) ─┐
raster: [crop to boundary bbox] ───────────┴─> contour (GDAL) -> editable copy (value, is_major)
   -> [clip lines] -> [smooth] -> [surface file] -> style, labels, metadata -> [GeoPackage write, then load]
```

Output files are **opened as layers only after every write succeeded**. On
Windows an open layer locks its file, which would make rollback impossible.
Every file or GeoPackage layer the run writes is recorded. On any exception,
including cancellation, `output.remove_written` deletes them, so no partial
outputs remain.

### Groundwater Mode: `core/groundwater.py`, `core/flow.py`

`ContourRequest.mode` is `general` (default) or `groundwater`. Every
Groundwater branch in `workflow.py` is guarded by `plan.groundwater`, so
General runs take the 0.1.0 code paths unchanged.

Planning, in addition to the General steps:

1. **Fields:** an existing head field (numeric or numeric text), or MP
   elevation and depth to water (different fields). An optional ground
   elevation field is read for QA only.
2. **Values:** `interpolation.read_point_rows` reads raw attributes
   (read-only). `groundwater.build_head_records` converts them with
   `parse_number`: numbers pass, text is trimmed and converted, NULL and
   blank are "no reading", other text (`Dry`, `N/A`, `202,51`) is "not a
   number". Nothing is ever treated as 0. Calculated heads are
   `MP - DTW`.
3. **QA** (warnings, never removal):
   - conflicting duplicate locations, with the nested-well explanation;
   - head above ground (if a ground field is set);
   - negative depth to water (calculated only);
   - off-trend wells: least-squares plane, then a robust modified z-score
     of the residuals (> 3.5, at least 5 wells) **and** a deviation of at
     least 10 % of the head range;
   - the General checks (fewer than 3 or collinear points, CRS, outside hull).
4. **Arrow area:** convex hull (default), hull + buffer, boundary polygon,
   or the whole contoured area; always intersected with the boundary and
   clip polygon. An IMPORTANT warning appears when it reaches beyond the
   hull (IDW extrapolates there; TIN has no values there).

Execution adds two stages:

- **Smoothing** (`smoothing.smooth_groundwater`): Douglas-Peucker simplify
  (about 1 cell), densify (max segment 6 cells for Light, 16 for Medium),
  Chaikin (3 iterations, offset 0.25). Each result is checked with
  `geometry_problems` (GEOS validity, and crossings between lines of
  different value via a spatial index). The first clean step of
  `options.groundwater_smoothing_fallbacks` is kept. If none is clean, the
  lines stay unsmoothed with an IMPORTANT warning. The maximum Hausdorff
  displacement is recorded in the metadata.
- **Flow arrows** (`flow.build_flow_arrows`): seeds on a regular grid over
  the arrow area, spaced `sqrt(area / count)`. At each seed the head gradient
  comes from central finite differences of the surface raster
  (`provider.sample` at ±d in x and y, with d = max(2 cells, 0.15 × spacing)).
  The flow vector is `-grad h`, and the azimuth is clockwise from grid
  north. A seed needs all four samples (so no arrows where TIN has no
  values) and the whole arrow inside the area. The output is a memory
  LineString layer `GW Flow Direction` (`azimuth`, `gradient`, `head`) with
  a QGIS Arrow symbol layer.
- **Generalized direction:** the circular mean of the arrow azimuths,
  reported only for at least 3 arrows with a mean resultant length of at
  least 0.8. The **hydraulic gradient** (median and range of `|grad h|`) is
  reported only for a projected CRS. No velocity or flux is computed.

Layer names: `GW Contours`, `GW Contours - Unsmoothed`, `GW Surface`,
`GW Flow Direction`. Every layer's metadata carries the groundwater items
and `groundwater.DISCLAIMER`.

### Extent and clipping: `core/extent.py`, `core/clipping.py`

- The **processing CRS** is the point layer's CRS, or the raster's.
  Boundary geometries are transformed into it with the project's transform
  context. A transformation failure is a clear error.
- Extent modes give a rectangle (bounding box, custom) or a polygon (hull,
  buffered hull, boundary). A boundary always clips. With a polygon mode, the
  clip polygon is the intersection.
- **Edge padding:** when there is a clip polygon, the interpolation grid and
  the raster crop extend two cells beyond it (`EDGE_PADDING_CELLS`). Contours
  are traced between cell centres, so an unpadded grid would lose contours in
  the outer half cell. This was found by the real-QGIS tests.
- **Clipping sequence (and why):** interpolate over the rectangle only (or,
  for raster input, crop it to the boundary's bounding box with
  `gdal:cliprasterbyextent`, which keeps values), contour, then clip the
  **lines** exactly with `native:clip`. Masking the raster to the polygon
  first was rejected: cells outside the mask become NoData, or 0 when no
  NoData value is set, which creates false contours along the edge. It is
  also only accurate to about half a cell. Vector clipping gives an exact edge.
- `mask_surface` (`gdal:cliprasterbymasklayer`) is used only for the optional
  surface output. That raster is the plugin's own, with a known NoData value.

### Smoothing, classification, styling

- `contouring.editable_copy` writes `value` and `is_major`
  (`intervals.is_major_level`: every *N*th multiple of the interval).
- `smoothing.smooth_lines` runs after clipping. Chaikin's new vertices lie
  on the original segments, so lines stay inside the clip polygon.
- `styling.apply_style` sets:
  - a categorized renderer on `is_major`: minor 0.25 mm, major 0.6 mm, in the
    preset colour;
  - native labels on `value` (simple labeling for all, rule-based for major
    only) with number formatting, curved placement and a buffer.

### Output: `core/output.py`

- GeoPackage layers are written with `QgsVectorFileWriter.writeAsVectorFormatV3`:
  - `CreateOrOverwriteFile` when the file is new;
  - `CreateOrOverwriteLayer` otherwise, always under a name made unique first
    against the file's layer list (read via GDAL/OGR, case-insensitive).
- Rollback deletes a newly created file, or just the new layers in an
  existing GeoPackage.

### Metadata: `core/report.py`

- An ordered list of `(label, value)` settings plus warnings.
- Written once per layer: as text to the metadata abstract (with the
  professional-review disclaimer), and as JSON in the custom property
  `contour_flow/metadata`.
- Features carry only `value` and `is_major`.

### Errors

- `ContourError` carries a user-facing sentence. `ContourCancelled` is the
  same type, for Cancel.
- `utils.qgis_helpers.run_algorithm()` turns "algorithm unavailable"
  (Processing plugin disabled) and algorithm failures into `ContourError`,
  and logs the parameters and Processing log.
- Any other exception is treated as a bug: the traceback goes to the log, and
  a generic message is shown.

## Design rules

1. **Single purpose.** Features that do not help produce editable contours do not belong here.
2. **Use existing algorithms.** Wrap QGIS/GDAL Processing; do not reimplement them.
3. **UI separate from logic.** `core` is usable without the dialog.
4. **Small modules.** One processing concern per module. Pure logic is kept
   apart, so it can be tested.
5. **Outputs are ordinary layers.** Editable, saveable, restylable.
6. **Never modify source layers.** All work happens on copies or temporary outputs.
7. **Be explicit.** Method, parameters, assumptions and warnings are shown
   before the run and stored with the output.
8. **Never overwrite silently.** Existing GeoPackage layers and files are kept;
   new names are reported.
9. **Minimal dependencies.** Only what ships with QGIS (PyQGIS, Processing, GDAL/OGR, `qgis.PyQt`).
10. **Qt 5 and Qt 6 compatible.** Import Qt via `qgis.PyQt` only and use scoped enums.

## Why interpolation is not reimplemented

Robust TIN, IDW and contour tracing must deal with duplicate and collinear
points, NoData, edges, large datasets, precision and CRSs. The QGIS and GDAL
implementations are tested, documented, maintained and already installed.
They are also **reproducible**: each step can be rerun in the Processing
Toolbox with the parameters recorded in the layer metadata, which matters for
professional and regulatory work. The plugin's value is a clear, safe,
documented workflow, not new mathematics.

## Open architectural questions

- **Background processing.** Runs are synchronous in the main thread, behind
  an application-modal progress dialog with Cancel. True background execution
  (`QgsTask`) would need the memory layers and Processing context handled
  across threads. It was judged too risky for this milestone.
- **Processing provider.** Exposing the workflow as a Processing algorithm
  (batch runs, Graphical Modeler) remains possible, because `core` is
  UI-independent.

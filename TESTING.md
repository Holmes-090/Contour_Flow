# Testing

Contour Flow uses **three test levels**. Most checks are automated. Only what
genuinely needs a person looking at the screen is left for manual testing.

| Level | What | How | When |
|---|---|---|---|
| **1. Unit tests** | Deterministic pure-Python logic: options, validation, intervals, grid, duplicates, naming, metadata | Plain Python, no QGIS | After every change |
| **2. Real-QGIS integration tests** | The actual plugin code running real QGIS Processing and GDAL algorithms on synthetic fixtures | QGIS's own Python, headless | After changes to interpolation, contouring, clipping, smoothing, styling, outputs, metadata or validation, and before every commit that touches `contour_flow/core` or `contour_flow/ui` |
| **3. Visual GUI smoke test** | What a person must see: layout, map rendering, labels, editing | Manual, about 5 minutes | Before a release, or after UI changes |

## Principles

1. **Never claim a QGIS workflow works unless it has been tested.** Record the
   QGIS version and what was run.
2. **Test the real code.** Level 2 calls `contour_flow.core.workflow`, the
   styling, output and plugin lifecycle code. It does not re-implement them.
3. **No mocks at Level 2.** Every Processing algorithm really runs.
4. **Check results, not just the absence of errors.** The fixtures are designed
   so the correct answer is known (see below).
5. **Do not hide failures.** A failing test prints the stage, the error and
   the QGIS/Processing log.

## Level 1: unit tests

From the repository root, with any Python 3.9+ (no QGIS needed):

```bash
python -m unittest discover -s tests -t .
```

111 tests cover `core/options.py`, `core/input_validation.py`,
`core/intervals.py`, `core/grid.py` and `core/report.py`.

## Level 2: real-QGIS integration tests

### Run

From the repository root in a Windows command prompt or PowerShell:

```bat
tests\integration\run_qgis_integration_tests.bat
```

- The wrapper finds QGIS by itself: `%QGIS_ROOT%` if set, otherwise the newest
  `C:\Program Files\QGIS 3.44*`, otherwise the newest `QGIS 3*`. It runs the
  tests with QGIS's Python launcher (`bin\python-qgis-ltr.bat`), headless
  (`QT_QPA_PLATFORM=offscreen`).
- Exit code: 0 all passed, 1 failures, 2 QGIS not found.
- Options:
  - `--only "word,word"` runs only tests whose name contains a word, e.g.
    `--only "smoothing,geopackage"`;
  - `--fixtures-only` just writes the fixture data;
  - `--output DIR` changes the output folder.
- Output (fixtures and every written file) goes to `tests/integration_output/`.
  It is recreated on each run and ignored by Git.
- A full run takes about 15 seconds.

### Fixtures (generated, fictional)

`tests/integration/fixtures.py` creates everything locally:

| Fixture | Content | Why it is predictable |
|---|---|---|
| `points` (EPSG:32633) | 10 points with `id` (integer), `elev` (double) and `name` (text). One NULL, one equal-value duplicate location, one conflicting duplicate. | Valid values lie on the plane `elev = 100 + 0.03·dx + 0.01·dy`, so a linear TIN must reproduce it exactly. |
| `boundary_wgs84` (EPSG:4326) | One quadrilateral | Exercises the CRS transformation to the points' UTM CRS. |
| `boundary_multi` (EPSG:32633) | A two-part multipolygon plus an invalid "bow-tie" | Multipart handling, repair, and selected-only mode. |
| `gradient_dem.tif` (EPSG:32633) | 200 × 100 cells of 1 m, value `50 + 0.1·column`, NoData −9999 | Contour level L must lie on the line x = (L − 50)/0.1 + 0.5 m. |

### What the suite verifies

| Test | Checks |
|---|---|
| Algorithms available | All 7 algorithm IDs exist; TIN `METHOD` options are Linear / Clough-Toucher; IDW has `DISTANCE_COEFFICIENT`. |
| Raster contour | Raw `gdal:contour` gives line geometry and levels 52–68. Through the workflow: the automatic interval is 2, fields are `value` and `is_major`, geometries are valid, and line positions are correct to 1e-5 m. |
| TIN Linear | Plan: 7 usable points, the duplicate/conflict/NULL warnings, interval 0.5, cell 0.2. The surface stays within 100–104. All contour vertices lie on the fixture plane (within 0.01). |
| TIN Clough-Toucher | Runs, values are multiples of the interval, it reproduces the planar data, and the metadata names the method. |
| IDW | Runs; power 2 and power 5 give different surfaces; the power is recorded in metadata. |
| Boundary clipping + CRS transform | WGS84 boundary over UTM points: every line is inside the boundary, valid, and ends on its edge. The multipart + invalid boundary is repaired and reported. Selected-feature-only mode clips to that feature only. |
| Raster + boundary clipping | Crop → contour → exact clip. Lines are inside the boundary, and the levels next to the edge are kept (51–58). |
| Convex hull + buffer | Extent = hull ± 20 m (+ 2-cell padding). The clip area matches the analytic area within 1 %. IDW extrapolation warning. Contours reach 20 m beyond the points but not beyond the buffer. |
| Smoothing | Light and Medium: more vertices, identical `value`s, valid geometry, metadata records the mode. The unsmoothed copy is kept and marked. |
| Major/minor classification | Interval 0.5, major every 4: `is_major` = 1 exactly for even levels. |
| GeoPackage output | File and layer created and loaded from disk; fields preserved; a second run writes `_2` with a warning; the style is stored in `layer_styles`; values are identical after reopening. |
| GeoTIFF output | File written in EPSG:32633 at about 500 × 500 cells; an existing name gives `surface_2.tif`; with a boundary the surface is masked (NoData outside). |
| Invalid input handling | These stop cleanly with a clear message and write no output file: fewer than 3 points (selected only), collinear points, all values equal, interval producing more than 1000 levels, cell size too small, conflicting duplicates in "stop" mode, a selected-only boundary with nothing selected. |
| Cancellation + cleanup | Cancelling after the GeoTIFF was written removes it, and no GeoPackage is left behind. |
| Styling and labels | For each preset: categorized renderer on `is_major`, widths 0.25 / 0.6 mm, preset colour, label field `value`, decimals, curved placement, and the major-only rule filter. |
| Plugin load + dialog | `classFactory`, toolbar and menu action, icon. The dialog with real QGIS widgets filters layers and fields correctly; **Generate** through the dialog adds the layer and restores the cursor; unload and two reload cycles leave nothing behind. |
| Plugin discovery from QGIS profile | QGIS's own plugin scanner finds "Contour Flow" through the development link. Skipped if the link doesn't exist. |

### Reading a failure

```
FAIL GeoTIFF output
--- GeoTIFF output failed at stage: masked to boundary
Check: masked size 502 x 502
QGIS log:
  [Processing] gdalwarp ... (the exact GDAL command and output)
```

`Check:` lines are failed expectations. Other exception types are shown with
a traceback.

## Level 3: visual GUI smoke test

Only what automation cannot judge. About 5 minutes, in QGIS 3.44.

1. Create the fixture data:
   `tests\integration\run_qgis_integration_tests.bat --fixtures-only`
2. Start QGIS and open **Contour Flow** (toolbar button, or **Plugins ▸ Contour Flow**).
3. Check that the dialog appears correctly: groups are readable, nothing is
   cut off, scrolling works, and the summary updates.
4. Drag `tests\integration_output\fixtures\contour_flow_fixtures.gpkg` into
   QGIS and add the `points` and `boundary_wgs84` layers.
5. Points: `points`, field `elev`, style **Groundwater (blue)**, labels
   *Major contours only*, boundary `boundary_wgs84`. Click **Generate Contours**.
6. Check that the blue contours and labels look reasonable on the map, that
   the labels follow the lines, and that the major lines are thicker.
7. Check that the progress dialog appeared, and that the main dialog is
   usable again afterwards.
8. Toggle editing on the contour layer, move a vertex, and save. Editing works.
9. Look for obvious visual glitches: overlapping labels, wrong colours,
   layer order, icons.

Record the result:

```markdown
### Smoke test: <date>, QGIS <version>, <OS>
Steps 1-9: PASS / FAIL (notes)
```

## Development-only offline harnesses

During development, extra harnesses (kept outside the repository) drove the
dialog and workflow under plain PyQt5. Shapely provided the geometry, and the
Processing calls were replaced by recorders. Level 2 now covers the same
ground on real QGIS, so they are not part of the project's test suite.

## History

- Phase 0 (repository), Phase 1 (plugin shell) and Phase 2 (input selection):
  manual checklists passed in QGIS 3.44 LTR.
- Core engine and Professional controls: superseded by the Level 2 suite.
  First full real-QGIS run on QGIS 3.44.15 / GDAL 3.13.3: **16 passed, 0
  failed** (plus discovery), after the fixes listed in CHANGELOG.md.

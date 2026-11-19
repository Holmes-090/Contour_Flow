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

113 tests cover `core/options.py`, `core/input_validation.py`,
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
| `gw_wells` (EPSG:32633) | 13 wells over 200 × 200 m with `head`, `mp_elev`, `dtw`, `ground`, `wl_text`, plus 4 records without a usable head (NULL, `Dry`, `N/A`, blank) | Heads lie on `100 − 0.01·dx + 0.01·dy`, so flow is exactly **south-east (135°)** with gradient 0.01·√2. |
| `gw_qa_wells` | The 13 wells with one +1.5 m off-trend head, one head above ground and a nested well with a different head | Each QA warning has exactly one known cause. |
| `gw_boundary_wgs84` (EPSG:4326) | The UTM rectangle (20, 20)–(180, 120) | Boundary-clipped arrows and contours across CRSs. |

### What the suite verifies

| Test | Checks |
|---|---|
| Algorithms available | All 7 algorithm IDs exist; TIN `METHOD` options are Linear / Clough-Toucher (QGIS's own spelling); IDW has `DISTANCE_COEFFICIENT`. |
| Raster contour | Raw `gdal:contour` gives line geometry and levels 52–68. Through the workflow: the automatic interval is 2, fields are `value` and `is_major`, geometries are valid, and line positions are correct to 1e-5 m. |
| TIN Linear | Plan: 7 usable points, the duplicate/conflict/NULL warnings, interval 0.5, cell 0.2. The surface stays within 100–104. All contour vertices lie on the fixture plane (within 0.01). |
| TIN Clough-Tocher | Runs, values are multiples of the interval, it reproduces the planar data, and the metadata names the method. |
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
| Dialog: simple view, Advanced, first-run messages | Empty project shows the "add a point layer or raster" message; a raster-only project starts in Raster mode; a point layer without numeric fields is explained; Advanced is collapsed by default; dependent controls enable/disable correctly (IDW power, manual cell size, hull buffer, custom extent, custom smoothing, major frequency, boundary options); the request carries the Advanced values; the summary shows the concise fields. |
| Sample data (README tests) | The four `sample_data/README.md` tests plus bedrock. Test 4 (Groundwater Mode): about ten north-east arrows and the generalized direction, 12 usable / 1 NULL with only MW-12 flagged in calculated mode, 11 usable / 2 text for `wl_text`. Also: sensible level counts, everything inside the site boundary, majors on whole metres, NULL bedrock reported; the DEM test; the sample project opens with the right layer order. |
| Desktop sequence: contour project layers, reopen project | Regression for a crash found in this milestone: open the sample project, contour its raster and points, add the results, pump the event loop, reopen the project. Three rounds. |
| Plugin discovery from QGIS profile | QGIS's own plugin scanner finds "Contour Flow" through the development link. Skipped if the link doesn't exist. |
| GW existing field | Groundwater run with Light smoothing, unsmoothed copy, surface and arrows. Checks: layer names; source layer unchanged; values preserved; no invalid geometry or crossings; vertex displacement ≤ 2 cells, recorded in metadata; every arrow at 135° ± 1°, gradient within 2 %, drawn towards the south-east, inside the hull; Arrow symbol; summary gives "southeast / approximately 135°" and the gradient, and no velocity; metadata has the flow method and disclaimer. |
| GW calculated head | MP − DTW gives 13 heads and the same levels as the head field; the metadata names the calculation; the same field twice is an error. |
| GW numeric text field | `wl_text` is offered as "text field, numeric values detected", `well_id` is not; 13 used, 2 NULL/blank and 2 text (`Dry`, `N/A`) reported; minimum head shows no text became 0; a field with no numbers is an error. |
| GW boundary in another CRS | WGS84 boundary: contours and arrows inside it, for both the hull and the boundary arrow areas; still south-east. |
| GW QA warnings and errors | Nested-well, head-above-ground (naming the right feature) and off-trend IMPORTANT warnings, with the run still allowed; errors for fewer than 3 wells and raster input; the IDW and TIN warnings for arrows beyond the wells; TIN draws no arrows outside the hull; geographic-CRS warning. |
| GW dialog | Starts in General; switching to Groundwater shows the GW controls, sets the Groundwater style and Light smoothing, preselects `head`/`mp_elev`/`dtw`/`ground`, labels `wl_text` as numeric text; the summary and "13 usable groundwater elevations / 4 skipped"; arrow settings follow the checkbox; **Generate** adds GW Contours and GW Flow Direction; switching back restores the General style. |

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

## Package test (release ZIP)

```bat
scripts\run_with_qgis.bat scripts\package_plugin.py
```

Builds `dist/contour-flow-<version>.zip` and validates its contents. It then
installs the ZIP into a temporary, isolated QGIS profile (never your own) and
uses QGIS's plugin loader there: discovery, enable, toolbar and menu, dialog,
the sample point and raster workflows, and unload. Details are in
[DEVELOPMENT.md](DEVELOPMENT.md#release-packaging).

## Level 3: visual GUI smoke test

Only what automation cannot judge. About 5 minutes in QGIS 3.44, with the
plugin installed from the release ZIP or the development link.

Open `sample_data/contour_flow_sample.qgs`, open **Contour Flow**, and run
sample Test 1 (see `sample_data/README.md`). Then check:

1. The dialog layout is clean and understandable; nothing is cut off.
2. **Advanced settings** expands and collapses properly.
3. The sample groundwater contours look reasonable (they fall towards the north-east).
4. The blue **Groundwater** style looks appropriate: thin minor lines, thicker majors.
5. The labels are readable and follow the lines.
6. The progress dialog appears during the run (with **Cancel**), and the main
   dialog is usable again afterwards.
7. The contours can be edited by hand (toggle editing, move a vertex, save).
8. There are no obvious clipping or layout glitches.

Record the result:

```markdown
### Smoke test: <date>, QGIS <version>, <OS>
Steps 1-8: PASS / FAIL (notes)
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
- Release readiness (0.1.0): 113 unit tests and **20 real-QGIS tests** pass,
  together with the package test. The new tests found and fixed a crash
  (multi-step feedback) that affected desktop use.
- Groundwater Mode (0.2.0, branch `groundwater-mode`): 149 unit tests and
  **26 real-QGIS tests** (the 20 General tests unchanged, plus 6 Groundwater
  tests) pass, together with the package test. Running on the sample data
  found that Douglas-Peucker followed by Chaikin moved lines by up to 5.5 m
  and could make them cross. Densifying first, validating, and falling back
  to milder settings fixed this (≤ 1 m). The same run showed that the
  outlier check flagged a real recharge mound. A minimum deviation of 10 %
  of the head range fixed that.

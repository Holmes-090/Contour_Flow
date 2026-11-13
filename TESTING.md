# Testing

## Philosophy

1. **A small manual test after every phase.** No phase is complete until its
   checklist (below) has been run in a real QGIS session and the results
   recorded in the phase's CHANGELOG entry or pull request.
2. **Automated tests for deterministic helper logic.** Pure-Python code with
   no QGIS dependency, such as `core/intervals.py`, gets unit tests in `tests/`
   that run with ordinary Python (`python -m pytest`, or `python -m unittest`).
3. **Manual QGIS tests for GUI and Processing integration.** Dialogs, layer
   pickers and Processing calls are tested by hand in QGIS against small,
   known datasets. Automated QGIS tests may be added later if they prove
   worthwhile, but are not a Phase 0 goal.
4. **Never claim a QGIS workflow works unless it has been tested.** "Should
   work" is not a test result. Record the QGIS version, OS and dataset used. If
   something was not tested, say so explicitly.
5. **Test on both target versions:** QGIS 3.44 LTR, and QGIS 4.x when
   available. Note which one(s) each test ran on.
6. **Check results, not just absence of errors.** For contouring phases, compare
   output against the equivalent manual Processing Toolbox run, and check a
   few contour values against known input values.

## Test data (future)

Small, license-clean sample datasets will live in a `tests/data/` folder when
the first processing phase needs them, for example:

- A handful of points with known values on a simple plane, so the correct
  contours are obvious.
- A small DEM raster.
- A polygon boundary for clipping.
- Edge cases: duplicate points, null values, a single point, collinear points,
  a non-numeric field, a layer with no CRS.

## Phase 0 manual test

Goal: confirm the development installation works. The plugin does nothing yet.

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| 1 | Create the junction as in DEVELOPMENT.md and list its contents. | Plugin files are listed. | |
| 2 | Start QGIS 3.44. | QGIS starts with no plugin error dialog. | |
| 3 | Open **Plugins ▸ Manage and Install Plugins ▸ Installed**. | "Contour Generator" is listed, marked experimental, version 0.0.1. | |
| 4 | Tick the checkbox to enable it. | No error dialog or message bar error. | |
| 5 | Look at menus and toolbars. | **Nothing new appears.** This is expected in Phase 0. | |
| 6 | Open **View ▸ Panels ▸ Log Messages**, check the *Plugins* and *Python warning* tabs. | No errors mentioning `contour_generator`. | |
| 7 | (If Plugin Reloader is installed) configure it for `contour_generator` and click reload. | No errors. | |
| 8 | Untick the plugin to disable it, then restart QGIS. | No errors. Plugin stays disabled. | |
| 9 | (Optional) Repeat steps 2–6 on QGIS 4.x, using that version's profile folder. | Same results. | |

Result (2026-11, QGIS 3.44 LTR, Windows): **PASS**, as reported by the developer.
The plugin appeared in the Plugin Manager, enabled without errors, and the stub loaded.

## Phase 1 manual test: plugin shell

Goal: confirm the toolbar button, menu entry, dialog and the load/unload/reload
lifecycle work cleanly. Plugin Reloader must be installed and configured for
`contour_generator` (see DEVELOPMENT.md).

Before starting: restart QGIS, so that the updated `metadata.txt` is read.

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| 1 | Start QGIS. | No error dialog or message bar error. | |
| 2 | **Plugins ▸ Manage and Install Plugins ▸ Installed**: confirm Contour Generator is ticked (enabled). Close the manager. | Enabled. | |
| 3 | Look at the **Plugins Toolbar**. If it is hidden, enable it via **View ▸ Toolbars ▸ Plugins Toolbar**. | Exactly **one** Contour Generator icon (brown contour rings). Hovering shows the tooltip "Contour Generator". | |
| 4 | Open the **Plugins** menu. | Exactly **one** "Contour Generator" submenu, containing one "Contour Generator" item with the same icon. | |
| 5 | Click the toolbar icon. | — | |
| 6 | Check the dialog. | One dialog titled "Contour Generator" opens, with: the intro line; a Diagnostics section; greyed-out "Input source" and "Contour settings" sections; and a Close button. | |
| 7 | Compare "QGIS version" with **Help ▸ About**. | Same version string (e.g. `3.44.x-Solothurn`). "Plugin version" shows `0.0.1`. "Status" shows `Phase 1 development build`. | |
| 8 | Click **Close**. | Dialog closes. QGIS keeps working. The toolbar icon is still there. | |
| 9 | Reopen via **Plugins ▸ Contour Generator ▸ Contour Generator**. | Dialog opens again with the same content. | |
| 10 | With the dialog open, click the toolbar icon again. Optionally, first move the dialog or click the map canvas so the dialog is behind the main window. | The existing dialog comes to the front. | |
| 11 | Check for duplicates, e.g. drag the dialog aside, or look at the taskbar or Alt+Tab. | Still only **one** Contour Generator dialog. | |
| 12 | With the dialog still open, untick Contour Generator in the Plugin Manager (disable it). | Dialog closes. No error. | |
| 13 | Close the Plugin Manager and check the toolbar and Plugins menu. | Contour Generator icon and submenu are gone. | |
| 14 | Re-enable Contour Generator in the Plugin Manager. | No error. | |
| 15 | Check the toolbar and Plugins menu. | Exactly **one** icon and **one** submenu entry are back. | |
| 16 | Reload with Plugin Reloader (its toolbar button, or its entry in the **Plugins** menu), with `contour_generator` selected in its settings. Repeat 2–3 times. | No error. | |
| 17 | Check the toolbar and Plugins menu. | Still exactly **one** icon and **one** submenu entry. | |
| 18 | Open the dialog from the toolbar, then close it. | Works as in steps 6–8. | |
| 19 | **View ▸ Panels ▸ Log Messages**: check the *Python warning*, *Plugins* and *Contour Generator* tabs (the last appears only if something was logged). | No errors mentioning `contour_generator`. No Python error dialogs appeared during the test. | |

Optional extra check: close the dialog with the window's **X** button and with
**Esc** instead of Close. Both should behave like step 8.

Result (2026-11, QGIS 3.44 LTR, Windows): **PASS**, as reported by the
developer. The plugin loaded without errors. The toolbar action and Plugins
menu entry each appeared once. The dialog opened and closed correctly with no
duplicates. Disable/enable and Plugin Reloader left no duplicate actions.

## Automated tests

Run these from the repository root with plain Python (no QGIS needed):

```bash
python -m unittest discover -s tests -t .
```

111 tests for the pure modules: `core/options.py`, `core/input_validation.py`,
`core/intervals.py`, `core/grid.py` and `core/report.py`. They cover:

- IDW, extent, buffer, boundary, smoothing, major, label and output-path validation;
- duplicate-location handling;
- intervals and major classification;
- output naming;
- metadata serialization.

The dialog and the Processing calls are tested manually in QGIS.

During development, extra offline harnesses (kept outside the repository)
drive the real dialog and workflow code under PyQt5. Shapely provides the
geometry, and the Processing calls are replaced by recorders. They check
orchestration, visibility rules and cleanup, but are not a substitute for the
QGIS test below.

## Phase 2 manual test: input selection and live validation

Goal: confirm the layer and field selectors, mode switching and the Generate
button's enabled state react correctly to the project. **No processing should run.**

### Test data

Paste these snippets into the **Python Console** (**Plugins ▸ Python Console**)
when the steps say so. They create small in-memory layers. Nothing is written to disk.

**Snippet A**: a point layer with one text field and two numeric fields:

```python
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsProject
pts = QgsVectorLayer("Point?crs=EPSG:3857&field=well_id:string&field=gw_elev:double&field=depth:integer", "Test wells", "memory")
feats = []
for i, (x, y, z) in enumerate([(0, 0, 101.5), (100, 0, 102.0), (0, 100, 100.8), (100, 100, 101.1), (50, 50, 101.9)]):
    f = QgsFeature(pts.fields()); f.setAttributes([f"W{i + 1}", z, 10 + i]); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y))); feats.append(f)
pts.dataProvider().addFeatures(feats); pts.updateExtents(); QgsProject.instance().addMapLayer(pts)
```

**Snippet B**: a polygon boundary layer:

```python
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject
poly = QgsVectorLayer("Polygon?crs=EPSG:3857", "Test boundary", "memory")
f = QgsFeature(); f.setGeometry(QgsGeometry.fromWkt("POLYGON((-10 -10, 110 -10, 110 110, -10 110, -10 -10))")); poly.dataProvider().addFeatures([f])
QgsProject.instance().addMapLayer(poly)
```

**Raster:** use any GeoTIFF DEM you have (drag it into QGIS). If you have none,
run **Processing ▸ Toolbox ▸ Raster creation ▸ Create constant raster layer**
once, with any extent, to make a temporary raster.

### Checklist

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| 1 | Start QGIS (restart if it was open) with an **empty project**. | No errors. | |
| 2 | Open Contour Generator from the toolbar. | Dialog opens. Status shows `Phase 2 development build`. *Point layer* mode is selected. | |
| 3 | Look at the Generate Contours button. | **Disabled.** Status text: "Select a point layer." | |
| 4 | Run **Snippet A** in the Python Console. | Layer "Test wells" appears in the Layers panel. | |
| 5 | Check the **Point layer** selector. | "Test wells" is listed (and selected automatically). | |
| 6 | (Checked again at steps 17 and 23.) | Polygon and raster layers never appear in the Point layer selector. | |
| 7 | Make sure "Test wells" is selected. | — | |
| 8 | Open the **Value / elevation field** selector. | Only `gw_elev` and `depth` are listed. `well_id` (text) is **not**. | |
| 9 | Select `gw_elev`. | — | |
| 10 | With **Features: All features**: | Generate Contours **enabled**. Status: "Inputs are valid." Selected count: `0 of 5`. | |
| 11 | Switch Features to **Selected features only** (nothing selected on the map). | — | |
| 12 | Check the button. | **Disabled.** Status: "No features are selected in the point layer." | |
| 13 | In QGIS, select 2 points (Select Features tool, with "Test wells" active in the Layers panel). | — | |
| 14 | Check the dialog. | Selected count updates to `2 of 5` immediately. Generate **enabled**. | |
| 15 | Clear the selection (**Edit ▸ Select ▸ Deselect Features from All Layers**). | — | |
| 16 | Check the dialog. | Count `0 of 5`. Generate **disabled** again. | |
| 17 | Add a raster layer (see Test data). Check the Point layer selector. | The raster is **not** in the Point layer selector. | |
| 18 | Switch **Input source** to **Raster**. | — | |
| 19 | Check the groups. | *Point input* is greyed out. *Raster input* is enabled. | |
| 20 | Select the raster in the **Raster layer** selector (it may already be selected). | — | |
| 21 | Check the button. | Generate **enabled**. Status: "Inputs are valid." | |
| 22 | Run **Snippet B**. | Layer "Test boundary" appears in the Layers panel. | |
| 23 | Check all three layer selectors. | "Test boundary" appears **only** in the Boundary selector (after "None"). It does not appear under Point or Raster. Boundary still shows "None" until you pick it. Pick it: no change to validity. | |
| 24 | With Raster mode active, remove the selected raster from the project (right-click ▸ Remove Layer…). | — | |
| 25 | Check the dialog. | No error. The raster selector is empty and Generate is **disabled** ("Select a raster layer."). Switch to Point mode, then remove "Test wells": the selectors and count clear, and Generate is disabled ("Select a point layer."). Re-run Snippet A to continue. | |
| 26 | With valid inputs (Point mode, Test wells, `gw_elev`, All features), click **Generate Contours**. | — | |
| 27 | Check the result. | A blue message bar **inside the dialog** says "Inputs are valid. Contour processing will be added in a later phase." No new layers appear, and no new entry appears in **Processing ▸ History** (compare before/after clicking). | |
| 28 | Reload with **Plugin Reloader**. | No error. The dialog closes. | |
| 29 | Reopen the dialog. Repeat steps 13–16 and 26 once. | Same behaviour. Exactly one toolbar icon and one menu entry. Each selection change updates the count once (no flicker or errors). Only one message bar message per click. | |
| 30 | **View ▸ Panels ▸ Log Messages**: check the *Python warning*, *Plugins* and *Contour Generator* tabs. | No errors mentioning `contour_generator`. No Python error dialogs during the test. | |

Optional extras:

- **Rename** "Test wells" in the Layers panel. The selector shows the new name.
- **Project switch:** with the dialog open, use **Project ▸ New**. All selectors
  empty, Generate disabled, no errors.
- **No numeric fields:** create a point scratch layer with only a text field.
  When it is selected, the status says "The point layer has no numeric fields."
- **Empty layer:** a point layer with zero features gives "The point layer has no features."

## Core engine acceptance test

Goal: confirm TIN and raster contouring, intervals, data checks and editable
output in real QGIS. Restart QGIS first, because `metadata.txt` changed.

**Test data:** in an empty project, open the **Python Console** and run:

```python
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsProject
pts = QgsVectorLayer("Point?crs=EPSG:32633&field=well_id:string&field=gw_elev:double", "Test wells", "memory")
data = [(0, 0, 101.5), (100, 0, 102.0), (0, 100, 100.8), (100, 100, 101.1), (50, 50, 101.9), (20, 70, 101.3), (50, 50, 99.0), (80, 30, None)]
feats = []
for i, (x, y, z) in enumerate(data):
    f = QgsFeature(pts.fields()); f.setAttributes([f"W{i + 1}", z]); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y))); feats.append(f)
pts.dataProvider().addFeatures(feats); pts.updateExtents(); QgsProject.instance().addMapLayer(pts)
```

This creates 8 points: 6 valid, one duplicate location (W7, at the same spot
as W5 but with a different value) and one NULL value (W8).

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| 1 | Open Contour Generator. Point mode: *Test wells*, field `gw_elev`, All features, TIN linear, cell size Automatic, interval **Fixed 0.25**. Tick **Also add the interpolated surface**. Click **Generate Contours**. | After a moment, a green message: "Created 'Contours gw_elev (0.25)' with N line(s)…". A yellow note: 1 point skipped (no usable value in `gw_elev`), and 1 point ignored at a duplicate location (1 with a different value). Two new layers: the contours and "Surface gw_elev (temporary)". | |
| 2 | Look at the map. | Contour lines lie inside the triangle hull of the points, over the surface raster. | |
| 3 | Open the contour layer's attribute table. | Fields `ID` and `value`. All `value`s are multiples of 0.25 between 100.8 and 102.0 (e.g. 101, 101.25, 101.5, 101.75). | |
| 4 | Toggle editing on the contour layer, move a vertex, save edits. | Works. The layer is fully editable. The layer icon shows it is a temporary (memory) layer. | |
| 5 | **Layer Properties ▸ Metadata ▸ Identification ▸ Abstract**. | Lists the input, "Points used: 6 of 8 read", "TIN, linear, cell size 0.2 (automatic)", the interval, and the warnings. | |
| 6 | Interval **Automatic**, count 10, then Generate again. | A second layer, named with the chosen interval (expected 0.1 or 0.2). Its `value`s are multiples of that interval. | |
| 7 | Switch to **Raster** mode. Raster: "Surface gw_elev (temporary)", band 1, interval **Fixed 0.25**. Generate. | A new contour layer whose lines coincide with those from step 1. No point warnings. | |
| 8 | Back to Point mode. Select only 2 points on the map. Features: **Selected features only**. Generate. | **Red** message: "At least 3 points with values at distinct locations are needed; 2 found." No new layer. | |
| 9 | Features: All features. Interval **Fixed 0.0001**. Generate. | Red message saying the interval would create too many levels (limit 1000). No new layer. | |
| 10 | Add any polygon layer (e.g. Snippet B from the Phase 2 test), pick it as the Boundary, interval Fixed 0.25, Generate. | It works, plus a note that clipping is not implemented and the contours are not clipped. | |
| 11 | Plugin Reloader, then repeat step 1. | Same result. One toolbar icon. No errors. | |
| 12 | **View ▸ Panels ▸ Log Messages**: the *Contour Generator* and *Python warning* tabs. | A "Contours generated." summary for each run, and "Contour generation stopped" for steps 8–9. No Python tracebacks. | |

Optional, with a real DEM: Raster mode, Automatic interval → about 10 sensible
contours. With a large DEM, expect QGIS to be busy (wait cursor) until it finishes.

## Professional controls acceptance test

Goal: one pass over the major workflows in real QGIS 3.44. Restart QGIS
first, because `metadata.txt` changed. Use an **empty project**.

**Test data:** paste both snippets into the **Python Console**.

*A: 8 wells in UTM 33N (EPSG:32633).* 6 are valid; W7 is at W5's location
with a different value, and W8 has a NULL value.

```python
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsProject
pts = QgsVectorLayer("Point?crs=EPSG:32633&field=well_id:string&field=gw_elev:double", "Test wells", "memory")
data = [(0, 0, 101.5), (100, 0, 102.0), (0, 100, 100.8), (100, 100, 101.1), (50, 50, 101.9), (20, 70, 101.3), (50, 50, 99.0), (80, 30, None)]
feats = []
for i, (x, y, z) in enumerate(data):
    f = QgsFeature(pts.fields()); f.setAttributes([f"W{i + 1}", z]); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500000 + x, 5000000 + y))); feats.append(f)
pts.dataProvider().addFeatures(feats); pts.updateExtents(); QgsProject.instance().addMapLayer(pts)
```

*B: a site boundary stored in WGS84 (EPSG:4326),* to exercise the CRS
transformation:

```python
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject, QgsCoordinateReferenceSystem, QgsCoordinateTransform
g = QgsGeometry.fromWkt("POLYGON((500010 5000010, 500090 5000010, 500090 5000060, 500010 5000090, 500010 5000010))")
g.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:32633"), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()))
poly = QgsVectorLayer("Polygon?crs=EPSG:4326", "Site boundary (WGS84)", "memory")
f = QgsFeature(); f.setGeometry(g); poly.dataProvider().addFeatures([f]); QgsProject.instance().addMapLayer(poly)
```

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| 1 | Open Contour Generator. Points: *Test wells*, `gw_elev`, all features, duplicates *Keep first*, TIN linear, extent *Bounding box*, interval Automatic (10), major every 5, labels *Major contours only*. | **Summary:** "Points: 6 usable, 2 skipped or merged", "Range: 100.8 to 102", "Interval: 0.2, about 7 contour level(s)". A **red IMPORTANT** line about different values at one location, and an orange line about 1 point with no usable value. | |
| 2 | **Generate Contours.** | The progress dialog shows stages. A green "Created 'Contours gw_elev (0.2)'…" message, then a red "Please check" note repeating the IMPORTANT warning. In the attribute table: `value` holds multiples of 0.2 and `is_major` = 1 only for 101 (and 102, if a line exists at the maximum). Major lines are thicker and only they are labelled. | |
| 3 | *Layer Properties ▸ Metadata*. | The abstract lists the input, field, feature mode, method, cell size 0.2 (automatic), extent, interval, major every 5 (1), smoothing None, labels, style, plugin and QGIS versions, the warnings and the review disclaimer. | |
| 4 | Duplicates → *Stop if values differ*. Wait for the summary, then Generate. | Summary and message: **Error** "…location(s) have points with different values…". Nothing is added. Set it back to *Keep first*. | |
| 5 | Method **IDW** (power 2), extent **Convex hull + buffer**, buffer **20**. | The IDW power row appears. The summary shows a red IMPORTANT "…outside the convex hull… IDW extrapolates". Generate: contours reach about 20 m beyond the wells. | |
| 6 | Method TIN linear, Boundary: *Site boundary (WGS84)*, extent **Boundary polygon**. Generate. | All lines end **exactly** on the boundary edge (zoom in on a corner). Nothing lies outside it, although the boundary is in a different CRS. | |
| 7 | Boundary *Use: Selected features only* with nothing selected. | Generate is disabled: "No features are selected in the boundary layer." Select the polygon: Generate is enabled again. | |
| 8 | Smoothing **Medium**, tick *Also keep an unsmoothed copy*, labels **All contours**, decimals 1, style **Groundwater (blue)**. Generate. | Two new layers, "… smoothed" and the unsmoothed one, blue with all contours labelled. Metadata: "Smoothing: Medium (iterations 2, offset 0.25)" and "Smoothed geometry: yes/no" respectively. | |
| 9 | Output **Save to GeoPackage**: pick a new `test.gpkg`, layer name `wells_contours`. Surface **Save as GeoTIFF**: pick a new `surface.tif`. Generate **twice**. | First run: layers loaded from `test.gpkg`, plus a surface raster masked to the boundary. Second run: a note that the name exists and was saved as `wells_contours_2`, and that the surface was saved as `surface_2.tif`. In the Browser panel, `test.gpkg` shows the layers, and they open styled. | |
| 10 | Switch to **Raster**: raster = the saved `surface.tif`, band 1, boundary still set, interval **Fixed 0.25**, major every 4, smoothing None, output Temporary. | The interpolation and extent groups and the surface row are hidden. The summary shows band and range. Generate: lines clipped to the boundary, with `is_major` = 1 for whole numbers (101, and 102 if present). | |
| 11 | Points again, IDW, extent Bounding box, cell size **0.025** (about 16 million cells). Generate, then click **Cancel** in the progress dialog. | "Cancelled. Nothing was added." No new layers. The dialog is usable again. | |
| 12 | Plugin Reloader, then repeat step 2. *View ▸ Panels ▸ Log Messages*: the *Contour Generator* and *Python warning* tabs. | The same result as step 2. A "Contours generated." summary for each run and "Contour generation stopped" for step 4. No Python tracebacks. | |

If step 11 finishes before you can cancel, lower the cell size slightly. A
grid of more than 25 million cells is refused by design.

## Manual test checklist template

Copy this for each phase.

```markdown
### Phase N manual test: <short title>

- Date:
- Tester:
- OS:
- QGIS version(s): (e.g. 3.44.x LTR / 4.x)
- Plugin commit / version:
- Test data used:

| # | Step | Expected result | Actual result | Pass/Fail |
|---|------|-----------------|---------------|-----------|
| 1 |      |                 |               |           |
| 2 |      |                 |               |           |

Errors seen in Log Messages (Plugins / Python warning / Processing / Contour Generator tabs):

-

Source layers unchanged after the run? (yes/no):

Output layer editable (toggle editing, move a vertex, save)? (yes/no/n.a.):

Not tested / known gaps:

-

Result: PASS / FAIL / PARTIAL
```

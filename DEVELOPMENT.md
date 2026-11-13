# Development guide

This guide assumes no prior QGIS plugin experience. Paths are given for
Windows first because that is the main development machine. Linux and macOS
equivalents are noted where they differ.

## Target QGIS versions

Checked against the official QGIS release schedule
(<https://www.qgis.org/resources/roadmap/>) on **2026-11-12**:

- **Current Long Term Release (LTR): QGIS 3.44.** This is the last QGIS 3.x
  series (Qt 5). It became the LTR in early 2026, when 3.40 was retired.
- **Current latest release: QGIS 4.x** (Qt 6). The 4.0 series arrived in early 2026.
- **The schedule shows the 4.4 series moving into the LTR repository in early
  2027 (around February–March), replacing 3.44.** At that point QGIS 3 will no longer
  receive LTR point releases.

| Role | Version | Why |
|---|---|---|
| **Recommended development version** | **QGIS 3.44 LTR** | The supported LTR today, what most professional and consultancy users run, and well documented. |
| **Second test version** | **QGIS 4.x latest** (4.4 once released) | Becomes the next LTR in early 2027. Testing on it from the start avoids a painful port later. |
| **Minimum supported (`qgisMinimumVersion`)** | **3.44** | 3.40 and older are no longer maintained. Supporting them would add test burden for no benefit. |
| **Maximum declared (`qgisMaximumVersion`)** | **4.99** | QGIS 4 will not load a plugin unless its maximum version is ≥ 4.0. |

Notes:

- The old `supportsQt6=True` metadata flag is **no longer used**. QGIS 4
  compatibility is declared only through `qgisMaximumVersion`
  (<https://plugins.qgis.org/docs/migrate-qgis4>).
- To run on both QGIS 3.44 (Qt 5) and QGIS 4 (Qt 6), always import Qt through
  `qgis.PyQt` (e.g. `from qgis.PyQt.QtWidgets import QDialog`), never from
  `PyQt5` or `PyQt6`, and use fully scoped enum names.
- If you want to target QGIS 4 only, raise `qgisMinimumVersion` to `4.0`.
  This is listed as an open decision in the Phase 0 summary.

### Installing QGIS (Windows)

1. Download from <https://qgis.org/download/>. Choose the **standalone
   installer for the Long Term Release (3.44)**.
2. Optionally, also install the latest **QGIS 4.x** standalone installer.
   Each version installs into its own folder, and you can run them one at a time.
3. Start QGIS 3.44 once and close it. This creates your user profile folder.

## How QGIS finds plugins

When QGIS starts, it looks for Python plugins in:

1. **The active user profile's plugin folder** (where Plugin Manager installs plugins):

   | OS | QGIS 3.x path |
   |---|---|
   | Windows | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` (i.e. `C:\Users\<you>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`) |
   | Linux | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
   | macOS | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |

   **QGIS 4:** the profile folder location could not be confirmed from the
   current documentation. Do not guess. In QGIS 4, use
   **Settings ▸ User Profiles ▸ Open Active Profile Folder** and go into
   `python\plugins` from there.

2. Any folders listed in the `QGIS_PLUGINPATH` environment variable.
3. The system plugin folder inside the QGIS installation (core plugins such
   as Processing). **Do not put your plugin there.**

Each **subfolder** that contains a `metadata.txt` and an `__init__.py` is
treated as a plugin. The subfolder name becomes the Python package name,
which is why the plugin folder is called `contour_flow`.

Finding a plugin does not activate it. You must **enable** it once in
**Plugins ▸ Manage and Install Plugins ▸ Installed**. QGIS then remembers
this in your profile.

## Ways to get the plugin into QGIS during development

| Approach | How it works | Verdict |
|---|---|---|
| **Directory link (junction / symlink)** | A link in the profile `plugins` folder points at `contour_flow/` in this repository. QGIS reads your working files directly. | **Recommended.** Edit in one place, no copying. |
| Direct copy | Copy `contour_flow/` into the profile `plugins` folder after each change. | Works, but easy to test a stale copy by mistake. |
| `QGIS_PLUGINPATH` | Point QGIS at an extra folder that contains plugin folders. | Valid alternative, but it would point at the repo root, which also contains `tests/` and docs. More setup, no real gain here. |
| Install from ZIP | Zip the plugin folder and use *Install from ZIP*. | **Only for release testing** (see below), not day-to-day development. |

### Recommended: a Windows directory junction

A *junction* is a Windows directory link. Unlike a symlink, it does **not**
require administrator rights or Developer Mode.

In **PowerShell** (not as administrator), with QGIS closed:

```powershell
$plugins = "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins"
New-Item -ItemType Directory -Force $plugins | Out-Null
New-Item -ItemType Junction -Path "$plugins\contour_flow" -Target "C:\Dev\GIS Contour Plugin\contour_flow"
```

Check that it worked:

```powershell
Get-ChildItem "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\contour_flow"
```

You should see `__init__.py`, `metadata.txt`, `contour_flow.py`, etc.

Linux/macOS equivalent: `ln -s /path/to/repo/contour_flow <profile>/python/plugins/contour_flow`.

> ⚠️ **Do not click "Uninstall plugin"** for Contour Flow in the Plugin
> Manager while it is a junction. Uninstall deletes the plugin folder, and
> through a link that can mean deleting **your source files in this
> repository**. To stop using the plugin, *disable* it (untick it). To remove
> the link, delete only the junction:
>
> ```powershell
> (Get-Item "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins\contour_flow").Delete()
> ```
>
> This removes the link and leaves the target folder alone. Commit and push
> your work regularly as a second line of defence.

## When you need to restart QGIS

| Change | What to do |
|---|---|
| First time the junction is created | **Restart QGIS**, then enable the plugin in the Plugin Manager. |
| `metadata.txt` changed | Restart QGIS. Metadata is read at startup. |
| Python code changed (`.py`, `.ui`) | Use **Plugin Reloader** (below), or restart QGIS. |
| Strange behaviour after several reloads | Restart QGIS. Reloading cannot always undo everything. |

## Plugin Reloader

[Plugin Reloader](https://plugins.qgis.org/plugins/plugin_reloader/) is the
standard tool for this. It unloads your plugin, re-imports its Python
modules, and loads it again without restarting QGIS. It is still maintained
(version 0.24, September 2026) and declares support for QGIS 3.0–4.99, so it
remains appropriate for both target versions.

Setup (once per QGIS installation):

1. **Plugins ▸ Manage and Install Plugins ▸ All**, search for **Plugin Reloader**, install it.
2. It adds a toolbar button and a configure option. Open its configuration
   and choose **contour_flow** as the plugin to reload.

Daily use:

1. Edit code in your editor.
2. Click the Plugin Reloader button.
3. Test in QGIS. Check the Log Messages panel for errors.

Reloading calls the plugin's `unload()` and then `initGui()`. From Phase 1
onward, `unload()` must remove every menu entry and toolbar button that
`initGui()` added, or duplicates will appear after each reload.

Only plain Python and `.ui` changes are reliably picked up. Restart QGIS
after changing `metadata.txt`.

## Python / PyQGIS workflow

- **Use the Python that ships inside QGIS.** QGIS bundles its own Python
  interpreter with PyQGIS, PyQt and GDAL. Do not `pip install` anything into
  it for this plugin. The project policy is *no external dependencies*.
  To see which Python version your QGIS uses, open the Python Console and run
  `import sys; sys.version`.
- **Editor:** any editor works. VS Code is a good free choice. Open the
  repository root folder. Autocompletion for `qgis.*` imports will not work
  out of the box because the editor does not know about the QGIS Python.
  That is fine for now, and can be improved later by pointing the editor at
  the QGIS-bundled Python.
- **Python Console** (**Plugins ▸ Python Console**, or `Ctrl+Alt+P`): run
  PyQGIS snippets interactively. It is the quickest way to try an API call
  before writing it into the plugin.
- **Qt Designer** edits `ui/contour_dialog.ui`. On Windows it is installed with
  QGIS. Look for it in the QGIS folder of the Start menu.
- **Processing Toolbox** (**Processing ▸ Toolbox**): run each underlying
  algorithm by hand to check parameters and results before automating them.
  Hovering over an algorithm, or using its *Help* button, shows its ID.
- **Command-line PyQGIS** (later phases, if needed): the Windows install
  includes an **OSGeo4W Shell** in which `python` can import `qgis`.

## Inspecting logs and Python errors

- **Python error dialog / message bar:** when plugin code raises an
  exception, QGIS shows a message bar or dialog with a *Stack trace* /
  *Details* button. That trace names the file and line.
- **Log Messages panel:** **View ▸ Panels ▸ Log Messages**. Useful tabs:
  - *Python warning*: Python warnings and some errors.
  - *Plugins*: plugin loading problems (e.g. a broken `metadata.txt`).
  - *Processing*: output of Processing algorithms.
  - From Phase 1 the plugin will write to its own tab ("Contour Flow")
    via `QgsMessageLog`.
- **Processing history:** **Processing ▸ History** lists every algorithm run
  with its exact parameters.
- **Plugin Manager:** a plugin that fails to load is shown there with an error
  message.

## Plugin GUI notes (learned in Phase 1)

### Toolbar button and menu entry

- One `QAction` is created in `initGui()`, parented to `iface.mainWindow()`,
  and added to **both** places:
  - `iface.addToolBarIcon(action)` puts it on the **Plugins Toolbar**. If you
    don't see the button, check **View ▸ Toolbars ▸ Plugins Toolbar**.
  - `iface.addPluginToMenu("Contour Flow", action)` creates a
    **Plugins ▸ Contour Flow** submenu holding the action. A one-item
    submenu named after the plugin is the standard QGIS convention, and it
    leaves room for later items such as Help or About.
- `unload()` must call the matching `iface.removePluginMenu(...)` and
  `iface.removeToolBarIcon(...)` with the **same** menu name and action.
  QGIS removes the submenu itself once it is empty.
- The action is also explicitly disconnected and `deleteLater()`'d. Without
  this, every reload leaves an orphaned `QAction` attached to the main window.

### Dialog loading and `.ui` files

- `ui/contour_dialog.ui` is loaded at runtime with
  `qgis.PyQt.uic.loadUiType(...)`. No `pyuic` step and no generated
  `ui_*.py` file (those are ignored in `.gitignore`).
- Widget `objectName`s in the `.ui` file (e.g. `qgis_version_value`,
  `button_box`) become attributes of the dialog in Python. **Renaming a
  widget in Qt Designer breaks the Python code that uses it.** Keep names in
  sync.
- The dialog is modeless (`show()` + `raise_()` + `activateWindow()`). A modal
  `exec()` would block the toolbar, making a "bring the existing dialog
  forward" behaviour impossible.
- The plugin keeps one dialog instance in `self.dialog`. Closing the dialog
  only hides it; `unload()` closes and deletes it.
- Always import Qt classes from `qgis.PyQt`, e.g.
  `from qgis.PyQt.QtWidgets import QAction, QDialog`. (In Qt 6 `QAction`
  moved to `QtGui`; check this when QGIS 4 testing starts.)

### Plugin Reloader and the lifecycle

- Plugin Reloader calls `unload()` on the running instance, re-imports the
  package, then calls `classFactory()` and `initGui()` on a new instance.
  Anything `unload()` forgets (a toolbar button, a menu entry, an open dialog)
  survives as a duplicate or orphan. That is the main thing to check after
  every reload.
- An open dialog is closed by `unload()`. After a reload you need to open it again.
- Changes to `.ui` files are picked up by Plugin Reloader, because the
  dialog module, which loads the `.ui` file, is re-imported.
- Changes to `metadata.txt`, including the version, still need a QGIS
  restart for the Plugin Manager. The dialog reads the version straight from
  the file, so it may show the new version before the Plugin Manager does.

### Logging

- Errors go to **View ▸ Panels ▸ Log Messages ▸ Contour Flow** tab via
  `utils.qgis_helpers.log_message()`. Use this instead of `print()`, whose
  output is not visible in normal QGIS use.
- Normal UI events (opening or closing the dialog) are deliberately not logged.

## QGIS input widgets (learned in Phase 2)

### Using QGIS widgets in a `.ui` file

- `QgsMapLayerComboBox`, `QgsFieldComboBox` and `QgsMessageBar` are placed in
  the `.ui` file as **custom widgets** with `<header>qgis.gui</header>`. When
  the file is loaded, the widget is imported from `qgis.gui`. In Qt Designer,
  use **Promote to…** on a `QComboBox` (base class) and enter that class and
  header, or use the QGIS widgets panel if your Designer shows one.
- The `.ui` file only places the widgets. Filters and signal wiring are set
  in `contour_dialog.py`, so behaviour stays readable in one place.

### Filters

- Layer combos: `setFilters(Qgis.LayerFilter.PointLayer)` / `RasterLayer` /
  `PolygonLayer`. `Qgis.LayerFilter` is the current API (since QGIS 3.34). The
  older `QgsMapLayerProxyModel.Filter` / integer form is deprecated.
  "Point layer" includes multipoint layers.
- Field combo: `setFilters(QgsFieldProxyModel.Filter.Numeric)`, which covers
  Int, LongLong and Double fields. Text, date and boolean fields are hidden.
- The field combo follows the point combo through one connection:
  `point_layer_combo.layerChanged.connect(value_field_combo.setLayer)`.
- `setAllowEmptyLayer(True, "None")` adds a "None" entry to the optional
  boundary combo.

### Live project updates come for free

`QgsMapLayerComboBox` watches the current project (`QgsProject.instance()`)
by itself. Adding, removing or renaming layers, and opening another project,
update the list automatically and emit `layerChanged` when the current layer
changes. The dialog therefore never caches layers or layer IDs. It always reads
`combo.currentLayer()` when validating.

### Signals that are not handled by the widgets

- Selection changes and feature additions/deletions are signals on the
  **layer**, not on the combo box. The dialog connects to `selectionChanged`,
  `featureAdded` and `featuresDeleted` of the *current* point layer only. It
  moves the connections when the layer changes, and disconnects in `cleanup()`
  on unload and reload.
- A layer removed from the project is deleted by QGIS. Python still holds a
  wrapper object, but touching it raises `RuntimeError: wrapped C/C++ object
  … has been deleted`. The disconnect code catches exactly that case.
- Connections to widgets *inside* the dialog die with the dialog and need no
  manual disconnection.

### Running the unit tests

The automated tests need only plain Python, not QGIS:

```bash
python -m unittest discover -s tests -t .
```

Run this from the repository root. They cover the pure modules
(`options`, `input_validation`, `intervals`, `grid`, `report`), not the dialog
or the Processing calls.

## Real-QGIS integration tests

The project runs its real code against a real QGIS installation, headless:

```bat
tests\integration\run_qgis_integration_tests.bat
```

See [TESTING.md](TESTING.md#level-2-real-qgis-integration-tests) for what it
covers. How it works:

- The `.bat` wrapper finds QGIS: `%QGIS_ROOT%`, otherwise
  `C:\Program Files\QGIS 3.44*`, otherwise `QGIS 3*`. It calls QGIS's own
  `bin\python-qgis-ltr.bat` (or `python-qgis.bat`), which sets `PATH`,
  `PYTHONPATH` and `QGIS_PREFIX_PATH` through `o4w_env.bat`.
- The runner starts `QgsApplication` with the GUI enabled but
  `QT_QPA_PLATFORM=offscreen`, so real QGIS widgets and the dialog work
  without a screen. It then calls `Processing.initialize()` (which registers
  `native`, `qgis`, `gdal` and the other providers), runs the tests, and exits
  with `os._exit(code)` after `exitQgis()`, so the exit code is reliable.
- `qgis_process` was used to verify algorithm IDs and parameters
  (`qgis_process-qgis-ltr.bat help gdal:contour`). It is not needed for the
  suite, because standalone PyQGIS proved reliable on this installation.

### Installation used for verification (this machine)

| Item | Value |
|---|---|
| QGIS | 3.44.15-Solothurn (LTR), `C:\Program Files\QGIS 3.44.15` (the only install) |
| `qgis_process` | `C:\Program Files\QGIS 3.44.15\bin\qgis_process-qgis-ltr.bat`, which wraps `apps\qgis-ltr\bin\qgis_process.exe` |
| Python | `C:\Program Files\QGIS 3.44.15\bin\python3.exe` (3.12), via `bin\python-qgis-ltr.bat` |
| GDAL / PROJ / GEOS / Qt | 3.13.3 / 9.8.1 / 3.15.0 / 5.15.13 |

### QGIS 3.44 behaviour learned from the real tests

- **Windows file locks:** an output file opened as a QGIS layer cannot be
  deleted. The workflow therefore opens output files only after every write
  succeeded, so rollback after a failure or Cancel can delete them.
- **Contours stop half a cell inside a grid** (they are traced between cell
  centres). Grids and raster crops are padded by two cells around a clip
  polygon (`workflow.EDGE_PADDING_CELLS`); the vector clip is exact.
- **`bandStatistics()`** warns "deprecated" in PyQGIS 3.44 even with the
  recommended `Qgis.RasterBandStatistic` flags. With only Min|Max requested,
  the GDAL provider returns `elementCount` 0, so judge validity by min/max.
- **`saveStyleToDatabaseV2`** exists in 3.44.15 (documented as 4.0); the old
  `saveStyleToDatabase` is deprecated.
- After storing a style in a **new** GeoPackage, the loaded layer must be
  `reload()`ed, otherwise GDAL prints "unable to open database file" on the
  next feature count.

- **Do not use `QgsProcessingMultiStepFeedback`** for these algorithm runs.
  On 3.44.15, running `gdal:contour` through it led to an **access violation
  on the next event-loop pass** after the feedback objects were freed, or when
  layers were later deleted (for example by opening another project). The
  real-QGIS suite has a regression test for this ("Desktop sequence").
- **Never call `gdal.UseExceptions()` globally** inside a QGIS process (e.g.
  in fixtures or plugin code). It changes GDAL's error mode for all of QGIS's
  Python code, and here it crashed the test process. Scripts call
  `gdal.DontUseExceptions()` explicitly instead, which keeps the default and
  silences GDAL's FutureWarning.
- **Headless rendering needs fonts:** Qt's `offscreen` platform renders no
  text unless `QT_QPA_FONTDIR` points at a font folder.
  `scripts/capture_screenshots.py` sets it to `%WINDIR%\Fonts`.

## Helper scripts (`scripts/`)

All of them run with QGIS's Python through `scripts\run_with_qgis.bat`,
which finds QGIS like the test wrapper does.

| Script | Purpose |
|---|---|
| `make_sample_data.py` | Regenerates `sample_data/` (GeoPackage, DEM, QGIS project) from formulas |
| `render_icon.py` | Renders `contour_flow/icons/contour_flow.svg` to the 64 px PNG used by `metadata.txt` |
| `capture_screenshots.py` | Renders the README screenshots in `docs/images/` with real QGIS (the dialog via Qt, the maps via the QGIS map renderer) |
| `package_plugin.py` | Builds, validates and test-installs the release ZIP (see below) |

### After the rename from `contour_generator`

The development link in the QGIS profile must point at `contour_flow`:

```powershell
$plugins = "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins"
cmd /c rmdir "$plugins\contour_generator"   # removes only the old link
New-Item -ItemType Junction -Path "$plugins\contour_flow" -Target "C:\Dev\GIS Contour Plugin\contour_flow"
```

Restart QGIS, then enable **Contour Flow** in the Plugin Manager. The old
plugin entry is gone, and the "enabled" setting is per package name.

## Processing algorithms used

| Step | Algorithm ID | Notes |
|---|---|---|
| TIN interpolation | `qgis:tininterpolation` | `INTERPOLATION_DATA` = `"<layer id>::~::0::~::0::~::0"`: the attribute in field 0 of the plugin's temporary point layer, used as points. `METHOD` 0 = linear, 1 = Clough-Toucher. `EXTENT` `"xmin,xmax,ymin,ymax"`, `PIXEL_SIZE` = cell size. The output raster carries the input CRS and has no values outside the points' convex hull. |
| IDW interpolation | `qgis:idwinterpolation` | Same `INTERPOLATION_DATA`, `EXTENT` and `PIXEL_SIZE`. `DISTANCE_COEFFICIENT` = IDW power (QGIS allows 0–99.99; default 2). Fills the whole extent, i.e. it extrapolates. |
| Raster crop (raster input + boundary) | `gdal:cliprasterbyextent` | `PROJWIN` = the boundary's bounding box intersected with the raster extent, in the raster's CRS. Cell values are not changed. |
| Contouring | `gdal:contour` | `INTERVAL`, `OFFSET` 0, `FIELD_NAME` `value`. Only file-based (GDAL provider) rasters work. |
| Line clipping | `native:clip` | `OVERLAY` = a temporary memory polygon layer holding the clip polygon. The output is a memory layer. |
| Smoothing | `native:smoothgeometry` | `ITERATIONS` 1–5 (the plugin's limit; QGIS allows 10), `OFFSET` 0.05–0.5, `MAX_ANGLE` 180. Chaikin corner cutting. |
| Surface mask (surface output + clip polygon only) | `gdal:cliprasterbymasklayer` | `NODATA` = the surface's own NoData value, `CROP_TO_CUTLINE`, `KEEP_RESOLUTION`. |

All of these come from the core **Processing** plugin, which must be
enabled. If it isn't, the dialog says so instead of failing obscurely.

How a run is wired:

- A fresh `QgsProcessingContext` is used per run. The temporary point layer
  goes into the context's temporary layer store, so the interpolation
  algorithm can find it by ID.
- `processing.run` returns memory outputs (`"memory:"`) as layer objects and
  file outputs (`TEMPORARY_OUTPUT`) as paths. `qgis_helpers.result_vector_layer`
  accepts either.
- Temporary files live in QGIS's Processing temp folder and are deleted when
  QGIS exits. The contours are always copied into memory layers, or written to
  the GeoPackage. The *temporary* surface option depends on its temp file;
  choose GeoTIFF to keep it.
- **Progress and Cancel:** algorithms receive the caller's
  `QgsProcessingFeedback` directly. The dialog combines "stage *i* of *n*"
  (from the workflow's `on_stage` callback) with each algorithm's own
  progress into one bar. Its `QProgressDialog` is application-modal, so QGIS
  keeps repainting and Cancel works, but the user cannot start other work
  during the run. Algorithms check `feedback.isCanceled()` themselves, and
  the workflow also checks between stages.
- When an algorithm fails, the parameters and the Processing log are written to
  **Log Messages ▸ Contour Flow**, and the *Processing* tab shows the GDAL
  command line.
- **To reproduce a run by hand,** use the same algorithms in the Processing
  Toolbox with the values from the output layer's metadata
  (**Layer Properties ▸ Metadata ▸ Identification ▸ Abstract**).
- The same metadata is stored as JSON in a layer custom property. In the
  Python console:

  ```python
  import json
  json.loads(iface.activeLayer().customProperty("contour_flow/metadata"))
  ```

### Why TIN vs IDW behave differently at the edges

TIN interpolates only inside the triangulation, the convex hull of the
points: a bounding-box extent leaves NoData corners and the contours stop at
the hull. IDW computes a weighted mean everywhere, so it produces values far
from any data. That is why the plugin measures how much of the processing area
lies outside the hull, and warns (IMPORTANT for IDW).

## Release packaging

```bat
scripts\run_with_qgis.bat scripts\package_plugin.py
```

This produces `dist\contour-flow-<version>.zip` (`dist/` is ignored by Git).
The script stops with exit code 1 if any step fails:

1. **Fast checks:**
   - byte-compiles every plugin module and runs the unit tests;
   - checks `metadata.txt`: required fields, a PNG/JPEG icon present;
   - reports placeholder values (e.g. a TODO email) as **release blockers**.
2. **Build:** exactly one top-level folder `contour_flow/`, holding only
   plugin files (code, `.ui`, icons, `metadata.txt`, `LICENSE`). No tests,
   sample data, caches, VCS or IDE files.
3. **Validate:**
   - every required file is present and nothing forbidden is included;
   - one top-level folder;
   - the ZIP's metadata version matches;
   - the icon referenced in `metadata.txt` exists;
   - the ZIP is under 25 MB.
4. **Isolated install test:** a separate QGIS process with a **temporary
   profile folder** (`QgsApplication(..., profileFolder)`):
   - extracts the ZIP with the Plugin Manager's own `pyplugin_installer.unzip`
     into that profile's plugin folder;
   - discovers, loads and starts the plugin with `qgis.utils`, and checks
     that the code comes from the ZIP, not the repository;
   - checks the toolbar and menu, opens the dialog, generates contours from
     the sample points and the sample DEM, and unloads the plugin;
   - deletes the temporary profile afterwards. Your own QGIS profile is
     never used.

Options: `--no-tests`, `--no-install-test`, `--output DIR`. `tests/test_packaging.py`
unit-tests the build and validation rules (e.g. that a stray `__pycache__` or a
missing `LICENSE` fails validation).

### Installing a release ZIP by hand

**Plugins ▸ Manage and Install Plugins ▸ Install from ZIP**. QGIS copies the
files into the profile's `plugins` folder; later edits in this repository do
not affect that copy.

**Remove the development junction first** (`cmd /c rmdir` on the link, see
above). Otherwise the install writes into, or replaces, your working copy.

### Publishing (not done yet)

Upload the ZIP at <https://plugins.qgis.org> (**My plugins ▸ Upload**), with
an OSGeo account. Resolve the release blockers reported by the script first.

# SPDX-License-Identifier: GPL-2.0-or-later
"""Build, validate and test-install the Contour Flow release ZIP.

Run with QGIS's Python from the repository root (needed for the install test)::

    scripts\\run_with_qgis.bat scripts\\package_plugin.py

Steps (each must pass, otherwise the exit code is 1):

1. **Fast checks:** byte-compile the plugin, run the unit tests, and check
   ``metadata.txt``.
2. **Build** ``dist/contour-flow-<version>.zip`` with exactly one top-level
   folder, ``contour_flow/``. Only plugin files go in: no tests, sample data,
   caches, VCS or development files.
3. **Validate** the ZIP: required files present, forbidden ones absent, and
   the metadata and icon inside the ZIP readable.
4. **Isolated install test** (skipped with ``--no-install-test``, or when not
   run with QGIS's Python), in a separate process with a temporary QGIS
   profile and plugin folder:
   - extract the ZIP with the QGIS Plugin Manager's own unzip routine;
   - discover the plugin and enable it with QGIS's plugin loader
     (``qgis.utils``), checking that it really is the ZIP's code;
   - check the toolbar and menu action, and open the dialog;
   - generate contours from the sample points and the sample DEM;
   - unload the plugin and check nothing is left behind.

Your own QGIS profile is never touched.

Options: ``--no-tests`` (skip the unit tests), ``--no-install-test``,
``--output DIR`` (default ``dist``).
"""

import argparse
import configparser
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PACKAGE = "contour_flow"
SOURCE = os.path.join(REPO, PACKAGE)

#: Files that must be in the ZIP (relative to the top-level folder).
REQUIRED = [
    "__init__.py", "contour_flow.py", "metadata.txt", "LICENSE",
    "ui/__init__.py", "ui/contour_dialog.py", "ui/contour_dialog.ui",
    "icons/contour_flow.svg", "icons/contour_flow.png",
    "core/__init__.py", "core/workflow.py", "core/options.py", "core/input_validation.py",
    "core/intervals.py", "core/grid.py", "core/report.py", "core/interpolation.py",
    "core/extent.py", "core/contouring.py", "core/clipping.py", "core/smoothing.py",
    "core/styling.py", "core/output.py",
    "utils/__init__.py", "utils/qgis_helpers.py",
]
#: Path fragments that must never be packaged.
FORBIDDEN = ("__pycache__", ".pyc", ".pyo", ".git", "tests/", "integration_output", "sample_data",
             ".aux.xml", ".DS_Store", "Thumbs.db", ".idea", ".vscode", "~")
#: Directory and file names skipped while collecting.
SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "tests"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".aux.xml", "~", ".orig", ".rej", ".bak")

#: metadata.txt fields required by the QGIS plugin repository.
REQUIRED_METADATA = ["name", "qgisMinimumVersion", "description", "about", "version", "author", "email", "repository"]


class PackagingError(Exception):
    pass


def step(title):
    print(f"\n== {title}")


# ------------------------------------------------------------- 1. checks


def read_metadata(text_or_path, from_text=False):
    parser = configparser.ConfigParser(interpolation=None)
    if from_text:
        parser.read_string(text_or_path)
    else:
        with open(text_or_path, encoding="utf-8") as handle:
            parser.read_file(handle)
    return parser["general"]


def check_metadata():
    meta = read_metadata(os.path.join(SOURCE, "metadata.txt"))
    missing = [key for key in REQUIRED_METADATA if not meta.get(key, "").strip()]
    if missing:
        raise PackagingError(f"metadata.txt is missing required fields: {missing}")
    icon = meta.get("icon", "")
    if not icon or not os.path.isfile(os.path.join(SOURCE, icon)):
        raise PackagingError(f"metadata.txt icon '{icon}' does not exist in the package")
    if not icon.lower().endswith((".png", ".jpg", ".jpeg")):
        raise PackagingError("metadata.txt icon must be PNG or JPEG (QGIS plugin repository rule)")
    blockers = [key for key in REQUIRED_METADATA + ["homepage", "tracker"] if "todo" in meta.get(key, "").lower()]
    print(f"  name={meta['name']} version={meta['version']} qgis={meta['qgisMinimumVersion']}-"
          f"{meta.get('qgisMaximumVersion', '')} experimental={meta.get('experimental', 'False')}")
    for key in blockers:
        print(f"  RELEASE BLOCKER: metadata field '{key}' is still a placeholder: {meta[key]}")
    return meta, blockers


def fast_checks(run_tests):
    step("1. Fast checks")
    count = 0
    for folder, dirs, files in os.walk(SOURCE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                py_compile.compile(os.path.join(folder, name), cfile=os.path.join(tempfile.gettempdir(), "cf_compile.pyc"),
                                   doraise=True)
                count += 1
    print(f"  byte-compiled {count} plugin modules")
    if run_tests:
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                cwd=REPO, capture_output=True, text=True)
        summary = [line for line in result.stderr.splitlines() if line.startswith(("Ran ", "OK", "FAILED"))]
        print("  unit tests: " + " / ".join(summary))
        if result.returncode != 0:
            print(result.stderr[-3000:])
            raise PackagingError("unit tests failed")
    return check_metadata()


# -------------------------------------------------------------- 2. build


def collect_files():
    files = []
    for folder, dirs, names in os.walk(SOURCE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            if name.startswith(".") or name.endswith(SKIP_SUFFIXES):
                continue
            path = os.path.join(folder, name)
            files.append((path, os.path.relpath(path, SOURCE).replace(os.sep, "/")))
    return files


def build_zip(output_dir, version):
    step("2. Build ZIP")
    os.makedirs(output_dir, exist_ok=True)
    target = os.path.join(output_dir, f"contour-flow-{version}.zip")
    if os.path.exists(target):
        os.remove(target)
    files = collect_files()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            archive.write(path, f"{PACKAGE}/{relative}")
    print(f"  {os.path.relpath(target, REPO)}: {len(files)} files, {os.path.getsize(target):,} bytes")
    return target


# ----------------------------------------------------------- 3. validate


def validate_zip(path, version):
    step("3. Validate ZIP")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise PackagingError("ZIP is corrupt")
        names = archive.namelist()
        tops = {name.split("/")[0] for name in names}
        problems = []
        if tops != {PACKAGE}:
            problems.append(f"expected one top-level folder '{PACKAGE}/', found {sorted(tops)}")
        inside = {name[len(PACKAGE) + 1:] for name in names if name.startswith(PACKAGE + "/")}
        missing = [name for name in REQUIRED if name not in inside]
        if missing:
            problems.append(f"missing required files: {missing}")
        forbidden = [name for name in names if any(fragment in name for fragment in FORBIDDEN)]
        if forbidden:
            problems.append(f"forbidden files packaged: {forbidden[:10]}")
        meta = read_metadata(archive.read(f"{PACKAGE}/metadata.txt").decode("utf-8"), from_text=True)
        if meta["version"] != version:
            problems.append(f"metadata version {meta['version']} != {version}")
        if f"{PACKAGE}/{meta.get('icon', '')}" not in names:
            problems.append("metadata icon not in the ZIP")
        if os.path.getsize(path) > 25 * 1024 * 1024:
            problems.append("ZIP exceeds the 25 MB plugin repository limit")
    if problems:
        raise PackagingError("ZIP validation failed:\n  - " + "\n  - ".join(problems))
    print(f"  one top-level folder '{PACKAGE}/'; {len(REQUIRED)} required files present; "
          f"no tests/caches/VCS/sample data; metadata version {version}; icon present")
    return names


# ------------------------------------------------------- 4. install test

INSTALL_TEST = r'''
import faulthandler, json, os, sys
faulthandler.enable()
zip_path, root, repo, expected_version, expected_email = sys.argv[1:6]
profile = os.path.join(root, "profile")
plugins = os.path.join(profile, "python", "plugins")
os.makedirs(plugins, exist_ok=True)
# Nothing from the repository may be importable: only the extracted ZIP.
sys.path = [p for p in sys.path if os.path.abspath(p or ".") != os.path.abspath(repo)]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qgis.core import Qgis, QgsApplication, QgsProject
QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
app = QgsApplication([], True, profile)          # isolated settings/profile folder
app.initQgis()
sys.path.append(os.path.join(os.environ["QGIS_PREFIX_PATH"], "python", "plugins"))
from processing.core.Processing import Processing
Processing.initialize()
results = {}
def ok(name, value=True):
    results[name] = value
    print(("PASS " if value else "FAIL ") + name, flush=True)

from pyplugin_installer.unzip import unzip      # the Plugin Manager's own ZIP extraction
unzip(zip_path, plugins)
ok("extracted with the Plugin Manager unzip routine", os.path.isfile(os.path.join(plugins, "contour_flow", "metadata.txt")))

import qgis.utils
from qgis.PyQt.QtWidgets import QMainWindow, QMenu, QToolBar
from qgis.gui import QgsMapCanvas, QgsMessageBar

class Iface:
    def __init__(self):
        self.window, self.toolbar, self.menu = QMainWindow(), QToolBar("Plugins"), QMenu("Plugins")
        self.window.addToolBar(self.toolbar)
        self.canvas, self.bar = QgsMapCanvas(), QgsMessageBar()
    def mainWindow(self): return self.window
    def mapCanvas(self): return self.canvas
    def messageBar(self): return self.bar
    def addToolBarIcon(self, a): self.toolbar.addAction(a)
    def removeToolBarIcon(self, a): self.toolbar.removeAction(a)
    def submenu(self, name):
        return next((a.menu() for a in self.menu.actions() if a.menu() and a.menu().title() == name), None)
    def addPluginToMenu(self, name, a): (self.submenu(name) or self.menu.addMenu(name)).addAction(a)
    def removePluginMenu(self, name, a):
        m = self.submenu(name); m.removeAction(a)
        if not m.actions(): self.menu.removeAction(m.menuAction())

qgis.utils.iface = Iface()
qgis.utils.plugin_paths = [plugins]
sys.path.insert(0, plugins)
qgis.utils.updateAvailablePlugins()
ok("QGIS discovers the plugin", "contour_flow" in qgis.utils.available_plugins)
ok("metadata name is 'Contour Flow'", qgis.utils.pluginMetadata("contour_flow", "name") == "Contour Flow")
ok(f"loaded plugin reports version {expected_version}",
   qgis.utils.pluginMetadata("contour_flow", "version") == expected_version)
ok(f"packaged metadata has support email {expected_email}",
   qgis.utils.pluginMetadata("contour_flow", "email") == expected_email)
log = []
QgsApplication.messageLog().messageReceived.connect(lambda message, tag, level: log.append((tag, level, message)))
ok("plugin loads", qgis.utils.loadPlugin("contour_flow"))
ok("plugin starts (enabled)", qgis.utils.startPlugin("contour_flow"))
import contour_flow
ok("code comes from the extracted ZIP", os.path.abspath(contour_flow.__file__).startswith(os.path.abspath(plugins)))
iface = qgis.utils.iface
plugin = qgis.utils.plugins["contour_flow"]
actions = iface.toolbar.actions()
ok("one toolbar action 'Contour Flow' with icon", len(actions) == 1 and actions[0].text() == "Contour Flow"
   and not actions[0].icon().isNull())
ok("Plugins menu entry", iface.submenu("Contour Flow") is not None)

project = QgsProject.instance()
ok("sample project opens", project.read(os.path.join(repo, "sample_data", "contour_flow_sample.qgs")))
layers = {l.name(): l for l in project.mapLayers().values()}
plugin.show_dialog()
dialog = plugin.dialog
ok("dialog opens", dialog is not None and dialog.isVisible() and dialog.windowTitle() == "Contour Flow")

dialog.point_mode_radio.setChecked(True)
dialog.point_layer_combo.setLayer(layers["sample_wells"])
dialog.value_field_combo.setField("gw_elev")
dialog.boundary_layer_combo.setLayer(layers["site_boundary"])
before = set(project.mapLayers())
dialog.generate_button.click()
added = [project.mapLayer(i) for i in set(project.mapLayers()) - before]
ok("sample points generate contours", len(added) == 1 and added[0].featureCount() > 0)
point_contours = added[0] if added else None
if point_contours is not None:  # output must be an ordinary editable layer
    feature = next(point_contours.getFeatures())
    geometry = feature.geometry()
    geometry.translate(1.0, 1.0)
    editable = (point_contours.startEditing() and point_contours.changeGeometry(feature.id(), geometry)
                and point_contours.changeAttributeValue(feature.id(), point_contours.fields().indexOf("is_major"), 1)
                and point_contours.commitChanges())
    ok("output layer is editable (geometry + attribute edit committed)", bool(editable))

dialog.raster_mode_radio.setChecked(True)
dialog.raster_layer_combo.setLayer(layers["sample_dem"])
dialog.boundary_layer_combo.setLayer(None)
before = set(project.mapLayers())
dialog.generate_button.click()
added = [project.mapLayer(i) for i in set(project.mapLayers()) - before]
ok("sample raster generates contours", len(added) == 1 and added[0].featureCount() > 0)

ok("plugin unloads", qgis.utils.unloadPlugin("contour_flow"))
ok("no toolbar/menu left after unload", not iface.toolbar.actions() and iface.submenu("Contour Flow") is None)
project.clear()
for _ in range(3):
    QgsApplication.processEvents()
errors = [m for tag, level, m in log if level == Qgis.MessageLevel.Critical or "Traceback" in m]
ok("no critical messages or tracebacks in the QGIS log", not errors)
for message in errors[:5]:
    print("  LOG: " + message[:300], flush=True)
failed = [k for k, v in results.items() if not v]
print(json.dumps({"passed": len(results) - len(failed), "failed": failed}), flush=True)
os._exit(1 if failed else 0)
'''


def install_test(zip_path, meta):
    step("4. Isolated install test (temporary QGIS profile)")
    import importlib.util

    if importlib.util.find_spec("qgis") is None:
        print("  SKIPPED: not running with QGIS's Python (use scripts\\run_with_qgis.bat)")
        return None
    root = tempfile.mkdtemp(prefix="contour_flow_install_")
    script = os.path.join(root, "install_test.py")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(INSTALL_TEST)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUNBUFFERED="1")
    try:
        result = subprocess.run([sys.executable, script, zip_path, root, REPO, meta["version"], meta["email"]],
                                cwd=root, env=env,
                                capture_output=True, text=True, timeout=600)
        lines = [line for line in result.stdout.splitlines() if line.startswith(("PASS", "FAIL", "{"))]
        for line in lines:
            print("  " + line)
        if "Traceback" in result.stderr or "Traceback" in result.stdout:
            print(result.stderr[-3000:])
            raise PackagingError("a Python traceback appeared during the isolated install test")
        if result.returncode != 0:
            print(result.stderr[-3000:])
            raise PackagingError(f"isolated install test failed (exit code {result.returncode})")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"  temporary profile removed: {root}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build and validate the Contour Flow release ZIP.")
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--no-install-test", action="store_true")
    parser.add_argument("--output", default=os.path.join(REPO, "dist"))
    args = parser.parse_args()
    try:
        meta, blockers = fast_checks(not args.no_tests)
        zip_path = build_zip(args.output, meta["version"])
        validate_zip(zip_path, meta["version"])
        installed = None if args.no_install_test else install_test(zip_path, meta)
    except PackagingError as exc:
        print(f"\nPACKAGING FAILED: {exc}")
        return 1
    print(f"\nPackage ready: {zip_path}")
    if installed is None:
        print("Note: the isolated install test did not run.")
    if blockers:
        print(f"Release blockers in metadata.txt: {', '.join(blockers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

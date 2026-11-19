# SPDX-License-Identifier: GPL-2.0-or-later
"""Capture README screenshots with real QGIS (no mock-ups).

Run with QGIS's Python, from the repository root::

    scripts\\run_with_qgis.bat scripts\\capture_screenshots.py

Writes to ``docs/images/``:

* ``dialog.png`` and ``dialog_advanced.png``: the real Contour Flow dialog,
  rendered by Qt, set up for the sample groundwater test;
* ``groundwater_contours.png``: QGIS map rendering of the sample groundwater
  contours (Groundwater style, major labels) with the wells and site boundary;
* ``dem_contours.png``: QGIS map rendering of contours from the sample DEM;
* ``dialog_groundwater.png``: the dialog in Groundwater Mode (calculated heads,
  flow arrows on);
* ``groundwater_flow.png``: Groundwater Mode result: light-smoothed GW
  contours and GW Flow Direction arrows with the wells and site boundary.

The contours are produced by the plugin's own workflow on ``sample_data/``.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
OUT = os.path.join(REPO, "docs", "images")

from qgis.core import QgsApplication  # noqa: E402


def render_map(layers, extent, path, size=(960, 680)):
    from qgis.core import QgsMapRendererParallelJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor

    settings = QgsMapSettings()
    settings.setLayers(layers)
    settings.setDestinationCrs(layers[0].crs())
    settings.setOutputSize(QSize(*size))
    settings.setBackgroundColor(QColor("white"))
    settings.setOutputDpi(120)
    settings.setExtent(extent)
    job = QgsMapRendererParallelJob(settings)
    job.start()
    job.waitForFinished()
    if not job.renderedImage().save(path):
        raise RuntimeError(f"could not save {path}")
    print(f"  {os.path.relpath(path, REPO)}")


def main():
    from qgis.core import QgsProject

    from contour_flow.core import groundwater as gw
    from contour_flow.core import options as opt
    from contour_flow.core.workflow import ContourRequest, run_contour_workflow
    from contour_flow.ui.contour_dialog import ContourDialog

    os.makedirs(OUT, exist_ok=True)
    project = QgsProject.instance()
    if not project.read(os.path.join(REPO, "sample_data", "contour_flow_sample.qgs")):
        raise RuntimeError(project.error())
    layers = {layer.name(): layer for layer in project.mapLayers().values()}
    wells, site, dem = layers["sample_wells"], layers["site_boundary"], layers["sample_dem"]

    # --- the dialog, set up for sample test 1 (groundwater)
    dialog = ContourDialog()
    dialog.point_mode_radio.setChecked(True)
    dialog.point_layer_combo.setLayer(wells)
    dialog.value_field_combo.setField("gw_elev")
    dialog.boundary_layer_combo.setLayer(site)
    dialog.style_combo.setCurrentIndex(dialog.style_combo.findData(opt.STYLE_GROUNDWATER))
    dialog.label_mode_combo.setCurrentIndex(dialog.label_mode_combo.findData(opt.LABELS_MAJOR))
    dialog.resize(520, 1010)
    dialog.show()
    QgsApplication.processEvents()
    dialog._refresh_summary()
    QgsApplication.processEvents()
    dialog.grab().save(os.path.join(OUT, "dialog.png"))
    print(f"  {os.path.relpath(os.path.join(OUT, 'dialog.png'), REPO)}")
    dialog.advanced_group.setCollapsed(False)
    dialog.resize(500, 1400)
    QgsApplication.processEvents()
    dialog.scroll_contents.grab().save(os.path.join(OUT, "dialog_advanced.png"))
    print(f"  {os.path.relpath(os.path.join(OUT, 'dialog_advanced.png'), REPO)}")
    dialog.cleanup()
    dialog.hide()

    # --- sample groundwater contours
    result = run_contour_workflow(ContourRequest(
        point_layer=wells, value_field="gw_elev", boundary_layer=site,
        style_preset=opt.STYLE_GROUNDWATER, label_mode=opt.LABELS_MAJOR))
    contours = result.contour_layer
    project.addMapLayer(contours)
    extent = site.extent().buffered(45)
    render_map([wells, contours, site], extent, os.path.join(OUT, "groundwater_contours.png"))

    # --- DEM contours over the sample DEM
    result = run_contour_workflow(ContourRequest(
        source_type="raster", raster_layer=dem, style_preset=opt.STYLE_TOPOGRAPHIC,
        label_mode=opt.LABELS_MAJOR, label_decimals=1))
    dem_contours = result.contour_layer
    project.addMapLayer(dem_contours)
    render_map([dem_contours, dem], dem.extent(), os.path.join(OUT, "dem_contours.png"))

    # --- Groundwater Mode: dialog and result
    dialog = ContourDialog()
    dialog.point_layer_combo.setLayer(wells)
    dialog.boundary_layer_combo.setLayer(site)
    dialog.mode_combo.setCurrentIndex(dialog.mode_combo.findData(gw.MODE_GROUNDWATER))
    dialog.gw_method_combo.setCurrentIndex(dialog.gw_method_combo.findData(gw.GW_CALCULATED))
    dialog.flow_arrows_check.setChecked(True)
    dialog.resize(520, 1080)
    dialog.show()
    QgsApplication.processEvents()
    dialog._refresh_summary()
    QgsApplication.processEvents()
    dialog.grab().save(os.path.join(OUT, "dialog_groundwater.png"))
    print(f"  {os.path.relpath(os.path.join(OUT, 'dialog_groundwater.png'), REPO)}")
    dialog.cleanup()
    dialog.hide()

    result = run_contour_workflow(ContourRequest(
        mode=gw.MODE_GROUNDWATER, point_layer=wells, value_field="gw_elev", boundary_layer=site,
        smoothing_mode=opt.SMOOTH_LIGHT, flow_arrows=True, style_preset=opt.STYLE_GROUNDWATER,
        label_mode=opt.LABELS_MAJOR))
    project.addMapLayers([result.contour_layer, result.arrow_layer])
    render_map([wells, result.arrow_layer, result.contour_layer, site], extent,
               os.path.join(OUT, "groundwater_flow.png"))
    for line in result.summary:
        if "flow" in line.lower():
            print(f"    {line}")
    project.clear()


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Qt's offscreen platform only renders text if it is given a font folder.
    windows_fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(windows_fonts):
        os.environ.setdefault("QT_QPA_FONTDIR", windows_fonts)
    QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
    app = QgsApplication([], True)
    app.initQgis()
    from qgis.PyQt.QtGui import QFont

    app.setFont(QFont("Segoe UI", 9))
    sys.path.append(os.path.join(os.environ["QGIS_PREFIX_PATH"], "python", "plugins"))
    from processing.core.Processing import Processing

    Processing.initialize()
    code = 0
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"ERROR: {exc}")
        code = 1
    sys.stdout.flush()
    os._exit(code)

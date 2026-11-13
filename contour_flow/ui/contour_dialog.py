# SPDX-License-Identifier: GPL-2.0-or-later
"""Main Contour Flow dialog.

The layout lives in ``contour_dialog.ui`` and is loaded at runtime with
``qgis.PyQt.uic.loadUiType``, so no generated ``ui_*.py`` file is committed.
This module holds the dialog's behaviour only:

* configuring the QGIS widgets (layer/field/band filters, file pickers);
* showing only the controls that matter for the current choices;
* cheap live validation that enables "Generate Contours";
* a compact summary computed with ``core.workflow.plan_contours``, which is
  the same planning step the run uses;
* running ``core.workflow.run_contour_workflow`` with a progress dialog and
  Cancel, then adding the returned layers to the project.

No GIS processing happens here; that belongs in ``contour_flow.core``.
Layers are never cached by ID. Every check reads the widgets' *current*
layers. The only external objects this dialog connects to are the current
point and boundary layers (selection and feature changes). ``cleanup()``
releases those connections.
"""

import html
import os
import traceback

from qgis.core import Qgis, QgsFieldProxyModel, QgsProcessingFeedback, QgsProject
from qgis.gui import QgsFileWidget
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QCoreApplication, Qt, QTimer
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import QApplication, QDialog, QProgressDialog

from ..core import ContourCancelled, ContourError
from ..core.input_validation import (
    DUPLICATE_LABELS,
    DUPLICATES_KEEP_FIRST,
    DUPLICATES_MEAN,
    DUPLICATES_STOP,
    FEATURES_ALL,
    FEATURES_SELECTED,
    is_numeric_field,
    point_input_problem,
    raster_input_problem,
)
from ..core.intervals import INTERVAL_AUTO, INTERVAL_FIXED
from ..core import options as opt
from ..core.workflow import (
    SOURCE_POINTS,
    SOURCE_RASTER,
    ContourRequest,
    plan_contours,
    run_contour_workflow,
)
from ..utils.qgis_helpers import PLUGIN_NAME, log_message, plugin_version

#: Shown in the dialog's diagnostics row. Update at each milestone.
BUILD_STATUS = "Professional controls development build"

#: Layer signals that trigger re-validation (point and boundary layers).
WATCHED_LAYER_SIGNALS = ("selectionChanged", "featureAdded", "featuresDeleted")

#: The summary is refreshed automatically only below these sizes.
SUMMARY_AUTO_MAX_FEATURES = 100_000
SUMMARY_AUTO_MAX_CELLS = 50_000_000
SUMMARY_DELAY_MS = 600

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "contour_dialog.ui")
)


def _fill(combo, items):
    for data, text in items:
        combo.addItem(text, data)


def _show(visible, *widgets):
    for widget in widgets:
        widget.setVisible(visible)


class ContourDialog(QDialog, FORM_CLASS):
    """Modeless main dialog. One instance is kept by the plugin and reused."""

    def __init__(self, parent=None, map_canvas=None):
        super().__init__(parent)
        self.setupUi(self)

        # Layers whose signals are connected: {"point": layer, "boundary": layer}.
        self._watched = {}
        self._running = False

        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(SUMMARY_DELAY_MS)
        self._summary_timer.timeout.connect(self._refresh_summary_if_cheap)

        self._configure_widgets(map_canvas)
        self._connect_signals()
        self._fill_diagnostics()

        self._watch("point", self.point_layer_combo.currentLayer())
        self._watch("boundary", self.boundary_layer_combo.currentLayer())
        self._update_custom_extent_crs()
        self._on_inputs_changed()

    # ------------------------------------------------------------------ setup

    def _configure_widgets(self, map_canvas):
        self.point_layer_combo.setFilters(Qgis.LayerFilter.PointLayer)
        self.raster_layer_combo.setFilters(Qgis.LayerFilter.RasterLayer)
        self.boundary_layer_combo.setFilters(Qgis.LayerFilter.PolygonLayer)
        self.boundary_layer_combo.setAllowEmptyLayer(True, "None")
        self.boundary_layer_combo.setLayer(None)

        # Numeric = Int | LongLong | Double.
        self.value_field_combo.setFilters(QgsFieldProxyModel.Filter.Numeric)
        self.value_field_combo.setLayer(self.point_layer_combo.currentLayer())
        self.raster_band_combo.setLayer(self.raster_layer_combo.currentLayer())

        _fill(self.feature_mode_combo, [(FEATURES_ALL, "All features"), (FEATURES_SELECTED, "Selected features only")])
        _fill(self.duplicate_mode_combo, [
            (mode, DUPLICATE_LABELS[mode]) for mode in (DUPLICATES_KEEP_FIRST, DUPLICATES_MEAN, DUPLICATES_STOP)
        ])
        _fill(self.method_combo, [
            (m, opt.METHOD_LABELS[m]) for m in (opt.METHOD_TIN_LINEAR, opt.METHOD_TIN_CLOUGH_TOCHER, opt.METHOD_IDW)
        ])
        self.idw_power_spin.setValue(opt.IDW_POWER_DEFAULT)
        _fill(self.extent_mode_combo, list(opt.EXTENT_LABELS.items()))
        _fill(self.boundary_mode_combo, [(opt.BOUNDARY_ALL, "All features"), (opt.BOUNDARY_SELECTED, "Selected features only")])
        _fill(self.interval_mode_combo, [(INTERVAL_AUTO, "Automatic (approximate count)"), (INTERVAL_FIXED, "Fixed interval")])
        self.major_every_spin.setValue(opt.MAJOR_EVERY_DEFAULT)
        _fill(self.smoothing_combo, list(opt.SMOOTH_LABELS.items()))
        self.smooth_iterations_spin.setMaximum(opt.SMOOTH_MAX_ITERATIONS)
        _fill(self.label_mode_combo, list(opt.LABEL_LABELS.items()))
        self.label_mode_combo.setCurrentIndex(self.label_mode_combo.findData(opt.LABELS_MAJOR))
        self.label_decimals_spin.setMaximum(opt.LABEL_PRECISION_MAX)
        _fill(self.style_combo, [(key, value["label"]) for key, value in opt.STYLE_PRESETS.items()])
        _fill(self.output_mode_combo, [(opt.OUTPUT_TEMPORARY, "Temporary layer"), (opt.OUTPUT_GEOPACKAGE, "Save to GeoPackage")])
        _fill(self.surface_mode_combo, [
            (opt.SURFACE_NONE, "Do not add"),
            (opt.SURFACE_TEMPORARY, "Add as temporary raster"),
            (opt.SURFACE_GEOTIFF, "Save as GeoTIFF"),
        ])

        for widget, file_filter, title in (
            (self.geopackage_file_widget, "GeoPackage (*.gpkg)", "GeoPackage for contours"),
            (self.surface_file_widget, "GeoTIFF (*.tif)", "GeoTIFF for the interpolated surface"),
        ):
            widget.setStorageMode(QgsFileWidget.StorageMode.SaveFile)
            widget.setFilter(file_filter)
            widget.setDialogTitle(title)
            # Never replace files: GeoPackages get a new layer, GeoTIFFs a new name.
            widget.setConfirmOverwrite(False)

        if map_canvas is not None:
            self.custom_extent_widget.setMapCanvas(map_canvas)

    def _connect_signals(self):
        """Connect signals of widgets owned by this dialog (die with it)."""
        changed = self._on_inputs_changed
        self.point_mode_radio.toggled.connect(changed)
        # Order matters: update the dependent widget first, then validate.
        self.point_layer_combo.layerChanged.connect(self.value_field_combo.setLayer)
        self.point_layer_combo.layerChanged.connect(self._on_point_layer_changed)
        self.raster_layer_combo.layerChanged.connect(self.raster_band_combo.setLayer)
        self.raster_layer_combo.layerChanged.connect(changed)
        self.boundary_layer_combo.layerChanged.connect(self._on_boundary_layer_changed)

        for signal in (
            self.value_field_combo.fieldChanged,
            self.raster_band_combo.bandChanged,
            self.feature_mode_combo.currentIndexChanged,
            self.duplicate_mode_combo.currentIndexChanged,
            self.method_combo.currentIndexChanged,
            self.idw_power_spin.valueChanged,
            self.cell_size_spin.valueChanged,
            self.extent_mode_combo.currentIndexChanged,
            self.buffer_spin.valueChanged,
            self.custom_extent_widget.extentChanged,
            self.boundary_mode_combo.currentIndexChanged,
            self.interval_mode_combo.currentIndexChanged,
            self.target_count_spin.valueChanged,
            self.fixed_interval_spin.valueChanged,
            self.smoothing_combo.currentIndexChanged,
            self.label_mode_combo.currentIndexChanged,
            self.output_mode_combo.currentIndexChanged,
            self.surface_mode_combo.currentIndexChanged,
            self.geopackage_file_widget.fileChanged,
            self.surface_file_widget.fileChanged,
        ):
            signal.connect(changed)

        self.refresh_summary_button.clicked.connect(self._refresh_summary)
        self.generate_button.clicked.connect(self._on_generate_clicked)
        self.button_box.rejected.connect(self.reject)

    def _fill_diagnostics(self):
        self.qgis_version_value.setText(Qgis.version())
        self.plugin_version_value.setText(plugin_version())
        self.status_value.setText(BUILD_STATUS)

    # -------------------------------------------------- external layer tracking

    def _on_point_layer_changed(self, layer):
        self._watch("point", layer)
        self._update_custom_extent_crs()
        self._on_inputs_changed()

    def _on_boundary_layer_changed(self, layer):
        self._watch("boundary", layer)
        self._on_inputs_changed()

    def _watch(self, role, layer):
        """Follow selection and feature changes of ``layer`` (one per role)."""
        self._unwatch(role)
        if layer is None:
            return
        for signal_name in WATCHED_LAYER_SIGNALS:
            getattr(layer, signal_name).connect(self._on_inputs_changed)
        self._watched[role] = layer

    def _unwatch(self, role):
        layer = self._watched.pop(role, None)
        if layer is None:
            return
        for signal_name in WATCHED_LAYER_SIGNALS:
            try:
                getattr(layer, signal_name).disconnect(self._on_inputs_changed)
            except (RuntimeError, TypeError):
                # RuntimeError: the layer was already deleted, which also
                # removed its connections. TypeError: already disconnected.
                pass

    def cleanup(self):
        """Release connections to objects outside this dialog (unload/reload)."""
        self._summary_timer.stop()
        for role in list(self._watched):
            self._unwatch(role)

    def _update_custom_extent_crs(self):
        layer = self._current_point_layer()
        if layer is None:
            return
        self.custom_extent_widget.setOutputCrs(layer.crs())
        self.custom_extent_widget.setOriginalExtent(layer.extent(), layer.crs())
        if not self.custom_extent_widget.isValid():
            self.custom_extent_widget.setCurrentExtent(layer.extent(), layer.crs())

    # ------------------------------------------------------ current choices

    def _is_point_mode(self):
        return self.point_mode_radio.isChecked()

    def _current_point_layer(self):
        layer = self.point_layer_combo.currentLayer()
        return layer if layer is not None and layer.isValid() else None

    def _current_raster_layer(self):
        layer = self.raster_layer_combo.currentLayer()
        return layer if layer is not None and layer.isValid() else None

    def _current_boundary_layer(self):
        layer = self.boundary_layer_combo.currentLayer()
        return layer if layer is not None and layer.isValid() else None

    def _build_request(self):
        point_mode = self._is_point_mode()
        return ContourRequest(
            source_type=SOURCE_POINTS if point_mode else SOURCE_RASTER,
            point_layer=self._current_point_layer(),
            value_field=self.value_field_combo.currentField(),
            selected_only=self.feature_mode_combo.currentData() == FEATURES_SELECTED,
            duplicate_mode=self.duplicate_mode_combo.currentData(),
            method=self.method_combo.currentData(),
            idw_power=self.idw_power_spin.value(),
            cell_size=self.cell_size_spin.value(),
            extent_mode=self.extent_mode_combo.currentData(),
            buffer_distance=self.buffer_spin.value(),
            custom_extent=self.custom_extent_widget.outputExtent() if self.custom_extent_widget.isValid() else None,
            custom_extent_crs=self.custom_extent_widget.outputCrs(),
            raster_layer=self._current_raster_layer(),
            raster_band=self.raster_band_combo.currentBand(),
            boundary_layer=self._current_boundary_layer(),
            boundary_selected_only=self.boundary_mode_combo.currentData() == opt.BOUNDARY_SELECTED,
            interval_mode=self.interval_mode_combo.currentData(),
            target_count=self.target_count_spin.value(),
            fixed_interval=self.fixed_interval_spin.value(),
            major_every=self.major_every_spin.value(),
            smoothing_mode=self.smoothing_combo.currentData(),
            smooth_iterations=self.smooth_iterations_spin.value(),
            smooth_offset=self.smooth_offset_spin.value(),
            keep_unsmoothed=self.keep_unsmoothed_check.isChecked(),
            label_mode=self.label_mode_combo.currentData(),
            label_decimals=self.label_decimals_spin.value(),
            style_preset=self.style_combo.currentData(),
            output_mode=self.output_mode_combo.currentData(),
            geopackage_path=self.geopackage_file_widget.filePath().strip(),
            output_name=self.output_name_edit.text(),
            surface_mode=self.surface_mode_combo.currentData() if point_mode else opt.SURFACE_NONE,
            surface_path=self.surface_file_widget.filePath().strip(),
        )

    # ------------------------------------------------- visibility/validation

    def _on_inputs_changed(self, *_args):
        if self._running:
            return
        self._update_visibility()
        self._validate()
        self._schedule_summary()

    def _update_visibility(self):
        point_mode = self._is_point_mode()
        self.point_input_widget.setVisible(point_mode)
        self.raster_input_widget.setVisible(not point_mode)
        self.interpolation_group.setVisible(point_mode)
        self.extent_group.setVisible(point_mode)

        _show(self.method_combo.currentData() == opt.METHOD_IDW, self.idw_power_caption, self.idw_power_spin)
        extent_mode = self.extent_mode_combo.currentData()
        self.buffer_spin.setEnabled(extent_mode == opt.EXTENT_BUFFERED_HULL)
        self.buffer_caption.setEnabled(extent_mode == opt.EXTENT_BUFFERED_HULL)
        _show(extent_mode == opt.EXTENT_CUSTOM, self.custom_extent_caption, self.custom_extent_widget)

        has_boundary = self._current_boundary_layer() is not None
        for widget in (self.boundary_mode_caption, self.boundary_mode_combo,
                       self.boundary_count_caption, self.boundary_count_label):
            widget.setEnabled(has_boundary)

        automatic = self.interval_mode_combo.currentData() == INTERVAL_AUTO
        self.target_count_spin.setEnabled(automatic)
        self.fixed_interval_spin.setEnabled(not automatic)

        smoothing = self.smoothing_combo.currentData()
        _show(smoothing == opt.SMOOTH_CUSTOM, self.smooth_iterations_caption, self.smooth_iterations_spin,
              self.smooth_offset_caption, self.smooth_offset_spin)
        self.keep_unsmoothed_check.setEnabled(smoothing != opt.SMOOTH_NONE)
        self.label_decimals_spin.setEnabled(self.label_mode_combo.currentData() != opt.LABELS_NONE)

        geopackage = self.output_mode_combo.currentData() == opt.OUTPUT_GEOPACKAGE
        self.geopackage_file_widget.setEnabled(geopackage)
        self.geopackage_caption.setEnabled(geopackage)
        _show(point_mode, self.surface_mode_caption, self.surface_mode_combo,
              self.surface_file_caption, self.surface_file_widget)
        geotiff = self.surface_mode_combo.currentData() == opt.SURFACE_GEOTIFF
        self.surface_file_widget.setEnabled(geotiff)
        self.surface_file_caption.setEnabled(geotiff)

    def _update_counts(self):
        layer = self._current_point_layer()
        if layer is None:
            text = "-"
        else:
            total = layer.featureCount()
            selected = layer.selectedFeatureCount()
            text = f"{selected} of {total}" if total >= 0 else f"{selected} (total unknown)"
        self.selection_count_label.setText(text)
        boundary = self._current_boundary_layer()
        self.boundary_count_label.setText(
            "-" if boundary is None else f"{boundary.selectedFeatureCount()} of {boundary.featureCount()}"
        )

    def _point_problem(self):
        layer = self._current_point_layer()
        if layer is not None and self.value_field_combo.count() == 0:
            return "The point layer has no numeric fields."
        field_name = self.value_field_combo.currentField()
        problem = point_input_problem(
            has_layer=layer is not None,
            field_name=field_name,
            field_is_numeric=is_numeric_field(layer, field_name),
            feature_mode=self.feature_mode_combo.currentData(),
            total_count=layer.featureCount() if layer is not None else 0,
            selected_count=layer.selectedFeatureCount() if layer is not None else 0,
        )
        if problem:
            return problem
        if self.method_combo.currentData() == opt.METHOD_IDW:
            problem = opt.idw_power_problem(self.idw_power_spin.value())
            if problem:
                return problem
        problem = opt.extent_problem(
            self.extent_mode_combo.currentData(),
            self._current_boundary_layer() is not None,
            self.buffer_spin.value(),
            self.custom_extent_widget.isValid(),
        )
        if problem:
            return problem
        if self.surface_mode_combo.currentData() == opt.SURFACE_GEOTIFF:
            return opt.output_path_problem(self.surface_file_widget.filePath().strip(), ".tif", "GeoTIFF")
        return None

    def _live_problem(self):
        """Cheap checks only. Data checks run in the summary and the run."""
        if self._is_point_mode():
            problem = self._point_problem()
        else:
            problem = raster_input_problem(
                self._current_raster_layer() is not None, self.raster_band_combo.currentBand()
            )
        if problem:
            return problem
        boundary = self._current_boundary_layer()
        problem = opt.boundary_problem(
            boundary is not None,
            self.boundary_mode_combo.currentData(),
            boundary.selectedFeatureCount() if boundary is not None else 0,
        )
        if problem:
            return problem
        if self.output_mode_combo.currentData() == opt.OUTPUT_GEOPACKAGE:
            return opt.output_path_problem(self.geopackage_file_widget.filePath().strip(), ".gpkg", "GeoPackage")
        return None

    def _validate(self, *_args):
        """Re-check the current inputs and update the UI. Returns True if valid."""
        self._update_counts()
        problem = self._live_problem()
        self.generate_button.setEnabled(problem is None and not self._running)
        self.validation_label.setText(problem or "Inputs look valid.")
        return problem is None

    # ---------------------------------------------------------------- summary

    def _schedule_summary(self):
        self._summary_timer.start()

    def _summary_is_cheap(self):
        if self._is_point_mode():
            layer = self._current_point_layer()
            return layer is not None and 0 <= layer.featureCount() <= SUMMARY_AUTO_MAX_FEATURES
        layer = self._current_raster_layer()
        return layer is not None and layer.width() * layer.height() <= SUMMARY_AUTO_MAX_CELLS

    def _refresh_summary_if_cheap(self):
        if not self.isVisible():
            return  # refreshed again by showEvent
        if self._summary_is_cheap():
            self._refresh_summary()
        else:
            self.summary_label.setText("Large input: click <b>Refresh summary</b> to compute it.")

    def _refresh_summary(self):
        if self._running:
            return
        problem = self._live_problem()
        if problem:
            self.summary_label.setText(html.escape(problem))
            return
        try:
            plan = plan_contours(self._build_request())
        except Exception:  # noqa: BLE001 - never break the dialog over a preview
            log_message("Summary failed:\n" + traceback.format_exc(), Qgis.MessageLevel.Warning)
            self.summary_label.setText("The summary could not be computed (see the log).")
            return
        parts = [html.escape(line) for line in plan.summary_lines()]
        parts += [f'<span style="color:#b00020;"><b>Error:</b> {html.escape(e)}</span>' for e in plan.errors]
        for warning in plan.warnings:
            style = "color:#b00020;" if warning.startswith("IMPORTANT:") else "color:#8a5a00;"
            parts.append(f'<span style="{style}">{html.escape(warning)}</span>')
        self.summary_label.setText("<br>".join(parts) or "-")

    # ---------------------------------------------------------------- events

    def showEvent(self, event):  # noqa: N802 - Qt override
        """Re-validate whenever the dialog is shown (inputs may have changed)."""
        super().showEvent(event)
        self._on_inputs_changed()

    def _set_running(self, running):
        self._running = running
        self.scroll_area.setEnabled(not running)
        self.generate_button.setEnabled(not running)

    def _on_generate_clicked(self):
        # Re-check first: something may have changed without a signal we follow.
        if not self._validate():
            return
        request = self._build_request()

        feedback = QgsProcessingFeedback()
        progress = QProgressDialog("Starting...", "Cancel", 0, 100, self)
        progress.setWindowTitle(PLUGIN_NAME)
        # Application-modal: QGIS stays responsive enough to repaint and to
        # accept Cancel, but cannot start other work during the run.
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(feedback.cancel)
        feedback.progressChanged.connect(lambda value: progress.setValue(int(value)))

        def on_stage(text, index, count):
            progress.setLabelText(f"{text}... ({index + 1}/{count})")
            QCoreApplication.processEvents()

        self._set_running(True)
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        progress.show()
        try:
            result = run_contour_workflow(request, feedback=feedback, on_stage=on_stage)
        except ContourCancelled:
            self.message_bar.pushMessage(
                PLUGIN_NAME, "Cancelled. Nothing was added.", level=Qgis.MessageLevel.Info, duration=6
            )
            return
        except ContourError as exc:
            log_message(f"Contour generation stopped: {exc}", Qgis.MessageLevel.Warning)
            self.message_bar.pushMessage(
                "Cannot generate contours", str(exc), level=Qgis.MessageLevel.Critical, duration=0
            )
            return
        except Exception:  # noqa: BLE001 - unexpected bug: report, don't crash QGIS
            log_message("Unexpected error:\n" + traceback.format_exc(), Qgis.MessageLevel.Critical)
            self.message_bar.pushMessage(
                "Unexpected error",
                "See the Log Messages panel, 'Contour Flow' tab, for details.",
                level=Qgis.MessageLevel.Critical,
                duration=0,
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
            progress.deleteLater()
            self._set_running(False)
            self._on_inputs_changed()

        project = QgsProject.instance()
        for layer in ([result.surface_layer] if result.surface_layer is not None else []) + result.extra_layers:
            project.addMapLayer(layer)
        project.addMapLayer(result.contour_layer)

        log_message("\n".join(["Contours generated."] + result.summary + result.warnings))
        self.message_bar.pushMessage(
            PLUGIN_NAME,
            f"Created '{result.contour_layer.name()}' with {result.contour_layer.featureCount()} line(s) "
            f"at interval {result.interval:g}. Settings are in Layer Properties > Metadata.",
            level=Qgis.MessageLevel.Success,
            duration=10,
        )
        if result.warnings:
            important = any(w.startswith("IMPORTANT:") for w in result.warnings)
            self.message_bar.pushMessage(
                "Please check" if important else "Note",
                " ".join(result.warnings),
                level=Qgis.MessageLevel.Critical if important else Qgis.MessageLevel.Warning,
                duration=0,
            )

# SPDX-License-Identifier: GPL-2.0-or-later
"""Plans and runs contour generation. The only entry points the UI calls.

``plan_contours(request)`` does everything that is cheap and decides the run:
reading and checking point values, extent and clip polygon, cell size,
interval and level count. The dialog uses it for its live summary, and the
run uses the same plan, so the summary is what will happen.

``run_contour_workflow(request)`` then executes::

    points: interpolate (TIN/IDW) over the extent ──┐
    raster: [crop to boundary bbox] ────────────────┴─> GDAL contour
      -> editable copy with value / is_major -> [clip to polygon] -> [smooth]
      -> [GeoPackage] -> style + labels + metadata

Source layers are only read. Nothing is added to the project; the caller does
that with the returned layers. On failure or cancellation, files and
GeoPackage layers written by this run are removed again.
"""

import os
import shutil
from dataclasses import dataclass, field

from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingMultiStepFeedback,
    QgsProject,
    QgsRasterLayer,
)

from ..utils.qgis_helpers import plugin_version
from . import ContourCancelled, ContourError
from .clipping import clip_lines, crop_raster, mask_surface
from .contouring import editable_copy, raster_value_range, run_contour
from .extent import (
    boundary_geometry,
    fraction_outside,
    point_processing_area,
    points_hull,
    transform_rectangle,
)
from .grid import auto_cell_size, grid_problem
from .input_validation import (
    DUPLICATE_LABELS,
    DUPLICATES_KEEP_FIRST,
    crs_warnings,
    is_numeric_field,
    point_data_report,
    prepare_point_samples,
    raster_range_problem,
)
from .interpolation import build_point_layer, read_point_samples, run_interpolation
from .intervals import INTERVAL_AUTO, level_count, resolve_interval
from .options import (
    BOUNDARY_ALL,
    BOUNDARY_SELECTED,
    EXTENT_BUFFERED_HULL,
    EXTENT_CUSTOM,
    EXTENT_LABELS,
    EXTENT_POINTS,
    LABEL_LABELS,
    LABELS_MAJOR,
    LABELS_NONE,
    MAJOR_EVERY_DEFAULT,
    METHOD_IDW,
    METHOD_LABELS,
    METHOD_TIN_LINEAR,
    OUTPUT_GEOPACKAGE,
    OUTPUT_TEMPORARY,
    SMOOTH_LABELS,
    SMOOTH_NONE,
    STYLE_NEUTRAL,
    STYLE_PRESETS,
    SURFACE_GEOTIFF,
    SURFACE_NONE,
    boundary_problem,
    clean_layer_name,
    default_layer_name,
    extent_problem,
    idw_power_problem,
    label_precision_problem,
    major_every_problem,
    output_path_problem,
    smoothing_parameters,
    suggested_label_precision,
    unique_file_path,
    unique_name,
)
from .output import geopackage_layer_names, remove_written, write_geopackage_layer
from .report import METADATA_PROPERTY, metadata_json, metadata_text
from .smoothing import smooth_lines
from .styling import apply_style

SOURCE_POINTS = "points"
SOURCE_RASTER = "raster"

#: Share of the processing area outside the points' hull worth a warning.
OUTSIDE_HULL_WARNING_FRACTION = 0.001


@dataclass
class ContourRequest:
    """Everything the user chose in the dialog, as plain values."""

    source_type: str = SOURCE_POINTS
    # Point input
    point_layer: object = None
    value_field: str = ""
    selected_only: bool = False
    duplicate_mode: str = DUPLICATES_KEEP_FIRST
    method: str = METHOD_TIN_LINEAR
    idw_power: float = 2.0
    cell_size: float = 0.0  # 0 = automatic
    extent_mode: str = EXTENT_POINTS
    buffer_distance: float = 0.0
    custom_extent: object = None  # QgsRectangle
    custom_extent_crs: object = None  # QgsCoordinateReferenceSystem
    # Raster input
    raster_layer: object = None
    raster_band: int = 1
    # Boundary (both inputs)
    boundary_layer: object = None
    boundary_selected_only: bool = False
    # Contours
    interval_mode: str = INTERVAL_AUTO
    target_count: int = 10
    fixed_interval: float = 1.0
    major_every: int = MAJOR_EVERY_DEFAULT
    smoothing_mode: str = SMOOTH_NONE
    smooth_iterations: int = 1
    smooth_offset: float = 0.25
    keep_unsmoothed: bool = False
    label_mode: str = LABELS_MAJOR
    label_decimals: int = 2
    style_preset: str = STYLE_NEUTRAL
    # Output
    output_mode: str = OUTPUT_TEMPORARY
    geopackage_path: str = ""
    output_name: str = ""
    surface_mode: str = SURFACE_NONE
    surface_path: str = ""


@dataclass
class ContourPlan:
    request: ContourRequest
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    crs: object = None
    base_name: str = ""
    samples: object = None
    raw_count: int = 0
    value_min: float = None
    value_max: float = None
    interval: float = None
    levels: int = None
    cell_size: float = None
    cell_size_auto: bool = False
    extent: object = None  # QgsRectangle, processing CRS
    clip_polygon: object = None  # QgsGeometry or None
    smoothing: tuple = None  # (iterations, offset) or None

    @property
    def ok(self):
        return not self.errors

    def summary_lines(self):
        """Short preview lines for the dialog (no settings echo)."""
        r = self.request
        lines = []
        if r.source_type == SOURCE_POINTS and self.samples is not None:
            usable = len(self.samples.points)
            lines.append(f"Points: {usable} usable, {self.raw_count - usable} skipped or merged")
        elif r.source_type == SOURCE_RASTER and r.raster_layer is not None:
            lines.append(f"Raster band: {r.raster_band}")
        if self.value_min is not None:
            lines.append(f"Range: {self.value_min:g} to {self.value_max:g}")
        if r.source_type == SOURCE_POINTS and self.cell_size is not None:
            method = METHOD_LABELS.get(r.method, r.method)
            if r.method == METHOD_IDW:
                method += f", power {r.idw_power:g}"
            lines.append(f"Method: {method}")
            lines.append(f"Cell size: {self.cell_size:g}{' (automatic)' if self.cell_size_auto else ''}")
            lines.append(f"Extent: {EXTENT_LABELS.get(r.extent_mode, r.extent_mode)}")
        if r.boundary_layer is not None:
            lines.append(f"Clipped to: {r.boundary_layer.name()}")
        if self.interval is not None:
            lines.append(f"Interval: {self.interval:g}, about {self.levels} contour level(s)")
        return lines


def _current_is_canceled(feedback):
    return feedback is not None and feedback.isCanceled()


# ------------------------------------------------------------------ planning


def _plan_options(plan):
    r = plan.request
    for problem in (
        major_every_problem(r.major_every),
        label_precision_problem(r.label_decimals),
        None if r.style_preset in STYLE_PRESETS else f"Unknown style preset: {r.style_preset!r}.",
        None if r.label_mode in LABEL_LABELS else f"Unknown label mode: {r.label_mode!r}.",
    ):
        if problem:
            plan.errors.append(problem)
    plan.smoothing, problem = smoothing_parameters(r.smoothing_mode, r.smooth_iterations, r.smooth_offset)
    if problem:
        plan.errors.append(problem)
    if r.output_mode == OUTPUT_GEOPACKAGE:
        problem = output_path_problem(r.geopackage_path, ".gpkg", "GeoPackage")
        if problem:
            plan.errors.append(problem)
    elif r.output_mode != OUTPUT_TEMPORARY:
        plan.errors.append(f"Unknown output mode: {r.output_mode!r}.")
    if r.source_type == SOURCE_POINTS and r.surface_mode == SURFACE_GEOTIFF:
        problem = output_path_problem(r.surface_path, ".tif", "GeoTIFF")
        if problem:
            plan.errors.append(problem)
    if r.boundary_layer is not None:
        if not r.boundary_layer.isValid():
            plan.errors.append("The boundary layer is not available.")
        else:
            problem = boundary_problem(
                True,
                BOUNDARY_SELECTED if r.boundary_selected_only else BOUNDARY_ALL,
                r.boundary_layer.selectedFeatureCount(),
            )
            if problem:
                plan.errors.append(problem)


def _boundary(plan, project):
    r = plan.request
    if r.boundary_layer is None:
        return None
    geometry, warnings = boundary_geometry(
        r.boundary_layer, r.boundary_selected_only, plan.crs, project.transformContext()
    )
    plan.warnings.extend(warnings)
    return geometry


def _set_interval(plan):
    r = plan.request
    plan.interval, problem = resolve_interval(
        r.interval_mode, plan.value_min, plan.value_max, r.target_count, r.fixed_interval
    )
    if problem:
        plan.errors.append(problem)
        return
    plan.levels = level_count(plan.value_min, plan.value_max, plan.interval)
    needed = suggested_label_precision(plan.interval)
    if r.label_mode != LABELS_NONE and r.label_decimals < needed:
        plan.warnings.append(
            f"Labels use {r.label_decimals} decimal(s), but interval {plan.interval:g} needs {needed} "
            "to show every level exactly."
        )


def _plan_points(plan, project, feedback):
    r = plan.request
    layer = r.point_layer
    if layer is None or not layer.isValid():
        plan.errors.append("The point layer is not available.")
        return
    if not is_numeric_field(layer, r.value_field):
        plan.errors.append(f"Field '{r.value_field}' is not a numeric field of the point layer.")
        return
    if r.method not in METHOD_LABELS:
        plan.errors.append(f"Unknown interpolation method: {r.method!r}.")
    elif r.method == METHOD_IDW and idw_power_problem(r.idw_power):
        plan.errors.append(idw_power_problem(r.idw_power))
    custom_valid = r.custom_extent is not None and not r.custom_extent.isEmpty()
    problem = extent_problem(r.extent_mode, r.boundary_layer is not None, r.buffer_distance, custom_valid)
    if problem:
        plan.errors.append(problem)
    if plan.errors:
        return

    plan.crs = layer.crs()
    plan.base_name = r.value_field
    raw, skipped = read_point_samples(layer, r.value_field, r.selected_only, feedback)
    plan.raw_count = len(raw) + skipped
    plan.samples = prepare_point_samples(raw, skipped, r.duplicate_mode)
    errors, warnings = point_data_report(plan.samples, r.value_field)
    plan.errors.extend(errors)
    plan.warnings.extend(warnings)
    plan.warnings.extend(
        crs_warnings(plan.crs.isValid(), plan.crs.isGeographic(), plan.crs.userFriendlyIdentifier())
    )
    if errors:
        return
    values = [p[2] for p in plan.samples.points]
    plan.value_min, plan.value_max = min(values), max(values)

    hull = points_hull(plan.samples.points)
    boundary = _boundary(plan, project)
    custom = None
    if r.extent_mode == EXTENT_CUSTOM:
        custom = transform_rectangle(
            r.custom_extent, r.custom_extent_crs or plan.crs, plan.crs, project.transformContext()
        )
    plan.extent, plan.clip_polygon = point_processing_area(
        r.extent_mode, plan.samples.points, hull, r.buffer_distance, boundary, custom
    )
    if r.extent_mode == EXTENT_BUFFERED_HULL and plan.crs.isGeographic():
        plan.warnings.append(
            f"The hull buffer of {r.buffer_distance:g} is in degrees, because the point layer's CRS is geographic."
        )

    outside = fraction_outside(plan.extent, plan.clip_polygon, hull)
    if outside > OUTSIDE_HULL_WARNING_FRACTION:
        share = f"{outside:.0%}" if outside >= 0.01 else "<1%"
        if r.method == METHOD_IDW:
            plan.warnings.append(
                f"IMPORTANT: {share} of the processing area lies outside the convex hull of the "
                "points. IDW extrapolates values there; treat those contours with caution."
            )
        else:
            plan.warnings.append(
                f"{share} of the processing area lies outside the convex hull of the points. "
                "TIN gives no values there, so contours stop at the hull."
            )

    plan.cell_size_auto = not r.cell_size > 0
    plan.cell_size = (
        auto_cell_size(plan.extent.width(), plan.extent.height()) if plan.cell_size_auto else r.cell_size
    )
    problem = grid_problem(plan.extent.width(), plan.extent.height(), plan.cell_size)
    if problem:
        plan.errors.append(problem)
        return
    _set_interval(plan)


def _plan_raster(plan, project):
    r = plan.request
    layer = r.raster_layer
    if layer is None or not layer.isValid():
        plan.errors.append("The raster layer is not available.")
        return
    if layer.providerType() != "gdal":
        plan.errors.append(
            f"Raster '{layer.name()}' is not a file-based (GDAL) raster; only those can be contoured."
        )
        return
    if not 1 <= r.raster_band <= layer.bandCount():
        plan.errors.append(f"Raster '{layer.name()}' has no band {r.raster_band}.")
        return
    plan.crs = layer.crs()
    plan.base_name = layer.name()
    plan.warnings.extend(crs_warnings(plan.crs.isValid(), False, "", role="raster layer"))

    vmin, vmax, valid_cells = raster_value_range(layer, r.raster_band)
    problem = raster_range_problem(vmin, vmax, valid_cells, r.raster_band)
    if problem:
        plan.errors.append(problem)
        return
    plan.value_min, plan.value_max = vmin, vmax

    boundary = _boundary(plan, project)
    plan.extent = layer.extent()
    if boundary is not None:
        plan.clip_polygon = boundary
        plan.extent = layer.extent().intersect(boundary.boundingBox())
        if plan.extent.isEmpty():
            plan.errors.append("The boundary does not overlap the raster.")
            return
    _set_interval(plan)


def plan_contours(request, project=None, feedback=None):
    """Check ``request`` and work out the run. Never raises for user problems."""
    project = project or QgsProject.instance()
    plan = ContourPlan(request)
    _plan_options(plan)
    try:
        if request.source_type == SOURCE_POINTS:
            _plan_points(plan, project, feedback)
        elif request.source_type == SOURCE_RASTER:
            _plan_raster(plan, project)
        else:
            plan.errors.append(f"Unknown source type: {request.source_type!r}.")
    except ContourError as exc:
        plan.errors.append(str(exc))
    return plan


# ------------------------------------------------------------------ metadata


def metadata_items(plan, output_description):
    r = plan.request
    points = r.source_type == SOURCE_POINTS
    items = [
        ("Plugin version", plugin_version()),
        ("QGIS version", Qgis.version()),
        ("Input type", "Point layer" if points else "Raster"),
    ]
    if points:
        items += [
            ("Source layer", r.point_layer.name()),
            ("Source field", r.value_field),
            ("Feature mode", "Selected features only" if r.selected_only else "All features"),
            ("Duplicate locations", DUPLICATE_LABELS[r.duplicate_mode]),
            ("Points used", len(plan.samples.points)),
            ("Points skipped or merged", plan.raw_count - len(plan.samples.points)),
            ("Interpolation method", METHOD_LABELS[r.method]),
        ]
        if r.method == METHOD_IDW:
            items.append(("IDW power (distance coefficient)", r.idw_power))
        items += [
            ("Cell size", plan.cell_size),
            ("Cell size mode", "automatic" if plan.cell_size_auto else "manual"),
            ("Extent mode", EXTENT_LABELS[r.extent_mode]),
        ]
        if r.extent_mode == EXTENT_BUFFERED_HULL:
            items.append(("Hull buffer distance", r.buffer_distance))
    else:
        items += [("Source layer", r.raster_layer.name()), ("Band", r.raster_band)]
    e = plan.extent
    items += [
        ("Processing extent (xmin, ymin, xmax, ymax)", (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum())),
        ("Boundary layer", r.boundary_layer.name() if r.boundary_layer is not None else None),
    ]
    if r.boundary_layer is not None:
        items.append(("Boundary features", "Selected only" if r.boundary_selected_only else "All"))
    items += [
        ("CRS", plan.crs.authid() if plan.crs is not None and plan.crs.isValid() else None),
        ("Value range", (plan.value_min, plan.value_max)),
        ("Contour interval", plan.interval),
        (
            "Interval mode",
            f"automatic (about {r.target_count} contours)" if r.interval_mode == INTERVAL_AUTO else "fixed",
        ),
        ("Contour levels", plan.levels),
        ("Major contour every", f"{r.major_every} intervals ({plan.interval * r.major_every:g})"),
        (
            "Smoothing",
            SMOOTH_LABELS[r.smoothing_mode]
            + (f" (iterations {plan.smoothing[0]}, offset {plan.smoothing[1]:g})" if plan.smoothing else ""),
        ),
        (
            "Labels",
            LABEL_LABELS[r.label_mode]
            + (f", {r.label_decimals} decimals" if r.label_mode != LABELS_NONE else ""),
        ),
        ("Style preset", STYLE_PRESETS[r.style_preset]["label"]),
        ("Output", output_description),
    ]
    return items


def _apply_metadata(layer, items, warnings):
    metadata = layer.metadata()
    metadata.setAbstract(metadata_text(items, warnings))
    layer.setMetadata(metadata)
    layer.setCustomProperty(METADATA_PROPERTY, metadata_json(items, warnings))


# ----------------------------------------------------------------- execution


@dataclass
class ContourResult:
    contour_layer: object
    extra_layers: list = field(default_factory=list)  # e.g. unsmoothed copy
    surface_layer: object = None
    interval: float = 0.0
    warnings: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    metadata: list = field(default_factory=list)


def _steps(plan):
    r = plan.request
    steps = []
    if r.source_type == SOURCE_POINTS:
        steps.append(("interpolate", f"Interpolating ({METHOD_LABELS[r.method]})"))
    elif plan.clip_polygon is not None:
        steps.append(("crop", "Cropping raster to the boundary"))
    steps.append(("contour", "Extracting contours (GDAL)"))
    steps.append(("prepare", "Classifying major/minor contours"))
    if plan.clip_polygon is not None:
        steps.append(("clip", "Clipping contours"))
    if plan.smoothing:
        steps.append(("smooth", "Smoothing contours"))
    if r.source_type == SOURCE_POINTS and r.surface_mode != SURFACE_NONE:
        steps.append(("surface", "Preparing surface output"))
    if r.output_mode == OUTPUT_GEOPACKAGE:
        steps.append(("write", "Writing GeoPackage"))
    steps.append(("style", "Styling and labelling"))
    return steps


def run_contour_workflow(request, project=None, feedback=None, on_stage=None):
    """Generate contours. Raises ``ContourError`` (or ``ContourCancelled``).

    ``on_stage(text, index, count)`` is called as each stage starts.
    """
    project = project or QgsProject.instance()
    feedback = feedback or QgsProcessingFeedback()
    if on_stage:
        on_stage("Checking inputs", 0, 1)
    plan = plan_contours(request, project, feedback)
    if _current_is_canceled(feedback):
        raise ContourCancelled("Cancelled.")
    if plan.errors:
        raise ContourError(" ".join(plan.errors))

    written = []
    try:
        return _execute(plan, project, feedback, on_stage, written)
    except Exception:
        remove_written(written)
        raise


def _execute(plan, project, feedback, on_stage, written):
    r = plan.request
    points = r.source_type == SOURCE_POINTS
    warnings = list(plan.warnings)
    steps = _steps(plan)
    keys = [key for key, _ in steps]
    child = QgsProcessingMultiStepFeedback(len(steps), feedback)
    context = QgsProcessingContext()
    context.setProject(project)

    def stage(key):
        index = keys.index(key)
        child.setCurrentStep(index)
        if on_stage:
            on_stage(steps[index][1], index, len(steps))
        if feedback.isCanceled():
            raise ContourCancelled("Cancelled.")

    # 1. Surface to contour
    if points:
        stage("interpolate")
        point_layer = build_point_layer(plan.samples.points, plan.crs)
        surface_path = run_interpolation(
            point_layer, r.method, plan.cell_size, plan.extent, r.idw_power, "TEMPORARY_OUTPUT", context, child
        )
        surface = QgsRasterLayer(surface_path, "surface")
        if not surface.isValid():
            raise ContourError(f"Could not read the interpolated surface ({surface_path}).")
        vmin, vmax, cells = raster_value_range(surface, 1)
        if raster_range_problem(vmin, vmax, cells):
            raise ContourError(
                "The interpolated surface has no usable values in the processing extent "
                "(TIN only covers the convex hull of the points)."
            )
        contour_input, band = surface_path, 1
    else:
        contour_input, band = r.raster_layer, r.raster_band
        if plan.clip_polygon is not None:
            stage("crop")
            contour_input = crop_raster(r.raster_layer, plan.extent, context, child)

    # 2. Contours, editable copy, clip, smooth
    stage("contour")
    contour_path = run_contour(contour_input, band, plan.interval, context, child)
    stage("prepare")
    lines = editable_copy(contour_path, "contours", plan.crs, plan.interval, r.major_every)
    if plan.clip_polygon is not None:
        stage("clip")
        lines = clip_lines(lines, plan.clip_polygon, plan.crs, context, child)
    unsmoothed = lines
    if plan.smoothing:
        stage("smooth")
        lines = smooth_lines(lines, plan.smoothing[0], plan.smoothing[1], context, child)

    requested = clean_layer_name(r.output_name)
    final_name = requested or default_layer_name(plan.base_name, plan.interval, smoothed=bool(plan.smoothing))
    outputs = [(lines, final_name)]
    if plan.smoothing and r.keep_unsmoothed:
        outputs.append(
            (unsmoothed, f"{requested} unsmoothed" if requested else default_layer_name(plan.base_name, plan.interval))
        )

    # 3. Optional surface output
    surface_layer = None
    if points and r.surface_mode != SURFACE_NONE:
        stage("surface")
        target = "TEMPORARY_OUTPUT"
        if r.surface_mode == SURFACE_GEOTIFF:
            target = unique_file_path(r.surface_path)
            if target != r.surface_path:
                warnings.append(f"{r.surface_path} already exists; the surface was saved as {target}.")
        if plan.clip_polygon is not None:
            provider = surface.dataProvider()
            nodata = provider.sourceNoDataValue(1) if provider.sourceHasNoDataValue(1) else -9999.0
            surface_out = mask_surface(surface_path, plan.clip_polygon, plan.crs, nodata, target, context, child)
        elif target == "TEMPORARY_OUTPUT":
            surface_out = surface_path
        else:
            try:
                shutil.copyfile(surface_path, target)
            except OSError as exc:
                raise ContourError(f"Could not write the surface GeoTIFF {target}: {exc}") from exc
            surface_out = target
        if r.surface_mode == SURFACE_GEOTIFF:
            written.append(("file", surface_out, None))
        temporary = " (temporary)" if r.surface_mode != SURFACE_GEOTIFF else ""
        surface_layer = QgsRasterLayer(surface_out, f"Surface {plan.base_name} ({METHOD_LABELS[r.method]}){temporary}")
        if not surface_layer.isValid():
            raise ContourError(f"Could not load the surface output ({surface_out}).")

    # 4. Output: temporary or GeoPackage
    final_layers = []
    if r.output_mode == OUTPUT_GEOPACKAGE:
        stage("write")
        path = r.geopackage_path
        existing = geopackage_layer_names(path)
        if not os.path.exists(path):
            written.append(("file", path, None))
            new_file = True
        else:
            new_file = False
        for layer, name in outputs:
            safe = unique_name(name, existing)
            if safe != name:
                warnings.append(f"A layer named '{name}' already exists in {os.path.basename(path)}; saved as '{safe}'.")
            written_layer = write_geopackage_layer(layer, path, safe, project.transformContext())
            if not new_file:
                written.append(("gpkg_layer", path, safe))
            existing.append(safe)
            final_layers.append(written_layer)
        output_description = f"GeoPackage {path}"
    else:
        for layer, name in outputs:
            layer.setName(name)
            final_layers.append(layer)
        output_description = "Temporary layer (save it to keep it)"

    # 5. Style, labels, metadata
    stage("style")
    items = metadata_items(plan, output_description)
    for index, layer in enumerate(final_layers):
        apply_style(layer, r.style_preset, r.label_mode, r.label_decimals)
        layer_items = items + [("Smoothed geometry", bool(plan.smoothing) and index == 0)]
        _apply_metadata(layer, layer_items, warnings)
        if r.output_mode == OUTPUT_GEOPACKAGE:
            try:  # store the style in the GeoPackage so it reopens styled
                layer.saveStyleToDatabase(layer.name(), "Contour Generator style", True, "")
            except Exception:  # noqa: BLE001 - optional convenience
                warnings.append(f"The style could not be stored in the GeoPackage for '{layer.name()}'.")
    if surface_layer is not None:
        _apply_metadata(surface_layer, items, warnings)

    contour_layer = final_layers[0]
    if contour_layer.featureCount() == 0:
        warnings.append("No contour lines were produced.")
    summary = plan.summary_lines() + [
        f"Output: '{contour_layer.name()}' with {contour_layer.featureCount()} line(s)"
        + (", smoothed" if plan.smoothing else "")
    ]
    return ContourResult(
        contour_layer, final_layers[1:], surface_layer, plan.interval, warnings, summary, items
    )

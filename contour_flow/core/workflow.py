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
      -> style + labels + metadata -> [GeoPackage]

Source layers are only read. Nothing is added to the project; the caller does
that with the returned layers. On failure or cancellation, files and
GeoPackage layers written by this run are removed again.
"""

import os
import shutil
from dataclasses import dataclass, field

from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingFeedback,
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
from . import groundwater as gw
from .flow import FLOW_METHOD, build_flow_arrows
from .interpolation import build_point_layer, read_point_rows, read_point_samples, run_interpolation
from .intervals import INTERVAL_AUTO, auto_major_every, level_count, resolve_interval
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
    MAJOR_EVERY_AUTO,
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
    groundwater_smoothing_fallbacks,
    groundwater_smoothing_parameters,
    idw_power_problem,
    label_precision_problem,
    major_every_problem,
    output_path_problem,
    smoothing_parameters,
    suggested_label_precision,
    unique_file_path,
    unique_name,
)
from .output import geopackage_layer_names, load_geopackage_layer, remove_written, write_geopackage_layer
from .report import METADATA_PROPERTY, metadata_json, metadata_text
from .smoothing import max_displacement, smooth_groundwater, smooth_lines
from .styling import apply_arrow_style, apply_style

SOURCE_POINTS = "points"
SOURCE_RASTER = "raster"

#: Grids and raster crops extend this many cells beyond a clip polygon, so
#: contours near its edge are not lost (they are traced between cell centres).
EDGE_PADDING_CELLS = 2

#: Share of the processing area outside the points' hull worth a warning.
OUTSIDE_HULL_WARNING_FRACTION = 0.001


@dataclass
class ContourRequest:
    """Everything the user chose in the dialog, as plain values."""

    mode: str = gw.MODE_GENERAL
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
    major_every: int = MAJOR_EVERY_AUTO  # 0 = automatic
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
    # Groundwater Mode (ignored in General mode)
    gw_value_method: str = gw.GW_EXISTING  # head from value_field, or MP - DTW
    mp_field: str = ""
    dtw_field: str = ""
    ground_field: str = ""  # optional, QA only
    flow_arrows: bool = False
    arrow_count: int = gw.ARROW_COUNT_DEFAULT
    arrow_scaling: str = gw.ARROWS_UNIFORM
    arrow_length: float = 0.0  # 0 = automatic
    arrow_support: str = gw.ARROWS_HULL
    arrow_buffer: float = 0.0


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
    smoothing: tuple = None  # (iterations, offset[, simplify cells]) or None
    major_every: int = None  # resolved (automatic or chosen)
    head_stats: object = None  # groundwater.HeadStats (Groundwater Mode)
    hull: object = None  # QgsGeometry of the usable points
    boundary: object = None  # boundary union in the processing CRS
    arrow_support: object = None  # QgsGeometry where flow arrows may be drawn

    @property
    def ok(self):
        return not self.errors

    @property
    def groundwater(self):
        return self.request.mode == gw.MODE_GROUNDWATER

    def summary_lines(self):
        """Concise preview lines for the dialog; only applicable fields."""
        if self.groundwater:
            return self._groundwater_summary()
        r = self.request
        points = r.source_type == SOURCE_POINTS
        lines = []
        if points and self.samples is not None:
            usable = len(self.samples.points)
            lines.append(f"Usable points: {usable}")
            if self.raw_count > usable:
                lines.append(f"Skipped or merged: {self.raw_count - usable}")
        elif not points and r.raster_layer is not None:
            lines.append(f"Band: {r.raster_band}")
        if self.value_min is not None:
            decimals = 2 if self.value_max - self.value_min >= 1 else 4
            lines.append(f"Range: {self.value_min:.{decimals}f} – {self.value_max:.{decimals}f}")
        if points and self.cell_size is not None:
            method = METHOD_LABELS.get(r.method, r.method)
            if r.method == METHOD_IDW:
                method += f" (power {r.idw_power:g})"
            lines.append(f"Method: {method}")
            lines.append(f"Cell size: {self.cell_size:g}{_unit_suffix(self.crs)}"
                         f"{' (automatic)' if self.cell_size_auto else ''}")
            if r.extent_mode != EXTENT_POINTS:
                lines.append(f"Extent: {EXTENT_LABELS.get(r.extent_mode, r.extent_mode)}")
        if r.boundary_layer is not None:
            lines.append(f"Clipped to: {r.boundary_layer.name()}")
        if self.interval is not None:
            lines.append(f"Contour interval: {self.interval:g}")
            lines.append(f"Estimated levels: {self.levels}")
        return lines

    def _groundwater_summary(self):
        r = self.request
        lines = []
        if self.samples is not None:
            usable = len(self.samples.points)
            lines.append(f"Usable wells: {usable}")
            if self.raw_count > usable:
                lines.append(f"Skipped records: {self.raw_count - usable}")
        if self.value_min is not None:
            decimals = 2 if self.value_max - self.value_min >= 1 else 3
            lines.append(f"Head range: {self.value_min:.{decimals}f} \u2013 {self.value_max:.{decimals}f}")
        if self.cell_size is not None:
            method = METHOD_LABELS.get(r.method, r.method)
            if r.method == METHOD_IDW:
                method += f" (power {r.idw_power:g})"
            lines.append(f"Interpolation: {method}")
        if self.interval is not None:
            lines.append(f"Contour interval: {self.interval:g}")
            lines.append(f"Estimated contours: {self.levels}")
        lines.append(f"Smoothing: {SMOOTH_LABELS.get(r.smoothing_mode, r.smoothing_mode)}")
        if r.flow_arrows:
            lines.append(f"Flow arrows: on, {gw.ARROW_SUPPORT_LABELS.get(r.arrow_support, r.arrow_support).lower()}")
        else:
            lines.append("Flow arrows: off")
        if r.boundary_layer is not None:
            lines.append(f"Clipped to: {r.boundary_layer.name()}")
        return lines


def _unit_suffix(crs):
    """' m', ' ft', ' deg'... for the CRS's map units ('' if unknown)."""
    try:
        from qgis.core import QgsUnitTypes

        text = QgsUnitTypes.toAbbreviatedString(crs.mapUnits())
        return f" {text}" if text else ""
    except Exception:  # noqa: BLE001 - cosmetic only
        return ""


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
    smoothing = groundwater_smoothing_parameters if plan.groundwater else smoothing_parameters
    plan.smoothing, problem = smoothing(r.smoothing_mode, r.smooth_iterations, r.smooth_offset)
    if problem:
        plan.errors.append(problem)
    if plan.groundwater:
        _plan_groundwater_options(plan)
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


def _plan_groundwater_options(plan):
    r = plan.request
    if r.source_type != SOURCE_POINTS:
        plan.errors.append("Groundwater Mode works on point layers (monitoring wells).")
    if r.gw_value_method not in (gw.GW_EXISTING, gw.GW_CALCULATED):
        plan.errors.append(f"Unknown groundwater value method: {r.gw_value_method!r}.")
    if r.flow_arrows:
        if not (isinstance(r.arrow_count, int) and 1 <= r.arrow_count <= 500):
            plan.errors.append("The approximate arrow count must be a whole number from 1 to 500.")
        if r.arrow_scaling not in (gw.ARROWS_UNIFORM, gw.ARROWS_SCALED):
            plan.errors.append(f"Unknown arrow scaling: {r.arrow_scaling!r}.")
        if r.arrow_support not in gw.ARROW_SUPPORT_LABELS:
            plan.errors.append(f"Unknown arrow area: {r.arrow_support!r}.")
        elif r.arrow_support == gw.ARROWS_BOUNDARY and r.boundary_layer is None:
            plan.errors.append("Flow arrows 'within the boundary polygon' need a boundary layer.")
        elif r.arrow_support == gw.ARROWS_BUFFERED_HULL and not r.arrow_buffer > 0:
            plan.errors.append("The arrow hull buffer must be greater than 0.")
        if r.arrow_length < 0:
            plan.errors.append("The arrow length must be 0 (automatic) or positive.")


def _groundwater_field_problem(layer, r):
    names = set(layer.fields().names())
    if r.gw_value_method == gw.GW_CALCULATED:
        if not r.mp_field or not r.dtw_field:
            return "Choose both the measuring-point elevation field and the depth-to-water field."
        if r.mp_field == r.dtw_field:
            return "The measuring-point elevation and depth-to-water fields must be different."
        missing = [f for f in (r.mp_field, r.dtw_field) if f not in names]
    else:
        if not r.value_field:
            return "Choose a groundwater elevation field."
        missing = [r.value_field] if r.value_field not in names else []
    if r.ground_field and r.ground_field not in names:
        missing.append(r.ground_field)
    if missing:
        return f"Field(s) not found in the point layer: {', '.join(missing)}."
    return None


def _groundwater_samples(plan, layer, feedback):
    """Read heads (existing or MP - DTW), run groundwater QA. Returns errors."""
    r = plan.request
    calculated = r.gw_value_method == gw.GW_CALCULATED
    names = ["" if calculated else r.value_field, r.mp_field if calculated else "",
             r.dtw_field if calculated else "", r.ground_field]
    rows, skipped = read_point_rows(layer, names, r.selected_only, feedback)
    stats = gw.build_head_records(
        [(x, y, fid, *values) for x, y, fid, values in rows], r.gw_value_method, skipped
    )
    plan.head_stats = stats
    plan.raw_count = len(rows) + skipped
    describe = f"'{r.mp_field}' or '{r.dtw_field}'" if calculated else f"field '{r.value_field}'"
    raw = [(record.x, record.y, record.head) for record in stats.records if record.head is not None]
    plan.samples = prepare_point_samples(raw, 0, r.duplicate_mode)
    errors, warnings = point_data_report(plan.samples, describe, groundwater=True)
    if stats.usable == 0:
        errors = [f"No valid groundwater elevations: {describe} has no numeric values for the chosen features."]
    plan.warnings.extend(gw.head_value_warnings(stats, describe))
    plan.warnings.extend(warnings)
    plan.warnings.extend(gw.head_above_ground(stats.records))
    if calculated:
        plan.warnings.extend(gw.negative_depth_to_water(stats.records))
    if not errors:
        plan.warnings.extend(gw.outlier_warnings(plan.samples.points))
    return errors


def _plan_arrow_support(plan, boundary):
    """Polygon where flow arrows may be drawn; warns when it reaches beyond the wells."""
    r = plan.request
    if r.arrow_support == gw.ARROWS_HULL:
        support = QgsGeometry(plan.hull)
    elif r.arrow_support == gw.ARROWS_BUFFERED_HULL:
        support = plan.hull.buffer(r.arrow_buffer, 8)
    elif r.arrow_support == gw.ARROWS_BOUNDARY:
        support = QgsGeometry(boundary)
    else:
        support = QgsGeometry(plan.clip_polygon) if plan.clip_polygon is not None else QgsGeometry.fromRect(plan.extent)
    if boundary is not None and r.arrow_support != gw.ARROWS_BOUNDARY:
        support = support.intersection(boundary)
    if plan.clip_polygon is not None:
        support = support.intersection(plan.clip_polygon)
    if support.isEmpty() or support.area() <= 0:
        plan.errors.append("The flow-arrow area does not overlap the contoured area.")
        return
    plan.arrow_support = support
    outside = fraction_outside(plan.extent, support, plan.hull)
    if outside > OUTSIDE_HULL_WARNING_FRACTION:
        share = f"{outside:.0%}" if outside >= 0.01 else "<1%"
        if r.method == METHOD_IDW:
            plan.warnings.append(
                f"IMPORTANT: {share} of the flow-arrow area lies outside the monitoring-well network (convex hull). "
                "IDW extrapolates heads there, so arrows in that area are not supported by measurements."
            )
        else:
            plan.warnings.append(
                f"IMPORTANT: {share} of the flow-arrow area lies outside the monitoring-well network (convex hull). "
                "TIN gives no heads there, so no arrows are drawn outside the network."
            )


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
    plan.major_every = r.major_every or auto_major_every(plan.interval)
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
    if plan.groundwater:
        problem = _groundwater_field_problem(layer, r)
        if problem:
            plan.errors.append(problem)
            return
    elif not is_numeric_field(layer, r.value_field):
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
    if plan.groundwater:
        plan.base_name = "GW"
        errors = _groundwater_samples(plan, layer, feedback)
        plan.errors.extend(errors)
    else:
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
    plan.hull = hull
    boundary = _boundary(plan, project)
    plan.boundary = boundary
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
    if plan.clip_polygon is not None:
        # Contours are traced between cell centres, so nothing is produced in
        # the outer half cell of a grid. Pad the grid so contours reach the
        # clip polygon's edge; the exact vector clip removes the padding.
        plan.extent = plan.extent.buffered(EDGE_PADDING_CELLS * plan.cell_size)
    problem = grid_problem(plan.extent.width(), plan.extent.height(), plan.cell_size)
    if problem:
        plan.errors.append(problem)
        return
    _set_interval(plan)
    if plan.groundwater and r.flow_arrows:
        _plan_arrow_support(plan, boundary)


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
        items += [("Source layer", r.point_layer.name())]
        if plan.groundwater:
            items += _groundwater_metadata(plan)
        else:
            items.append(("Source field", r.value_field))
        items += [
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
        (
            "Major contour every",
            f"{plan.major_every} intervals ({plan.interval * plan.major_every:g})"
            + (" (automatic)" if r.major_every == MAJOR_EVERY_AUTO else ""),
        ),
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


def _groundwater_metadata(plan):
    r = plan.request
    if r.gw_value_method == gw.GW_CALCULATED:
        source = f"Calculated: '{r.mp_field}' (measuring-point elevation) - '{r.dtw_field}' (depth to water)"
    else:
        source = f"Existing field '{r.value_field}'"
    stats = plan.head_stats
    return [
        ("Mode", "Groundwater"),
        ("Groundwater elevation", source),
        ("Ground elevation field (QA only)", r.ground_field or None),
        ("Valid groundwater elevations", stats.usable if stats else None),
        ("Records without a usable head",
         (stats.null + stats.non_numeric + stats.skipped_geometries) if stats else None),
        ("Interpretation note", gw.DISCLAIMER),
    ]


def _arrow_metadata(plan, info):
    r = plan.request
    direction = info["direction"]
    gradient = info["gradient"]
    units_ok = plan.crs is not None and plan.crs.isValid() and not plan.crs.isGeographic()
    return [
        ("Flow arrows", f"{info['count']} arrow(s)"),
        ("Flow-direction method", FLOW_METHOD),
        ("Gradient sampling distance", round(info["step"], 6)),
        ("Arrow area", gw.ARROW_SUPPORT_LABELS[r.arrow_support]),
        ("Arrow spacing (approx.)", round(info["spacing"], 6)),
        ("Arrow length", ("scaled by gradient, up to " if r.arrow_scaling == gw.ARROWS_SCALED else "uniform, ")
         + f"{info['length']:g}"),
        ("Generalized flow direction",
         f"{direction[2]} (about {direction[0]:.0f} degrees; consistency {direction[1]:.2f}) - a generalized "
         "interpretation, not the direction everywhere" if direction else
         "not reported (too few arrows or directions too variable)"),
        ("Local hydraulic gradient (dimensionless)",
         f"median {gradient[0]:.3g}, range {gradient[1]:.3g}-{gradient[2]:.3g}; assumes heads and coordinates "
         "share a length unit; not a velocity or flux" if gradient and units_ok else
         "not reported" + ("" if units_ok else " (geographic or unknown CRS)")),
    ]


def _apply_metadata(layer, items, warnings):
    metadata = layer.metadata()
    metadata.setAbstract(metadata_text(items, warnings))
    layer.setMetadata(metadata)
    layer.setCustomProperty(METADATA_PROPERTY, metadata_json(items, warnings))


# ----------------------------------------------------------------- execution


@dataclass
class ContourResult:
    contour_layer: object
    extra_layers: list = field(default_factory=list)  # e.g. unsmoothed copy, flow arrows
    surface_layer: object = None
    interval: float = 0.0
    warnings: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    metadata: list = field(default_factory=list)
    arrow_layer: object = None


def _load_written_layer(memory_layer, path, name, warnings):
    """Load a layer just written to a GeoPackage, carrying over style and metadata.

    Falls back to the in-memory layer (with a warning) if loading fails, so a
    completed write is never rolled back.
    """
    try:
        loaded = load_geopackage_layer(path, name)
    except ContourError as exc:
        warnings.append(f"{exc} The in-memory copy was added instead.")
        return memory_layer
    loaded.setRenderer(memory_layer.renderer().clone())
    labeling = memory_layer.labeling()
    loaded.setLabeling(labeling.clone() if labeling is not None else None)
    loaded.setLabelsEnabled(memory_layer.labelsEnabled())
    loaded.setMetadata(memory_layer.metadata())
    loaded.setCustomProperty(METADATA_PROPERTY, memory_layer.customProperty(METADATA_PROPERTY))
    try:  # store the style in the GeoPackage so the layer reopens styled
        if hasattr(loaded, "saveStyleToDatabaseV2"):  # present in 3.44.15; the old call is deprecated
            loaded.saveStyleToDatabaseV2(name, "Contour Flow style", True, "")
        else:
            loaded.saveStyleToDatabase(name, "Contour Flow style", True, "")
    except Exception:  # noqa: BLE001 - optional convenience
        warnings.append(f"The style could not be stored in the GeoPackage for '{name}'.")
    # Saving the style creates the layer_styles table in a new file. Reopen the
    # provider's connection, otherwise GDAL reports "unable to open database
    # file" on the next feature count (seen with QGIS 3.44 / GDAL 3.13).
    loaded.reload()
    return loaded


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
    if plan.groundwater and r.flow_arrows:
        steps.append(("arrows", "Deriving flow arrows"))
    if r.source_type == SOURCE_POINTS and r.surface_mode != SURFACE_NONE:
        steps.append(("surface", "Preparing surface output"))
    steps.append(("style", "Styling and labelling"))
    if r.output_mode == OUTPUT_GEOPACKAGE:
        steps.append(("write", "Writing GeoPackage"))
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
    # Algorithms get the caller's feedback directly. QgsProcessingMultiStepFeedback
    # is deliberately NOT used: on QGIS 3.44.15, running algorithms through it
    # led to an access violation on the next event-loop pass after the run
    # (found by the real-QGIS tests). Overall progress is combined by the
    # caller from on_stage(index, count) and the per-algorithm progress.
    child = feedback
    context = QgsProcessingContext()
    context.setProject(project)

    def stage(key):
        index = keys.index(key)
        feedback.setProgress(0)
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
            # Pad the crop by a few cells (see EDGE_PADDING_CELLS); the vector clip is exact.
            layer = r.raster_layer
            pad = EDGE_PADDING_CELLS * max(layer.rasterUnitsPerPixelX(), layer.rasterUnitsPerPixelY())
            crop = plan.extent.buffered(pad).intersect(layer.extent())
            contour_input = crop_raster(layer, crop, context, child)

    # 2. Contours, editable copy, clip, smooth
    stage("contour")
    contour_path = run_contour(contour_input, band, plan.interval, context, child)
    stage("prepare")
    lines = editable_copy(contour_path, "contours", plan.crs, plan.interval, plan.major_every)
    if plan.clip_polygon is not None:
        stage("clip")
        lines = clip_lines(lines, plan.clip_polygon, plan.crs, context, child)
    unsmoothed = lines
    smoothing_items = []
    smoothed = bool(plan.smoothing)
    if plan.smoothing:
        stage("smooth")
        if plan.groundwater:
            lines, applied, rejected = smooth_groundwater(
                lines, plan.cell_size, groundwater_smoothing_fallbacks(plan.smoothing), context, child
            )
            smoothed = applied is not None
            smoothing_items, notes = _groundwater_smoothing_report(plan, applied, rejected, lines, unsmoothed)
            warnings.extend(notes)
        else:
            lines = smooth_lines(lines, plan.smoothing[0], plan.smoothing[1], context, child)

    requested = clean_layer_name(r.output_name)
    if plan.groundwater:
        final_name = requested or "GW Contours"
        unsmoothed_name = f"{final_name} - Unsmoothed"
    else:
        final_name = requested or default_layer_name(plan.base_name, plan.interval, smoothed=smoothed)
        unsmoothed_name = f"{requested} unsmoothed" if requested else default_layer_name(plan.base_name, plan.interval)
    outputs = [(lines, final_name, "contours")]
    if smoothed and r.keep_unsmoothed:
        outputs.append((unsmoothed, unsmoothed_name, "contours"))

    # Groundwater flow arrows from the interpolated head surface
    arrow_info = None
    if plan.groundwater and r.flow_arrows:
        stage("arrows")
        arrows, arrow_info = build_flow_arrows(
            surface, plan.arrow_support, plan.crs, plan.cell_size, r.arrow_count, r.arrow_scaling,
            r.arrow_length, "GW Flow Direction",
        )
        if arrow_info["count"] == 0:
            warnings.append("No flow arrows could be drawn in the chosen area (surface too small or flat).")
        else:
            outputs.append((arrows, "GW Flow Direction", "arrows"))

    # 3. Optional surface output. The file is only *opened* as a layer at the
    #    very end: on Windows an open GDAL handle locks the file, and a locked
    #    file could not be removed if a later step failed.
    surface_out = None
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

    # 4. Style, labels and metadata, on the in-memory layers
    stage("style")
    geopackage = r.output_mode == OUTPUT_GEOPACKAGE
    output_description = f"GeoPackage {r.geopackage_path}" if geopackage else "Temporary layer (save it to keep it)"
    items = metadata_items(plan, output_description) + smoothing_items
    if arrow_info is not None:
        items = items + _arrow_metadata(plan, arrow_info)
    for index, (layer, name, kind) in enumerate(outputs):
        layer.setName(name)
        if kind == "arrows":
            apply_arrow_style(layer, STYLE_PRESETS[r.style_preset]["color"])
            _apply_metadata(layer, items, warnings)
        else:
            apply_style(layer, r.style_preset, r.label_mode, r.label_decimals)
            _apply_metadata(layer, items + [("Smoothed geometry", smoothed and index == 0)], warnings)

    # 5. GeoPackage: write every layer first, then load them. No file handle
    #    is open until all writes have succeeded (see step 3).
    if geopackage:
        stage("write")
        path = r.geopackage_path
        existing = geopackage_layer_names(path)
        new_file = not os.path.exists(path)
        if new_file:
            written.append(("file", path, None))
        names = []
        for layer, name, _kind in outputs:
            safe = unique_name(name, existing)
            if safe != name:
                warnings.append(f"A layer named '{name}' already exists in {os.path.basename(path)}; saved as '{safe}'.")
            write_geopackage_layer(layer, path, safe, project.transformContext())
            if not new_file:
                written.append(("gpkg_layer", path, safe))
            existing.append(safe)
            names.append(safe)
        final_layers = []
        for (memory_layer, _name, _kind), safe in zip(outputs, names):
            final_layers.append(_load_written_layer(memory_layer, path, safe, warnings))
    else:
        final_layers = [layer for layer, _name, _kind in outputs]
    arrow_layer = None
    for (_layer, _name, kind), final in zip(outputs, final_layers):
        if kind == "arrows":
            arrow_layer = final
    final_layers = [final for (_l, _n, kind), final in zip(outputs, final_layers) if kind != "arrows"]

    # 6. Nothing below may raise: outputs are complete and must not be rolled back.
    surface_layer = None
    if surface_out is not None:
        temporary = " (temporary)" if r.surface_mode != SURFACE_GEOTIFF else ""
        surface_name = "GW Surface" if plan.groundwater else f"Surface {plan.base_name} ({METHOD_LABELS[r.method]})"
        surface_layer = QgsRasterLayer(surface_out, f"{surface_name}{temporary}")
        if surface_layer.isValid():
            _apply_metadata(surface_layer, items, warnings)
        else:
            warnings.append(f"The surface was written to {surface_out} but could not be loaded.")
            surface_layer = None

    contour_layer = final_layers[0]
    if contour_layer.featureCount() == 0:
        warnings.append("No contour lines were produced.")
    summary = plan.summary_lines() + [
        f"Output: '{contour_layer.name()}' with {contour_layer.featureCount()} line(s)"
        + (", smoothed" if smoothed else "")
    ]
    if arrow_info is not None:
        summary += _arrow_summary(plan, arrow_info)
    return ContourResult(
        contour_layer, final_layers[1:], surface_layer, plan.interval, warnings, summary, items, arrow_layer
    )


def _groundwater_smoothing_report(plan, applied, rejected, smoothed, original):
    """Metadata items and warnings for Groundwater smoothing."""
    cell = plan.cell_size
    notes = []
    if applied is None:
        notes.append("IMPORTANT: smoothing was skipped because every setting tried made contours cross or "
                     "become invalid; the contours are unsmoothed.")
        return [("Smoothing applied", "none (all settings produced crossings or invalid lines)")], notes
    iterations, offset, simplify, segment = applied
    if rejected:
        notes.append("Smoothing was reduced automatically to avoid contour crossings or invalid lines.")
    shift = max_displacement(smoothed, original)
    items = [
        ("Smoothing applied",
         f"Douglas-Peucker simplify {simplify * cell:.4g} ({simplify:g} cells), densify to "
         f"{segment * cell:.4g} ({segment:g} cells), Chaikin {iterations} iteration(s), offset {offset:g}"
         + (" (reduced automatically to avoid crossings)" if rejected else "")),
        ("Maximum smoothing displacement", round(shift, 4) if shift is not None else "not measured (large output)"),
        ("Smoothing validation", "no invalid geometries, no crossings between different levels"),
        ("Smoothing note", "Smoothing changes line geometry for readability only; it does not increase accuracy."),
    ]
    return items, notes


def _arrow_summary(plan, info):
    """Result lines for flow arrows: count, generalized direction, gradient (only when defensible)."""
    lines = [f"Flow arrows: {info['count']}"]
    direction = info["direction"]
    if direction:
        lines.append(
            f"General groundwater flow direction: {direction[2]} / approximately {direction[0]:.0f}° "
            "(generalized interpretation)"
        )
    elif info["count"]:
        lines.append("General flow direction: not reported (directions vary across the site)")
    gradient = info["gradient"]
    if gradient and plan.crs is not None and plan.crs.isValid() and not plan.crs.isGeographic():
        lines.append(f"Hydraulic gradient: median {gradient[0]:.2g} (range {gradient[1]:.2g}–{gradient[2]:.2g})")
    return lines

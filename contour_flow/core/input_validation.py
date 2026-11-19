# SPDX-License-Identifier: GPL-2.0-or-later
"""Input checks run before any processing.

Two levels of checking:

* **Live checks** (``point_input_problem``, ``raster_input_problem``): cheap
  "is there enough input to start?" checks the dialog runs on every change.
* **Data checks** (``prepare_point_samples``, ``point_data_report``,
  ``crs_warnings``, ``raster_range_problem``): run once, when contours are
  generated. They separate **errors** (contouring cannot proceed) from
  **warnings** (it proceeds, and the user is told what was assumed or skipped).

Design notes:

* This module does not import ``qgis``. Everything takes plain values, so it
  can be unit-tested with ordinary Python. ``is_numeric_field`` only calls
  methods on the layer object it is given.
* Checks report problems as short, plain-language sentences and never modify
  any layer.
* No assumption is made about what the numeric field represents (groundwater
  elevation, ground elevation, survey value, ...).
"""

import math
from dataclasses import dataclass, field

#: Feature-use modes for point input.
FEATURES_ALL = "all"
FEATURES_SELECTED = "selected"


def is_numeric_field(layer, field_name):
    """Return True if ``layer`` has a numeric field called ``field_name``.

    :param layer: a ``QgsVectorLayer`` (or ``None``).
    :param field_name: field name as returned by ``QgsFieldComboBox.currentField()``.
    """
    if layer is None or not field_name:
        return False
    fields = layer.fields()
    index = fields.lookupField(field_name)
    return index >= 0 and fields.at(index).isNumeric()


def usable_feature_count(feature_mode, total_count, selected_count):
    """Return how many features the chosen feature-use mode would use.

    ``total_count`` may be negative when the data provider cannot count
    features cheaply. That "unknown" value is passed through unchanged.
    """
    if feature_mode == FEATURES_ALL:
        return total_count
    if feature_mode == FEATURES_SELECTED:
        return selected_count
    raise ValueError(f"Unknown feature mode: {feature_mode!r}")


def point_input_problem(
    has_layer, field_name, field_is_numeric, feature_mode, total_count, selected_count
):
    """Return the first problem with point-mode inputs, or ``None`` if usable.

    :param has_layer: a valid point layer is selected.
    :param field_name: the selected field name ("" if none).
    :param field_is_numeric: the selected field exists and is numeric.
    :param feature_mode: ``FEATURES_ALL`` or ``FEATURES_SELECTED``.
    :param total_count: features in the layer (negative = unknown).
    :param selected_count: currently selected features in the layer.
    """
    if not has_layer:
        return "Choose a point layer."
    if not field_name:
        return "Choose a value / elevation field."
    if not field_is_numeric:
        return f"Field '{field_name}' is not numeric."
    count = usable_feature_count(feature_mode, total_count, selected_count)
    if count == 0:
        if feature_mode == FEATURES_SELECTED:
            return "Select one or more point features in QGIS, or switch to All features."
        return "The point layer has no features."
    return None


def raster_input_problem(has_layer, band=1):
    """Return the problem with raster-mode inputs, or ``None`` if usable."""
    if not has_layer:
        return "Choose a raster layer."
    if band is None or band < 1:
        return "Choose a raster band."
    return None


# ------------------------------------------------------------- data checks

#: Minimum number of distinct point locations for a TIN surface.
MIN_TIN_POINTS = 3

#: Points count as collinear when no point is further than this fraction of
#: the extent's length from the line through them.
COLLINEAR_TOLERANCE = 1e-6


#: How several points at exactly the same location are handled.
DUPLICATES_KEEP_FIRST = "keep_first"
DUPLICATES_MEAN = "mean"
DUPLICATES_STOP = "stop"
DUPLICATE_LABELS = {
    DUPLICATES_KEEP_FIRST: "Keep first value and warn",
    DUPLICATES_MEAN: "Average the values",
    DUPLICATES_STOP: "Stop if values differ",
}
#: Values at one location count as different when they differ by more than
#: this fraction of the overall value range.
DUPLICATE_VALUE_TOLERANCE = 1e-6
MAX_CONFLICT_EXAMPLES = 3


@dataclass
class PointSamples:
    """Point values prepared for interpolation.

    ``points`` holds one ``(x, y, value)`` per distinct location, with a
    finite value. Where several points share a location, ``value`` is the
    first one or the mean, depending on ``duplicate_mode``.
    """

    points: list = field(default_factory=list)
    missing_values: int = 0
    #: Extra points at already-used locations (all groups).
    duplicate_points: int = 0
    #: Locations with several points whose values are (nearly) equal.
    equal_duplicate_locations: int = 0
    #: Locations with several points whose values differ materially.
    conflicting_locations: int = 0
    #: Up to MAX_CONFLICT_EXAMPLES ``(x, y, [values])`` for messages.
    conflict_examples: list = field(default_factory=list)
    skipped_geometries: int = 0
    duplicate_mode: str = DUPLICATES_KEEP_FIRST


def prepare_point_samples(raw_samples, skipped_geometries=0, duplicate_mode=DUPLICATES_KEEP_FIRST):
    """Clean raw ``(x, y, value)`` samples, counting what was dropped.

    ``value`` may be ``None`` (NULL) or non-finite. Such samples are counted as
    missing and dropped. Exact duplicate locations are grouped. Their values
    are compared against a tolerance of ``DUPLICATE_VALUE_TOLERANCE`` x the
    overall value range.
    """
    if duplicate_mode not in DUPLICATE_LABELS:
        raise ValueError(f"Unknown duplicate mode: {duplicate_mode!r}")
    result = PointSamples(skipped_geometries=skipped_geometries, duplicate_mode=duplicate_mode)
    groups = {}  # insertion order = first occurrence order
    for x, y, value in raw_samples:
        if value is None or not math.isfinite(value):
            result.missing_values += 1
            continue
        groups.setdefault((x, y), []).append(value)

    all_values = [v for values in groups.values() for v in values]
    span = (max(all_values) - min(all_values)) if all_values else 0.0
    tolerance = max(span * DUPLICATE_VALUE_TOLERANCE, 1e-12)

    for (x, y), values in groups.items():
        if len(values) > 1:
            result.duplicate_points += len(values) - 1
            if max(values) - min(values) > tolerance:
                result.conflicting_locations += 1
                if len(result.conflict_examples) < MAX_CONFLICT_EXAMPLES:
                    result.conflict_examples.append((x, y, list(values)))
            else:
                result.equal_duplicate_locations += 1
        value = sum(values) / len(values) if duplicate_mode == DUPLICATES_MEAN else values[0]
        result.points.append((x, y, value))
    return result


def are_collinear(points, tolerance=COLLINEAR_TOLERANCE):
    """Return True if all ``(x, y, ...)`` points lie (almost) on one line."""
    if len(points) < 3:
        return True
    x0, y0 = points[0][0], points[0][1]
    far = max(points, key=lambda p: (p[0] - x0) ** 2 + (p[1] - y0) ** 2)
    dx, dy = far[0] - x0, far[1] - y0
    length = math.hypot(dx, dy)
    if length == 0:
        return True
    max_offset = max(abs(dx * (p[1] - y0) - dy * (p[0] - x0)) for p in points) / length
    return max_offset <= tolerance * length


def _conflict_text(samples):
    examples = "; ".join(
        f"({x:.10g}, {y:.10g}): " + ", ".join(f"{v:g}" for v in values)
        for x, y, values in samples.conflict_examples
    )
    more = " ..." if samples.conflicting_locations > len(samples.conflict_examples) else ""
    return f"{samples.conflicting_locations} location(s) have points with different values (e.g. {examples}{more})"


GROUNDWATER_DUPLICATE_NOTE = (
    ". In groundwater data this often means nested wells, multiple screened intervals, "
    "duplicate GIS points or different aquifers; they are not merged silently"
)


def point_data_report(samples, field_name, groundwater=False):
    """Return ``(errors, warnings)`` for prepared point samples.

    Warnings starting with "IMPORTANT:" deserve the user's attention before
    the contours are relied on. ``groundwater`` adds the hydrogeological
    meaning of conflicting duplicate locations.
    """
    errors, warnings = [], []
    if samples.conflicting_locations:
        text = _conflict_text(samples) + (GROUNDWATER_DUPLICATE_NOTE if groundwater else "")
        if samples.duplicate_mode == DUPLICATES_STOP:
            errors.append(
                f"{text}. Check whether they are different wells, screens or intervals, "
                "then fix the data or choose another duplicate option."
            )
        elif samples.duplicate_mode == DUPLICATES_MEAN:
            warnings.append(f"IMPORTANT: {text}. Their values were averaged, as chosen.")
        else:
            warnings.append(
                f"IMPORTANT: {text}. Only the first value at each location was used. "
                "Check whether these are different wells, screens or intervals."
            )
    if samples.equal_duplicate_locations:
        warnings.append(
            f"{samples.equal_duplicate_locations} location(s) have several points with the "
            "same value; one point per location was used."
        )
    if samples.skipped_geometries:
        warnings.append(
            f"{samples.skipped_geometries} feature(s) skipped: empty or missing geometry."
        )
    if samples.missing_values:
        warnings.append(
            f"{samples.missing_values} point(s) skipped: no usable value in field "
            f"'{field_name}' (NULL or not a finite number)."
        )

    points = samples.points
    if len(points) < MIN_TIN_POINTS:
        errors.append(
            f"At least {MIN_TIN_POINTS} points with values at distinct locations "
            f"are needed; {len(points)} found."
        )
    elif are_collinear(points):
        errors.append("All points lie on one straight line, so no surface can be interpolated.")
    else:
        values = [p[2] for p in points]
        if min(values) == max(values):
            errors.append(
                f"All point values are equal ({values[0]:g}); there is nothing to contour."
            )
    return errors, warnings


def crs_warnings(is_valid, is_geographic, description, role="point layer"):
    """Return warnings about the coordinate reference system of an input."""
    if not is_valid:
        return [f"The {role} has no coordinate reference system; the output will have none either."]
    if is_geographic:
        return [
            f"The {role} uses a geographic CRS ({description}). Distances and cell "
            "sizes are in degrees, which distorts the interpolated surface. "
            "A projected CRS is recommended."
        ]
    return []


def raster_range_problem(vmin, vmax, valid_cells, band=1):
    """Return why a surface's value range cannot be contoured, or ``None``.

    Min/max decide: QGIS reports min > max (or non-finite values) when a band
    has no valid cells. ``valid_cells`` is only used to confirm a flat 0..0
    result, because not every raster provider fills it in.
    """
    no_range = not (math.isfinite(vmin) and math.isfinite(vmax)) or vmin > vmax
    if no_range or (valid_cells == 0 and vmin == vmax):
        return f"Band {band} has no valid (non-NoData) cells."
    if vmin == vmax:
        return f"All values in band {band} are equal ({vmin:g}); there is nothing to contour."
    return None


# ------------------------------------------------------- groundwater fields

#: Features read to decide whether a text field holds numeric values.
TEXT_FIELD_SAMPLE = 500
TEXT_FIELD_NOTE = "text field, numeric values detected"


def groundwater_field_choices(layer, sample_size=TEXT_FIELD_SAMPLE):
    """Fields that can hold groundwater values: ``[(name, label, is_text)]``.

    Numeric fields are offered as they are. Text fields are offered when most
    of their non-empty values (in the first ``sample_size`` features) convert
    to numbers, labelled e.g. ``"WL - text field, numeric values detected"``.
    The layer is only read.
    """
    from .groundwater import looks_numeric  # plain Python module

    if layer is None:
        return []
    fields = layer.fields()
    numeric = [fields.at(i).isNumeric() for i in range(fields.count())]
    samples = {i: [] for i in range(fields.count()) if not numeric[i]}
    if samples:
        for count, feature in enumerate(layer.getFeatures()):
            if count >= sample_size:
                break
            for i in samples:
                samples[i].append(feature.attribute(i))
    choices = []
    for i in range(fields.count()):
        name = fields.at(i).name()
        if numeric[i]:
            choices.append((name, name, False))
            continue
        values = samples[i]
        texts_only = all(isinstance(v, str) for v in values if v is not None and not _is_null(v))
        if texts_only and looks_numeric(values):
            choices.append((name, f"{name} — {TEXT_FIELD_NOTE}", True))
    return choices


def _is_null(value):
    try:
        return bool(value.isNull())
    except AttributeError:
        return False

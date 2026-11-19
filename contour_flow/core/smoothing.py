# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional smoothing of contour lines with QGIS "Smooth" (``native:smoothgeometry``).

The algorithm uses Chaikin corner cutting: each iteration replaces every
corner with two points at ``offset`` (0-0.5) along the adjacent segments.
New vertices lie on the original segments, so smoothed lines stay inside a
clip polygon the original lines were inside.

Smoothing changes contour geometry only. Source values and the surface
raster are untouched. It is cosmetic, and it can move lines slightly away
from the interpolated values, which is why it is off by default and
recorded in the metadata. Smoothing never makes contours more accurate.

Groundwater Mode uses a scale-aware pipeline (``smooth_groundwater``):
simplify, densify, Chaikin, then validate, with automatic milder fallbacks.
"""

from qgis.core import QgsSpatialIndex

from ..utils.qgis_helpers import result_vector_layer, run_algorithm

SMOOTH_ALGORITHM = "native:smoothgeometry"
SIMPLIFY_ALGORITHM = "native:simplifygeometries"
DENSIFY_ALGORITHM = "native:densifygeometriesgivenaninterval"

#: Displacement is measured only below this many vertices (Hausdorff distance cost).
DISPLACEMENT_MAX_VERTICES = 300_000


def simplify_lines(lines, tolerance, context, feedback):
    """Douglas-Peucker simplification (QGIS "Simplify"), used before smoothing in Groundwater Mode."""
    result = run_algorithm(
        SIMPLIFY_ALGORITHM,
        {"INPUT": lines, "METHOD": 0, "TOLERANCE": tolerance, "OUTPUT": "memory:"},
        context,
        feedback,
    )
    return result_vector_layer(result["OUTPUT"], lines.name())


def densify_lines(lines, interval, context, feedback):
    """Add vertices so no segment is longer than ``interval`` (QGIS "Densify by interval")."""
    result = run_algorithm(
        DENSIFY_ALGORITHM, {"INPUT": lines, "INTERVAL": interval, "OUTPUT": "memory:"}, context, feedback
    )
    return result_vector_layer(result["OUTPUT"], lines.name())


def max_displacement(smoothed, original):
    """Largest Hausdorff distance between each smoothed line and its original, or ``None``.

    Features are paired in order (the QGIS algorithms keep feature order).
    """
    if smoothed.featureCount() != original.featureCount():
        return None
    pairs = list(zip(smoothed.getFeatures(), original.getFeatures()))
    vertices = sum(f.geometry().constGet().nCoordinates() for f, _o in pairs if not f.geometry().isNull())
    if vertices > DISPLACEMENT_MAX_VERTICES:
        return None
    worst = 0.0
    for new, old in pairs:
        if new.geometry().isNull() or old.geometry().isNull():
            continue
        worst = max(worst, new.geometry().hausdorffDistance(old.geometry()))
    return worst


def smooth_groundwater(lines, cell_size, steps, context, feedback):
    """Scale-aware smoothing with validation. Returns ``(lines, applied, rejected)``.

    ``steps`` are ``(iterations, offset, simplify_cells, segment_cells)`` from
    the chosen setting to milder ones. The first result without invalid
    geometries or crossings of different levels is kept. If every step has
    problems, the unsmoothed lines are returned with ``applied = None``.
    ``rejected`` lists ``(step, invalid, crossings)`` for rejected steps.
    """
    rejected = []
    for step in steps:
        iterations, offset, simplify, segment = step
        result = lines
        if simplify > 0:
            result = simplify_lines(result, simplify * cell_size, context, feedback)
        if segment > 0:
            result = densify_lines(result, segment * cell_size, context, feedback)
        result = smooth_lines(result, iterations, offset, context, feedback)
        invalid, crossings = geometry_problems(result)
        if not invalid and not crossings:
            return result, step, rejected
        rejected.append((step, invalid, crossings))
    return lines, None, rejected


def geometry_problems(lines, value_field="value"):
    """Return ``(invalid_count, crossing_pairs)`` for a contour layer.

    A crossing is two lines with *different* contour values that intersect;
    contours of a continuous surface never do, so any crossing means the
    geometry was distorted (e.g. by smoothing).
    """
    features = {f.id(): f for f in lines.getFeatures()}
    invalid = sum(1 for f in features.values() if not f.geometry().isGeosValid())
    index = QgsSpatialIndex()
    for feature in features.values():
        index.addFeature(feature)
    crossings = 0
    for fid, feature in features.items():
        geometry = feature.geometry()
        for other_id in index.intersects(geometry.boundingBox()):
            if other_id <= fid:
                continue
            other = features[other_id]
            if other[value_field] != feature[value_field] and geometry.intersects(other.geometry()):
                crossings += 1
    return invalid, crossings


def smooth_lines(lines, iterations, offset, context, feedback):
    """Return a smoothed memory copy of ``lines``."""
    result = run_algorithm(
        SMOOTH_ALGORITHM,
        {"INPUT": lines, "ITERATIONS": iterations, "OFFSET": offset, "MAX_ANGLE": 180.0, "OUTPUT": "memory:"},
        context,
        feedback,
    )
    return result_vector_layer(result["OUTPUT"], lines.name())

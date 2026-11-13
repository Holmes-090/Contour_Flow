# SPDX-License-Identifier: GPL-2.0-or-later
"""Processing extent and clipping geometry, in the processing CRS.

* The *processing CRS* is the point layer's CRS (point input) or the
  raster's CRS (raster input). Every geometry here is in that CRS.
* The boundary layer may use any CRS. Its geometries are transformed with
  the project's transform context.
* The result is an extent rectangle (where to interpolate) and an optional
  clip polygon (where contours are kept).
"""

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsCsException,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
)

from . import ContourError
from .options import (
    EXTENT_BOUNDARY,
    EXTENT_BUFFERED_HULL,
    EXTENT_CUSTOM,
    EXTENT_HULL,
    EXTENT_POINTS,
)

#: Segments per quarter circle for hull buffers.
BUFFER_SEGMENTS = 8


def _transform_or_none(source_crs, target_crs, transform_context):
    if not (source_crs.isValid() and target_crs.isValid()) or source_crs == target_crs:
        return None
    return QgsCoordinateTransform(source_crs, target_crs, transform_context)


def boundary_geometry(layer, selected_only, target_crs, transform_context):
    """Union of the boundary polygons, transformed to ``target_crs``.

    Returns ``(geometry, warnings)``. Invalid polygons are repaired with
    ``makeValid`` (and reported). Raises ``ContourError`` if nothing usable
    remains or the transformation fails.
    """
    transform = _transform_or_none(layer.crs(), target_crs, transform_context)
    features = layer.getSelectedFeatures() if selected_only else layer.getFeatures()
    geometries, repaired, dropped, warnings = [], 0, 0, []
    for feature in features:
        geometry = QgsGeometry(feature.geometry())
        if geometry.isNull() or geometry.isEmpty():
            continue
        if transform is not None:
            try:
                geometry.transform(transform)
            except QgsCsException as exc:
                raise ContourError(
                    f"Could not transform the boundary from {layer.crs().authid() or 'its CRS'} "
                    f"to {target_crs.authid() or 'the processing CRS'}: {exc}"
                ) from exc
        if not geometry.isGeosValid():
            repaired += 1
            geometry = geometry.makeValid()
            if geometry.type() != Qgis.GeometryType.Polygon:
                # makeValid may return a collection; keep only its polygon parts.
                converted = geometry.convertToType(Qgis.GeometryType.Polygon, True)
                geometry = converted if converted is not None else QgsGeometry()
        if geometry.isNull() or geometry.isEmpty():
            dropped += 1
            continue
        geometries.append(geometry)
    if repaired:
        warnings.append(f"{repaired} invalid boundary polygon(s) were repaired (makeValid) before use.")
    if dropped:
        warnings.append(f"{dropped} boundary feature(s) without usable polygon geometry were ignored.")
    if not geometries:
        raise ContourError("The boundary layer has no usable polygon geometry.")
    union = QgsGeometry.unaryUnion(geometries)
    if union.isNull() or union.isEmpty() or union.area() <= 0:
        raise ContourError("The boundary polygons could not be combined into a valid area.")
    return union, warnings


def points_hull(points):
    """Convex hull polygon of ``(x, y, ...)`` points."""
    return QgsGeometry.fromMultiPointXY([QgsPointXY(p[0], p[1]) for p in points]).convexHull()


def points_rectangle(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return QgsRectangle(min(xs), min(ys), max(xs), max(ys))


def transform_rectangle(rectangle, source_crs, target_crs, transform_context):
    transform = _transform_or_none(source_crs, target_crs, transform_context)
    if transform is None:
        return QgsRectangle(rectangle)
    try:
        return transform.transformBoundingBox(rectangle)
    except QgsCsException as exc:
        raise ContourError(f"Could not transform the custom extent to the processing CRS: {exc}") from exc


def point_processing_area(mode, points, hull, buffer_distance, boundary, custom_rectangle):
    """Return ``(extent_rectangle, clip_polygon_or_None)`` for point input.

    * Hull modes and Boundary give a polygon; the extent is its bounding box.
    * A boundary, if any, always clips too (intersected with the mode's area).
    * Bounding box and Custom give a rectangle and no polygon of their own.
    """
    polygon = None
    if mode == EXTENT_HULL:
        polygon = QgsGeometry(hull)
    elif mode == EXTENT_BUFFERED_HULL:
        polygon = hull.buffer(buffer_distance, BUFFER_SEGMENTS)
    elif mode == EXTENT_BOUNDARY:
        polygon = QgsGeometry(boundary)

    if mode == EXTENT_POINTS:
        rectangle = points_rectangle(points)
    elif mode == EXTENT_CUSTOM:
        rectangle = QgsRectangle(custom_rectangle)
    else:
        rectangle = None

    if boundary is not None and mode != EXTENT_BOUNDARY:
        if polygon is not None:
            polygon = polygon.intersection(boundary)
        else:
            polygon = QgsGeometry(boundary)
            rectangle = rectangle.intersect(boundary.boundingBox())

    if polygon is not None:
        if polygon.isEmpty() or polygon.area() <= 0:
            raise ContourError("The interpolation extent and the boundary do not overlap.")
        rectangle = polygon.boundingBox() if rectangle is None else rectangle.intersect(polygon.boundingBox())
    if rectangle is None or rectangle.isEmpty() or rectangle.width() <= 0 or rectangle.height() <= 0:
        raise ContourError("The interpolation extent is empty.")
    return rectangle, polygon


def fraction_outside(area_rectangle, area_polygon, hull):
    """Fraction of the processing area that lies outside the points' hull."""
    area = QgsGeometry(area_polygon) if area_polygon is not None else QgsGeometry.fromRect(area_rectangle)
    total = area.area()
    if total <= 0:
        return 0.0
    return max(0.0, area.difference(hull).area() / total)

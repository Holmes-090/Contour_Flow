# SPDX-License-Identifier: GPL-2.0-or-later
"""Point-to-raster interpolation with the built-in QGIS algorithms.

The interpolation mathematics is NOT reimplemented here. This module:

1. reads ``(x, y, value)`` samples from the user's point layer (read only);
2. writes the cleaned samples to a temporary in-memory point layer;
3. runs ``qgis:tininterpolation`` or ``qgis:idwinterpolation`` on that layer
   over a given extent and cell size, producing a surface raster.
"""

import math

from qgis.core import QgsFeature, QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsVectorLayer

from ..utils.qgis_helpers import run_algorithm
from .options import METHOD_IDW, METHOD_TIN_CLOUGH_TOCHER, METHOD_TIN_LINEAR

TIN_ALGORITHM = "qgis:tininterpolation"
IDW_ALGORITHM = "qgis:idwinterpolation"

#: Values of the TIN algorithm's METHOD parameter.
_TIN_METHOD_PARAMETER = {METHOD_TIN_LINEAR: 0, METHOD_TIN_CLOUGH_TOCHER: 1}

#: Field holding the value in the temporary point layer.
VALUE_FIELD = "value"


def _to_float(value):
    """Return ``value`` as float, or ``None`` for NULL / non-numeric values."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):  # NULL arrives as a QVariant in QGIS 3
        return None
    return number if math.isfinite(number) else None


def read_point_samples(layer, field_name, selected_only, feedback=None):
    """Read ``(x, y, value)`` for every point vertex. The layer is not changed.

    Multipoint features contribute one sample per part. Returns
    ``(raw_samples, skipped_geometries)``. ``value`` is ``None`` where the
    attribute is NULL or not a finite number.
    """
    index = layer.fields().lookupField(field_name)
    request = QgsFeatureRequest()
    request.setSubsetOfAttributes([index])
    if selected_only:
        request.setFilterFids(layer.selectedFeatureIds())

    raw_samples, skipped_geometries = [], 0
    for count, feature in enumerate(layer.getFeatures(request)):
        if feedback is not None and count % 5000 == 0 and feedback.isCanceled():
            break
        geometry = feature.geometry()
        if geometry is None or geometry.isNull() or geometry.isEmpty():
            skipped_geometries += 1
            continue
        value = _to_float(feature.attribute(index))
        for vertex in geometry.vertices():
            raw_samples.append((vertex.x(), vertex.y(), value))
    return raw_samples, skipped_geometries


def build_point_layer(points, crs):
    """Return a temporary memory point layer holding ``(x, y, value)`` points."""
    layer = QgsVectorLayer(f"Point?field={VALUE_FIELD}:double", "contour_generator_points", "memory")
    layer.setCrs(crs)
    features = []
    for x, y, value in points:
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feature.setAttributes([value])
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    return layer


def run_interpolation(point_layer, method, cell_size, extent, idw_power, output, context, feedback):
    """Interpolate ``point_layer`` over ``extent`` (QgsRectangle, layer CRS).

    ``output`` is a file path or ``"TEMPORARY_OUTPUT"``. Returns the raster path.
    ``point_layer`` must come from ``build_point_layer``. It is handed to the
    processing context, which takes ownership of it.
    """
    context.temporaryLayerStore().addMapLayer(point_layer)
    # Format expected by both algorithms:
    # layer::~::value source::~::field index::~::source type
    # value source 0 = attribute; source type 0 = points.
    parameters = {
        "INTERPOLATION_DATA": f"{point_layer.id()}::~::0::~::0::~::0",
        "EXTENT": f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()}",
        "PIXEL_SIZE": cell_size,
        "OUTPUT": output,
    }
    if method == METHOD_IDW:
        parameters["DISTANCE_COEFFICIENT"] = idw_power
        algorithm = IDW_ALGORITHM
    else:
        parameters["METHOD"] = _TIN_METHOD_PARAMETER[method]
        algorithm = TIN_ALGORITHM
    return run_algorithm(algorithm, parameters, context, feedback)["OUTPUT"]

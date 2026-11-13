# SPDX-License-Identifier: GPL-2.0-or-later
"""Raster-to-contour-line generation with the GDAL contour algorithm.

* ``raster_value_range`` reads a band's minimum and maximum.
* ``run_contour`` runs ``gdal:contour`` (shipped with QGIS Processing).
* ``editable_copy`` copies the result into an in-memory layer with the
  fields ``value`` and ``is_major``, so later steps (clip, smooth, save)
  work on an ordinary, editable QGIS layer.
"""

import warnings

from qgis.core import Qgis, QgsFeature, QgsVectorLayer, QgsWkbTypes

from ..utils.qgis_helpers import run_algorithm
from . import ContourError
from .intervals import is_major_level

CONTOUR_ALGORITHM = "gdal:contour"

#: Attributes of the output layer.
CONTOUR_FIELD = "value"
MAJOR_FIELD = "is_major"


def raster_value_range(raster_layer, band):
    """Return ``(minimum, maximum, valid_cell_count)`` of a raster band.

    Note: with only Min|Max requested, the GDAL provider reports
    ``valid_cell_count`` 0 (verified on QGIS 3.44.15), so callers must judge
    validity from min/max (see ``input_validation.raster_range_problem``).
    """
    with warnings.catch_warnings():
        # PyQGIS 3.44 emits "bandStatistics() is deprecated" for every call,
        # including the recommended Qgis.RasterBandStatistic form used here.
        warnings.filterwarnings("ignore", message=r".*bandStatistics\(\) is deprecated", category=DeprecationWarning)
        stats = raster_layer.dataProvider().bandStatistics(
            band, Qgis.RasterBandStatistic.Min | Qgis.RasterBandStatistic.Max
        )
    return stats.minimumValue, stats.maximumValue, stats.elementCount


def run_contour(raster, band, interval, context, feedback):
    """Contour ``raster`` (layer or file path). Returns the output vector path.

    Levels are the multiples of ``interval`` (offset 0).
    """
    parameters = {
        "INPUT": raster,
        "BAND": band,
        "INTERVAL": interval,
        "FIELD_NAME": CONTOUR_FIELD,
        "CREATE_3D": False,
        "IGNORE_NODATA": False,
        "OFFSET": 0.0,
        "OUTPUT": "TEMPORARY_OUTPUT",
    }
    return run_algorithm(CONTOUR_ALGORITHM, parameters, context, feedback)["OUTPUT"]


def editable_copy(path, name, fallback_crs, interval, major_every):
    """Copy the contour file at ``path`` into a memory layer called ``name``.

    Only ``value`` is kept from the file, and ``is_major`` (1/0) is added.
    If the file has no CRS, ``fallback_crs`` (the input's CRS) is used.
    """
    source = QgsVectorLayer(path, "contours", "ogr")
    if not source.isValid():
        raise ContourError(f"Could not read the contour output ({path}).")
    value_index = source.fields().lookupField(CONTOUR_FIELD)
    if value_index < 0:
        raise ContourError(f"The contour output has no '{CONTOUR_FIELD}' field.")

    geometry_type = QgsWkbTypes.displayString(source.wkbType())
    if geometry_type in ("", "Unknown", "NoGeometry"):  # e.g. an empty output file
        geometry_type = "LineString"
    copy = QgsVectorLayer(
        f"{geometry_type}?field={CONTOUR_FIELD}:double&field={MAJOR_FIELD}:integer&index=yes",
        name,
        "memory",
    )
    copy.setCrs(source.crs() if source.crs().isValid() else fallback_crs)

    features = []
    for feature in source.getFeatures():
        value = feature.attribute(value_index)
        new_feature = QgsFeature(copy.fields())
        new_feature.setGeometry(feature.geometry())
        new_feature.setAttributes([value, int(is_major_level(value, interval, major_every))])
        features.append(new_feature)
    copy.dataProvider().addFeatures(features)
    copy.updateExtents()
    return copy

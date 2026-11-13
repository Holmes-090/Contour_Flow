# SPDX-License-Identifier: GPL-2.0-or-later
"""Writing contour layers to a GeoPackage, without silently overwriting.

* ``geopackage_layer_names`` lists the existing layers, read with GDAL/OGR,
  which ships with QGIS.
* ``write_geopackage_layer`` adds one new layer to a new or existing ``.gpkg``;
  ``load_geopackage_layer`` opens it afterwards. The workflow writes all
  layers before opening any, because an open layer locks the file on Windows
  and would prevent rollback.
* ``remove_written`` undoes writes after a failed run, so no partial outputs
  are left behind.
"""

import os

from qgis.core import QgsCoordinateTransformContext, QgsVectorFileWriter, QgsVectorLayer

from . import ContourError


def geopackage_layer_names(path):
    """Names of the layers in the GeoPackage at ``path`` (empty if it doesn't exist)."""
    if not os.path.exists(path):
        return []
    from osgeo import ogr

    dataset = ogr.Open(path)
    if dataset is None:
        raise ContourError(f"{path} exists but is not a readable GeoPackage.")
    try:
        return [dataset.GetLayerByIndex(i).GetName() for i in range(dataset.GetLayerCount())]
    finally:
        dataset = None


def write_geopackage_layer(layer, path, layer_name, transform_context=None):
    """Write ``layer`` as a new layer ``layer_name`` in ``path``.

    The caller must have made ``layer_name`` unique (see ``options.unique_name``).
    The written layer is not opened here (see ``load_geopackage_layer``).
    """
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = layer_name
    options.fileEncoding = "UTF-8"
    options.actionOnExistingFile = (
        QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        if os.path.exists(path)
        else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    )
    error, _new_file, _new_layer, message = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, transform_context or QgsCoordinateTransformContext(), options
    )
    if error != QgsVectorFileWriter.WriterError.NoError:
        raise ContourError(f"Could not write layer '{layer_name}' to {path}: {message or error}")


def load_geopackage_layer(path, layer_name):
    """Open layer ``layer_name`` of the GeoPackage at ``path`` as a QGIS layer."""
    loaded = QgsVectorLayer(f"{path}|layername={layer_name}", layer_name, "ogr")
    if not loaded.isValid():
        raise ContourError(f"Layer '{layer_name}' was written to {path} but could not be loaded.")
    return loaded


def remove_written(written):
    """Undo writes after a failure. ``written`` holds ``(kind, path, layer_name)``.

    kind "file": delete the file this run created. kind "gpkg_layer": delete
    one layer from an existing GeoPackage. Errors are ignored (best effort).
    """
    for kind, path, layer_name in reversed(written):
        try:
            if kind == "file" and os.path.exists(path):
                os.remove(path)
            elif kind == "gpkg_layer":
                from osgeo import ogr

                dataset = ogr.Open(path, 1)
                if dataset is not None:
                    for i in range(dataset.GetLayerCount()):
                        if dataset.GetLayerByIndex(i).GetName() == layer_name:
                            dataset.DeleteLayer(i)
                            break
                    dataset = None
        except Exception:  # noqa: BLE001 - cleanup must never raise
            pass

# SPDX-License-Identifier: GPL-2.0-or-later
"""Clipping to the processing area, with standard Processing algorithms.

Sequence used by the workflow, and why:

1. The interpolation runs only over the extent rectangle. A large raster
   input is first cropped to the boundary's bounding box
   (``gdal:cliprasterbyextent``), which keeps cell values unchanged.
2. Contours are generated from that (unmasked) raster.
3. The contour **lines** are clipped exactly to the clip polygon
   (``native:clip``).

The alternative, masking the raster to the polygon before contouring, was
rejected. Cells outside the mask become NoData, or 0 when the raster has no
NoData value, which creates false contours along the edge. Cell-based
masking is also only accurate to about half a cell. Clipping the vectors
gives an exact edge.

``mask_surface`` (``gdal:cliprasterbymasklayer``) is used only for the
optional surface output. That surface is the plugin's own Float32 raster
with a known NoData value.
"""

from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

from ..utils.qgis_helpers import result_vector_layer, run_algorithm

CLIP_ALGORITHM = "native:clip"
CROP_RASTER_ALGORITHM = "gdal:cliprasterbyextent"
MASK_RASTER_ALGORITHM = "gdal:cliprasterbymasklayer"


def polygon_layer(geometry, crs, name="contour_flow_clip"):
    """Memory polygon layer holding ``geometry`` (used as a clip overlay)."""
    layer = QgsVectorLayer("MultiPolygon", name, "memory")
    layer.setCrs(crs)
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry(geometry))
    layer.dataProvider().addFeatures([feature])
    layer.updateExtents()
    return layer


def clip_lines(lines, polygon, crs, context, feedback):
    """Clip ``lines`` (memory layer) to ``polygon``. Returns a memory layer."""
    overlay = polygon_layer(polygon, crs)
    result = run_algorithm(
        CLIP_ALGORITHM, {"INPUT": lines, "OVERLAY": overlay, "OUTPUT": "memory:"}, context, feedback
    )
    return result_vector_layer(result["OUTPUT"], lines.name())


def crop_raster(raster, rectangle, context, feedback):
    """Crop ``raster`` (layer or source, raster CRS) to ``rectangle``. Returns a file path."""
    extent = f"{rectangle.xMinimum()},{rectangle.xMaximum()},{rectangle.yMinimum()},{rectangle.yMaximum()}"
    result = run_algorithm(
        CROP_RASTER_ALGORITHM,
        {"INPUT": raster, "PROJWIN": extent, "OUTPUT": "TEMPORARY_OUTPUT"},
        context,
        feedback,
    )
    return result["OUTPUT"]


def mask_surface(raster_path, polygon, crs, nodata, output, context, feedback):
    """Mask the plugin's surface raster to ``polygon``. Returns the output path."""
    mask = polygon_layer(polygon, crs, "contour_flow_mask")
    result = run_algorithm(
        MASK_RASTER_ALGORITHM,
        {
            "INPUT": raster_path,
            "MASK": mask,
            "NODATA": nodata,
            "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True,
            "OUTPUT": output,
        },
        context,
        feedback,
    )
    return result["OUTPUT"]

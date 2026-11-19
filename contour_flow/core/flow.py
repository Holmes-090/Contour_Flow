# SPDX-License-Identifier: GPL-2.0-or-later
"""Groundwater flow-direction arrows from the interpolated head surface.

Method (deterministic, documented in the layer metadata):

1. Seed points on a regular grid over the *support area* (convex hull of the
   wells by default), spaced for about the requested number of arrows.
2. At each seed, the head gradient is estimated by **central finite
   differences** of the interpolated surface raster, sampled at +/- d in x
   and y (``QgsRasterDataProvider.sample``). The sampling distance d also
   smooths the direction over that scale.
3. Flow direction is -grad(h): the direction of steepest *decrease* of
   hydraulic head. Azimuth is clockwise from grid north.
4. A seed gets an arrow only if all four samples have values (i.e. the
   surface is supported there) and the arrow lies inside the support area.

Arrows are an interpretation of the interpolated surface's gradient, not
measured flow; no velocities or fluxes are computed.
"""

import math

from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer

from . import groundwater as gw

FLOW_METHOD = (
    "Central finite differences of the interpolated head raster "
    "(flow = -grad h, direction of steepest head decrease)"
)


def _sampler(surface_layer):
    provider = surface_layer.dataProvider()

    def sample(x, y):
        value, ok = provider.sample(QgsPointXY(x, y), 1)
        if not ok or value is None or not math.isfinite(value):
            return None
        return value

    return sample


def build_flow_arrows(surface_layer, support, crs, cell_size, target_count, scaling, arrow_length, name):
    """Create the arrow layer. Returns ``(layer, info)``.

    ``support`` is a polygon QgsGeometry in the surface CRS; ``arrow_length``
    0 means automatic (60 % of the arrow spacing).
    """
    area = support.area()
    spacing = gw.arrow_spacing(area, max(1, target_count))
    base_length = arrow_length if arrow_length > 0 else 0.6 * spacing
    step = max(2.0 * cell_size, 0.15 * spacing)
    sample = _sampler(surface_layer)
    box = support.boundingBox()

    arrows = []
    for x, y in gw.arrow_seeds(box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum(), spacing):
        if not support.contains(QgsGeometry.fromPointXY(QgsPointXY(x, y))):
            continue
        gradient = gw.central_gradient(sample, x, y, step)
        if gradient is None:
            continue
        azimuth, magnitude = gw.flow_vector(*gradient)
        if magnitude <= 1e-12:
            continue  # flat surface: no defined direction
        arrows.append((x, y, azimuth, magnitude, sample(x, y)))

    lengths = gw.arrow_lengths([a[3] for a in arrows], base_length, scaling)
    layer = QgsVectorLayer(
        "LineString?field=azimuth:double&field=gradient:double&field=head:double&index=yes", name, "memory"
    )
    layer.setCrs(crs)
    features, kept = [], []
    for (x, y, azimuth, magnitude, head), length in zip(arrows, lengths):
        (x0, y0), (x1, y1) = gw.arrow_segment(x, y, azimuth, length)
        line = QgsGeometry.fromPolylineXY([QgsPointXY(x0, y0), QgsPointXY(x1, y1)])
        if not support.contains(line):
            continue  # keep whole arrows inside the supported area
        feature = QgsFeature(layer.fields())
        feature.setGeometry(line)
        feature.setAttributes([round(azimuth, 1), magnitude, head])
        features.append(feature)
        kept.append((azimuth, magnitude))
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    info = {
        "count": len(kept),
        "spacing": spacing,
        "step": step,
        "length": base_length,
        "direction": gw.generalized_direction([a for a, _m in kept]),
        "gradient": gw.gradient_summary([m for _a, m in kept]),
    }
    return layer, info

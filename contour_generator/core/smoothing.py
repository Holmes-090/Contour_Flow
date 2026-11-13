# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional smoothing of contour lines with QGIS "Smooth" (``native:smoothgeometry``).

The algorithm uses Chaikin corner cutting: each iteration replaces every
corner with two points at ``offset`` (0-0.5) along the adjacent segments.
New vertices lie on the original segments, so smoothed lines stay inside a
clip polygon the original lines were inside.

Smoothing changes contour geometry only. Source values and the surface
raster are untouched. It is cosmetic, and it can move lines slightly away
from the interpolated values, which is why it is off by default and
recorded in the metadata.
"""

from ..utils.qgis_helpers import result_vector_layer, run_algorithm

SMOOTH_ALGORITHM = "native:smoothgeometry"


def smooth_lines(lines, iterations, offset, context, feedback):
    """Return a smoothed memory copy of ``lines``."""
    result = run_algorithm(
        SMOOTH_ALGORITHM,
        {"INPUT": lines, "ITERATIONS": iterations, "OFFSET": offset, "MAX_ANGLE": 180.0, "OUTPUT": "memory:"},
        context,
        feedback,
    )
    return result_vector_layer(result["OUTPUT"], lines.name())

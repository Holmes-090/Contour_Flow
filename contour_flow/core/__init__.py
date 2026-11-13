# SPDX-License-Identifier: GPL-2.0-or-later
"""Processing logic for Contour Flow.

Modules in this package must not import anything from ``contour_flow.ui``.
Where practical they wrap standard QGIS / GDAL Processing algorithms rather
than reimplementing GIS mathematics.

Pure-Python modules (no ``qgis`` import, unit-tested): ``input_validation``,
``intervals``, ``grid``, ``options``, ``report``. QGIS modules:
``interpolation``, ``extent``, ``contouring``, ``clipping``, ``smoothing``,
``styling``, ``output`` and ``workflow``.
"""


class ContourError(Exception):
    """A problem that stops contour generation, with a user-readable message."""


class ContourCancelled(ContourError):
    """The user cancelled the run."""

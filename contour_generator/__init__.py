# SPDX-License-Identifier: GPL-2.0-or-later
"""Contour Generator QGIS plugin package.

QGIS imports this package when the plugin is enabled and calls
``classFactory(iface)``. That function is the only entry point QGIS requires.

The plugin class itself lives in ``contour_generator.py``.
"""


def classFactory(iface):  # noqa: N802 - name is required by QGIS
    """Return the plugin instance. Called once by QGIS.

    :param iface: The QGIS interface object (``QgisInterface``).
    """
    from .contour_generator import ContourGeneratorPlugin

    return ContourGeneratorPlugin(iface)

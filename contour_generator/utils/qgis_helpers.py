# SPDX-License-Identifier: GPL-2.0-or-later
"""Thin convenience helpers around PyQGIS shared by the whole plugin.

Keep these generic. Contour-specific logic belongs in ``core``.
"""

import configparser
import os

from qgis.core import Qgis, QgsMessageLog

#: Display name used for the action, the Plugins submenu and the log tab.
PLUGIN_NAME = "Contour Generator"

#: Root folder of the plugin package (the folder that holds metadata.txt).
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_message(message, level=Qgis.MessageLevel.Info):
    """Write to the plugin's own tab in the QGIS Log Messages panel."""
    QgsMessageLog.logMessage(message, PLUGIN_NAME, level)


def run_algorithm(algorithm_id, parameters, context, feedback):
    """Run a QGIS Processing algorithm and return its results dictionary.

    Raises ``ContourError`` with a readable message if the algorithm is not
    available (e.g. the Processing plugin is disabled) or if it fails. The
    full Processing log is written to the plugin's log tab on failure.
    """
    import processing  # QGIS Processing framework (core plugin)
    from qgis.core import QgsApplication, QgsProcessingException

    from ..core import ContourCancelled, ContourError

    if feedback is not None and feedback.isCanceled():
        raise ContourCancelled("Cancelled.")
    if QgsApplication.processingRegistry().algorithmById(algorithm_id) is None:
        raise ContourError(
            f"The Processing algorithm '{algorithm_id}' is not available. Make sure "
            "the Processing plugin is enabled (Plugins > Manage and Install "
            "Plugins > Installed)."
        )
    try:
        return processing.run(algorithm_id, parameters, context=context, feedback=feedback)
    except QgsProcessingException as exc:
        if feedback is not None and feedback.isCanceled():
            raise ContourCancelled("Cancelled.") from exc
        log_message(
            f"Algorithm '{algorithm_id}' failed: {exc}\nParameters: {parameters}\n"
            f"Processing log:\n{feedback.textLog()}",
            Qgis.MessageLevel.Critical,
        )
        raise ContourError(f"The Processing algorithm '{algorithm_id}' failed: {exc}") from exc


def result_vector_layer(value, name):
    """Return a Processing vector output as a layer named ``name``.

    ``processing.run`` returns memory outputs as layer objects and file
    outputs as paths. This accepts either.
    """
    from qgis.core import QgsVectorLayer

    from ..core import ContourError

    layer = value if isinstance(value, QgsVectorLayer) else QgsVectorLayer(str(value), name, "ogr")
    if not layer.isValid():
        raise ContourError(f"Could not read the Processing output ({value}).")
    layer.setName(name)
    return layer


def plugin_version():
    """Return the plugin version from ``metadata.txt``.

    ``metadata.txt`` is the single source of truth for the version, because
    QGIS and plugins.qgis.org read it from there too. Returns ``"unknown"``
    (and logs a warning) if the file cannot be read.
    """
    path = os.path.join(PLUGIN_DIR, "metadata.txt")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(path, encoding="utf-8") as metadata_file:
            parser.read_file(metadata_file)
        return parser.get("general", "version")
    except (OSError, configparser.Error) as exc:
        log_message(
            f"Could not read the plugin version from {path}: {exc}",
            Qgis.MessageLevel.Warning,
        )
        return "unknown"

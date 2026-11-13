# SPDX-License-Identifier: GPL-2.0-or-later
"""QGIS plugin lifecycle for Contour Generator.

Handles only what QGIS asks of a plugin:

* ``initGui()``: create one action and add it to the Plugins toolbar and
  the Plugins menu.
* ``show_dialog()``: open the main dialog (a single, reused instance).
* ``unload()``: remove everything ``initGui()`` added and close the dialog.

No interpolation, contouring or validation logic belongs here. That lives in
``contour_generator.core``.
"""

import os
import traceback

from qgis.core import Qgis
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .utils.qgis_helpers import PLUGIN_NAME, log_message


class ContourGeneratorPlugin:
    """Plugin object that QGIS creates through ``classFactory``."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self.action = None
        self.dialog = None

    def initGui(self):  # noqa: N802 - name is required by QGIS
        """Called by QGIS when the plugin is enabled (or reloaded)."""
        icon = QIcon(os.path.join(self.plugin_dir, "icons", "contour.svg"))
        self.action = QAction(icon, PLUGIN_NAME, self.iface.mainWindow())
        self.action.setObjectName("contourGeneratorAction")
        self.action.setToolTip(PLUGIN_NAME)
        self.action.setStatusTip("Open the Contour Generator dialog")
        self.action.triggered.connect(self.show_dialog)

        # The same action is used for the toolbar button and the menu entry.
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.action)

    def unload(self):
        """Called by QGIS when the plugin is disabled, reloaded or QGIS exits.

        Must undo everything ``initGui()`` did, otherwise Plugin Reloader
        leaves duplicate buttons and menu entries behind.
        """
        self._close_dialog()

        if self.action is None:
            return
        self.iface.removePluginMenu(PLUGIN_NAME, self.action)
        self.iface.removeToolBarIcon(self.action)
        self.action.triggered.disconnect(self.show_dialog)
        self.action.deleteLater()
        self.action = None

    def show_dialog(self):
        """Open the dialog, or bring the existing one to the front."""
        if self.dialog is None:
            try:
                # Imported here so that a broken .ui file only affects the
                # dialog, not loading the plugin itself.
                from .ui.contour_dialog import ContourDialog

                self.dialog = ContourDialog(self.iface.mainWindow(), self.iface.mapCanvas())
            except Exception:  # noqa: BLE001 - report any failure to the user
                self.dialog = None
                log_message(
                    "Could not open the dialog:\n" + traceback.format_exc(),
                    Qgis.MessageLevel.Critical,
                )
                self.iface.messageBar().pushMessage(
                    PLUGIN_NAME,
                    "Could not open the dialog. Details are in the Log "
                    "Messages panel, 'Contour Generator' tab.",
                    level=Qgis.MessageLevel.Critical,
                    duration=10,
                )
                return

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _close_dialog(self):
        """Close and delete the dialog instance, if one exists."""
        if self.dialog is None:
            return
        self.dialog.cleanup()
        self.dialog.close()
        self.dialog.deleteLater()
        self.dialog = None

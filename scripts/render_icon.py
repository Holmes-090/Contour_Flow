# SPDX-License-Identifier: GPL-2.0-or-later
"""Render contour_flow/icons/contour_flow.svg to PNG (metadata.txt needs PNG/JPEG).

Run with QGIS's Python:  scripts\\run_with_qgis.bat scripts\\render_icon.py
Writes contour_flow/icons/contour_flow.png (64 x 64) and, for checking at
toolbar size, a 24 x 24 preview in tests/integration_output/ (not committed).
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qgis.PyQt.QtCore import Qt  # noqa: E402
from qgis.PyQt.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from qgis.PyQt.QtSvg import QSvgRenderer  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(REPO, "contour_flow", "icons", "contour_flow.svg")


def render(size, path):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(SVG).render(painter)
    painter.end()
    if not image.save(path):
        raise RuntimeError(f"could not write {path}")
    print(f"{path}: {size} x {size}")


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    render(64, os.path.join(REPO, "contour_flow", "icons", "contour_flow.png"))
    preview = os.path.join(REPO, "tests", "integration_output")
    os.makedirs(preview, exist_ok=True)
    render(24, os.path.join(preview, "icon_24.png"))
    render(256, os.path.join(preview, "icon_256.png"))

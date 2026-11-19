# SPDX-License-Identifier: GPL-2.0-or-later
"""Default symbology and labels for output contour layers.

Everything here is ordinary QGIS styling: a categorized renderer on
``is_major`` (thin minor / thick major lines) and native labeling on
``value``. Users can change all of it in Layer Properties. Nothing is baked
into the geometry or attributes.
"""

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsLineSymbol,
    QgsPalLayerSettings,
    QgsRendererCategory,
    QgsRuleBasedLabeling,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayerSimpleLabeling,
    Qgis,
)
from qgis.PyQt.QtGui import QColor

from .contouring import CONTOUR_FIELD, MAJOR_FIELD
from .options import (
    LABELS_ALL,
    LABELS_MAJOR,
    MAJOR_LINE_WIDTH_MM,
    MINOR_LINE_WIDTH_MM,
    STYLE_PRESETS,
)


def _line_symbol(color, width_mm):
    return QgsLineSymbol.createSimple(
        {"line_color": color, "line_width": str(width_mm), "line_width_unit": "MM", "capstyle": "round"}
    )


def _label_settings(color, decimals):
    settings = QgsPalLayerSettings()
    settings.fieldName = CONTOUR_FIELD
    settings.isExpression = False
    settings.formatNumbers = True
    settings.decimals = decimals
    settings.plusSign = False
    settings.placement = Qgis.LabelPlacement.Curved
    try:
        line_settings = settings.lineSettings()
        line_settings.setPlacementFlags(Qgis.LabelLinePlacementFlag.OnLine)
        settings.setLineSettings(line_settings)
    except (AttributeError, TypeError):  # older flag API: keep QGIS's default line placement
        pass

    text_format = QgsTextFormat()
    text_format.setColor(QColor(color))
    text_format.setSize(8)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setColor(QColor("white"))
    buffer.setSize(0.8)
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    return settings


def apply_arrow_style(layer, color="#1f5fbf"):
    """Blue straight arrows using QGIS's own Arrow symbol layer (editable in Layer Properties)."""
    from qgis.core import QgsArrowSymbolLayer, QgsSingleSymbolRenderer

    arrow = QgsArrowSymbolLayer.create({
        "arrow_width": "0.5", "arrow_width_unit": "MM",
        "arrow_start_width": "0.5", "arrow_start_width_unit": "MM",
        "head_length": "2.2", "head_length_unit": "MM",
        "head_thickness": "1.5", "head_thickness_unit": "MM",
        "arrow_type": "0", "head_type": "0", "is_curved": "0", "is_repeated": "0",
    })
    arrow.subSymbol().setColor(QColor(color))
    symbol = QgsLineSymbol()
    symbol.changeSymbolLayer(0, arrow)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()


def apply_style(layer, preset, label_mode, decimals):
    """Apply a style preset and optional labels to a contour ``layer``."""
    color = STYLE_PRESETS[preset]["color"]
    categories = [
        QgsRendererCategory(0, _line_symbol(color, MINOR_LINE_WIDTH_MM), "Minor contour"),
        QgsRendererCategory(1, _line_symbol(color, MAJOR_LINE_WIDTH_MM), "Major contour"),
    ]
    layer.setRenderer(QgsCategorizedSymbolRenderer(MAJOR_FIELD, categories))

    if label_mode == LABELS_ALL:
        layer.setLabeling(QgsVectorLayerSimpleLabeling(_label_settings(color, decimals)))
        layer.setLabelsEnabled(True)
    elif label_mode == LABELS_MAJOR:
        root = QgsRuleBasedLabeling.Rule(None)
        rule = QgsRuleBasedLabeling.Rule(_label_settings(color, decimals))
        rule.setFilterExpression(f'"{MAJOR_FIELD}" = 1')
        rule.setDescription("Major contours")
        root.appendChild(rule)
        layer.setLabeling(QgsRuleBasedLabeling(root))
        layer.setLabelsEnabled(True)
    else:
        layer.setLabelsEnabled(False)
    layer.triggerRepaint()

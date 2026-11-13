# SPDX-License-Identifier: GPL-2.0-or-later
"""Processing metadata: an ordered list of ``(label, value)`` pairs.

Pure Python, no ``qgis`` import. The workflow collects the settings it used.
This module turns them into:

* human-readable text, for the layer's metadata abstract and the log;
* JSON, stored as a layer custom property so tools can read it back.

Metadata is stored once per layer, never repeated on every feature.
"""

import json
import math

#: Layer custom-property key holding the JSON metadata.
METADATA_PROPERTY = "contour_generator/metadata"

DISCLAIMER = (
    "Interpolated contours are estimates derived from the supplied data and "
    "the chosen method; they require professional review before use in "
    "technical interpretation."
)


def format_value(value):
    """Render a metadata value as short text."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:g}" if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(format_value(v) for v in value) or "none"
    return str(value)


def metadata_text(items, warnings=()):
    """Return the abstract text: settings, warnings, disclaimer."""
    lines = ["Created by the Contour Generator QGIS plugin."]
    lines += [f"{label}: {format_value(value)}" for label, value in items]
    if warnings:
        lines.append("Warnings:")
        lines += [f"- {w}" for w in warnings]
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def metadata_json(items, warnings=()):
    """Return JSON text with settings and warnings (order preserved)."""
    def plain(value):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        if isinstance(value, tuple):
            return list(value)
        return value

    return json.dumps(
        {"settings": [[label, plain(value)] for label, value in items], "warnings": list(warnings)},
        ensure_ascii=False,
    )


def parse_metadata_json(text):
    """Inverse of ``metadata_json``: returns ``(items, warnings)``."""
    data = json.loads(text)
    return [tuple(pair) for pair in data["settings"]], data["warnings"]

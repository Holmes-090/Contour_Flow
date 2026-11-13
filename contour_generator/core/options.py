# SPDX-License-Identifier: GPL-2.0-or-later
"""User-facing options: constants, labels, defaults and validators.

Pure Python, no ``qgis`` import, so it can be unit-tested anywhere. Every
``*_problem`` function returns a plain-language sentence, or ``None`` when
the value is usable.
"""

import math
import os
import re

# ------------------------------------------------------------ interpolation

METHOD_TIN_LINEAR = "tin_linear"
METHOD_TIN_CLOUGH_TOCHER = "tin_clough_toucher"
METHOD_IDW = "idw"
METHOD_LABELS = {
    METHOD_TIN_LINEAR: "TIN, linear",
    METHOD_TIN_CLOUGH_TOCHER: "TIN, Clough-Toucher (cubic)",
    METHOD_IDW: "IDW (inverse distance weighting)",
}

#: IDW distance coefficient (power). QGIS accepts 0 to 99.99.
IDW_POWER_DEFAULT = 2.0
IDW_POWER_MAX = 99.99


def idw_power_problem(power):
    if not (isinstance(power, (int, float)) and math.isfinite(power)) or power <= 0:
        return "The IDW power must be a number greater than 0."
    if power > IDW_POWER_MAX:
        return f"The IDW power can be at most {IDW_POWER_MAX:g}."
    return None


# ------------------------------------------------------------------- extent

EXTENT_POINTS = "points"
EXTENT_HULL = "hull"
EXTENT_BUFFERED_HULL = "buffered_hull"
EXTENT_BOUNDARY = "boundary"
EXTENT_CUSTOM = "custom"
EXTENT_LABELS = {
    EXTENT_POINTS: "Bounding box of usable points",
    EXTENT_HULL: "Convex hull of usable points",
    EXTENT_BUFFERED_HULL: "Convex hull + buffer",
    EXTENT_BOUNDARY: "Boundary polygon",
    EXTENT_CUSTOM: "Custom extent",
}

#: Extent modes whose area is a polygon, so the result is clipped to it.
POLYGON_EXTENT_MODES = (EXTENT_HULL, EXTENT_BUFFERED_HULL, EXTENT_BOUNDARY)


def buffer_problem(distance):
    if not (isinstance(distance, (int, float)) and math.isfinite(distance)) or distance <= 0:
        return "The hull buffer distance must be greater than 0."
    return None


def extent_problem(mode, has_boundary, buffer_distance=0.0, custom_extent_valid=False):
    """Check that the chosen extent mode has what it needs."""
    if mode not in EXTENT_LABELS:
        return f"Unknown extent mode: {mode!r}."
    if mode == EXTENT_BUFFERED_HULL:
        return buffer_problem(buffer_distance)
    if mode == EXTENT_BOUNDARY and not has_boundary:
        return "Extent 'Boundary polygon' needs a boundary layer."
    if mode == EXTENT_CUSTOM and not custom_extent_valid:
        return "Set a custom extent."
    return None


# ----------------------------------------------------------------- boundary

BOUNDARY_ALL = "all"
BOUNDARY_SELECTED = "selected"


def boundary_problem(has_boundary, feature_mode, selected_count):
    if not has_boundary:
        return None
    if feature_mode == BOUNDARY_SELECTED and selected_count == 0:
        return "No features are selected in the boundary layer."
    return None


# ---------------------------------------------------------------- smoothing

SMOOTH_NONE = "none"
SMOOTH_LIGHT = "light"
SMOOTH_MEDIUM = "medium"
SMOOTH_CUSTOM = "custom"
SMOOTH_LABELS = {
    SMOOTH_NONE: "None",
    SMOOTH_LIGHT: "Light",
    SMOOTH_MEDIUM: "Medium",
    SMOOTH_CUSTOM: "Custom",
}
#: (iterations, offset) for the presets of QGIS "Smooth" (Chaikin corner cutting).
SMOOTH_PRESETS = {SMOOTH_LIGHT: (1, 0.25), SMOOTH_MEDIUM: (2, 0.25)}
#: Kept below the algorithm's maximum (10) to avoid heavy distortion.
SMOOTH_MAX_ITERATIONS = 5
SMOOTH_MAX_OFFSET = 0.5


def smoothing_parameters(mode, iterations=1, offset=0.25):
    """Return ``((iterations, offset) or None, problem)`` for a smoothing mode."""
    if mode == SMOOTH_NONE:
        return None, None
    if mode in SMOOTH_PRESETS:
        return SMOOTH_PRESETS[mode], None
    if mode != SMOOTH_CUSTOM:
        return None, f"Unknown smoothing mode: {mode!r}."
    if not (isinstance(iterations, int) and 1 <= iterations <= SMOOTH_MAX_ITERATIONS):
        return None, f"Smoothing iterations must be a whole number from 1 to {SMOOTH_MAX_ITERATIONS}."
    if not (isinstance(offset, (int, float)) and 0 < offset <= SMOOTH_MAX_OFFSET):
        return None, f"Smoothing offset must be greater than 0 and at most {SMOOTH_MAX_OFFSET:g}."
    return (iterations, float(offset)), None


# ------------------------------------------------------- major/labels/style

MAJOR_EVERY_DEFAULT = 5
MAJOR_EVERY_MAX = 1000


def major_every_problem(major_every):
    if not (isinstance(major_every, int) and 1 <= major_every <= MAJOR_EVERY_MAX):
        return f"'Major contour every' must be a whole number from 1 to {MAJOR_EVERY_MAX}."
    return None


LABELS_NONE = "none"
LABELS_MAJOR = "major"
LABELS_ALL = "all"
LABEL_LABELS = {
    LABELS_NONE: "No labels",
    LABELS_MAJOR: "Major contours only",
    LABELS_ALL: "All contours",
}
LABEL_PRECISION_MAX = 6


def label_precision_problem(decimals):
    if not (isinstance(decimals, int) and 0 <= decimals <= LABEL_PRECISION_MAX):
        return f"Label precision must be a whole number from 0 to {LABEL_PRECISION_MAX}."
    return None


def suggested_label_precision(interval):
    """Decimals needed to show every level of ``interval`` exactly (max 6)."""
    for decimals in range(LABEL_PRECISION_MAX + 1):
        if abs(round(interval, decimals) - interval) < 1e-9 * max(1.0, abs(interval)):
            return decimals
    return LABEL_PRECISION_MAX


STYLE_NEUTRAL = "neutral"
STYLE_TOPOGRAPHIC = "topographic"
STYLE_GROUNDWATER = "groundwater"
#: Line colours and widths (millimetres) for the presets.
STYLE_PRESETS = {
    STYLE_NEUTRAL: {"label": "Neutral (black)", "color": "#000000"},
    STYLE_TOPOGRAPHIC: {"label": "Topographic (brown)", "color": "#8c5a2b"},
    STYLE_GROUNDWATER: {"label": "Groundwater (blue)", "color": "#1f5fbf"},
}
MINOR_LINE_WIDTH_MM = 0.25
MAJOR_LINE_WIDTH_MM = 0.6

# ------------------------------------------------------------------- output

OUTPUT_TEMPORARY = "temporary"
OUTPUT_GEOPACKAGE = "geopackage"
SURFACE_NONE = "none"
SURFACE_TEMPORARY = "temporary"
SURFACE_GEOTIFF = "geotiff"


def clean_layer_name(name):
    """Trim and collapse whitespace; drop control characters."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", name or "")
    return re.sub(r"\s+", " ", name).strip()


def default_layer_name(base, interval, smoothed=False):
    name = f"Contours {base} ({interval:g})"
    return f"{name} smoothed" if smoothed else name


def unique_name(name, existing):
    """Return ``name``, or ``name_2``, ``name_3``... not in ``existing`` (case-insensitive)."""
    taken = {n.lower() for n in existing}
    if name.lower() not in taken:
        return name
    counter = 2
    while f"{name}_{counter}".lower() in taken:
        counter += 1
    return f"{name}_{counter}"


def unique_file_path(path, exists=os.path.exists):
    """Return ``path`` or ``stem_2.ext``, ``stem_3.ext``... that does not exist yet."""
    if not exists(path):
        return path
    stem, extension = os.path.splitext(path)
    counter = 2
    while exists(f"{stem}_{counter}{extension}"):
        counter += 1
    return f"{stem}_{counter}{extension}"


def output_path_problem(path, extension, description):
    """Check a file path the plugin will create or add a layer to."""
    if not path:
        return f"Choose a {description} file."
    if not path.lower().endswith(extension):
        return f"The {description} file name must end with {extension}."
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        return f"The folder {folder} does not exist."
    if os.path.exists(path):
        if not os.access(path, os.W_OK):
            return f"The file {path} is not writable."
    elif not os.access(folder, os.W_OK):
        return f"The folder {folder} is not writable."
    return None

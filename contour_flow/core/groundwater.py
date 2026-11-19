# SPDX-License-Identifier: GPL-2.0-or-later
"""Groundwater Mode: head values, hydrogeological QA, and flow-direction maths.

Pure Python, no ``qgis`` import, so everything here is unit-tested with plain
Python. The QGIS side (reading layers, sampling the surface, writing arrow
layers) lives in ``workflow.py``.

Terminology: *head* means groundwater elevation / hydraulic head / piezometric
elevation. The plugin does not assume a field name or unit; heads and map
coordinates are assumed to share a length unit only where a dimensionless
hydraulic gradient is reported.

Nothing here models groundwater flow. Flow arrows are the direction of
steepest *decrease* of the interpolated head surface, i.e. an interpretation of
the hydraulic gradient, not measured flow.
"""

import math
from dataclasses import dataclass, field

MODE_GENERAL = "general"
MODE_GROUNDWATER = "groundwater"

#: How heads are obtained in Groundwater Mode.
GW_EXISTING = "existing"
GW_CALCULATED = "calculated"

#: Where flow arrows may be drawn ("spatial support").
ARROWS_HULL = "hull"
ARROWS_BUFFERED_HULL = "buffered_hull"
ARROWS_BOUNDARY = "boundary"
ARROWS_EXTENT = "extent"
ARROW_SUPPORT_LABELS = {
    ARROWS_HULL: "Within the well network (convex hull)",
    ARROWS_BUFFERED_HULL: "Convex hull + buffer",
    ARROWS_BOUNDARY: "Within the boundary polygon",
    ARROWS_EXTENT: "Whole interpolated area",
}
ARROWS_UNIFORM = "uniform"
ARROWS_SCALED = "scaled"
ARROW_COUNT_DEFAULT = 9

#: Values in a text field count as numeric when at least this share converts.
NUMERIC_TEXT_THRESHOLD = 0.5

#: Robust z-score above which a residual from the planar trend is flagged.
OUTLIER_Z = 3.5
OUTLIER_MIN_POINTS = 5
#: ...and the deviation must be at least this share of the site's head range,
#: so real local features (a small recharge mound) are not flagged.
OUTLIER_MIN_RANGE_SHARE = 0.10

#: Generalized direction is reported only above this consistency (0..1).
DIRECTION_CONSISTENCY = 0.8
DIRECTION_MIN_ARROWS = 3

COMPASS_8 = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")

DISCLAIMER = (
    "Groundwater contours and flow arrows are interpretations derived from the supplied "
    "monitoring data and interpolation settings. Flow arrows show the interpreted "
    "hydraulic-gradient direction of the interpolated surface, not measured groundwater flow."
)


# ------------------------------------------------------------ number parsing

PARSE_OK = "ok"
PARSE_NULL = "null"
PARSE_BLANK = "blank"
PARSE_TEXT = "text"


def parse_number(value):
    """Return ``(number_or_None, status)`` for a raw attribute value.

    * numbers pass through (non-finite numbers count as text/invalid);
    * NULL (``None`` or a QVariant NULL) gives ``PARSE_NULL``;
    * strings are trimmed; blank gives ``PARSE_BLANK``; ``"202.51"`` converts;
      anything else (``"N/A"``, ``"Dry"``, ``"202,51"``, ``"nan"``) is
      ``PARSE_TEXT``. Text is never treated as zero.
    """
    if value is None:
        return None, PARSE_NULL
    if isinstance(value, bool):
        return None, PARSE_TEXT
    if isinstance(value, (int, float)):
        number = float(value)
        return (number, PARSE_OK) if math.isfinite(number) else (None, PARSE_TEXT)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, PARSE_BLANK
        try:
            number = float(text)
        except ValueError:
            return None, PARSE_TEXT
        return (number, PARSE_OK) if math.isfinite(number) else (None, PARSE_TEXT)
    # QVariant NULL and other wrappers: try a numeric conversion, else NULL.
    try:
        if hasattr(value, "isNull") and value.isNull():
            return None, PARSE_NULL
        number = float(value)
    except (TypeError, ValueError):
        return None, PARSE_NULL
    return (number, PARSE_OK) if math.isfinite(number) else (None, PARSE_TEXT)


def looks_numeric(values, threshold=NUMERIC_TEXT_THRESHOLD):
    """True if most non-empty values of a text field convert to numbers."""
    numeric = non_empty = 0
    for value in values:
        number, status = parse_number(value)
        if status in (PARSE_NULL, PARSE_BLANK):
            continue
        non_empty += 1
        numeric += status == PARSE_OK
    return numeric > 0 and numeric / non_empty >= threshold


# -------------------------------------------------------------- head values


@dataclass
class HeadRecord:
    """One monitoring point (or multipoint part) with its derived head."""

    x: float
    y: float
    fid: int
    head: float = None
    ground: float = None
    dtw: float = None
    problem: str = None  # why no head: "null", "blank", "text", "mp:..", "dtw:.."
    raw_text: str = None  # offending text, for messages


@dataclass
class HeadStats:
    records: list = field(default_factory=list)
    usable: int = 0
    null: int = 0
    non_numeric: int = 0
    text_examples: list = field(default_factory=list)
    skipped_geometries: int = 0


def head_from_mp_dtw(mp, dtw):
    """Groundwater elevation = measuring-point elevation - depth to water."""
    return mp - dtw


def build_head_records(rows, method, skipped_geometries=0, max_examples=4):
    """Turn raw rows into ``HeadRecord``s and counts.

    ``rows`` are ``(x, y, fid, head_raw, mp_raw, dtw_raw, ground_raw)``; for
    ``GW_EXISTING`` only ``head_raw`` is used, for ``GW_CALCULATED`` only
    ``mp_raw`` and ``dtw_raw``. ``ground_raw`` is optional (QA only).
    """
    stats = HeadStats(skipped_geometries=skipped_geometries)
    for x, y, fid, head_raw, mp_raw, dtw_raw, ground_raw in rows:
        record = HeadRecord(x, y, fid)
        record.ground, _ = parse_number(ground_raw)
        if method == GW_CALCULATED:
            mp, mp_status = parse_number(mp_raw)
            dtw, dtw_status = parse_number(dtw_raw)
            record.dtw = dtw
            if mp_status == PARSE_OK and dtw_status == PARSE_OK:
                record.head = head_from_mp_dtw(mp, dtw)
            else:
                bad_status, bad_raw = (mp_status, mp_raw) if mp_status != PARSE_OK else (dtw_status, dtw_raw)
                record.problem = bad_status
                record.raw_text = None if bad_raw is None else str(bad_raw).strip()
        else:
            record.head, status = parse_number(head_raw)
            if status != PARSE_OK:
                record.problem = status
                record.raw_text = None if head_raw is None else str(head_raw).strip()
        if record.head is not None:
            stats.usable += 1
        elif record.problem == PARSE_TEXT:
            stats.non_numeric += 1
            new = record.raw_text and record.raw_text not in stats.text_examples
            if new and len(stats.text_examples) < max_examples:
                stats.text_examples.append(record.raw_text)
        else:
            stats.null += 1
        stats.records.append(record)
    return stats


def head_value_warnings(stats, describe_source):
    """Normal warnings about skipped records. ``describe_source``: e.g. "field 'WL'"."""
    warnings = []
    if stats.null:
        warnings.append(f"{stats.null} record(s) skipped: no reading ({describe_source} is NULL or blank).")
    if stats.non_numeric:
        examples = ", ".join(f"'{t}'" for t in stats.text_examples)
        warnings.append(
            f"{stats.non_numeric} record(s) skipped: {describe_source} is not a number"
            + (f" (e.g. {examples})" if examples else "") + "."
        )
    if stats.skipped_geometries:
        warnings.append(f"{stats.skipped_geometries} feature(s) skipped: empty or missing geometry.")
    return warnings


# ------------------------------------------------------------------- QA


def _where(record):
    return f"feature {record.fid} at ({record.x:.10g}, {record.y:.10g})"


def head_above_ground(records, limit=3):
    """IMPORTANT warning for heads above the (optional) ground elevation."""
    hits = [r for r in records if r.head is not None and r.ground is not None and r.head > r.ground]
    if not hits:
        return []
    examples = "; ".join(f"{_where(r)}: head {r.head:g} > ground {r.ground:g}" for r in hits[:limit])
    more = " ..." if len(hits) > limit else ""
    return [
        f"IMPORTANT: {len(hits)} well(s) have groundwater elevation above ground elevation ({examples}{more}). "
        "This can be real (flowing artesian conditions) or a datum/data-entry problem; "
        "review before relying on the contours."
    ]


def negative_depth_to_water(records, limit=3):
    """IMPORTANT warning for negative depth-to-water (water above the measuring point)."""
    hits = [r for r in records if r.dtw is not None and r.dtw < 0]
    if not hits:
        return []
    examples = "; ".join(f"{_where(r)}: depth to water {r.dtw:g}" for r in hits[:limit])
    more = " ..." if len(hits) > limit else ""
    return [
        f"IMPORTANT: {len(hits)} reading(s) have a negative depth to water ({examples}{more}), i.e. water above the "
        "measuring point. Possible for flowing wells, otherwise check the sign convention and data entry."
    ]


def _solve3(a, b):
    """Solve a 3x3 linear system with partial pivoting; None if singular."""
    m = [row[:] + [rhs] for row, rhs in zip(a, b)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for row in range(3):
            if row != col:
                factor = m[row][col] / m[col][col]
                m[row] = [v - factor * p for v, p in zip(m[row], m[col])]
    return [m[i][3] / m[i][i] for i in range(3)]


def planar_trend(points):
    """Least-squares plane h = a + b*x + c*y through ``(x, y, h)`` points (None if degenerate)."""
    n = len(points)
    if n < 3:
        return None
    mx = sum(p[0] for p in points) / n  # centre coordinates for numerical stability
    my = sum(p[1] for p in points) / n
    sxx = sxy = syy = sx = sy = sh = sxh = syh = 0.0
    for x, y, h in points:
        x, y = x - mx, y - my
        sx += x
        sy += y
        sh += h
        sxx += x * x
        sxy += x * y
        syy += y * y
        sxh += x * h
        syh += y * h
    solution = _solve3([[n, sx, sy], [sx, sxx, sxy], [sy, sxy, syy]], [sh, sxh, syh])
    if solution is None:
        return None
    a, b, c = solution
    return a - b * mx - c * my, b, c


def trend_outliers(points, z_threshold=OUTLIER_Z, min_points=OUTLIER_MIN_POINTS,
                   min_range_share=OUTLIER_MIN_RANGE_SHARE):
    """Indices of points far from the site-wide planar trend.

    Residuals from a least-squares plane are compared with a robust z-score
    (modified z = 0.6745 * |r - median| / MAD, Iglewicz & Hoaglin). Removing
    the plane first means a regional gradient is not mistaken for outliers.
    To stay conservative a point is flagged only if the deviation is also at
    least ``min_range_share`` of the head range.
    Returns ``[(index, residual, z), ...]``; nothing is removed.
    """
    if len(points) < min_points:
        return []
    plane = planar_trend(points)
    if plane is None:
        return []
    a, b, c = plane
    residuals = [h - (a + b * x + c * y) for x, y, h in points]
    med = _median(residuals)
    mad = _median([abs(r - med) for r in residuals])
    if mad <= 1e-12:
        return []
    heads = [h for _x, _y, h in points]
    min_deviation = min_range_share * (max(heads) - min(heads))
    flagged = []
    for index, residual in enumerate(residuals):
        z = 0.6745 * abs(residual - med) / mad
        if z > z_threshold and abs(residual - med) >= min_deviation:
            flagged.append((index, residual, z))
    return flagged


def outlier_warnings(points, limit=3):
    flagged = trend_outliers(points)
    if not flagged:
        return []
    examples = "; ".join(
        f"({points[i][0]:.10g}, {points[i][1]:.10g}): head {points[i][2]:g}, {r:+.3g} from the trend"
        for i, r, _z in flagged[:limit]
    )
    more = " ..." if len(flagged) > limit else ""
    return [
        f"IMPORTANT: {len(flagged)} well(s) differ strongly from the site-wide head trend ({examples}{more}); "
        f"robust z-score above {OUTLIER_Z:g} and at least {OUTLIER_MIN_RANGE_SHARE:.0%} of the head range. "
        "They are kept; check for data-entry, datum or different-aquifer issues."
    ]


# --------------------------------------------------------- flow direction


def central_gradient(sample, x, y, step):
    """Head gradient (dh/dx, dh/dy) by central differences at distance ``step``.

    ``sample(x, y)`` returns the surface value or ``None`` (no data). All four
    samples must exist, so no gradient is produced at the edge of the
    supported surface.
    """
    east, west = sample(x + step, y), sample(x - step, y)
    north, south = sample(x, y + step), sample(x, y - step)
    if None in (east, west, north, south):
        return None
    return (east - west) / (2 * step), (north - south) / (2 * step)


def flow_vector(dhdx, dhdy):
    """Return ``(azimuth_degrees, gradient_magnitude)`` of flow = -grad(h).

    Azimuth is clockwise from grid north (0 = north, 90 = east).
    """
    fx, fy = -dhdx, -dhdy
    magnitude = math.hypot(fx, fy)
    azimuth = math.degrees(math.atan2(fx, fy)) % 360.0
    return azimuth, magnitude


def compass_name(azimuth):
    return COMPASS_8[int(((azimuth % 360) + 22.5) // 45) % 8]


def arrow_spacing(area, target_count):
    """Grid spacing giving about ``target_count`` arrows over ``area``."""
    if not (area > 0 and target_count >= 1):
        raise ValueError("Area and target count must be positive.")
    return math.sqrt(area / target_count)


def arrow_seeds(xmin, ymin, xmax, ymax, spacing):
    """Regular grid of seed points (cell centres) covering a rectangle."""
    columns = max(1, int(round((xmax - xmin) / spacing)))
    rows = max(1, int(round((ymax - ymin) / spacing)))
    step_x = (xmax - xmin) / columns
    step_y = (ymax - ymin) / rows
    return [(xmin + (i + 0.5) * step_x, ymin + (j + 0.5) * step_y) for j in range(rows) for i in range(columns)]


def arrow_segment(x, y, azimuth, length):
    """Arrow from tail to head, centred on (x, y), pointing along ``azimuth``."""
    dx = math.sin(math.radians(azimuth)) * length / 2
    dy = math.cos(math.radians(azimuth)) * length / 2
    return (x - dx, y - dy), (x + dx, y + dy)


def arrow_lengths(magnitudes, base_length, scaling=ARROWS_UNIFORM, min_fraction=0.5):
    """Arrow lengths: uniform, or scaled by gradient within [min_fraction, 1] x base."""
    if scaling != ARROWS_SCALED or not magnitudes:
        return [base_length] * len(magnitudes)
    top = max(magnitudes)
    if top <= 0:
        return [base_length] * len(magnitudes)
    return [base_length * (min_fraction + (1 - min_fraction) * m / top) for m in magnitudes]


def generalized_direction(azimuths, min_arrows=DIRECTION_MIN_ARROWS, min_consistency=DIRECTION_CONSISTENCY):
    """Mean direction of unit vectors, or None when too few or too inconsistent.

    Returns ``(azimuth, consistency, compass_name)``. Consistency is the mean
    resultant length R (1 = all arrows parallel, 0 = no common direction).
    """
    if len(azimuths) < min_arrows:
        return None
    sx = sum(math.sin(math.radians(a)) for a in azimuths) / len(azimuths)
    sy = sum(math.cos(math.radians(a)) for a in azimuths) / len(azimuths)
    consistency = math.hypot(sx, sy)
    if consistency < min_consistency:
        return None
    azimuth = math.degrees(math.atan2(sx, sy)) % 360.0
    return azimuth, consistency, compass_name(azimuth)


def gradient_summary(magnitudes):
    """``(median, minimum, maximum)`` of local hydraulic gradients, or None."""
    if not magnitudes:
        return None
    return _median(magnitudes), min(magnitudes), max(magnitudes)


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2

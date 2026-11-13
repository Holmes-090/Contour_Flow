# SPDX-License-Identifier: GPL-2.0-or-later
"""Contour interval calculation.

Pure Python, no ``qgis`` import, so it can be unit-tested anywhere.

Contour levels are the multiples of the interval (offset 0), matching what
``gdal_contour -i <interval>`` produces: with an interval of 2.5 the levels
are ..., 97.5, 100, 102.5, ...
"""

import math

#: Mantissas used for "nice" automatic intervals (x 10^n).
NICE_MANTISSAS = (1, 2, 2.5, 5)

#: Upper limit on contour levels, to stop accidental huge outputs.
MAX_CONTOUR_LEVELS = 1000

#: Interval modes.
INTERVAL_AUTO = "auto"
INTERVAL_FIXED = "fixed"

_EPS = 1e-9


def level_count(vmin, vmax, interval):
    """Number of contour levels (multiples of ``interval``) within [vmin, vmax]."""
    if not interval > 0:
        raise ValueError("Interval must be positive.")
    first = math.ceil(vmin / interval - _EPS)
    last = math.floor(vmax / interval + _EPS)
    return max(0, last - first + 1)


def nice_interval(vmin, vmax, target_count):
    """Pick a 1/2/2.5/5 x 10^n interval giving about ``target_count`` levels.

    Ties are resolved in favour of the larger interval (fewer lines).
    """
    if target_count < 1:
        raise ValueError("Target contour count must be at least 1.")
    span = vmax - vmin
    if not (math.isfinite(span) and span > 0):
        raise ValueError("Value range must be finite and greater than zero.")
    exponent = math.floor(math.log10(span / target_count))
    candidates = [
        float(f"{mantissa}e{power}")
        for power in range(exponent - 1, exponent + 2)
        for mantissa in NICE_MANTISSAS
    ]
    return min(
        candidates,
        key=lambda step: (abs(level_count(vmin, vmax, step) - target_count), -step),
    )


def is_major_level(value, interval, major_every):
    """True if ``value`` is every ``major_every``-th multiple of ``interval``.

    Example: interval 0.25, major every 4 -> 100.0, 101.0, ... are major.
    """
    if not interval > 0 or major_every < 1:
        raise ValueError("Interval must be positive and major_every at least 1.")
    return round(value / interval) % major_every == 0


def interval_problem(vmin, vmax, interval):
    """Return why ``interval`` is unusable for the value range, or ``None``."""
    if not (math.isfinite(interval) and interval > 0):
        return "The contour interval must be a positive number."
    count = level_count(vmin, vmax, interval)
    if count == 0:
        return (
            f"An interval of {interval:g} gives no contour levels between "
            f"{vmin:g} and {vmax:g}. Use a smaller interval."
        )
    if count > MAX_CONTOUR_LEVELS:
        return (
            f"An interval of {interval:g} would create {count} contour levels "
            f"(limit {MAX_CONTOUR_LEVELS}). Use a larger interval."
        )
    return None


def resolve_interval(mode, vmin, vmax, target_count=10, fixed_interval=None):
    """Return ``(interval, problem)`` for the chosen mode.

    ``problem`` is ``None`` when the interval is usable, otherwise a sentence.
    """
    if mode == INTERVAL_AUTO:
        interval = nice_interval(vmin, vmax, target_count)
    elif mode == INTERVAL_FIXED:
        interval = fixed_interval
        if interval is None:
            return None, "Enter a fixed contour interval."
    else:
        raise ValueError(f"Unknown interval mode: {mode!r}")
    return interval, interval_problem(vmin, vmax, interval)

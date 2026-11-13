# SPDX-License-Identifier: GPL-2.0-or-later
"""Raster grid sizing for interpolated surfaces.

Pure Python, no ``qgis`` import, so it can be unit-tested anywhere.
Cell sizes are in the units of the point layer's CRS.
"""

import math

#: Automatic cell size aims for this many cells along the longer extent side.
AUTO_CELLS_LONG_SIDE = 500

#: Upper limit on surface size, to protect memory and run time.
MAX_GRID_CELLS = 25_000_000


def _round_down_2_significant(value):
    exponent = math.floor(math.log10(value)) - 1
    factor = 10.0 ** exponent
    return float(f"{math.floor(value / factor + 1e-9)}e{exponent}")


def auto_cell_size(width, height):
    """Cell size giving about ``AUTO_CELLS_LONG_SIDE`` cells on the long side.

    Rounded down to two significant figures (e.g. 0.37, 1.2, 250).
    """
    long_side = max(width, height)
    if not (math.isfinite(long_side) and long_side > 0):
        raise ValueError("Extent must have a positive width or height.")
    return _round_down_2_significant(long_side / AUTO_CELLS_LONG_SIDE)


def grid_shape(width, height, cell_size):
    """Return ``(columns, rows)`` covering the extent at ``cell_size``."""
    if not cell_size > 0:
        raise ValueError("Cell size must be positive.")
    columns = max(1, math.ceil(width / cell_size - 1e-9) + 1)
    rows = max(1, math.ceil(height / cell_size - 1e-9) + 1)
    return columns, rows


def grid_problem(width, height, cell_size):
    """Return why the grid is unusable, or ``None``."""
    if not (math.isfinite(cell_size) and cell_size > 0):
        return "The cell size must be a positive number."
    columns, rows = grid_shape(width, height, cell_size)
    if columns * rows > MAX_GRID_CELLS:
        return (
            f"A cell size of {cell_size:g} would create a {columns} x {rows} "
            f"surface ({columns * rows:,} cells, limit {MAX_GRID_CELLS:,}). "
            "Use a larger cell size."
        )
    return None

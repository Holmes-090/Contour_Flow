# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for core.grid (plain Python, no QGIS)."""

import unittest

from contour_generator.core.grid import MAX_GRID_CELLS, auto_cell_size, grid_problem, grid_shape


class AutoCellSizeTests(unittest.TestCase):
    def test_round_numbers(self):
        self.assertEqual(auto_cell_size(1000, 400), 2.0)

    def test_rounds_down_to_two_significant_figures(self):
        self.assertEqual(auto_cell_size(617, 10), 1.2)  # 1.234 -> 1.2

    def test_small_extent(self):
        self.assertAlmostEqual(auto_cell_size(0.185, 0.1), 0.00037)

    def test_uses_longer_side(self):
        self.assertEqual(auto_cell_size(10, 5000), 10.0)

    def test_zero_extent_raises(self):
        with self.assertRaises(ValueError):
            auto_cell_size(0, 0)

    def test_auto_grid_is_within_limit(self):
        for width, height in [(1000, 400), (3, 9e6), (1e-3, 1e-3)]:
            cell = auto_cell_size(width, height)
            self.assertIsNone(grid_problem(width, height, cell))


class GridShapeTests(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(grid_shape(100, 50, 10), (11, 6))

    def test_thin_extent_has_at_least_one_row(self):
        self.assertEqual(grid_shape(100, 0, 10), (11, 1))

    def test_too_large(self):
        problem = grid_problem(100000, 100000, 1)
        self.assertIn(f"{MAX_GRID_CELLS:,}", problem)

    def test_bad_cell_size(self):
        self.assertIn("positive", grid_problem(10, 10, 0))


if __name__ == "__main__":
    unittest.main()

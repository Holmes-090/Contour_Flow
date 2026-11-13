# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for core.intervals (plain Python, no QGIS)."""

import math
import unittest

from contour_flow.core.intervals import (
    INTERVAL_AUTO,
    INTERVAL_FIXED,
    MAX_CONTOUR_LEVELS,
    interval_problem,
    level_count,
    nice_interval,
    resolve_interval,
)


class LevelCountTests(unittest.TestCase):
    def test_inclusive_bounds(self):
        # 100, 102, 104, 106, 108, 110
        self.assertEqual(level_count(100, 110, 2), 6)

    def test_bounds_between_levels(self):
        # 101, 102, ..., 109
        self.assertEqual(level_count(100.5, 109.5, 1), 9)

    def test_negative_values(self):
        # -10, -5, 0, 5
        self.assertEqual(level_count(-12, 7, 5), 4)

    def test_decimal_interval_float_noise(self):
        # 0.1 .. 0.3 at 0.1 -> 0.1, 0.2, 0.3 despite binary rounding
        self.assertEqual(level_count(0.1, 0.3, 0.1), 3)

    def test_no_level_inside_range(self):
        self.assertEqual(level_count(101, 104, 5), 0)

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            level_count(0, 10, 0)


class NiceIntervalTests(unittest.TestCase):
    def test_typical_elevations(self):
        # 0.1 gives 13 levels and 0.2 gives 7: both 3 away from 10, so the
        # larger interval wins.
        self.assertEqual(nice_interval(100.8, 102.0, 10), 0.2)

    def test_result_is_nice(self):
        for vmin, vmax, target in [(0, 1234, 10), (-3.2, 8.9, 7), (0.001, 0.004, 5), (250, 2600, 20)]:
            interval = nice_interval(vmin, vmax, target)
            mantissa = interval / 10 ** math.floor(math.log10(interval))
            self.assertTrue(any(abs(mantissa - m) < 1e-9 for m in (1, 2, 2.5, 5)), interval)

    def test_count_close_to_target(self):
        interval = nice_interval(0, 1000, 10)
        self.assertEqual(interval, 100)
        self.assertEqual(level_count(0, 1000, interval), 11)

    def test_tie_prefers_larger_interval(self):
        # 0..10 target 4: interval 2.5 -> 5 levels, 5 -> 3 levels, both 1 away.
        self.assertEqual(nice_interval(0, 10, 4), 5)

    def test_zero_range_raises(self):
        with self.assertRaises(ValueError):
            nice_interval(5, 5, 10)

    def test_bad_target_raises(self):
        with self.assertRaises(ValueError):
            nice_interval(0, 10, 0)


class IntervalProblemTests(unittest.TestCase):
    def test_ok(self):
        self.assertIsNone(interval_problem(0, 100, 10))

    def test_too_many_levels(self):
        problem = interval_problem(0, 100000, 1)
        self.assertIn(str(MAX_CONTOUR_LEVELS), problem)

    def test_no_levels(self):
        self.assertIn("no contour levels", interval_problem(101, 104, 5))

    def test_non_positive(self):
        self.assertIn("positive", interval_problem(0, 10, -1))


class ResolveIntervalTests(unittest.TestCase):
    def test_auto(self):
        self.assertEqual(resolve_interval(INTERVAL_AUTO, 0, 1000, 10), (100, None))

    def test_fixed(self):
        self.assertEqual(resolve_interval(INTERVAL_FIXED, 0, 100, fixed_interval=25), (25, None))

    def test_fixed_problem(self):
        interval, problem = resolve_interval(INTERVAL_FIXED, 0, 100, fixed_interval=0.01)
        self.assertEqual(interval, 0.01)
        self.assertIsNotNone(problem)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            resolve_interval("other", 0, 1)


if __name__ == "__main__":
    unittest.main()

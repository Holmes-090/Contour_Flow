# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for core.options, core.report and major classification (plain Python)."""

import os
import tempfile
import unittest

from contour_flow.core import options as o
from contour_flow.core.intervals import auto_major_every, is_major_level
from contour_flow.core.report import (
    DISCLAIMER,
    format_value,
    metadata_json,
    metadata_text,
    parse_metadata_json,
)


class IdwTests(unittest.TestCase):
    def test_default_ok(self):
        self.assertIsNone(o.idw_power_problem(o.IDW_POWER_DEFAULT))

    def test_bounds(self):
        self.assertIsNone(o.idw_power_problem(0.5))
        self.assertIsNone(o.idw_power_problem(99.99))
        self.assertIsNotNone(o.idw_power_problem(0))
        self.assertIsNotNone(o.idw_power_problem(-1))
        self.assertIsNotNone(o.idw_power_problem(100))
        self.assertIsNotNone(o.idw_power_problem(float("nan")))


class ExtentTests(unittest.TestCase):
    def test_simple_modes_ok(self):
        for mode in (o.EXTENT_POINTS, o.EXTENT_HULL):
            self.assertIsNone(o.extent_problem(mode, has_boundary=False))

    def test_buffer_required(self):
        self.assertIsNotNone(o.extent_problem(o.EXTENT_BUFFERED_HULL, False, buffer_distance=0))
        self.assertIsNone(o.extent_problem(o.EXTENT_BUFFERED_HULL, False, buffer_distance=10))

    def test_buffer_validation(self):
        self.assertIsNone(o.buffer_problem(0.001))
        for bad in (0, -5, float("inf"), None):
            self.assertIsNotNone(o.buffer_problem(bad))

    def test_boundary_mode_needs_boundary(self):
        self.assertIn("boundary", o.extent_problem(o.EXTENT_BOUNDARY, has_boundary=False))
        self.assertIsNone(o.extent_problem(o.EXTENT_BOUNDARY, has_boundary=True))

    def test_custom_needs_extent(self):
        self.assertIsNotNone(o.extent_problem(o.EXTENT_CUSTOM, False, custom_extent_valid=False))
        self.assertIsNone(o.extent_problem(o.EXTENT_CUSTOM, False, custom_extent_valid=True))

    def test_unknown_mode(self):
        self.assertIsNotNone(o.extent_problem("world", False))

    def test_polygon_modes(self):
        self.assertNotIn(o.EXTENT_POINTS, o.POLYGON_EXTENT_MODES)
        self.assertNotIn(o.EXTENT_CUSTOM, o.POLYGON_EXTENT_MODES)


class BoundaryTests(unittest.TestCase):
    def test_no_boundary_is_fine(self):
        self.assertIsNone(o.boundary_problem(False, o.BOUNDARY_SELECTED, 0))

    def test_selected_without_selection(self):
        self.assertIn("Select one or more boundary polygons", o.boundary_problem(True, o.BOUNDARY_SELECTED, 0))

    def test_selected_with_selection(self):
        self.assertIsNone(o.boundary_problem(True, o.BOUNDARY_SELECTED, 2))
        self.assertIsNone(o.boundary_problem(True, o.BOUNDARY_ALL, 0))


class SmoothingTests(unittest.TestCase):
    def test_none(self):
        self.assertEqual(o.smoothing_parameters(o.SMOOTH_NONE), (None, None))

    def test_presets(self):
        self.assertEqual(o.smoothing_parameters(o.SMOOTH_LIGHT), ((1, 0.25), None))
        self.assertEqual(o.smoothing_parameters(o.SMOOTH_MEDIUM), ((2, 0.25), None))

    def test_custom_ok(self):
        self.assertEqual(o.smoothing_parameters(o.SMOOTH_CUSTOM, 3, 0.4), ((3, 0.4), None))

    def test_custom_invalid(self):
        for iterations, offset in [(0, 0.25), (6, 0.25), (2.5, 0.25), (2, 0), (2, 0.6)]:
            params, problem = o.smoothing_parameters(o.SMOOTH_CUSTOM, iterations, offset)
            self.assertIsNone(params)
            self.assertIsNotNone(problem, (iterations, offset))

    def test_unknown(self):
        self.assertIsNotNone(o.smoothing_parameters("heavy")[1])


class MajorAndLabelTests(unittest.TestCase):
    def test_major_every_four_quarter_interval(self):
        values = [100.0, 100.25, 100.5, 100.75, 101.0, 101.25]
        self.assertEqual([is_major_level(v, 0.25, 4) for v in values],
                         [True, False, False, False, True, False])

    def test_major_negative_and_float_noise(self):
        self.assertTrue(is_major_level(-1.0, 0.25, 4))
        self.assertTrue(is_major_level(0.1 * 30, 0.1, 10))  # 3.0000000000000004
        self.assertFalse(is_major_level(2.9, 0.1, 10))

    def test_major_every_one_means_all(self):
        self.assertTrue(all(is_major_level(v, 2, 1) for v in (2, 4, 6)))

    def test_major_invalid(self):
        with self.assertRaises(ValueError):
            is_major_level(1, 0, 4)
        self.assertIsNone(o.major_every_problem(o.MAJOR_EVERY_AUTO))  # 0 = automatic
        self.assertIsNotNone(o.major_every_problem(-1))
        self.assertIsNotNone(o.major_every_problem(2.5))
        self.assertIsNone(o.major_every_problem(5))

    def test_auto_major_every_gives_round_majors(self):
        for interval, every, major in [(0.25, 4, 1.0), (0.5, 2, 1.0), (1, 5, 5), (2, 5, 10), (2.5, 4, 10),
                                       (5, 2, 10), (0.1, 5, 0.5), (20, 5, 100), (0.05, 2, 0.1)]:
            self.assertEqual(auto_major_every(interval), every, interval)
            self.assertAlmostEqual(interval * auto_major_every(interval), major)

    def test_auto_major_every_unusual_interval(self):
        self.assertEqual(auto_major_every(0.3), 5)
        with self.assertRaises(ValueError):
            auto_major_every(0)

    def test_label_precision(self):
        self.assertIsNone(o.label_precision_problem(0))
        self.assertIsNone(o.label_precision_problem(6))
        for bad in (-1, 7, 1.5):
            self.assertIsNotNone(o.label_precision_problem(bad))

    def test_suggested_precision(self):
        self.assertEqual(o.suggested_label_precision(5), 0)
        self.assertEqual(o.suggested_label_precision(0.5), 1)
        self.assertEqual(o.suggested_label_precision(0.25), 2)
        self.assertEqual(o.suggested_label_precision(0.1), 1)

    def test_style_presets(self):
        self.assertEqual(o.STYLE_PRESETS[o.STYLE_GROUNDWATER]["color"], "#1f5fbf")
        self.assertLess(o.MINOR_LINE_WIDTH_MM, o.MAJOR_LINE_WIDTH_MM)


class NamingTests(unittest.TestCase):
    def test_clean_layer_name(self):
        self.assertEqual(o.clean_layer_name("  My \t contours\n "), "My contours")
        self.assertEqual(o.clean_layer_name(None), "")

    def test_default_layer_name(self):
        self.assertEqual(o.default_layer_name("gw_elev", 0.25), "Contours gw_elev (0.25)")
        self.assertEqual(o.default_layer_name("DEM", 5, smoothed=True), "Contours DEM (5) smoothed")

    def test_unique_name(self):
        self.assertEqual(o.unique_name("c", []), "c")
        self.assertEqual(o.unique_name("c", ["C"]), "c_2")
        self.assertEqual(o.unique_name("c", ["c", "c_2", "C_3"]), "c_4")

    def test_unique_file_path(self):
        existing = {"/x/a.tif", "/x/a_2.tif"}
        self.assertEqual(o.unique_file_path("/x/b.tif", existing.__contains__), "/x/b.tif")
        self.assertEqual(o.unique_file_path("/x/a.tif", existing.__contains__), "/x/a_3.tif")

    def test_output_path_problem(self):
        with tempfile.TemporaryDirectory() as folder:
            good = os.path.join(folder, "out.gpkg")
            self.assertIsNone(o.output_path_problem(good, ".gpkg", "GeoPackage"))
            self.assertIn(".gpkg", o.output_path_problem(os.path.join(folder, "out.shp"), ".gpkg", "GeoPackage"))
            self.assertIn("does not exist", o.output_path_problem(os.path.join(folder, "missing", "o.gpkg"), ".gpkg", "GeoPackage"))
            self.assertIn("Choose", o.output_path_problem("", ".gpkg", "GeoPackage"))


class MetadataTests(unittest.TestCase):
    ITEMS = [("Input type", "points"), ("Cell size", 0.5), ("Smoothing", None),
             ("Keep unsmoothed", True), ("Extent", (1.0, 2.0))]

    def test_format_value(self):
        self.assertEqual(format_value(0.25), "0.25")
        self.assertEqual(format_value(None), "none")
        self.assertEqual(format_value(False), "no")
        self.assertEqual(format_value([1.5, "a"]), "1.5, a")

    def test_text(self):
        text = metadata_text(self.ITEMS, ["W1"])
        self.assertIn("Cell size: 0.5", text)
        self.assertIn("Smoothing: none", text)
        self.assertIn("- W1", text)
        self.assertTrue(text.endswith(DISCLAIMER))

    def test_json_roundtrip(self):
        items, warnings = parse_metadata_json(metadata_json(self.ITEMS, ["W1"]))
        self.assertEqual(items[0], ("Input type", "points"))
        self.assertEqual(items[1], ("Cell size", 0.5))
        self.assertEqual(items[4], ("Extent", [1.0, 2.0]))
        self.assertEqual(warnings, ["W1"])

    def test_json_non_finite(self):
        items, _ = parse_metadata_json(metadata_json([("x", float("inf"))]))
        self.assertEqual(items, [("x", "inf")])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for the QGIS-independent parts of core.input_validation.

Run from the repository root with plain Python (no QGIS needed):

    python -m unittest discover -s tests -t .
"""

import unittest

from contour_flow.core.input_validation import (
    DUPLICATES_KEEP_FIRST,
    DUPLICATES_MEAN,
    DUPLICATES_STOP,
    MAX_CONFLICT_EXAMPLES,
    FEATURES_ALL,
    FEATURES_SELECTED,
    are_collinear,
    crs_warnings,
    point_data_report,
    point_input_problem,
    prepare_point_samples,
    raster_input_problem,
    raster_range_problem,
    usable_feature_count,
)

SQUARE = [(0, 0, 1.0), (10, 0, 2.0), (0, 10, 3.0), (10, 10, 4.0)]


class UsableFeatureCountTests(unittest.TestCase):
    def test_all_features_uses_total(self):
        self.assertEqual(usable_feature_count(FEATURES_ALL, 10, 3), 10)

    def test_selected_features_uses_selection(self):
        self.assertEqual(usable_feature_count(FEATURES_SELECTED, 10, 3), 3)

    def test_unknown_total_is_passed_through(self):
        self.assertEqual(usable_feature_count(FEATURES_ALL, -1, 0), -1)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            usable_feature_count("some", 10, 3)


class PointInputProblemTests(unittest.TestCase):
    def check(self, **overrides):
        values = dict(
            has_layer=True,
            field_name="value",
            field_is_numeric=True,
            feature_mode=FEATURES_ALL,
            total_count=5,
            selected_count=0,
        )
        values.update(overrides)
        return point_input_problem(**values)

    def test_valid_all_features(self):
        self.assertIsNone(self.check())

    def test_no_layer(self):
        self.assertEqual(self.check(has_layer=False), "Choose a point layer.")

    def test_no_field(self):
        self.assertEqual(self.check(field_name=""), "Choose a value / elevation field.")

    def test_non_numeric_field(self):
        self.assertIn("not numeric", self.check(field_is_numeric=False))

    def test_empty_layer(self):
        self.assertEqual(self.check(total_count=0), "The point layer has no features.")

    def test_unknown_feature_count_is_not_blocked(self):
        self.assertIsNone(self.check(total_count=-1))

    def test_selected_mode_with_no_selection(self):
        self.assertEqual(
            self.check(feature_mode=FEATURES_SELECTED, selected_count=0),
            "Select one or more point features in QGIS, or switch to All features.",
        )

    def test_selected_mode_with_selection(self):
        self.assertIsNone(self.check(feature_mode=FEATURES_SELECTED, selected_count=2))

    def test_layer_problem_reported_before_field_problem(self):
        self.assertEqual(self.check(has_layer=False, field_name=""), "Choose a point layer.")


class RasterInputProblemTests(unittest.TestCase):
    def test_valid(self):
        self.assertIsNone(raster_input_problem(True))

    def test_no_layer(self):
        self.assertEqual(raster_input_problem(False), "Choose a raster layer.")

    def test_no_band(self):
        self.assertEqual(raster_input_problem(True, -1), "Choose a raster band.")


class PreparePointSamplesTests(unittest.TestCase):
    def test_clean_input_unchanged(self):
        samples = prepare_point_samples(SQUARE)
        self.assertEqual(samples.points, SQUARE)
        self.assertEqual(
            (samples.missing_values, samples.duplicate_points, samples.conflicting_locations),
            (0, 0, 0),
        )

    def test_missing_and_non_finite_values_dropped(self):
        raw = SQUARE + [(5, 5, None), (6, 6, float("nan")), (7, 7, float("inf"))]
        samples = prepare_point_samples(raw)
        self.assertEqual(samples.points, SQUARE)
        self.assertEqual(samples.missing_values, 3)

    def test_equal_duplicates_are_not_conflicts(self):
        samples = prepare_point_samples(SQUARE + [(0, 0, 1.0), (0, 0, 1.0 + 1e-9)])
        self.assertEqual(samples.points, SQUARE)
        self.assertEqual((samples.duplicate_points, samples.equal_duplicate_locations), (2, 1))
        self.assertEqual(samples.conflicting_locations, 0)

    def test_conflicting_duplicates_keep_first(self):
        samples = prepare_point_samples(SQUARE + [(10, 0, 9.0)])
        self.assertEqual(samples.points, SQUARE)
        self.assertEqual(samples.conflicting_locations, 1)
        self.assertEqual(samples.conflict_examples, [(10, 0, [2.0, 9.0])])

    def test_conflicting_duplicates_mean(self):
        samples = prepare_point_samples(SQUARE + [(10, 0, 4.0)], duplicate_mode=DUPLICATES_MEAN)
        self.assertEqual(samples.points[1], (10, 0, 3.0))

    def test_first_occurrence_order_kept(self):
        raw = [(5, 5, 1.0), (0, 0, 2.0), (5, 5, 3.0)]
        self.assertEqual([p[:2] for p in prepare_point_samples(raw).points], [(5, 5), (0, 0)])

    def test_examples_are_limited(self):
        raw = SQUARE + [(x, y, v + 50) for x, y, v in SQUARE]
        samples = prepare_point_samples(raw)
        self.assertEqual(samples.conflicting_locations, 4)
        self.assertEqual(len(samples.conflict_examples), MAX_CONFLICT_EXAMPLES)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            prepare_point_samples(SQUARE, duplicate_mode="median")

    def test_skipped_geometries_passed_through(self):
        self.assertEqual(prepare_point_samples(SQUARE, skipped_geometries=2).skipped_geometries, 2)


class DuplicateReportTests(unittest.TestCase):
    def report(self, raw, mode):
        return point_data_report(prepare_point_samples(raw, duplicate_mode=mode), "gw_elev")

    def test_keep_first_warns_strongly(self):
        errors, warnings = self.report(SQUARE + [(10, 0, 9.0)], DUPLICATES_KEEP_FIRST)
        self.assertEqual(errors, [])
        self.assertTrue(warnings[0].startswith("IMPORTANT:"))
        self.assertIn("(10, 0): 2, 9", warnings[0])
        self.assertIn("first value", warnings[0])

    def test_mean_warns(self):
        _, warnings = self.report(SQUARE + [(10, 0, 9.0)], DUPLICATES_MEAN)
        self.assertIn("averaged", warnings[0])

    def test_stop_is_an_error(self):
        errors, _ = self.report(SQUARE + [(10, 0, 9.0)], DUPLICATES_STOP)
        self.assertIn("different values", errors[0])

    def test_stop_allows_equal_duplicates(self):
        errors, warnings = self.report(SQUARE + [(10, 0, 2.0)], DUPLICATES_STOP)
        self.assertEqual(errors, [])
        self.assertIn("same value", warnings[0])


class CollinearTests(unittest.TestCase):
    def test_square_is_not_collinear(self):
        self.assertFalse(are_collinear(SQUARE))

    def test_points_on_diagonal(self):
        self.assertTrue(are_collinear([(0, 0), (1, 1), (5, 5), (2, 2)]))

    def test_nearly_collinear_within_tolerance(self):
        self.assertTrue(are_collinear([(0, 0), (1000, 0), (500, 1e-7)]))

    def test_slightly_off_line_is_not_collinear(self):
        self.assertFalse(are_collinear([(0, 0), (1000, 0), (500, 1)]))

    def test_vertical_line(self):
        self.assertTrue(are_collinear([(3, 0), (3, 10), (3, 4)]))

    def test_fewer_than_three(self):
        self.assertTrue(are_collinear([(0, 0), (1, 5)]))


class PointDataReportTests(unittest.TestCase):
    def report(self, raw, skipped=0):
        return point_data_report(prepare_point_samples(raw, skipped), "gw_elev")

    def test_clean_data(self):
        self.assertEqual(self.report(SQUARE), ([], []))

    def test_too_few_points(self):
        errors, _ = self.report(SQUARE[:2])
        self.assertEqual(len(errors), 1)
        self.assertIn("At least 3", errors[0])

    def test_duplicates_do_not_count_towards_minimum(self):
        errors, warnings = self.report([(0, 0, 1.0), (0, 0, 2.0), (1, 1, 3.0)])
        self.assertIn("2 found", errors[0])
        self.assertTrue(any("different values" in w for w in warnings))

    def test_collinear(self):
        errors, _ = self.report([(0, 0, 1.0), (1, 1, 2.0), (2, 2, 3.0)])
        self.assertIn("straight line", errors[0])

    def test_all_values_equal(self):
        errors, _ = self.report([(x, y, 5.0) for x, y, _ in SQUARE])
        self.assertIn("All point values are equal", errors[0])

    def test_warnings_for_skipped_data(self):
        errors, warnings = self.report(SQUARE + [(5, 5, None)], skipped=1)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("gw_elev" in w for w in warnings))


class CrsAndRasterTests(unittest.TestCase):
    def test_projected_crs_no_warning(self):
        self.assertEqual(crs_warnings(True, False, "EPSG:32633"), [])

    def test_geographic_crs_warning(self):
        self.assertIn("geographic", crs_warnings(True, True, "EPSG:4326")[0])

    def test_missing_crs_warning(self):
        self.assertIn("no coordinate reference system", crs_warnings(False, False, "")[0])

    def test_raster_range_ok(self):
        self.assertIsNone(raster_range_problem(10.0, 20.0, 100))

    def test_raster_no_valid_cells(self):
        self.assertIn("no valid", raster_range_problem(float("inf"), float("-inf"), 0))
        self.assertIn("no valid", raster_range_problem(5.0, 1.0, 10))

    def test_raster_range_trusted_when_cell_count_missing(self):
        self.assertIsNone(raster_range_problem(10.0, 20.0, 0))

    def test_raster_flat(self):
        self.assertIn("equal", raster_range_problem(3.0, 3.0, 50))


if __name__ == "__main__":
    unittest.main()

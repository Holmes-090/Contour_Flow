# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for core.groundwater (plain Python, no QGIS)."""

import math
import unittest

from contour_flow.core import groundwater as gw


class ParseNumberTests(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(gw.parse_number(202.51), (202.51, gw.PARSE_OK))
        self.assertEqual(gw.parse_number(7), (7.0, gw.PARSE_OK))

    def test_numeric_text_is_trimmed_and_converted(self):
        self.assertEqual(gw.parse_number(" 202.51 "), (202.51, gw.PARSE_OK))
        self.assertEqual(gw.parse_number("-3"), (-3.0, gw.PARSE_OK))

    def test_null_blank_and_text_are_not_zero(self):
        self.assertEqual(gw.parse_number(None), (None, gw.PARSE_NULL))
        self.assertEqual(gw.parse_number("   "), (None, gw.PARSE_BLANK))
        for text in ("N/A", "Dry", "202,51", "nan", "inf", "approx 3"):
            self.assertEqual(gw.parse_number(text), (None, gw.PARSE_TEXT), text)
        self.assertEqual(gw.parse_number(float("nan")), (None, gw.PARSE_TEXT))
        self.assertEqual(gw.parse_number(True), (None, gw.PARSE_TEXT))

    def test_qvariant_like_null(self):
        class FakeNull:
            def isNull(self):
                return True

        self.assertEqual(gw.parse_number(FakeNull()), (None, gw.PARSE_NULL))

    def test_looks_numeric(self):
        self.assertTrue(gw.looks_numeric(["202.51", " 201.9", None, "", "Dry"]))
        self.assertFalse(gw.looks_numeric(["MW-1", "MW-2", "3"]))
        self.assertFalse(gw.looks_numeric([None, "", "  "]))


ROWS_EXISTING = [
    (0, 0, 1, "100.5", None, None, 101.0),
    (10, 0, 2, " 100.2 ", None, None, None),
    (0, 10, 3, None, None, None, None),
    (10, 10, 4, "Dry", None, None, None),
    (5, 5, 5, "N/A", None, None, None),
    (7, 3, 6, "", None, None, None),
]


class HeadRecordTests(unittest.TestCase):
    def test_existing_field_counts(self):
        stats = gw.build_head_records(ROWS_EXISTING, gw.GW_EXISTING)
        self.assertEqual((stats.usable, stats.null, stats.non_numeric), (2, 2, 2))
        self.assertEqual(stats.text_examples, ["Dry", "N/A"])
        self.assertEqual(stats.records[1].head, 100.2)
        self.assertEqual(stats.records[0].ground, 101.0)

    def test_calculated_head(self):
        rows = [(0, 0, 1, None, 105.0, 4.5, None), (1, 0, 2, None, "105.2", " 4.7", None),
                (2, 0, 3, None, 105.0, None, None), (3, 0, 4, None, 105.0, "Dry", None)]
        stats = gw.build_head_records(rows, gw.GW_CALCULATED)
        self.assertEqual([r.head for r in stats.records], [100.5, 100.5, None, None])
        self.assertEqual((stats.usable, stats.null, stats.non_numeric), (2, 1, 1))
        self.assertEqual(gw.head_from_mp_dtw(110.0, 2.25), 107.75)

    def test_warnings_text(self):
        stats = gw.build_head_records(ROWS_EXISTING, gw.GW_EXISTING, skipped_geometries=1)
        warnings = gw.head_value_warnings(stats, "field 'WL'")
        self.assertEqual(len(warnings), 3)
        self.assertIn("2 record(s) skipped: no reading", warnings[0])
        self.assertIn("'Dry', 'N/A'", warnings[1])


class QaTests(unittest.TestCase):
    def test_head_above_ground(self):
        records = [gw.HeadRecord(0, 0, 1, head=101.0, ground=100.0), gw.HeadRecord(1, 1, 2, head=99.0, ground=100.0),
                   gw.HeadRecord(2, 2, 3, head=99.0)]
        warnings = gw.head_above_ground(records)
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("IMPORTANT:"))
        self.assertIn("feature 1", warnings[0])
        self.assertIn("artesian", warnings[0])
        self.assertEqual(gw.head_above_ground(records[1:]), [])

    def test_negative_dtw(self):
        records = [gw.HeadRecord(0, 0, 1, head=105.2, dtw=-0.2), gw.HeadRecord(1, 0, 2, head=100.0, dtw=5.0)]
        warnings = gw.negative_depth_to_water(records)
        self.assertEqual(len(warnings), 1)
        self.assertIn("-0.2", warnings[0])

    def plane_points(self, outlier=None):
        points = []
        for i, (x, y) in enumerate([(0, 0), (100, 0), (0, 100), (100, 100), (50, 50), (25, 75), (75, 25),
                                    (60, 90), (90, 40), (10, 40)]):
            h = 100 - 0.01 * x + 0.02 * y + 0.01 * math.sin(i)  # gradient + tiny noise
            if outlier == i:
                h += 1.5
            points.append((x, y, h))
        return points

    def test_regional_gradient_is_not_an_outlier(self):
        self.assertEqual(gw.trend_outliers(self.plane_points()), [])

    def test_off_trend_well_is_flagged(self):
        flagged = gw.trend_outliers(self.plane_points(outlier=4))
        self.assertEqual([i for i, _r, _z in flagged], [4])
        self.assertGreater(flagged[0][1], 1.0)  # least-squares plane is pulled slightly towards the outlier
        self.assertIn("IMPORTANT:", gw.outlier_warnings(self.plane_points(outlier=4))[0])

    def test_small_local_feature_is_not_flagged(self):
        # a 0.15 m mound on a 3 m head range: statistically unusual but below 10 % of the range
        points = self.plane_points()
        x, y, h = points[4]
        points[4] = (x, y, h + 0.15)
        self.assertEqual(gw.trend_outliers(points), [])
        self.assertEqual([i for i, _r, _z in gw.trend_outliers(points, min_range_share=0)], [4])

    def test_outliers_need_enough_points(self):
        self.assertEqual(gw.trend_outliers(self.plane_points(outlier=1)[:4]), [])

    def test_planar_trend_recovers_plane(self):
        a, b, c = gw.planar_trend([(x, y, 5 + 2 * x - 3 * y) for x, y in [(0, 0), (1, 0), (0, 1), (2, 3), (5, 1)]])
        self.assertAlmostEqual(a, 5)
        self.assertAlmostEqual(b, 2)
        self.assertAlmostEqual(c, -3)
        self.assertIsNone(gw.planar_trend([(0, 0, 1), (1, 1, 2), (2, 2, 3)]))


class FlowTests(unittest.TestCase):
    def plane_sampler(self, b, c):
        return lambda x, y: 100 + b * x + c * y

    def test_flow_points_downgradient_southeast(self):
        # head falls to the east (b<0) and to the south (c>0): flow to the south-east
        sample = self.plane_sampler(-0.01, 0.01)
        dhdx, dhdy = gw.central_gradient(sample, 50, 50, 5)
        azimuth, magnitude = gw.flow_vector(dhdx, dhdy)
        self.assertAlmostEqual(azimuth, 135.0, places=6)
        self.assertAlmostEqual(magnitude, math.hypot(0.01, 0.01), places=9)
        self.assertEqual(gw.compass_name(azimuth), "southeast")

    def test_cardinal_directions(self):
        for b, c, expected in [(0, -0.01, 0.0), (-0.01, 0, 90.0), (0, 0.01, 180.0), (0.01, 0, 270.0)]:
            azimuth, _ = gw.flow_vector(*gw.central_gradient(self.plane_sampler(b, c), 0, 0, 1))
            self.assertAlmostEqual(azimuth, expected, places=6)

    def test_gradient_needs_all_samples(self):
        sample = lambda x, y: None if x > 10 else 1.0  # noqa: E731
        self.assertIsNone(gw.central_gradient(sample, 10, 0, 1))

    def test_compass_names(self):
        self.assertEqual([gw.compass_name(a) for a in (0, 22, 23, 90, 181, 300, 359)],
                         ["north", "north", "northeast", "east", "south", "northwest", "north"])

    def test_spacing_and_seeds(self):
        spacing = gw.arrow_spacing(10000, 9)
        self.assertAlmostEqual(spacing, 100 / 3)
        seeds = gw.arrow_seeds(0, 0, 100, 100, spacing)
        self.assertEqual(len(seeds), 9)
        self.assertAlmostEqual(seeds[0][0], 100 / 6)
        with self.assertRaises(ValueError):
            gw.arrow_spacing(0, 9)

    def test_segment_is_centred_and_points_downstream(self):
        (x0, y0), (x1, y1) = gw.arrow_segment(10, 10, 90, 4)
        self.assertAlmostEqual((x0, y0, x1, y1), (8, 10, 12, 10))

    def test_lengths(self):
        self.assertEqual(gw.arrow_lengths([0.1, 0.2], 10), [10, 10])
        self.assertEqual(gw.arrow_lengths([0.1, 0.2], 10, gw.ARROWS_SCALED), [7.5, 10])

    def test_generalized_direction(self):
        result = gw.generalized_direction([130, 135, 140, 138])
        self.assertAlmostEqual(result[0], 135.75, places=1)
        self.assertEqual(result[2], "southeast")
        self.assertGreater(result[1], 0.99)
        self.assertIsNone(gw.generalized_direction([0, 90, 180, 270]))  # no common direction
        self.assertIsNone(gw.generalized_direction([135, 135]))  # too few
        self.assertAlmostEqual(gw.generalized_direction([350, 10, 5])[0] % 360, 1.67, places=1)  # wraps at north

    def test_gradient_summary(self):
        self.assertEqual(gw.gradient_summary([0.004, 0.002, 0.006]), (0.004, 0.002, 0.006))
        self.assertIsNone(gw.gradient_summary([]))


class DensityAndWordingTests(unittest.TestCase):
    def test_arrow_count_is_near_target(self):
        for target in (4, 9, 25):
            seeds = gw.arrow_seeds(0, 0, 300, 200, gw.arrow_spacing(300 * 200, target))
            self.assertLessEqual(abs(len(seeds) - target), max(2, target // 3), target)

    def test_disclaimer_is_an_interpretation_without_transport_terms(self):
        text = gw.DISCLAIMER.lower()
        self.assertIn("interpretation", text)
        for word in ("velocity", "plume", "advection", "dispersion", "darcy"):
            self.assertNotIn(word, text.replace("not a velocity", ""))


class GroundwaterSmoothingTests(unittest.TestCase):
    def test_presets_are_scale_aware(self):
        from contour_flow.core import options as opt

        self.assertEqual(opt.groundwater_smoothing_parameters(opt.SMOOTH_LIGHT), ((3, 0.25, 1.0, 6.0), None))
        self.assertEqual(opt.groundwater_smoothing_parameters(opt.SMOOTH_MEDIUM), ((3, 0.25, 1.5, 16.0), None))
        self.assertEqual(opt.groundwater_smoothing_parameters(opt.SMOOTH_NONE), (None, None))
        self.assertEqual(opt.groundwater_smoothing_parameters(opt.SMOOTH_CUSTOM, 2, 0.3)[0], (2, 0.3, 1.0, 6.0))

    def test_fallbacks_get_milder(self):
        from contour_flow.core import options as opt

        steps = opt.groundwater_smoothing_fallbacks((3, 0.25, 1.0, 6.0))
        self.assertEqual(steps, [(3, 0.25, 1.0, 6.0), (3, 0.25, 1.0, 3.0), (1, 0.25, 0.5, 1.5)])
        segments = [step[3] for step in steps]
        self.assertEqual(segments, sorted(segments, reverse=True))
        self.assertIsNotNone(opt.groundwater_smoothing_parameters(opt.SMOOTH_CUSTOM, 99, 0.3)[1])

    def test_general_smoothing_unchanged(self):
        from contour_flow.core import options as opt

        self.assertEqual(opt.smoothing_parameters(opt.SMOOTH_LIGHT), ((1, 0.25), None))
        self.assertEqual(opt.smoothing_parameters(opt.SMOOTH_MEDIUM), ((2, 0.25), None))


class FieldChoiceTests(unittest.TestCase):
    """groundwater_field_choices with a minimal fake layer (no QGIS)."""

    class Field:
        def __init__(self, name, numeric):
            self._name, self._numeric = name, numeric

        def name(self):
            return self._name

        def isNumeric(self):  # noqa: N802 - QGIS API name
            return self._numeric

    class Fields:
        def __init__(self, fields):
            self._fields = fields

        def count(self):
            return len(self._fields)

        def at(self, i):
            return self._fields[i]

    class Feature:
        def __init__(self, values):
            self._values = values

        def attribute(self, i):
            return self._values[i]

    class Layer:
        def __init__(self, fields, rows):
            self._fields, self._rows = fields, rows

        def fields(self):
            return self._fields

        def getFeatures(self):  # noqa: N802 - QGIS API name
            return iter(self._rows)

    def test_numeric_and_numeric_text_fields(self):
        from contour_flow.core.input_validation import TEXT_FIELD_NOTE, groundwater_field_choices

        F = FieldChoiceTests
        fields = F.Fields([F.Field("well_id", False), F.Field("head", True), F.Field("WL", False)])
        rows = [F.Feature(v) for v in [("MW-1", 101.2, " 101.20"), ("MW-2", None, "Dry"),
                                       ("MW-3", 100.4, "100.4"), ("MW-4", 99.9, None)]]
        choices = groundwater_field_choices(F.Layer(fields, rows))
        self.assertEqual(choices, [("head", "head", False), ("WL", f"WL — {TEXT_FIELD_NOTE}", True)])
        self.assertEqual(groundwater_field_choices(None), [])


if __name__ == "__main__":
    unittest.main()

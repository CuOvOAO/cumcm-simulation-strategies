import math
import unittest
from fractions import Fraction

from strategies.b.region import (ANGLE_EPS, BEARING_HALF_WIDTH_DEG,
                                 FeasibleRegion, Observation, RegionTracker)
from strategies.b.safe_clear import (_box_covered, _enclosing_box, _sector_box,
                                     reliable_clear_point)


class SafeClearTests(unittest.TestCase):
    def region(self, *observations):
        tracker = RegionTracker()
        for point, result in observations:
            tracker.record(1, point, result)
        return tracker.channel(1).region

    def test_exact_closed_disk_boundary(self):
        for radius, expected in [(19.999, True), (20.0, True), (20.001, False)]:
            with self.subTest(radius=radius):
                r = Fraction(radius)
                self.assertEqual(_box_covered((-r, r, Fraction(0), Fraction(0)),
                                              (0.0, 0.0)), expected)
        r = Fraction(math.nextafter(20.0, math.inf))
        self.assertFalse(_box_covered((-r, r, 0, 0), (0.0, 0.0)))

    def test_near_and_offset_candidates(self):
        region = self.region(((0, 0), {"measure_result": "near"}))
        self.assertEqual(reliable_clear_point(region), (0.0, 0.0))
        self.assertEqual(reliable_clear_point(region, (14, 0)), (14, 0))
        self.assertIsNone(reliable_clear_point(region, (14.999, 0)))
        # Nominal 20 m is NOT enough: the region includes outward distance slack.
        self.assertIsNone(reliable_clear_point(region, (15, 0)))
        self.assertIsNone(reliable_clear_point(region, (15.001, 0)))

    def test_no_observations_or_only_absence(self):
        self.assertIsNone(reliable_clear_point(FeasibleRegion()))
        region = self.region(((0, 0), {"measure_result": "no_signal"}))
        self.assertIsNone(reliable_clear_point(region))

    def test_unresolved_direction(self):
        region = self.region(((0, 0), {"measure_result": "direction", "svd_deg": 0}))
        self.assertIsNone(reliable_clear_point(region))

    def test_contradictions(self):
        for second, response in [((11, 0), {"measure_result": "near"}),
                                 ((8, 8), {"measure_result": "near"}),
                                 ((0, 0), {"measure_result": "no_signal"}),
                                 ((100, 0), {"measure_result": "direction", "svd_deg": 0})]:
            with self.subTest(second=second, response=response):
                region = self.region(((0, 0), {"measure_result": "near"}),
                                     (second, response))
                self.assertIsNone(reliable_clear_point(region))

    def test_disk_intersection_without_near(self):
        region = self.region(((-1499.99, 0), {"measure_result": "direction", "svd_deg": 0}),
                             ((1499.99, 0), {"measure_result": "direction", "svd_deg": 180}),
                             ((0, -1499.99), {"measure_result": "direction", "svd_deg": 90}),
                             ((0, 1499.99), {"measure_result": "direction", "svd_deg": 270}))
        self.assertEqual(reliable_clear_point(region), (0.0, 0.0))

    def test_target_boundary_and_channel_isolation(self):
        tracker = RegionTracker()
        region = tracker.record(1, (1800, 0), {"measure_result": "near"})
        self.assertEqual(reliable_clear_point(region), (1800, 0))
        self.assertIsNone(reliable_clear_point(tracker.channel(2).region))

    def test_invalid_candidate(self):
        with self.assertRaises(ValueError):
            reliable_clear_point(FeasibleRegion(), (math.nan, 0))

    def test_crossed_bearings_shrink_box(self):
        region = self.region(((-500, 0), {"measure_result": "direction", "svd_deg": 0}),
                             ((0, -500), {"measure_result": "direction", "svd_deg": 90}))
        left, right, bottom, top = _enclosing_box(region)
        # Disk-only intersection had width and height 2500 m.
        self.assertLess(right - left, 53)
        self.assertLess(top - bottom, 53)
        self.assertLessEqual(left, 0)
        self.assertGreaterEqual(right, 0)
        self.assertLessEqual(bottom, 0)
        self.assertGreaterEqual(top, 0)

    def test_nearly_parallel_is_not_certified(self):
        region = self.region(((0, 0), {"measure_result": "direction", "svd_deg": 0}),
                             ((1, 0), {"measure_result": "direction", "svd_deg": 0.001}))
        self.assertIsNone(reliable_clear_point(region))

    def test_dense_sector_counterexample_search(self):
        # Deterministic regression search, NOT the containment proof.
        half = BEARING_HALF_WIDTH_DEG + ANGLE_EPS
        for bearing in (0, 0.2, 359.8, 90, 180, 270, 45, 135, 225, 315):
            observation = Observation((123.25, -456.5), "direction", bearing)
            left, right, bottom, top = _sector_box(observation)
            for i in range(401):
                angle = math.radians(bearing - half + 2 * half * i / 400)
                for radius in (0, 0.001, 5, 500, 1499.999, 1500, 1500 + 1e-9):
                    x = Fraction(123.25 + radius * math.cos(angle))
                    y = Fraction(-456.5 + radius * math.sin(angle))
                    self.assertTrue(left <= x <= right and bottom <= y <= top,
                                    (bearing, i, radius))

    def test_circle_extrema_and_wrap(self):
        for bearing, extreme in [(359.8, (1500, 0)), (90.2, (0, 1500)),
                                 (179.8, (-1500, 0)), (270.2, (0, -1500))]:
            box = _sector_box(Observation((0, 0), "direction", bearing))
            self.assertTrue(box[0] <= extreme[0] <= box[1])
            self.assertTrue(box[2] <= extreme[1] <= box[3])


if __name__ == "__main__":
    unittest.main()

import math
import unittest

from strategies.b.region import RegionTracker


def polar(angle, radius=1000):
    return radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle))


class RegionTests(unittest.TestCase):
    def setUp(self):
        self.tracker = RegionTracker()

    def direction(self, position, angle, channel=1):
        return self.tracker.record(channel, position, dict(measure_result="direction", svd_deg=angle))

    def test_initial_target_disk(self):
        for channel in range(1, 21):
            region = self.tracker.channel(channel).region
            with self.subTest(channel=channel):
                self.assertEqual(self.tracker.channel(channel).history, ())
                for point in ((0, 0), (1000, -1000), (-1799, 0)):
                    self.assertTrue(region.contains(point))
                for point in ((1801, 0), (0, -1801), (1500, 1500)):
                    self.assertFalse(region.contains(point))

    def test_target_disk_boundary_tolerance(self):
        region = self.tracker.channel(1).region
        for angle in (0, 45, 90, 180, 270, 359.99):
            with self.subTest(angle=angle):
                for radius in (1800 - 1e-8, 1800, 1800 + 5e-10):
                    self.assertTrue(region.contains(polar(angle, radius)))
                self.assertFalse(region.contains(polar(angle, 1800 + 1e-8)))

    def test_target_disk_persists_after_observations(self):
        # (1801, 0) satisfies each observation but is outside the target disk.
        snapshots = [self.tracker.channel(1).region]
        snapshots.append(self.direction((1000, 0), 0))
        snapshots.append(self.tracker.record(1, (0, 0), dict(measure_result="no_signal")))
        snapshots.append(self.tracker.record(1, (1800, 0), dict(measure_result="near")))
        for region in snapshots:
            self.assertTrue(region.contains((1799, 0)))
            self.assertFalse(region.contains((1801, 0)))
        # The observations still constrain positions inside the target disk.
        self.assertFalse(snapshots[1].contains((0, 0)))
        self.assertFalse(snapshots[2].contains((1000, 10)))
        self.assertFalse(snapshots[3].contains((1700, 0)))

    def test_cross_zero(self):
        region = self.direction((0, 0), 359.5)
        for angle in (358.5, 359.5, 0, 0.5):
            self.assertTrue(region.contains(polar(angle)))
        for angle in (358.4, 0.6, 180):
            self.assertFalse(region.contains(polar(angle)))

    def test_nearly_parallel(self):
        self.direction((0, 0), 0)
        region = self.direction((0, 0.001), 0.00001)
        self.assertTrue(region.contains((1000, 0)))
        self.assertFalse(region.contains((1000, 30)))
        self.assertFalse(region.contains((-1000, 0)))

    def test_rounding_half_width_boundaries(self):
        # Include both sides, the 0/360 seam and the atan2 +/-180 seam.
        for channel, reported in enumerate((0, 359.99, 180), start=1):
            region = self.direction((0, 0), reported, channel)
            for sign in (-1, 1):
                for offset in (1.004999999, 1.005, 1.005 + 5e-11):
                    with self.subTest(reported=reported, sign=sign, offset=offset):
                        self.assertTrue(region.contains(polar(reported + sign * offset)))
                self.assertFalse(region.contains(polar(reported + sign * 1.005001)))

    def test_rounded_feedback_retains_true_direction(self):
        # Synthetic public feedback: bounded physical error followed by round.
        # The error and rounding reinforce each other, giving nearly 1.005 deg.
        for channel, sign in enumerate((-1, 1), start=1):
            true_angle = sign * 1.004999999
            reported = round(true_angle - sign * 1.0, 2) % 360.0
            region = self.direction((0, 0), reported, channel)
            self.assertTrue(region.contains(polar(true_angle)))

    def test_direction_range_is_only_upper_bound(self):
        region = self.direction((0, 0), 0)
        for distance in (0, 1, 999, 1000, 1499, 1500):
            self.assertTrue(region.contains((distance, 0)))
        self.assertFalse(region.contains((1500.001, 0)))

    def test_no_signal_exclusion(self):
        region = self.tracker.record(1, (20, 30), dict(measure_result="no_signal"))
        self.assertFalse(region.contains((20, 30)))
        self.assertFalse(region.contains((1019.999, 30)))
        self.assertTrue(region.contains((1020, 30)))
        self.assertTrue(region.contains((1020.001, 30)))
        self.assertTrue(region.contains((1220, 30)))
        self.assertTrue(region.contains((-1700, 30)))
        self.assertFalse(region.contains((-2000, 30)))

    def test_repeats_do_not_narrow_bearing(self):
        original = self.direction((0, 0), 0)
        for angle in (0, 0, 0.5, -0.5):
            region = self.direction((0, 0), angle)
            self.assertEqual(original, region)
            self.assertTrue(region.contains(polar(-1.005)))
            self.assertTrue(region.contains(polar(1.005)))
        self.assertEqual(len(self.tracker.channel(1).history), 5)

    def test_near_and_contradictory_observations(self):
        first = self.tracker.record(1, (0, 0), dict(measure_result="near"))
        self.assertTrue(first.contains((5, 0)))
        self.assertFalse(first.contains((5.001, 0)))
        region = self.tracker.record(1, (0, 0), dict(measure_result="no_signal"))
        # These two constraints are analytically disjoint, without triangulation.
        for point in ((0, 0), (5, 0), (500, 0), (1000, 0), (2000, 0)):
            self.assertFalse(region.contains(point))
        self.assertEqual(len(region.constraints), 2)
        self.assertEqual(len(self.tracker.channel(1).history), 2)
        self.assertTrue(first.contains((0, 0)))  # earlier snapshot unchanged

    def test_channels_are_independent(self):
        self.assertEqual(len({id(self.tracker.channel(i)) for i in range(1, 21)}), 20)
        self.direction((0, 0), 0, 1)
        self.direction((0, 0), 180, 20)
        self.assertTrue(self.tracker.channel(1).region.contains((1000, 0)))
        self.assertFalse(self.tracker.channel(20).region.contains((1000, 0)))
        for channel in range(2, 20):
            self.assertEqual(self.tracker.channel(channel).history, ())
            self.assertTrue(self.tracker.channel(channel).region.contains((0, 1000)))
            self.assertFalse(self.tracker.channel(channel).region.contains((1e6, 1e6)))

    def test_invalid_feedback_is_atomic(self):
        for response in ({}, dict(measure_result="direction"),
                         dict(measure_result="direction", svd_deg=float("nan"))):
            with self.assertRaises(ValueError):
                self.tracker.record(1, (0, 0), response)
        for channel in (0, 21, True, 1.0):
            with self.assertRaises(ValueError):
                self.tracker.channel(channel)
        self.assertEqual(self.tracker.channel(1).history, ())


if __name__ == "__main__":
    unittest.main()

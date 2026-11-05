import math
import unittest

from strategies.b.candidate_actions import (
    COORDINATE_LIMIT_M, MAX_CANDIDATES, generate_candidates)
from strategies.b.region import RegionTracker
from strategies.b.safe_clear import reliable_clear_point


class CandidateActionTests(unittest.TestCase):
    def setUp(self):
        self.tracker = RegionTracker()

    def record(self, point, result="direction", bearing=0, channel=1):
        self.tracker.record(channel, point,
                            {"measure_result": result, "svd_deg": bearing})

    def generate(self, current=(0, 0), channel=1):
        before = self.tracker.channel(channel).history
        actions = generate_candidates(current, channel, self.tracker)
        self.assertEqual(before, self.tracker.channel(channel).history)
        self.assertEqual(actions, generate_candidates(current, channel, self.tracker))
        self.assertLessEqual(len(actions), MAX_CANDIDATES)
        cells = set()
        used = {(math.floor(o.position[0]), math.floor(o.position[1])) for o in before}
        for a in actions:
            self.assertEqual(a.channel, channel)
            self.assertTrue(a.reason)
            self.assertIn(a.action_type, ("clear", "measure"))
            self.assertTrue(all(math.isfinite(v) and abs(v) <= COORDINATE_LIMIT_M
                                for v in a.position))
            if a.action_type == "measure":
                cell = tuple(math.floor(v) for v in a.position)
                self.assertNotIn(cell, cells | used)
                cells.add(cell)
        return actions

    def test_no_observations(self):
        actions = self.generate()
        self.assertEqual(len(actions), MAX_CANDIDATES)
        self.assertEqual(actions[0].position, (0, 0))
        self.assertEqual(actions[0].reason, "enclosing_box_center")
        self.assertTrue(all(a.action_type == "measure" for a in actions))

    def test_single_direction_lateral_geometry(self):
        self.record((0, 0))
        actions = self.generate()
        center = actions[0].position
        self.assertAlmostEqual(center[0], 750, places=6)
        lateral = [a.position for a in actions if a.reason == "lateral_bearing_probe"]
        self.assertEqual(len(lateral), 2)
        self.assertTrue(all(abs(p[0] - center[0]) < 1e-8 for p in lateral))
        self.assertGreater(lateral[0][1], center[1])
        self.assertLess(lateral[1][1], center[1])

    def test_crossed_direction(self):
        self.record((-500, 0), bearing=0)
        self.record((0, -500), bearing=90)
        actions = self.generate()
        self.assertTrue(all(a.action_type == "measure" for a in actions))
        self.assertAlmostEqual(actions[0].position[0], 0, places=6)
        self.assertAlmostEqual(actions[0].position[1], 0, places=6)
        self.assertEqual(sum(a.reason == "lateral_bearing_probe" for a in actions), 4)

    def test_no_signal_reacquisition(self):
        self.record((0, 0), "no_signal")
        actions = self.generate()
        self.assertTrue(actions)
        self.assertTrue(all(a.reason == "signal_reacquisition_lattice" for a in actions))
        self.assertTrue(any(math.hypot(*a.position) > 1000 for a in actions))

    def test_near_certified_clear_can_reuse_measure_cell(self):
        self.record((12.5, -9.5), "near")
        actions = self.generate()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].action_type, "clear")
        self.assertEqual(actions[0].position, reliable_clear_point(self.tracker.channel(1).region))

    def test_direction_certified_clear(self):
        for point, angle in [((-1499.99, 0), 0), ((1499.99, 0), 180),
                             ((0, -1499.99), 90), ((0, 1499.99), 270)]:
            self.record(point, bearing=angle)
        self.assertEqual(self.generate()[0].action_type, "clear")

    def test_wrap_zero(self):
        self.record((0, 0), bearing=359.8)
        actions = self.generate()
        other = RegionTracker()
        other.record(1, (0, 0), {"measure_result": "direction", "svd_deg": -0.2})
        self.assertEqual(actions, generate_candidates((0, 0), 1, other))
        self.assertGreater(actions[0].position[0], 700)
        self.assertLess(abs(actions[0].position[1]), 10)

    def test_repeated_positions_and_negative_floor_cells(self):
        for point in [(0.1, 0.1), (0.9, 0.9), (-0.1, -0.1), (-0.9, -0.9)]:
            self.record(point, "no_signal")
        self.generate((0.5, 0.5))
        self.generate((-0.5, -0.5))
        # Floor puts these two locations in different cells.
        self.assertTrue(any(a.position == (0, -0.5) for a in self.generate((0, -0.5))))

    def test_channel_isolation(self):
        before = self.generate(channel=2)
        self.record((0, 0), "near", channel=1)
        self.assertEqual(before, self.generate(channel=2))
        self.assertEqual(self.generate(channel=1)[0].action_type, "clear")

    def test_lattice_progress_and_exhaustion(self):
        for _ in range(3):
            actions = self.generate()
            for action in actions:
                self.record(action.position, "no_signal")
        self.assertEqual(self.generate(), ())

    def test_invalid_inputs_and_coordinate_boundary(self):
        for point in [(math.nan, 0), (math.inf, 0), (2_000_001, 0), (0,), None]:
            with self.subTest(point=point), self.assertRaises(ValueError):
                generate_candidates(point, 1, self.tracker)
        for channel in [0, 21, True, 1.5]:
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                generate_candidates((0, 0), channel, self.tracker)
        self.assertTrue(any(a.position == (2_000_000, -2_000_000)
                            for a in self.generate((2_000_000, -2_000_000))))

    def test_empty_box_has_no_proposals(self):
        self.record((0, 0), "near")
        self.record((100, 0), "near")
        self.assertEqual(self.generate(), ())


if __name__ == "__main__":
    unittest.main()

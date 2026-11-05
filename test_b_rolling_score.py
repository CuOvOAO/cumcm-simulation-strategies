import math
import unittest

from strategies.b.candidate_actions import CandidateAction, generate_candidates
from strategies.b.region import RegionTracker
from strategies.b.rolling_score import WEIGHTS, score_candidates, select_action


def measure(point, channel=1):
    return CandidateAction("measure", channel, point, "test")


class RollingScoreTests(unittest.TestCase):
    def setUp(self):
        self.tracker = RegionTracker()

    def record(self, point, result="direction", bearing=0, channel=1):
        self.tracker.record(channel, point, {"measure_result": result, "svd_deg": bearing})

    def score(self, actions, current=(0, 0)):
        return score_candidates(current, actions, self.tracker)

    def test_clear_priority_across_channels_even_with_large_travel_cost(self):
        self.record((100, 0), "near", channel=2)
        clear = CandidateAction("clear", 2, (100, 0), "arbitrary_label")
        actions = [measure((-2_000_000, 0)), clear]
        ranked = self.score(actions, (-2_000_000, 0))
        self.assertEqual(ranked[0].candidate, clear)
        self.assertTrue(ranked[0].certified_clear)
        self.assertLess(ranked[0].score, ranked[1].score)
        self.assertEqual(select_action((-2_000_000, 0), actions, self.tracker), clear)

    def test_multiple_certified_clears_choose_nearest(self):
        self.record((0, 0), "near")
        near = CandidateAction("clear", 1, (0, 0), "test")
        far = CandidateAction("clear", 1, (10, 0), "test")
        self.assertEqual(self.score([far, near])[0].candidate, near)

    def test_clear_label_cannot_forge_certificate(self):
        with self.assertRaisesRegex(ValueError, "certified"):
            self.score([CandidateAction("clear", 1, (0, 0), "safe_clear_certified")])
        self.record((0, 0), "near")
        with self.assertRaisesRegex(ValueError, "certified"):
            self.score([CandidateAction("clear", 1, (100, 0), "safe_clear_certified")])

    def test_distance_cost_holds_information_fixed(self):
        action = measure((0, 0))
        close = self.score([action])[0]
        far = self.score([action], (300, 400))[0]
        self.assertAlmostEqual(close.score - far.score, WEIGHTS.distance * 0.5)
        self.assertEqual(close.shrink, far.shrink)
        self.assertEqual(close.reacquisition, far.reacquisition)

    def test_lateral_probe_beats_collinear_at_equal_travel(self):
        self.record((0, 0))
        lateral, axial = measure((750, 375)), measure((1125, 0))
        ranked = self.score([axial, lateral], (750, 0))
        by_action = {s.candidate: s for s in ranked}
        self.assertGreater(by_action[lateral].crossing, by_action[axial].crossing)
        self.assertGreater(by_action[lateral].shrink, by_action[axial].shrink)
        self.assertEqual(ranked[0].candidate, lateral)

    def test_repeated_and_nearby_measurements_penalized(self):
        self.record((-0.9, -0.9), "no_signal")
        same, nearby, fresh = [self.score([measure(p)])[0] for p in
                               [(-0.1, -0.1), (0, 0), (30, 0)]]
        self.assertEqual(same.repeat, 1)
        self.assertAlmostEqual(same.score, -WEIGHTS.repeat - WEIGHTS.distance * same.distance)
        self.assertGreater(nearby.repeat, 0)
        self.assertLess(nearby.repeat, 1)
        self.assertEqual(fresh.repeat, 0)

    def test_channel_isolation(self):
        actions = [measure((0, 0), 2), measure((700, 300), 2)]
        before = self.score(actions)
        self.record((0, 0), "near", channel=1)
        self.record((100, 0), "no_signal", channel=1)
        self.assertEqual(before, self.score(actions))
        self.assertEqual(self.score([measure((0, 0), 1)])[0].repeat, 1)

    def test_deterministic_order_independent_and_no_state_mutation(self):
        self.record((0, 0))
        actions = generate_candidates((0, 0), 1, self.tracker)
        history, region = self.tracker.channel(1).history, self.tracker.channel(1).region
        first = self.score(actions)
        self.assertEqual(first, self.score(reversed(actions)))
        self.assertEqual(first, self.score(actions))
        self.assertEqual(history, self.tracker.channel(1).history)
        self.assertIs(region, self.tracker.channel(1).region)

    def test_ties_use_channel_then_coordinates(self):
        a, b = measure((0, 0), 1), measure((0, 0), 2)
        self.assertEqual(self.score([b, a])[0].candidate, a)

    def test_empty_candidates(self):
        self.assertEqual(self.score([]), ())
        self.assertIsNone(select_action((0, 0), iter(()), self.tracker))

    def test_no_scenarios_does_not_claim_information_or_clear(self):
        self.record((0, 0), "near")
        self.record((100, 0), "near")
        s = self.score([measure((50, 0))])[0]
        self.assertEqual(s.scenario_count, 0)
        self.assertEqual((s.shrink, s.crossing, s.reacquisition), (0, 0, 0))
        self.assertFalse(s.certified_clear)

    def test_reacquisition_rewards_public_minimum_range_coverage(self):
        self.record((0, 0), "no_signal")
        useful = self.score([measure((1200, 0))])[0]
        remote = self.score([measure((10000, 0))])[0]
        self.assertGreater(useful.reacquisition, 0)
        self.assertEqual(remote.reacquisition, 0)
        self.assertEqual(remote.shrink, 0)

    def test_formula_and_feature_bounds(self):
        for s in self.score([measure((0, 0)), measure((900, 500))]):
            for value in (s.shrink, s.crossing, s.repeat, s.reacquisition):
                self.assertTrue(0 <= value <= 1)
            self.assertAlmostEqual(s.score, (1 - s.repeat) * (
                WEIGHTS.shrink * s.shrink + WEIGHTS.crossing * s.crossing
                + WEIGHTS.reacquisition * s.reacquisition)
                - WEIGHTS.distance * s.distance - WEIGHTS.repeat * s.repeat)

    def test_invalid_inputs(self):
        for action in [measure((math.nan, 0)), measure((2_000_001, 0)),
                       measure((0, 0), True), CandidateAction("move", 1, (0, 0), "test")]:
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.score([action])
        with self.assertRaises(ValueError):
            self.score([], (math.inf, 0))


if __name__ == "__main__":
    unittest.main()

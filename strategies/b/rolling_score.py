"""Deterministic public-state heuristics; neither execution nor certification."""

from dataclasses import dataclass
import math
from typing import Iterable, Optional, Tuple

from .candidate_actions import CandidateAction, _grid, _legal
from .region import BEARING_HALF_WIDTH_DEG, Point, RegionTracker, _point
from .safe_clear import _enclosing_box, reliable_clear_point


@dataclass(frozen=True)
class ScoreWeights:
    shrink: float = 4.0
    crossing: float = 2.0
    distance: float = 1.0
    repeat: float = 5.0
    reacquisition: float = 2.0


WEIGHTS = ScoreWeights()
SAMPLE_INTERVALS = 16
DISTANCE_SCALE_M = 1000.0
REPEAT_SCALE_M = 25.0
PUBLIC_MIN_RANGE_M = 1000.0
PUBLIC_MAX_RANGE_M = 1500.0
PUBLIC_NEAR_M = 5.0


@dataclass(frozen=True)
class ScoredAction:
    candidate: CandidateAction
    score: float
    shrink: float
    crossing: float
    distance: float
    repeat: float
    reacquisition: float
    scenario_count: int
    certified_clear: bool = False


def _scenarios(region):
    """Fixed box lattice, filtered by ALL constraints; never a coverage proof."""
    left, right, bottom, top = map(float, _enclosing_box(region))
    if left > right or bottom > top:
        return ()
    points = {
        (left + (right - left) * i / SAMPLE_INTERVALS,
         bottom + (top - bottom) * j / SAMPLE_INTERVALS)
        for i in range(SAMPLE_INTERVALS + 1)
        for j in range(SAMPLE_INTERVALS + 1)
    }
    return tuple(p for p in sorted(points) if region.contains(p))


def _outcomes_overlap(p, q, origin):
    """Can two scenarios share a feedback under public range/error bounds?"""
    dp, dq = math.dist(p, origin), math.dist(q, origin)
    if dp <= PUBLIC_NEAR_M and dq <= PUBLIC_NEAR_M:
        return True
    # Include the uncertain reception band; do not guess an actual radius.
    if dp >= PUBLIC_MIN_RANGE_M and dq >= PUBLIC_MIN_RANGE_M:
        return True
    if (PUBLIC_NEAR_M < dp <= PUBLIC_MAX_RANGE_M
            and PUBLIC_NEAR_M < dq <= PUBLIC_MAX_RANGE_M):
        a = math.degrees(math.atan2(p[1] - origin[1], p[0] - origin[0]))
        b = math.degrees(math.atan2(q[1] - origin[1], q[0] - origin[0]))
        return abs((a - b + 180) % 360 - 180) <= 2 * BEARING_HALF_WIDTH_DEG
    return False


def _measure_features(point, history, scenarios):
    repeat = max((1.0 if _grid(point) == _grid(o.position) else
                  max(0.0, 1.0 - math.dist(point, o.position) / REPEAT_SCALE_M)
                  for o in history), default=0.0)
    n = len(scenarios)
    if not n:
        return 0.0, 0.0, repeat, 0.0
    # Equal scenario weights are a quadrature heuristic, not a posterior.
    separated = sum(not _outcomes_overlap(p, q, point)
                    for i, p in enumerate(scenarios) for q in scenarios[i + 1:])
    shrink = 2.0 * separated / (n * n)
    bearings = tuple(sorted({o.position for o in history if o.result == "direction"}))
    crossing = 0.0
    for q in scenarios:
        ux, uy = point[0] - q[0], point[1] - q[1]
        norm = math.hypot(ux, uy)
        if not PUBLIC_NEAR_M < norm <= PUBLIC_MIN_RANGE_M:
            continue
        best = 0.0
        for old in bearings:
            vx, vy = old[0] - q[0], old[1] - q[1]
            old_norm = math.hypot(vx, vy)
            if old_norm:
                best = max(best, min(1.0, abs(ux * vy - uy * vx) / (norm * old_norm)))
        crossing += best / n
    lost = not history or history[-1].result == "no_signal"
    reacquisition = (sum(math.dist(point, q) <= PUBLIC_MIN_RANGE_M for q in scenarios) / n
                     if lost else 0.0)
    return shrink, crossing, repeat, reacquisition


def score_candidates(current_position: Point, candidates: Iterable[CandidateAction],
                     tracker: RegionTracker) -> Tuple[ScoredAction, ...]:
    """Rank supplied candidates, certified clear first; reject uncertified clear.

    Only each candidate's channel is consulted. No candidates are synthesized.
    Invalid inputs raise ValueError; empty input returns ().
    """
    current = _point(current_position)
    if not _legal(current):
        raise ValueError("Current position exceeds legal coordinate limits")
    ranked = []
    cache = {}
    for candidate in candidates:
        point = _point(candidate.position)
        if not _legal(point) or candidate.action_type not in ("measure", "clear"):
            raise ValueError("Invalid candidate action or position")
        state = tracker.channel(candidate.channel)
        distance = math.dist(current, point) / DISTANCE_SCALE_M
        if candidate.action_type == "clear":
            if reliable_clear_point(state.region, point) is None:
                raise ValueError("Clear candidate is not safe-clear certified")
            ranked.append(ScoredAction(candidate, -WEIGHTS.distance * distance,
                                       0.0, 0.0, distance, 0.0, 0.0, 0, True))
            continue
        if candidate.channel not in cache:
            cache[candidate.channel] = (state.history, _scenarios(state.region))
        history, scenarios = cache[candidate.channel]
        shrink, crossing, repeat, reacquisition = _measure_features(point, history, scenarios)
        score = ((1.0 - repeat) * (WEIGHTS.shrink * shrink + WEIGHTS.crossing * crossing
                                  + WEIGHTS.reacquisition * reacquisition)
                 - WEIGHTS.distance * distance - WEIGHTS.repeat * repeat)
        ranked.append(ScoredAction(candidate, score, shrink, crossing, distance,
                                   repeat, reacquisition, len(scenarios)))
    return tuple(sorted(ranked, key=lambda s: (
        not s.certified_clear, -s.score, s.candidate.channel,
        s.candidate.position[0], s.candidate.position[1], s.candidate.reason)))


def select_action(current_position: Point, candidates: Iterable[CandidateAction],
                  tracker: RegionTracker) -> Optional[CandidateAction]:
    """Return exactly one proposal or None; caller owns execution and lifecycle."""
    ranked = score_candidates(current_position, candidates, tracker)
    return ranked[0].candidate if ranked else None

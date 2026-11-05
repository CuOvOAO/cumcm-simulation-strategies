"""Bounded proposals from public channel state; no scoring or API execution."""

from dataclasses import dataclass
import math
from typing import Tuple

from .region import Point, RegionTracker, TARGET_RADIUS_M, _point
from .safe_clear import _enclosing_box, reliable_clear_point


MAX_CANDIDATES = 16
COORDINATE_LIMIT_M = 2_000_000.0
LATERAL_STEP_MIN_M = 25.0
LATERAL_STEP_MAX_M = 500.0


@dataclass(frozen=True)
class CandidateAction:
    action_type: str
    channel: int
    position: Point
    reason: str


def _legal(point: Point) -> bool:
    return all(math.isfinite(v) and abs(v) <= COORDINATE_LIMIT_M for v in point)


def _grid(point: Point) -> Tuple[int, int]:
    # Floor is significant for negative coordinates too.
    return math.floor(point[0]), math.floor(point[1])


def generate_candidates(current_position: Point, channel: int,
                        tracker: RegionTracker) -> Tuple[CandidateAction, ...]:
    """Return up to MAX_CANDIDATES, in proposal order (not score order).

    Only the requested channel is consulted. A certificate returns one clear
    proposal immediately. Otherwise propose box center, current location,
    lateral views and a fixed reacquisition lattice. Measurement grid cells
    already present in this channel's complete history are excluded, regardless
    of feedback type. Empty output is possible; it is not proof of no target.
    """
    current = _point(current_position)
    if not _legal(current):
        raise ValueError("Current position exceeds legal coordinate limits")
    state = tracker.channel(channel)
    region, history = state.region, state.history
    certified = reliable_clear_point(region)
    if certified is not None and _legal(certified):
        return (CandidateAction("clear", channel, certified, "safe_clear_certified"),)

    left, right, bottom, top = _enclosing_box(region)
    if left > right or bottom > top:
        return ()
    center = (float((left + right) / 2), float((bottom + top) / 2))
    occupied = {_grid(o.position) for o in history}
    candidates = []

    def add(point, reason):
        if len(candidates) >= MAX_CANDIDATES or not _legal(point):
            return
        cell = _grid(point)
        if cell in occupied:
            return
        occupied.add(cell)
        candidates.append(CandidateAction("measure", channel, point, reason))

    add(center, "enclosing_box_center")
    add(current, "current_position_probe")

    # Use the newest two distinct bearing cells, never an average of angles.
    # A baseline normal to the observed ray offers a different viewing angle
    # around the box center, without claiming any guaranteed information gain.
    bearing_cells = set()
    for observation in reversed(history):
        if observation.result != "direction":
            continue
        cell = _grid(observation.position)
        if cell in bearing_cells:
            continue
        bearing_cells.add(cell)
        angle = math.radians(observation.bearing_deg % 360.0)
        normal = (-math.sin(angle), math.cos(angle))
        distance = math.dist(observation.position, center)
        step = min(LATERAL_STEP_MAX_M, max(LATERAL_STEP_MIN_M, distance / 2))
        for sign in (1, -1):
            add((center[0] + sign * step * normal[0],
                 center[1] + sign * step * normal[1]), "lateral_bearing_probe")
        if len(bearing_cells) == 2:
            break

    # Public target-domain lattice, not candidate target truth. The full finite
    # pool is revisited on every call so measured cells expose later proposals.
    # Probe positions need not themselves belong to the feasible target region.
    spacing = TARGET_RADIUS_M / 2
    lattice = [(i * spacing, j * spacing)
               for i in range(-2, 3) for j in range(-2, 3)]
    lattice.sort(key=lambda p: (math.dist(current, p), p[0], p[1]))
    for point in lattice:
        add(point, "signal_reacquisition_lattice")
    return tuple(candidates)

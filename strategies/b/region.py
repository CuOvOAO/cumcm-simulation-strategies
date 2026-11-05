"""Conservative, implicit feasible sets using public measurement feedback only.

Regions describe possible positions conditional on a source existing. An empty
history leaves the known 1800-metre target disk, not evidence of a source.
No sampling, triangulation, or global non-emptiness claim is made here.
"""

from dataclasses import dataclass
import math
from typing import Mapping, Optional, Tuple

Point = Tuple[float, float]
TARGET_RADIUS_M = 1800.0
# Physical error (1 degree) plus rounding to two decimals (0.005 degree).
BEARING_HALF_WIDTH_DEG = 1.005
# Outward-only numerical slack, in metres and degrees respectively.
DISTANCE_EPS = 1e-9
ANGLE_EPS = 1e-10


def _point(value) -> Point:
    try:
        x, y = value
        point = (float(x), float(y))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Expected two finite coordinates") from exc
    if not all(math.isfinite(v) for v in point):
        raise ValueError("Expected two finite coordinates")
    return point


@dataclass(frozen=True)
class Observation:
    position: Point
    result: str
    bearing_deg: Optional[float] = None


@dataclass(frozen=True)
class FeasibleRegion:
    """Known target disk intersected with all observation constraints.

    The target disk is an invariant, independent of the observation tuple.
    `contains` tests a position; it does not determine whether the entire set
    is empty. Inconsistent constraints are retained without a fallback reset.
    """

    constraints: Tuple[Observation, ...] = ()

    def contains(self, position: Point) -> bool:
        x, y = _point(position)
        if math.hypot(x, y) > TARGET_RADIUS_M + DISTANCE_EPS:
            return False
        for observation in self.constraints:
            px, py = observation.position
            distance = math.hypot(x - px, y - py)
            if observation.result == "no_signal":
                # Boundary retained as a conservative floating-point relaxation.
                if distance < 1000.0 - DISTANCE_EPS:
                    return False
            elif observation.result == "near":
                if distance > 5.0 + DISTANCE_EPS:
                    return False
            else:
                if distance > 1500.0 + DISTANCE_EPS:
                    return False
                # Sector apex is retained conservatively; no inferred lower range.
                if distance == 0.0:
                    continue
                bearing = math.degrees(math.atan2(y - py, x - px))
                delta = (bearing - observation.bearing_deg + 180.0) % 360.0 - 180.0
                if abs(delta) > BEARING_HALF_WIDTH_DEG + ANGLE_EPS:
                    return False
        return True


class ChannelState:
    """One channel's complete history and persistent feasible-region snapshot."""

    def __init__(self):
        self._history = []
        self._region = FeasibleRegion()
        self._bearing_positions = set()

    @property
    def history(self) -> Tuple[Observation, ...]:
        return tuple(self._history)

    @property
    def region(self) -> FeasibleRegion:
        return self._region

    def _record(self, observation: Observation) -> None:
        self._history.append(observation)
        if observation.result == "direction":
            # Repeated measurements are correlated. Even if the reported angle
            # differs, keep only the first sector at these exact coordinates.
            if observation.position in self._bearing_positions:
                return
            self._bearing_positions.add(observation.position)
        if observation not in self._region.constraints:
            self._region = FeasibleRegion(self._region.constraints + (observation,))


class RegionTracker:
    """Feed `record(channel, position, api.measure(position, channel))`."""

    def __init__(self):
        self._channels = {channel: ChannelState() for channel in range(1, 21)}

    def channel(self, channel: int) -> ChannelState:
        if type(channel) is not int or channel not in self._channels:
            raise ValueError("Channel must be an integer from 1 to 20")
        return self._channels[channel]

    def record(self, channel: int, position: Point, response: Mapping) -> FeasibleRegion:
        state = self.channel(channel)
        point = _point(position)
        result = response.get("measure_result")
        if result not in ("direction", "no_signal", "near"):
            raise ValueError("Unknown measurement result")
        bearing = None
        if result == "direction":
            try:
                bearing = float(response["svd_deg"])
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Direction requires a finite svd_deg") from exc
            if not math.isfinite(bearing):
                raise ValueError("Direction requires a finite svd_deg")
            bearing %= 360.0
        observation = Observation(point, result, bearing)
        state._record(observation)
        return state.region

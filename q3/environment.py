"""Public environment boundary. Policy-visible observations never contain truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from .actions import MacroAction


class FeedbackKind(str, Enum):
    NO_SIGNAL = "no_signal"
    DIRECTION = "direction"
    NEAR = "near"
    CLEAR_SUCCESS = "clear_success"
    CLEAR_FAILURE = "clear_failure"
    ACTION_REJECTED = "action_rejected"


@dataclass(frozen=True)
class MeasureFeedback:
    channel_id: int
    kind: FeedbackKind
    position: tuple[float, float]
    svd_deg: float | None = None
    coverage_point_id: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.channel_id <= 20:
            raise ValueError("channel_id must lie in 1..20")
        if self.kind is FeedbackKind.DIRECTION:
            if self.svd_deg is None or not 0.0 <= float(self.svd_deg) < 360.0:
                raise ValueError("direction feedback requires svd_deg in [0, 360)")
        elif self.svd_deg is not None:
            raise ValueError("svd_deg is only valid for direction feedback")


@dataclass(frozen=True)
class EnvironmentObservation:
    robot_position: tuple[float, float]
    virtual_time_s: float
    feedback: tuple[MeasureFeedback, ...] = ()
    done: bool = False
    public_info: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class Q3Environment(Protocol):
    def reset(self, seed: int | None = None) -> EnvironmentObservation: ...
    def execute(self, action: MacroAction) -> EnvironmentObservation: ...
    def is_done(self) -> bool: ...
    def get_public_metrics(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TimingModel:
    speed_mps: float = 5.0
    measure_time_s: float = 5.0
    channel_switch_time_s: float = 1.0
    clear_time_s: float = 5.0
    clear_failure_time_s: float = 3.0

    def __post_init__(self) -> None:
        if min(self.speed_mps, self.measure_time_s, self.clear_time_s, self.clear_failure_time_s) <= 0:
            raise ValueError("speed and action times must be positive")
        if self.channel_switch_time_s < 0:
            raise ValueError("channel switch time must be nonnegative")

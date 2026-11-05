"""Minimal interface fake. NOT FOR MODEL EVALUATION."""

from __future__ import annotations

import math
from collections import Counter

from ..actions import ClearAction, LocalizeAction, SearchAction, TerminateAction
from ..environment import EnvironmentObservation, FeedbackKind, MeasureFeedback, TimingModel


class FakeEnvironment:
    """All-no-signal deterministic fake used only to exercise framework wiring."""

    NOT_FOR_MODEL_EVALUATION = True

    def __init__(self, timing: TimingModel | None = None) -> None:
        self.timing = timing or TimingModel()
        self._position = (0.0, 0.0)
        self._time = 0.0
        self._done = False
        self._current_channel: int | None = 1
        self._movement_distance = 0.0
        self._switches = 0
        self._clear_attempts = 0
        self._actions: Counter[str] = Counter()
        self._seed: int | None = None
        self._truth_access_count = 0

    @property
    def simulator_truth(self) -> None:
        self._truth_access_count += 1
        raise RuntimeError("simulator truth is intentionally unavailable to policy code")

    @property
    def truth_access_count(self) -> int:
        return self._truth_access_count

    def reset(self, seed: int | None = None) -> EnvironmentObservation:
        self.__init__(self.timing)
        self._seed = seed
        return EnvironmentObservation(self._position, self._time)

    def _move(self, target: tuple[float, float]) -> None:
        distance = math.hypot(target[0] - self._position[0], target[1] - self._position[1])
        self._movement_distance += distance
        self._time += distance / self.timing.speed_mps
        self._position = tuple(map(float, target))

    def _switch(self, channel: int) -> None:
        if self._current_channel != channel:
            self._switches += 1
            self._time += self.timing.channel_switch_time_s
            self._current_channel = channel

    def execute(self, action):
        if self._done:
            raise RuntimeError("cannot execute after termination")
        self._actions[action.kind.value] += 1
        feedback: list[MeasureFeedback] = []
        if isinstance(action, SearchAction):
            self._move(action.target_position)
            for channel in action.channels_to_measure:
                self._switch(channel)
                self._time += self.timing.measure_time_s
                feedback.append(MeasureFeedback(
                    channel, FeedbackKind.NO_SIGNAL, self._position,
                    coverage_point_id=action.coverage_point_id,
                ))
        elif isinstance(action, LocalizeAction):
            self._move(action.target_position)
            self._switch(action.channel)
            self._time += self.timing.measure_time_s
            feedback.append(MeasureFeedback(
                action.channel, FeedbackKind.ACTION_REJECTED, self._position,
                message="FakeEnvironment has no physical direction model",
            ))
        elif isinstance(action, ClearAction):
            self._move(action.target_position)
            self._time += self.timing.clear_time_s
            self._clear_attempts += 1
            feedback.append(MeasureFeedback(action.channel, FeedbackKind.CLEAR_SUCCESS, self._position))
        elif isinstance(action, TerminateAction):
            self._done = True
        else:
            raise ValueError(f"unsupported fake action: {action!r}")
        return EnvironmentObservation(self._position, self._time, tuple(feedback), self._done)

    def is_done(self) -> bool:
        return self._done

    def get_public_metrics(self) -> dict:
        return {
            "total_virtual_time_s": self._time,
            "movement_distance": self._movement_distance,
            "movement_time": self._movement_distance / self.timing.speed_mps,
            "channel_switch_count": self._switches,
            "clear_attempt_count": self._clear_attempts,
            "timeout": False,
            "missed_source_count": 0,
            "actions_summary": dict(self._actions),
            "fake_environment": True,
        }

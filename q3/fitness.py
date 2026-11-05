"""Safety-first lexicographic policy fitness."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Fitness:
    mission_failure_count: int
    timeout_count: int
    missed_source_count: int
    cvar95_time_s: float
    mean_time_s: float

    def to_tuple(self) -> tuple[int, int, int, float, float]:
        return (
            self.mission_failure_count,
            self.timeout_count,
            self.missed_source_count,
            self.cvar95_time_s,
            self.mean_time_s,
        )

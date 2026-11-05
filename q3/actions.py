"""Finite macro-action vocabulary exposed to the policy and environment."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Union


class ActionKind(str, Enum):
    SEARCH = "search"
    LOCALIZE = "localize"
    CLEAR = "clear"
    TERMINATE = "terminate"
    FALLBACK_REQUIRED = "fallback_required"


@dataclass(frozen=True)
class SearchAction:
    target_position: tuple[float, float]
    channels_to_measure: tuple[int, ...]
    coverage_point_id: str
    kind: ActionKind = ActionKind.SEARCH


@dataclass(frozen=True)
class LocalizeAction:
    channel: int
    target_position: tuple[float, float]
    reason: str
    predicted_robust_metric: float | None = None
    kind: ActionKind = ActionKind.LOCALIZE


@dataclass(frozen=True)
class ClearAction:
    channel: int
    target_position: tuple[float, float]
    reason: str
    kind: ActionKind = ActionKind.CLEAR


@dataclass(frozen=True)
class TerminateAction:
    reason: str = "all_channels_resolved"
    kind: ActionKind = ActionKind.TERMINATE


@dataclass(frozen=True)
class FallbackRequired:
    channel: int
    reason: str
    kind: ActionKind = ActionKind.FALLBACK_REQUIRED


MacroAction = Union[SearchAction, LocalizeAction, ClearAction, TerminateAction, FallbackRequired]

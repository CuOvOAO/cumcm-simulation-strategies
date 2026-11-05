"""Event-driven Scheme-C controllers using only accepted RobotAPI feedback."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .actions import ClearAction, LocalizeAction, SearchAction
from .active_sensing import generate_active_localization_candidates
from .coverage import coverage_backbone, required_coverage_ids
from .environment import FeedbackKind, MeasureFeedback, TimingModel
from .fallback import AngleContract, FallbackState
from .localization_service import LocalizationService, filter_q2_candidates
from .policy import estimate_action_cost, score_action
from .policy_params import PolicyParams
from .state import ChannelState, ChannelStatus, MissionState


class StrategyVariant(str, Enum):
    C0_SAFE = "C0_SAFE"
    C1_Q2_FALLBACK = "C1_Q2_FALLBACK"
    C2_ROLLING = "C2_ROLLING"
    C3_BATCH = "C3_BATCH"


@dataclass
class ControllerMetrics:
    strategy_variant: str
    angle_contract: str
    q1_source_sha256: str = ""
    q2_source_sha256: str = ""
    completed: bool = False
    termination_reason: str = "running"
    excluded_count: int = 0
    cleared_count: int = 0
    q2_calls: int = 0
    q2_total_wall_time_s: float = 0.0
    q2_mean_wall_time_s: float = 0.0
    q2_cache_hits: int = 0
    q2_cache_misses: int = 0
    selected_q2_candidate_count: int = 0
    active_sensing_candidate_count: int = 0
    active_sensing_selected_count: int = 0
    fallback_triggers: int = 0
    fallback_measure_count: int = 0
    measure_count: int = 0
    switch_count: int = 0
    clear_attempts: int = 0
    failed_clears: int = 0
    uncertified_clears: int = 0
    fairness_forced_count: int = 0
    weight_sensitivity_changes: dict[str, int] = field(default_factory=lambda: {
        "w_search_0.25": 0, "w_search_4": 0,
        "w_localize_0.25": 0, "w_localize_4": 0,
    })
    action_kind_counts: dict[str, int] = field(default_factory=lambda: {
        "search": 0, "localize_q2": 0, "localize_active": 0,
        "localize_fallback": 0, "clear": 0,
    })
    rolling_action_sequence: list[str] = field(default_factory=list)
    contract_errors: list[str] = field(default_factory=list)
    real_runtime_s: float = 0.0
    virtual_time_s: float = 0.0
    per_channel_first_discovery_time_s: dict[int, float | None] = field(default_factory=dict)
    per_channel_clear_time_s: dict[int, float | None] = field(default_factory=dict)
    per_channel_localize_clear_time_s: dict[int, float | None] = field(default_factory=dict)
    channel_status: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SchemeCController:
    """One-request-at-a-time C0/C1/C2 controller with H=8 obligations."""

    FAIRNESS_H = 8

    def __init__(self, api: Any, params: PolicyParams | None = None,
                 angle_contract: AngleContract = AngleContract.RETURNED_BEARING_BOUNDED_1_DEG,
                 q2_provider=None,
                 strategy_variant: StrategyVariant | str = StrategyVariant.C2_ROLLING) -> None:
        self.api = api
        self.params = params or PolicyParams()
        self.contract = AngleContract(angle_contract)
        self.variant = StrategyVariant(strategy_variant)
        self.state = MissionState()
        self.points = coverage_backbone(self.params.r_cover)
        self.coverage_id = f"seven_point:r={self.params.r_cover:.9f}"
        self.state.coverage_config_id = self.coverage_id
        self.required = required_coverage_ids(self.params.r_cover)
        self.positions = {p.point_id: p.position for p in self.points}
        self.timing = TimingModel()
        self.service = LocalizationService(
            q2_provider=q2_provider,
            permit_fast_certificates=self.contract.permits_frozen_fast_certificates,
            enable_q2=(self.variant is not StrategyVariant.C0_SAFE and
                       self.contract.permits_frozen_fast_certificates),
            q2_cache_namespace=self.contract.value,
        )
        self.metrics = ControllerMetrics(
            self.variant.value, self.contract.value,
            q1_source_sha256=self.service.q1_source_sha256,
            q2_source_sha256=self.service.q2_source_sha256,
        )
        self._obligation_since = {("search", 0): 0}
        self._active_fallback_channel: int | None = None
        self._counted_active_sets: set[tuple[int, int]] = set()
        if self.variant is StrategyVariant.C3_BATCH:
            from .batch import BatchPlanner
            self.batch = BatchPlanner(self)

    @staticmethod
    def _accepted(raw: dict[str, Any]) -> float:
        if raw.get("accepted") is not True:
            raise RuntimeError("action_rejected")
        return float(raw["virtual_time_s"])

    def _record_accepted_action(self, action: Any, metric_key: str) -> None:
        self.state.accepted_action_index += 1
        self.state.record_action(action)
        self.metrics.action_kind_counts[metric_key] += 1
        self.metrics.rolling_action_sequence.append(metric_key)
        if self.variant is StrategyVariant.C3_BATCH:
            self.batch.on_accepted(action, metric_key)

    def _measure(self, position, channel, coverage_point_id=None, normal=False,
                 fallback=False, action=None):
        switched = self.state.current_channel != channel
        raw = self.api.measure(position, channel)
        timestamp = self._accepted(raw)
        if switched:
            self.metrics.switch_count += 1
        self.metrics.measure_count += 1
        if fallback:
            self.metrics.fallback_measure_count += 1
        kind = {"no_signal": FeedbackKind.NO_SIGNAL, "near": FeedbackKind.NEAR,
                "direction": FeedbackKind.DIRECTION}[raw["measure_result"]]
        position = tuple(map(float, position))
        feedback = MeasureFeedback(
            channel, kind, position,
            float(raw["svd_deg"]) if kind is FeedbackKind.DIRECTION else None,
            coverage_point_id=coverage_point_id,
        )
        self.state.robot_position = position
        self.state.current_channel = channel
        self.state.virtual_time_s = timestamp
        item = self.state.channels[channel]
        item.record_feedback(feedback, timestamp, self.required, self.coverage_id,
                             self.positions, normal)
        if kind is FeedbackKind.DIRECTION and not fallback:
            if (self.variant is not StrategyVariant.C3_BATCH or
                    self.batch.phase == "CLEANUP"):
                self.service.refresh_channel(item)
        if action is None:
            action = LocalizeAction(channel, position, "direct_measure")
        metric_key = (
            "search" if isinstance(action, SearchAction) else
            "localize_fallback" if fallback else
            "localize_active" if getattr(action, "reason", "") == "active_sensing" else
            "localize_q2"
        )
        self._record_accepted_action(action, metric_key)
        return kind, raw

    def _clear(self, channel, action=None):
        item = self.state.channels[channel]
        position = item.clear_position
        if position is None or not item.safe_clear:
            self.metrics.uncertified_clears += 1
            raise RuntimeError(f"uncertified_clear:{channel}")
        raw = self.api.clear(position, channel)
        timestamp = self._accepted(raw)
        self.metrics.clear_attempts += 1
        self.state.robot_position = position
        self.state.virtual_time_s = timestamp
        success = raw["clear_result"] == "success"
        kind = FeedbackKind.CLEAR_SUCCESS if success else FeedbackKind.CLEAR_FAILURE
        item.record_feedback(MeasureFeedback(channel, kind, position), timestamp,
                             self.required, self.coverage_id, self.positions)
        self._record_accepted_action(
            action or ClearAction(channel, position, "bound_certificate"), "clear")
        if not success:
            self.metrics.failed_clears += 1
            raise RuntimeError(f"certified_clear_failed:{channel}")
        if self._active_fallback_channel == channel:
            self._active_fallback_channel = None

    def _activate_fallback(self, item: ChannelState, reason: str) -> None:
        if item.first_direction is None:
            raise RuntimeError("fallback_without_first_direction")
        if item.fallback_state is None:
            item.fallback_state = FallbackState.from_first(item.first_direction, self.contract)
            item.fallback_reason = reason
            self.metrics.fallback_triggers += 1

    def _search_actions(self):
        actions = []
        for item in self.state.channels.values():
            if item.status is not ChannelStatus.UNKNOWN:
                continue
            completed = item.search_completed.get(self.coverage_id, set())
            actions.extend(SearchAction(p.position, (item.channel_id,), p.point_id)
                           for p in self.points if p.point_id not in completed)
        return actions

    def _localize_actions(self):
        actions = []
        for item in self.state.channels.values():
            if (item.resolved or item.safe_clear or not item.observations or
                    item.fallback_state is not None):
                continue
            if not self.contract.permits_frozen_fast_certificates:
                self._activate_fallback(item, "angle_contract_requires_fallback")
            elif self.variant is StrategyVariant.C0_SAFE:
                self._activate_fallback(item, "c0_safe")
            elif item.numerical_failure_count:
                self._activate_fallback(item, "q1_numerical_failure")
            elif item.normal_followup_count >= self.params.localize_budget - 1:
                self._activate_fallback(item, "localize_budget_exhausted")
            elif len(item.observations) == 1:
                pool = filter_q2_candidates(item.q2_candidates, self.params.q2_delta)
                if not pool:
                    self._activate_fallback(item, "q2_candidate_unavailable")
                else:
                    actions.extend(LocalizeAction(item.channel_id, c.position,
                                                  "q2_final_plus", c.robust_metric)
                                   for c in pool)
            elif self.variant is StrategyVariant.C1_Q2_FALLBACK:
                self._activate_fallback(item, "c1_after_q2")
            else:
                points = generate_active_localization_candidates(self.state, item, self.params)
                if not points:
                    self._activate_fallback(item, "active_candidate_unavailable")
                else:
                    key = (item.channel_id, len(item.observations))
                    if key not in self._counted_active_sets:
                        self._counted_active_sets.add(key)
                        self.metrics.active_sensing_candidate_count += len(points)
                    actions.extend(LocalizeAction(item.channel_id, p, "active_sensing")
                                   for p in points)
        return actions

    @staticmethod
    def _action_channel(action):
        return action.channels_to_measure[0] if isinstance(action, SearchAction) else action.channel

    @classmethod
    def _tie_key(cls, action):
        return (cls._action_channel(action), getattr(action, "coverage_point_id", ""),
                tuple(round(float(v), 9) for v in action.target_position),
                getattr(action, "reason", ""))

    def _best(self, actions):
        return self._best_with_params(actions, self.params)

    def _best_with_params(self, actions, params):
        return min(actions, key=lambda a: (
            -score_action(a, self.state, params, self.timing),
            estimate_action_cost(a, self.state, self.timing), self._tie_key(a)))

    def _record_weight_sensitivity(self, actions, selected):
        if not any(isinstance(a, SearchAction) for a in actions):
            return
        if not any(isinstance(a, LocalizeAction) for a in actions):
            return
        base = (type(selected).__name__, self._tie_key(selected))
        values = (
            ("w_search_0.25", {**self.params.to_dict(), "w_search": .25}),
            ("w_search_4", {**self.params.to_dict(), "w_search": 4}),
            ("w_localize_0.25", {**self.params.to_dict(), "w_localize": .25}),
            ("w_localize_4", {**self.params.to_dict(), "w_localize": 4}),
        )
        for label, raw in values:
            alt = self._best_with_params(actions, PolicyParams(**raw))
            if (type(alt).__name__, self._tie_key(alt)) != base:
                self.metrics.weight_sensitivity_changes[label] += 1

    def _choose_action(self):
        if self.variant is StrategyVariant.C3_BATCH:
            return self.batch.choose_action()
        near = [ClearAction(c.channel_id, c.clear_position, "near_certificate")
                for c in self.state.channels.values()
                if c.near_certificate is not None and c.safe_clear and not c.resolved]
        if near:
            return min(near, key=self._tie_key)
        if self._active_fallback_channel is not None:
            item = self.state.channels[self._active_fallback_channel]
            if item.fallback_state is not None and not item.resolved:
                return LocalizeAction(item.channel_id, item.fallback_state.target_position,
                                      "deterministic_fallback")
            self._active_fallback_channel = None
        search = self._search_actions()
        localize = self._localize_actions()
        fallback_channels = [c.channel_id for c in self.state.channels.values()
                             if c.fallback_state is not None and not c.resolved]
        if fallback_channels:
            self._active_fallback_channel = min(
                fallback_channels,
                key=lambda c: (self._obligation_since.get(("localize", c), 0), c))
            item = self.state.channels[self._active_fallback_channel]
            return LocalizeAction(item.channel_id, item.fallback_state.target_position,
                                  "deterministic_fallback")
        mec_clear = [ClearAction(c.channel_id, c.clear_position, "q1_mec_certificate")
                     for c in self.state.channels.values()
                     if c.safe_clear and c.clear_position is not None and not c.resolved]
        actions = search + localize + mec_clear
        if not actions:
            raise RuntimeError("no_safe_action")
        groups = []
        if search:
            groups.append((("search", 0), search))
        channel_actions = localize + mec_clear
        for channel in sorted({a.channel for a in channel_actions}):
            groups.append((("localize", channel),
                           [a for a in channel_actions if a.channel == channel]))
        for key, _ in groups:
            self._obligation_since.setdefault(key, self.state.accepted_action_index)
        expired = [(self._obligation_since[key], key, candidates)
                   for key, candidates in groups
                   if self.state.accepted_action_index - self._obligation_since[key] >= self.FAIRNESS_H]
        if expired:
            _, _, candidates = min(expired, key=lambda row: (row[0], row[1]))
            self.metrics.fairness_forced_count += 1
            return self._best(candidates)
        selected = self._best(actions)
        self._record_weight_sensitivity(actions, selected)
        return selected

    def _service_obligation(self, action):
        if isinstance(action, SearchAction):
            self._obligation_since[("search", 0)] = self.state.accepted_action_index
        elif isinstance(action, LocalizeAction) and action.reason != "deterministic_fallback":
            self._obligation_since[("localize", action.channel)] = self.state.accepted_action_index

    def _execute_action(self, action):
        if isinstance(action, ClearAction):
            self._clear(action.channel, action)
        elif isinstance(action, SearchAction):
            self._measure(action.target_position, action.channels_to_measure[0],
                          coverage_point_id=action.coverage_point_id, action=action)
            self._service_obligation(action)
        elif isinstance(action, LocalizeAction):
            item = self.state.channels[action.channel]
            fallback = action.reason == "deterministic_fallback"
            kind, raw = self._measure(action.target_position, action.channel,
                                      normal=not fallback, fallback=fallback, action=action)
            if fallback:
                if kind is FeedbackKind.NO_SIGNAL:
                    item.contract_error = "fallback_certified_reception_no_signal"
                    raise RuntimeError(f"fallback_no_signal:{item.channel_id}")
                if kind is FeedbackKind.DIRECTION:
                    item.fallback_state = item.fallback_state.advance(float(raw["svd_deg"]))
            else:
                if action.reason == "q2_final_plus":
                    self.metrics.selected_q2_candidate_count += 1
                elif action.reason == "active_sensing":
                    self.metrics.active_sensing_selected_count += 1
                if kind is FeedbackKind.NO_SIGNAL:
                    item.contract_error = "certified_localize_no_signal"
                    raise RuntimeError(f"certified_localize_no_signal:{item.channel_id}")
                self._service_obligation(action)
        else:
            raise TypeError(f"unsupported action: {action!r}")

    def _finalize(self, started):
        s = self.service
        self.metrics.q2_source_sha256 = s.q2_source_sha256
        self.metrics.q2_calls = s.q2_call_count
        self.metrics.q2_total_wall_time_s = s.q2_total_wall_time_s
        self.metrics.q2_mean_wall_time_s = s.q2_total_wall_time_s / s.q2_call_count if s.q2_call_count else 0.0
        self.metrics.q2_cache_hits = s.q2_cache_hits
        self.metrics.q2_cache_misses = s.q2_cache_misses
        self.metrics.real_runtime_s = time.perf_counter() - started
        self.metrics.virtual_time_s = self.state.virtual_time_s
        self.metrics.excluded_count = sum(c.status is ChannelStatus.EXCLUDED for c in self.state.channels.values())
        self.metrics.cleared_count = sum(c.status is ChannelStatus.CLEARED for c in self.state.channels.values())
        self.metrics.contract_errors = [c.contract_error for c in self.state.channels.values() if c.contract_error]
        self.metrics.per_channel_first_discovery_time_s = {i: c.first_discovery_time_s for i, c in self.state.channels.items()}
        self.metrics.per_channel_clear_time_s = {i: c.cleared_time_s for i, c in self.state.channels.items()}
        self.metrics.per_channel_localize_clear_time_s = {
            i: (c.cleared_time_s - c.first_discovery_time_s
                if c.cleared_time_s is not None and c.first_discovery_time_s is not None else None)
            for i, c in self.state.channels.items()
        }
        self.metrics.channel_status = {i: c.status.value for i, c in self.state.channels.items()}

    def run(self, max_actions=10000):
        started = time.perf_counter()
        try:
            while not self.state.all_channels_resolved:
                if self.state.accepted_action_index >= max_actions:
                    raise RuntimeError("action_limit")
                self._execute_action(self._choose_action())
            self.state.terminated = True
            self.metrics.completed = True
            self.metrics.termination_reason = "all_channels_resolved"
        except Exception as exc:
            self.metrics.termination_reason = f"{type(exc).__name__}:{exc}"
        finally:
            self._finalize(started)
        return self.metrics

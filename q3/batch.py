"""C3_BATCH: one coverage sweep, then nearest certified cleanup actions."""
from __future__ import annotations

import itertools
import math
import time

from .actions import ClearAction, LocalizeAction, SearchAction
from .state import ChannelStatus


def shortest_coverage_order(points):
    """Enumerate 6! open paths after the already occupied origin/center."""
    center = next(p for p in points if p.position == (0.0, 0.0))
    others = sorted((p for p in points if p != center), key=lambda p: p.point_id)
    best, best_length = None, math.inf
    for suffix in itertools.permutations(others):
        route = (center,) + suffix
        distance = math.fsum(math.dist(a.position, b.position) for a, b in zip(route, route[1:]))
        # Symmetric paths differ only in floating-point roundoff; stable IDs break ties.
        if (distance < best_length - 1e-9 or
                (abs(distance - best_length) <= 1e-9 and
                 tuple(p.point_id for p in route) < tuple(p.point_id for p in best))):
            best, best_length = route, distance
    return best, best_length


class BatchPlanner:
    def __init__(self, controller):
        self.controller = controller
        self.phase = "DISCOVERY"
        self.order, self.path_length_m = shortest_coverage_order(controller.points)
        self.point_index = 0
        self.cleanup_prepared = False
        self.decisions = []
        self._pending = None
        self._previous_position = controller.state.robot_position
        self.metrics = {
            "schema_version": 1,
            "planned_coverage_order": [p.point_id for p in self.order],
            "planned_coverage_distance_m": self.path_length_m,
            "coverage_discovery_visits": {p.point_id: 0 for p in self.order},
            "coverage_all_phase_visits": {p.point_id: 0 for p in self.order},
            "actual_discovery_order": [],
            "point_channels": {p.point_id: [] for p in self.order},
            "first_discovery_point": {},
            "discovery_end": None,
            "cleanup_start": None,
            "movement_by_kind_m": {k: 0.0 for k in controller.metrics.action_kind_counts},
            "movement_by_phase_m": {"DISCOVERY": 0.0, "CLEANUP": 0.0},
            "total_movement_m": 0.0,
            "discovery_near_clear_count": 0,
            "discovery_near_clear_extra_movement_m": 0.0,
            "q2_preparation_wall_time_s": 0.0,
        }

    @property
    def discovery_complete(self):
        for item in self.controller.state.channels.values():
            if item.status is ChannelStatus.UNKNOWN:
                return False
            if item.status is ChannelStatus.EXCLUDED:
                if not self.controller.required <= item.search_no_signal.get(self.controller.coverage_id, set()):
                    raise RuntimeError("excluded_without_complete_certificate")
            elif item.first_discovery_time_s is None:
                raise RuntimeError("discovered_without_feedback")
        return True

    def _end_discovery(self):
        if self.phase != "DISCOVERY" or not self.discovery_complete:
            return
        state = self.controller.state
        self.metrics["discovery_end"] = {
            "virtual_time_s": state.virtual_time_s,
            "movement_m": self.metrics["total_movement_m"],
            "accepted_action_index": state.accepted_action_index,
            "position": state.robot_position,
            "q2_calls": self.controller.service.q2_call_count,
        }
        self.metrics["cleanup_start"] = {
            "discovered_count": sum(c.first_discovery_time_s is not None for c in state.channels.values()),
            "uncleared_discovered_count": sum(c.first_discovery_time_s is not None and not c.resolved
                                               for c in state.channels.values()),
            "observation_counts": {i: len(c.observations) for i, c in state.channels.items()
                                   if c.first_discovery_time_s is not None},
            "clear_ready_count": sum(c.safe_clear and not c.resolved for c in state.channels.values()),
            "excluded_count": sum(c.status is ChannelStatus.EXCLUDED for c in state.channels.values()),
        }
        self.phase = "CLEANUP"

    def _cleanup_action(self):
        c = self.controller
        near = [ClearAction(item.channel_id, item.clear_position, "near_certificate")
                for item in c.state.channels.values()
                if item.near_certificate and item.safe_clear and not item.resolved]
        if near:
            return min(near, key=c._tie_key)
        if not self.cleanup_prepared:
            started = time.perf_counter()
            for item in c.state.channels.values():
                if item.observations and not item.resolved:
                    c.service.refresh_channel(item)
            self.metrics["q2_preparation_wall_time_s"] = time.perf_counter() - started
            self.cleanup_prepared = True
        if c._active_fallback_channel is not None:
            item = c.state.channels[c._active_fallback_channel]
            if item.fallback_state is not None and not item.resolved:
                return LocalizeAction(item.channel_id, item.fallback_state.target_position,
                                      "deterministic_fallback")
            c._active_fallback_channel = None
        actions = c._localize_actions()  # Original Q2 filter, Active domain and budget/failure transitions.
        actions += [ClearAction(item.channel_id, item.clear_position, "q1_mec_certificate")
                    for item in c.state.channels.values() if item.safe_clear and not item.resolved]
        actions += [LocalizeAction(item.channel_id, item.fallback_state.target_position,
                                   "deterministic_fallback")
                    for item in c.state.channels.values()
                    if item.fallback_state is not None and not item.resolved and not item.safe_clear]
        if not actions:
            raise RuntimeError("cleanup_without_safe_action")
        selected = min(actions, key=lambda a: (math.dist(c.state.robot_position, a.target_position), c._tie_key(a)))
        if isinstance(selected, LocalizeAction) and selected.reason == "deterministic_fallback":
            c._active_fallback_channel = selected.channel
        return selected

    def choose_action(self):
        c = self.controller
        self._end_discovery()
        if self.phase == "DISCOVERY":
            near = [ClearAction(item.channel_id, item.clear_position, "near_certificate")
                    for item in c.state.channels.values()
                    if item.near_certificate and item.safe_clear and not item.resolved]
            if near:
                action = min(near, key=c._tie_key)
            else:
                action = None
                while self.point_index < len(self.order):
                    point = self.order[self.point_index]
                    pending = [item.channel_id for item in c.state.channels.values()
                               if item.status is ChannelStatus.UNKNOWN and
                               point.point_id not in item.search_completed.get(c.coverage_id, set())]
                    if pending:
                        action = SearchAction(point.position, (min(pending),), point.point_id)
                        break
                    self.point_index += 1
                if action is None:
                    raise RuntimeError("coverage_exhausted_before_discovery_complete")
        else:
            action = self._cleanup_action()
        record = {
            "decision_id": len(self.decisions) + 1, "phase": self.phase,
            "accepted_action_index_before": c.state.accepted_action_index,
            "position_before": c.state.robot_position, "channel_before": c.state.current_channel,
            "virtual_time_before_s": c.state.virtual_time_s,
            "target": action.target_position, "channel": c._action_channel(action),
            "kind": action.kind.value, "reason": getattr(action, "reason", "batch_search"),
            "coverage_point_id": getattr(action, "coverage_point_id", None), "accepted": False,
        }
        self.decisions.append(record)
        self._pending = record
        return action

    def on_accepted(self, action, category):
        c, state = self.controller, self.controller.state
        record = self._pending
        if record is None:
            raise RuntimeError("batch_action_without_decision")
        phase = record["phase"]
        distance = math.dist(record["position_before"], state.robot_position)
        record.update({"accepted": True, "category": category, "movement_m": distance,
                       "virtual_time_after_s": state.virtual_time_s,
                       "action_cost_s": state.virtual_time_s - record["virtual_time_before_s"]})
        self.metrics["movement_by_kind_m"][category] += distance
        self.metrics["movement_by_phase_m"][phase] += distance
        self.metrics["total_movement_m"] += distance
        for point in self.order:
            at_point = math.dist(state.robot_position, point.position) < 1e-6
            entered = state.accepted_action_index == 1 or math.dist(self._previous_position, point.position) >= 1e-6
            if at_point and entered:
                self.metrics["coverage_all_phase_visits"][point.point_id] += 1
                if phase == "DISCOVERY":
                    self.metrics["coverage_discovery_visits"][point.point_id] += 1
                    self.metrics["actual_discovery_order"].append(point.point_id)
        self._previous_position = state.robot_position
        if isinstance(action, SearchAction):
            channel = action.channels_to_measure[0]
            self.metrics["point_channels"][action.coverage_point_id].append(channel)
            item = state.channels[channel]
            if item.first_discovery_time_s is not None:
                self.metrics["first_discovery_point"].setdefault(channel, action.coverage_point_id)
            record["feedback"] = item.last_measurement.value
        if isinstance(action, ClearAction) and phase == "DISCOVERY":
            self.metrics["discovery_near_clear_count"] += 1
            self.metrics["discovery_near_clear_extra_movement_m"] += distance
        self._pending = None
        self._end_discovery()

    def summary(self):
        c = self.controller
        return {**self.metrics, "phase": self.phase,
                "measure_fixed_time_s": c.metrics.measure_count * c.timing.measure_time_s,
                "switch_fixed_time_s": c.metrics.switch_count * c.timing.channel_switch_time_s,
                "clear_fixed_time_s": (c.metrics.clear_attempts - c.metrics.failed_clears) * c.timing.clear_time_s,
                "failed_clear_fixed_time_s": c.metrics.failed_clears * c.timing.clear_failure_time_s,
                "s_per_cleared_source": c.state.virtual_time_s / c.metrics.cleared_count
                if c.metrics.cleared_count else None,
                "q2_calls": c.service.q2_call_count, "q2_wall_time_s": c.service.q2_total_wall_time_s}

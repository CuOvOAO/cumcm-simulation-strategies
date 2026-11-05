"""Simulator-independent episode runner and policy evaluator."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .actions import ClearAction, FallbackRequired, LocalizeAction, SearchAction, TerminateAction
from .coverage import required_coverage_ids
from .environment import Q3Environment
from .fitness import Fitness
from .policy import RollingPolicy
from .policy_params import PolicyParams
from .state import MissionState


@dataclass
class EpisodeResult:
    seed: int
    completed: bool
    cleared_count: int
    excluded_count: int
    total_virtual_time_s: float
    movement_distance: float | None
    movement_time: float | None
    measure_count: int
    channel_switch_count: int | None
    clear_attempt_count: int | None
    failed_clear_count: int
    per_channel_measure_count: dict[int, int]
    per_channel_first_discovery_time_s: dict[int, float | None]
    per_channel_clear_time_s: dict[int, float | None]
    action_count: int
    termination_reason: str
    timeout: bool = False
    missed_source_count: int = 0
    actions_summary: dict[str, int] = field(default_factory=dict)
    public_metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    params: PolicyParams
    seeds: tuple[int, ...]
    episodes: list[EpisodeResult]
    fitness: Fitness


def _update_current_channel(state: MissionState, action: Any) -> None:
    if isinstance(action, SearchAction) and action.channels_to_measure:
        state.current_channel = action.channels_to_measure[0]
    elif isinstance(action, LocalizeAction):
        state.current_channel = action.channel


def run_episode(
    env: Q3Environment,
    policy: RollingPolicy,
    params: PolicyParams,
    seed: int,
    max_actions: int = 10000,
) -> EpisodeResult:
    required = required_coverage_ids(params.r_cover)
    state = MissionState()
    state.apply_observation(env.reset(seed), required, policy.localization_service)
    action_counts: dict[str, int] = {}
    reason = "environment_done" if env.is_done() else "running"
    timeout = False

    for _ in range(max_actions):
        if env.is_done():
            reason = "environment_done"
            break
        action = policy.choose_action(state, params)
        state.record_action(action)
        name = action.kind.value
        action_counts[name] = action_counts.get(name, 0) + 1
        if isinstance(action, FallbackRequired):
            reason = f"fallback_required:{action.channel}:{action.reason}"
            break
        observation = env.execute(action)
        _update_current_channel(state, action)
        if isinstance(action, SearchAction):
            state.coverage_point_visits.add(action.coverage_point_id)
        if isinstance(action, TerminateAction):
            state.terminated = True
        state.apply_observation(observation, required, policy.localization_service)
    else:
        reason = "action_limit"
        timeout = True

    metrics = dict(env.get_public_metrics())
    completed = state.all_channels_resolved and (env.is_done() or state.terminated)
    if not completed and reason == "environment_done":
        reason = "environment_ended_before_safe_completion"
    channels = state.channels.values()
    missed = int(metrics.get("missed_source_count", 0) or 0)
    return EpisodeResult(
        seed=seed,
        completed=completed,
        cleared_count=sum(c.status.value == "cleared" for c in channels),
        excluded_count=sum(c.status.value == "excluded" for c in channels),
        total_virtual_time_s=float(metrics.get("total_virtual_time_s", state.virtual_time_s)),
        movement_distance=metrics.get("movement_distance"),
        movement_time=metrics.get("movement_time"),
        measure_count=sum(c.measure_count for c in channels),
        channel_switch_count=metrics.get("channel_switch_count"),
        clear_attempt_count=metrics.get("clear_attempt_count"),
        failed_clear_count=sum(c.failed_clear_count for c in channels),
        per_channel_measure_count={c.channel_id: c.measure_count for c in channels},
        per_channel_first_discovery_time_s={c.channel_id: c.first_discovery_time_s for c in channels},
        per_channel_clear_time_s={c.channel_id: c.cleared_time_s for c in channels},
        action_count=len(state.action_history),
        termination_reason=reason,
        timeout=timeout or bool(metrics.get("timeout", False)),
        missed_source_count=missed,
        actions_summary=action_counts,
        public_metrics=metrics,
    )


def evaluate_policy(
    env_factory: Callable[[], Q3Environment],
    params: PolicyParams,
    seeds: Sequence[int],
    policy_factory: Callable[[], RollingPolicy],
    max_actions: int = 10000,
    output_json: str | None = None,
    summary_csv: str | None = None,
) -> EvaluationResult:
    episodes = [run_episode(env_factory(), policy_factory(), params, int(seed), max_actions)
                for seed in seeds]
    failures=sum(not e.completed for e in episodes)
    times = sorted(e.total_virtual_time_s for e in episodes)
    # Failure time is never a reward. Time is ranked only if every episode completed.
    cvar = empirical_cvar(times,.95) if times and not failures else math.inf
    mean = sum(times) / len(times) if times and not failures else math.inf
    fitness = Fitness(
        mission_failure_count=failures,
        timeout_count=sum(e.timeout for e in episodes),
        missed_source_count=sum(e.missed_source_count for e in episodes),
        cvar95_time_s=cvar,
        mean_time_s=mean,
    )
    result = EvaluationResult(params, tuple(map(int, seeds)), episodes, fitness)
    if output_json is not None or summary_csv is not None:
        from .logging_utils import append_evaluation_csv, save_evaluation
        if output_json is not None:
            save_evaluation(output_json, result)
        if summary_csv is not None:
            append_evaluation_csv(summary_csv, result)
    return result


def empirical_cvar(values: Sequence[float], alpha: float=.95) -> float:
    """Exact empirical upper-tail CVaR with fractional mass at the quantile."""
    if not values or not 0<=alpha<1: raise ValueError("invalid CVaR input")
    ordered=sorted(map(float,values),reverse=True)
    mass=len(ordered)*(1-alpha)
    whole=int(math.floor(mass+1e-12)); fraction=mass-whole
    total=sum(ordered[:whole])
    if fraction>1e-12: total+=fraction*ordered[whole]
    return total/mass

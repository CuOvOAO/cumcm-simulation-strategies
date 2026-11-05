"""White-box legal actions and the six-parameter rolling score."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from .actions import ClearAction, FallbackRequired, LocalizeAction, MacroAction, SearchAction, TerminateAction
from .active_sensing import generate_active_localization_candidates
from .coverage import coverage_backbone
from .environment import TimingModel
from .localization_service import LocalizationService, filter_q2_candidates
from .policy_params import PolicyParams
from .state import ChannelStatus, MissionState

def _distance(a,b): return math.dist(a,b)

def generate_legal_actions(state: MissionState, params: PolicyParams,
                           localization_service: LocalizationService|None=None, fallback_planner=None):
    del localization_service, fallback_planner
    if state.all_channels_resolved: return [TerminateAction()]
    actions: list[MacroAction]=[]
    # Certificates outrank all scoring and remain bound to their recorded point.
    for channel in state.channels.values():
        if channel.resolved: continue
        if channel.contract_error:
            actions.append(FallbackRequired(channel.channel_id,channel.contract_error)); continue
        if channel.safe_clear and channel.clear_position is not None:
            actions.append(ClearAction(channel.channel_id,channel.clear_position,
                                       "near_certificate" if channel.near_certificate else "q1_mec_certificate"))
            continue
        if channel.fallback_state is not None:
            actions.append(LocalizeAction(channel.channel_id,channel.fallback_state.target_position,
                                          "deterministic_fallback")); continue
        if channel.observations:
            if len(channel.observations)==1:
                pool=filter_q2_candidates(channel.q2_candidates,params.q2_delta)
                if pool:
                    for candidate in pool:
                        actions.append(LocalizeAction(channel.channel_id,candidate.position,
                            "q2_final_plus_near_optimal",candidate.robust_metric))
                else: actions.append(FallbackRequired(channel.channel_id,"q2_candidate_unavailable"))
            elif channel.normal_followup_count>=params.localize_budget-1:
                actions.append(FallbackRequired(channel.channel_id,"localize_budget_exhausted"))
            else:
                points=generate_active_localization_candidates(state,channel,params)
                if not points:
                    actions.append(FallbackRequired(channel.channel_id,"active_candidate_unavailable"))
                for point in points:
                    actions.append(LocalizeAction(channel.channel_id,point,"mec_safe_active_sensing"))
    certified_clears=[a for a in actions if isinstance(a,ClearAction)]
    if certified_clears:
        return certified_clears
    # Search actions are atomic: one accepted response can certify only one channel.
    for point in coverage_backbone(params.r_cover):
        for channel in state.channels.values():
            if channel.status is ChannelStatus.UNKNOWN and point.point_id not in channel.no_signal_coverage:
                actions.append(SearchAction(point.position,(channel.channel_id,),point.point_id))
    return actions

def estimate_action_cost(action,state,timing):
    target=getattr(action,"target_position",state.robot_position)
    movement=_distance(state.robot_position,target)/timing.speed_mps
    if isinstance(action,(SearchAction,LocalizeAction)):
        channel=action.channels_to_measure[0] if isinstance(action,SearchAction) else action.channel
        return movement+timing.measure_time_s+(0 if state.current_channel==channel else timing.channel_switch_time_s)
    if isinstance(action,ClearAction): return movement+timing.clear_time_s
    return 0.

def estimate_search_gain(action,state):
    del state
    return 1/7 if isinstance(action,SearchAction) else 0.

def estimate_localization_gain(action,state):
    if not isinstance(action,LocalizeAction): return 0.
    channel=state.channels[action.channel]
    if action.predicted_robust_metric is not None:
        radius=action.predicted_robust_metric/math.sqrt(3)
        return max(0.,min(1.,40/(radius+20)))
    if channel.mec_radius is None or not math.isfinite(channel.mec_radius): return 0.
    baseline=min(1.,_distance(action.target_position,channel.mec_center)/1000)
    return max(0.,min(1.,baseline*(channel.mec_radius-20)/(channel.mec_radius+20)))

def score_action(action,state,params,timing):
    if isinstance(action,TerminateAction): return math.inf
    if isinstance(action,FallbackRequired): return -math.inf
    clear=1. if isinstance(action,ClearAction) else 0.
    benefit=params.w_search*estimate_search_gain(action,state)+params.w_localize*estimate_localization_gain(action,state)+clear
    return benefit/max(1e-9,estimate_action_cost(action,state,timing))

@dataclass
class RollingPolicy:
    localization_service: LocalizationService
    timing: TimingModel=field(default_factory=TimingModel)
    def choose_action(self,state,params):
        actions=generate_legal_actions(state,params,self.localization_service)
        if not actions: return FallbackRequired(1,"no_legal_action")
        clears=[a for a in actions if isinstance(a,ClearAction)]
        if clears: return min(clears,key=lambda a:(a.channel,a.target_position))
        fallback=[a for a in actions if isinstance(a,LocalizeAction) and a.reason=="deterministic_fallback"]
        if fallback: return min(fallback,key=lambda a:a.channel)
        errors=[a for a in actions if isinstance(a,FallbackRequired)]
        candidates=[a for a in actions if not isinstance(a,FallbackRequired)]
        if not candidates: return min(errors,key=lambda a:a.channel)
        return min(candidates,key=lambda a:(-score_action(a,state,params,self.timing),repr(a)))

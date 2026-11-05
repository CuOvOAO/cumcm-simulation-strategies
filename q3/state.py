"""Policy-visible state with evidence-bound channel transitions."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping
from .environment import EnvironmentObservation, FeedbackKind, MeasureFeedback

class ChannelStatus(str,Enum):
    UNKNOWN="unknown"; DISCOVERED="discovered"; LOCALIZING="localizing"
    SAFE_CLEAR="safe_clear"; CLEARED="cleared"; EXCLUDED="excluded"
TERMINAL_CHANNEL_STATUSES=frozenset({ChannelStatus.CLEARED,ChannelStatus.EXCLUDED})

@dataclass(frozen=True)
class DirectionObservation:
    position: tuple[float,float]
    svd_deg: float
    def __post_init__(self):
        if not all(math.isfinite(v) for v in self.position):
            raise ValueError("direction position must be finite")
        if not math.isfinite(self.svd_deg) or not 0<=self.svd_deg<360:
            raise ValueError("svd_deg must lie in [0,360)")

@dataclass(frozen=True)
class NearCertificate:
    channel: int
    position: tuple[float,float]

@dataclass(frozen=True)
class MECCertificate:
    channel: int
    position: tuple[float,float]
    radius: float
    observation_count: int

@dataclass
class ChannelState:
    channel_id: int
    status: ChannelStatus=ChannelStatus.UNKNOWN
    observations: list[DirectionObservation]=field(default_factory=list)
    last_measurement: FeedbackKind|None=None
    localization_result: dict[str,Any]|None=None
    localization_polygon: tuple[tuple[float,float],...]=()
    diameter: float|None=None
    mec_center: tuple[float,float]|None=None
    mec_radius: float|None=None
    safe_clear: bool=False
    near_certificate: NearCertificate|None=None
    mec_certificate: MECCertificate|None=None
    q2_candidates: list[Any]=field(default_factory=list)
    q2_requested: bool=False
    total_measure_count: int=0
    normal_followup_count: int=0
    failed_clear_count: int=0
    numerical_failure_count: int=0
    model_conflict_count: int=0
    contract_error: str|None=None
    search_completed: dict[str,set[str]]=field(default_factory=dict)
    search_no_signal: dict[str,set[str]]=field(default_factory=dict)
    first_discovery_time_s: float|None=None
    cleared_time_s: float|None=None
    fallback_state: Any=None
    fallback_reason: str|None=None
    wait_since_action: int=0

    def __post_init__(self):
        if not 1<=self.channel_id<=20: raise ValueError("channel_id must lie in 1..20")
    @property
    def first_direction(self): return self.observations[0] if self.observations else None
    @property
    def measure_count(self): return self.total_measure_count
    @property
    def no_signal_coverage(self):
        return set().union(*self.search_no_signal.values()) if self.search_no_signal else set()
    @property
    def resolved(self): return self.status in TERMINAL_CHANNEL_STATUSES
    @property
    def clear_position(self):
        if self.near_certificate: return self.near_certificate.position
        if self.mec_certificate: return self.mec_certificate.position
        return None

    def record_feedback(self, feedback: MeasureFeedback, virtual_time_s: float,
                        required_coverage: frozenset[str], coverage_config_id: str="legacy",
                        coverage_positions: Mapping[str,tuple[float,float]]|None=None,
                        is_normal_localize: bool=False):
        if self.resolved and feedback.kind is not FeedbackKind.ACTION_REJECTED:
            raise ValueError("resolved channel cannot accept feedback")
        self.last_measurement=feedback.kind
        measured={FeedbackKind.NO_SIGNAL,FeedbackKind.DIRECTION,FeedbackKind.NEAR}
        if feedback.kind in measured:
            self.total_measure_count+=1
            if is_normal_localize: self.normal_followup_count+=1
        point_id=feedback.coverage_point_id
        if point_id is not None:
            if point_id not in required_coverage: raise ValueError("unknown coverage point id")
            if coverage_positions is not None:
                expected=coverage_positions[point_id]
                if math.dist(feedback.position,expected)>1e-6:
                    raise ValueError("coverage point coordinate mismatch")
            self.search_completed.setdefault(coverage_config_id,set()).add(point_id)
        if feedback.kind is FeedbackKind.NO_SIGNAL:
            if point_id is not None:
                self.search_no_signal.setdefault(coverage_config_id,set()).add(point_id)
            elif self.status is not ChannelStatus.UNKNOWN:
                self.model_conflict_count+=1; self.contract_error="guaranteed_reception_no_signal"
            no_signal=self.search_no_signal.get(coverage_config_id,set())
            completed=self.search_completed.get(coverage_config_id,set())
            if self.status is ChannelStatus.UNKNOWN and required_coverage<=completed and required_coverage<=no_signal:
                self.status=ChannelStatus.EXCLUDED
        elif feedback.kind is FeedbackKind.DIRECTION:
            self.observations.append(DirectionObservation(feedback.position,float(feedback.svd_deg)))
            if self.first_discovery_time_s is None: self.first_discovery_time_s=virtual_time_s
            self.status=ChannelStatus.DISCOVERED if len(self.observations)==1 else ChannelStatus.LOCALIZING
            self._revoke_clear()
        elif feedback.kind is FeedbackKind.NEAR:
            if self.first_discovery_time_s is None: self.first_discovery_time_s=virtual_time_s
            self.near_certificate=NearCertificate(self.channel_id,feedback.position)
            self.safe_clear=True; self.status=ChannelStatus.SAFE_CLEAR
        elif feedback.kind is FeedbackKind.CLEAR_SUCCESS:
            if self.status is not ChannelStatus.SAFE_CLEAR or self.clear_position is None:
                raise ValueError("clear success without certificate")
            if math.dist(feedback.position,self.clear_position)>1e-6:
                raise ValueError("clear success position does not match certificate")
            self.status=ChannelStatus.CLEARED; self.cleared_time_s=virtual_time_s
            self.fallback_state=None
        elif feedback.kind is FeedbackKind.CLEAR_FAILURE:
            if self.status is not ChannelStatus.SAFE_CLEAR or self.clear_position is None:
                raise ValueError("clear failure without certificate")
            self.failed_clear_count+=1; self.contract_error="certified_clear_failed"
            self._revoke_clear(); self.status=ChannelStatus.LOCALIZING

    def _revoke_clear(self):
        self.safe_clear=False; self.near_certificate=None; self.mec_certificate=None

    def set_localization(self,result: dict[str,Any],permit_clear: bool=True):
        self.localization_result=result
        status=result.get("status")
        vertices=result.get("vertices",())
        finite_vertices=all(len(p)==2 and all(math.isfinite(float(x)) for x in p) for p in vertices)
        diameter=result.get("diameter")
        circle=result.get("enclosing_circle")
        valid=status in {"point","segment","bounded"} and finite_vertices
        if diameter is not None: valid=valid and math.isfinite(float(diameter))
        if circle:
            center=tuple(map(float,circle.get("center",())))
            radius=float(circle.get("radius",math.inf))
            valid=valid and len(center)==2 and all(math.isfinite(x) for x in center) and math.isfinite(radius) and radius>=0
        else: center=None; radius=None; valid=False
        self.localization_polygon=tuple(tuple(map(float,p)) for p in vertices) if finite_vertices else ()
        self.diameter=float(diameter) if diameter is not None and math.isfinite(float(diameter)) else diameter
        self.mec_center=center if valid else None; self.mec_radius=radius if valid else None
        authorized=bool(permit_clear and valid and result.get("safe_clear") and radius<=20-1e-6)
        self._revoke_clear()
        if authorized:
            self.safe_clear=True
            self.mec_certificate=MECCertificate(self.channel_id,center,radius,len(self.observations))
            self.status=ChannelStatus.SAFE_CLEAR
        else: self.status=ChannelStatus.LOCALIZING

    def record_numerical_failure(self):
        self.numerical_failure_count+=1; self._revoke_clear(); self.status=ChannelStatus.LOCALIZING
    def exclude(self,required_coverage,coverage_config_id="legacy"):
        if self.status is not ChannelStatus.UNKNOWN: raise ValueError("only UNKNOWN may be excluded")
        if not required_coverage<=self.search_completed.get(coverage_config_id,set()): raise ValueError("coverage incomplete")
        if not required_coverage<=self.search_no_signal.get(coverage_config_id,set()): raise ValueError("not all no_signal")
        self.status=ChannelStatus.EXCLUDED

@dataclass
class MissionState:
    robot_position: tuple[float,float]=(0.,0.)
    current_channel: int|None=1
    virtual_time_s: float=0.
    finished: bool=False; terminated: bool=False
    accepted_action_index: int=0
    action_history: list[Any]=field(default_factory=list)
    coverage_point_visits: set[str]=field(default_factory=set)
    coverage_config_id: str="legacy"
    policy_internal_state: dict[str,Any]=field(default_factory=dict)
    channels: dict[int,ChannelState]=field(default_factory=lambda:{i:ChannelState(i) for i in range(1,21)})
    @property
    def all_channels_resolved(self): return all(c.resolved for c in self.channels.values())
    def record_action(self,action): self.action_history.append(action)
    def apply_observation(self,observation,required_coverage,localization_service=None,
                          coverage_positions=None,action=None):
        self.robot_position=tuple(map(float,observation.robot_position)); self.virtual_time_s=float(observation.virtual_time_s)
        self.finished=bool(observation.done)
        for item in observation.feedback:
            c=self.channels[item.channel_id]
            normal=bool(action is not None and getattr(action,"kind",None) and getattr(action,"kind").value=="localize" and getattr(action,"reason","")!="fallback_bisection")
            c.record_feedback(item,self.virtual_time_s,required_coverage,self.coverage_config_id,coverage_positions,normal)
            if item.kind is FeedbackKind.DIRECTION and localization_service is not None:
                localization_service.refresh_channel(c)
        if observation.feedback: self.accepted_action_index+=1
    def unresolved_channels(self)->Iterable[ChannelState]: return (c for c in self.channels.values() if not c.resolved)

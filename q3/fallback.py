"""Finite, truth-free long-side bisection fallback."""
from __future__ import annotations
import math
from dataclasses import dataclass
from enum import Enum
from .state import DirectionObservation

class AngleContract(str, Enum):
    RETURNED_BEARING_BOUNDED_1_DEG="returned_bearing_bounded_1_deg"
    PRE_ROUND_1_DEG_NEAREST_001="pre_round_1_deg_nearest_001"
    UNKNOWN="unknown"
    @property
    def fallback_error_deg(self):
        if self is self.RETURNED_BEARING_BOUNDED_1_DEG: return 1.0
        if self is self.PRE_ROUND_1_DEG_NEAREST_001: return 1.005
        raise ValueError("unknown angle contract cannot certify fallback")
    @property
    def permits_frozen_fast_certificates(self):
        return self is self.RETURNED_BEARING_BOUNDED_1_DEG

@dataclass(frozen=True)
class FallbackState:
    first: DirectionObservation
    delta_deg: float
    x_low: float; x_high: float; y_low: float; y_high: float
    cuts: int=0
    numerical_margin_m: float=.001
    @classmethod
    def from_first(cls, first, contract):
        delta=contract.fallback_error_deg
        b=1500.0*math.sin(math.radians(delta))
        return cls(first,delta,0,1500,-b,b)
    @property
    def center_local(self):
        return ((self.x_low+self.x_high)/2,(self.y_low+self.y_high)/2)
    @property
    def side_lengths(self):
        return (self.x_high-self.x_low,self.y_high-self.y_low)
    @property
    def half_diagonal(self):
        return math.hypot(*self.side_lengths)/2
    @property
    def target_position(self):
        angle=math.radians(self.first.svd_deg); u=(math.cos(angle),math.sin(angle)); v=(-u[1],u[0])
        x,y=self.center_local
        return (self.first.position[0]+x*u[0]+y*v[0],self.first.position[1]+x*u[1]+y*v[1])
    def advance(self, measured_bearing_deg):
        if self.cuts>=16: raise RuntimeError("fallback_direction_after_16_cuts")
        if not math.isfinite(measured_bearing_deg): raise ValueError("nonfinite fallback bearing")
        local=math.radians((measured_bearing_deg-self.first.svd_deg)%360)
        component_x,component_y=math.cos(local),math.sin(local)
        xl,xh,yl,yh=self.x_low,self.x_high,self.y_low,self.y_high
        cx,cy=self.center_local; sx,sy=self.side_lengths
        tangent=math.tan(math.radians(self.delta_deg))
        if sx>=sy:
            slack=sy/2*tangent+self.numerical_margin_m
            if component_x>=0: xl=max(xl,cx-slack)
            else: xh=min(xh,cx+slack)
        else:
            slack=sx/2*tangent+self.numerical_margin_m
            if component_y>=0: yl=max(yl,cy-slack)
            else: yh=min(yh,cy+slack)
        if not all(math.isfinite(z) for z in (xl,xh,yl,yh)) or xl>xh or yl>yh:
            raise RuntimeError("invalid_fallback_box")
        result=FallbackState(self.first,self.delta_deg,xl,xh,yl,yh,self.cuts+1,self.numerical_margin_m)
        if result.half_diagonal>self.half_diagonal+1e-9: raise RuntimeError("fallback_box_did_not_contract")
        if result.half_diagonal>=1000: raise RuntimeError("fallback_reception_certificate_lost")
        return result

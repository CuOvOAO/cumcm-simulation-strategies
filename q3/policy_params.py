"""The six bounded Scheme-C parameters fixed by the formal model."""
from __future__ import annotations
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar, Mapping

@dataclass(frozen=True)
class ParameterSpec:
    kind: type; minimum: float; maximum: float; default: float; meaning: str

@dataclass(frozen=True)
class PolicyParams:
    r_cover: float = 1400.0
    q2_delta: float = 10.0
    w_search: float = 1.0
    w_localize: float = 1.0
    active_eta: float = 0.5
    localize_budget: int = 4
    SPECS: ClassVar[dict[str, ParameterSpec]] = {
        "r_cover": ParameterSpec(float,1150,1700,1400,"六点搜索环半径（米）"),
        "q2_delta": ParameterSpec(float,0,50,10,"Q2候选池U容差（米）"),
        "w_search": ParameterSpec(float,.25,4,1,"搜索阶段收益权重"),
        "w_localize": ParameterSpec(float,.25,4,1,"定位势收益权重"),
        "active_eta": ParameterSpec(float,0,1,.5,"主动候选环相对半径"),
        "localize_budget": ParameterSpec(int,2,6,4,"包含首方向的常规定位预算"),
    }
    def __post_init__(self):
        if type(self).repair(asdict(self)) != self or not isinstance(self.localize_budget,int):
            raise ValueError("invalid PolicyParams; use repair()")
    @classmethod
    def repair(cls, values: Mapping[str,Any] | "PolicyParams") -> "PolicyParams":
        raw=asdict(values) if isinstance(values,cls) else dict(values); cooked={}
        for item in fields(cls):
            spec=cls.SPECS[item.name]
            value=max(spec.minimum,min(spec.maximum,float(raw.get(item.name,spec.default))))
            cooked[item.name]=int(round(value)) if spec.kind is int else value
        return cls._construct(cooked)
    @classmethod
    def _construct(cls, values):
        obj=object.__new__(cls)
        for name,value in values.items(): object.__setattr__(obj,name,value)
        return obj
    def to_dict(self): return asdict(self)

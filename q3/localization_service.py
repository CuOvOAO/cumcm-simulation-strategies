"""Thin adapters around the frozen Q1 and Q2 Final+ implementations."""

from __future__ import annotations

import importlib.util
import hashlib
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .state import ChannelState, DirectionObservation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
Q1_ROOT = PROJECT_ROOT / "FINAL_Q1_Q2"
FINAL_PLUS_FILE = PROJECT_ROOT / "audit_temp" / "phase1" / "Q2_FINAL_PLUS" / "final_plus.py"


@dataclass(frozen=True)
class Q2Candidate:
    position: tuple[float, float]
    robust_metric: float
    movement_distance_m: float
    movement_time_s: float
    guaranteed_reception: bool
    reception_information: Mapping[str, Any]
    raw_record: Mapping[str, Any]


def filter_q2_candidates(candidates: Sequence[Q2Candidate], q2_delta: float) -> list[Q2Candidate]:
    if q2_delta < 0 or not math.isfinite(q2_delta):
        raise ValueError("q2_delta must be finite and nonnegative")
    certified = [c for c in candidates if c.guaranteed_reception and math.isfinite(c.robust_metric)]
    if not certified:
        return []
    best = min(c.robust_metric for c in certified)
    return sorted(
        (c for c in certified if c.robust_metric <= best + q2_delta + 1e-9),
        key=lambda c: (c.movement_distance_m, c.robust_metric, c.position),
    )


class LocalizationService:
    """Fail-closed Q1/Q2 facade; no geometry is reimplemented here."""

    _GLOBAL_Q2_CACHE: dict[tuple[Any, ...], tuple[Q2Candidate, ...]] = {}

    def __init__(
        self,
        q2_provider: Callable[[DirectionObservation], Iterable[Mapping[str, Any]]] | None = None,
        q1_root: Path = Q1_ROOT,
        final_plus_file: Path = FINAL_PLUS_FILE,
        permit_fast_certificates: bool = True,
        enable_q2: bool = True,
        q2_cache_namespace: str = "default",
    ) -> None:
        self.q1_root = Path(q1_root)
        self.final_plus_file = Path(final_plus_file)
        self._q2_provider = q2_provider
        self.permit_fast_certificates = bool(permit_fast_certificates)
        self.enable_q2 = bool(enable_q2)
        self.q2_cache_namespace = str(q2_cache_namespace)
        self.q2_call_count = 0
        self.q2_total_wall_time_s = 0.0
        self.q2_cache_hits = 0
        self.q2_cache_misses = 0
        self.q2_source_sha256 = (
            hashlib.sha256(self.final_plus_file.read_bytes()).hexdigest()
            if self.final_plus_file.exists() else ""
        )
        self._q1 = self._load_q1()

    def _load_q1(self) -> Any:
        path = self.q1_root / "q1q2.py"
        if not path.exists():
            raise FileNotFoundError(f"frozen Q1 module not found: {path}")
        root_text = str(self.q1_root.resolve())
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        name = "q3_frozen_q1"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load frozen Q1")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if Path(module.__file__).resolve() != path.resolve():
            raise RuntimeError("wrong Q1 module source")
        self.q1_source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        return module

    @property
    def numerical_error_type(self) -> type[Exception]:
        return self._q1.NumericalGeometryError

    def localize(self, observations: Sequence[DirectionObservation]) -> dict[str, Any]:
        measurements = [(o.position[0], o.position[1], o.svd_deg) for o in observations]
        return self._q1.localize(measurements)

    def refresh_channel(self, channel: ChannelState) -> None:
        try:
            result = self.localize(channel.observations)
        except self.numerical_error_type:
            channel.record_numerical_failure()
            return
        channel.set_localization(result, permit_clear=self.permit_fast_certificates)
        if self.enable_q2 and len(channel.observations) == 1 and not channel.q2_requested:
            channel.q2_requested = True
            try:
                channel.q2_candidates = self.get_q2_candidates(channel.observations[0])
            except (ValueError, FileNotFoundError, RuntimeError, ArithmeticError):
                channel.q2_candidates = []

    def _load_final_plus(self) -> Any:
        if not self.final_plus_file.exists():
            raise FileNotFoundError(f"frozen Q2 Final+ module not found: {self.final_plus_file}")
        name = "q2_final_plus_frozen"
        if name in sys.modules:
            module = sys.modules[name]
            if Path(module.__file__).resolve() != self.final_plus_file.resolve():
                raise RuntimeError("wrong cached Q2 Final+ source")
            return module
        directory = str(self.final_plus_file.parent)
        if directory not in sys.path:
            sys.path.insert(0, directory)
        spec = importlib.util.spec_from_file_location(name, self.final_plus_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load Q2 Final+ module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        if Path(module.__file__).resolve() != self.final_plus_file.resolve():
            raise RuntimeError("wrong Q2 Final+ module source")
        self.q2_source_sha256 = hashlib.sha256(self.final_plus_file.read_bytes()).hexdigest()
        return module

    def get_q2_candidates(self, first_observation: DirectionObservation) -> list[Q2Candidate]:
        self.q2_call_count += 1
        started = time.perf_counter()
        cache_key = None
        if self._q2_provider is None:
            cache_key = (
                self.q2_cache_namespace,
                first_observation.position,
                first_observation.svd_deg,
                self.q2_source_sha256,
                1200.0,
                0.25,
            )
            cached = self._GLOBAL_Q2_CACHE.get(cache_key)
            if cached is not None:
                self.q2_cache_hits += 1
                self.q2_total_wall_time_s += time.perf_counter() - started
                return list(cached)
        self.q2_cache_misses += 1
        try:
            if self._q2_provider is not None:
                rows = list(self._q2_provider(first_observation))
            else:
                module = self._load_final_plus()
                result = module.Planner(first_observation.position, first_observation.svd_deg,
                                        d_max=1200.0, h=0.25).solve()
                rows = result["candidates"]
        finally:
            self.q2_total_wall_time_s += time.perf_counter() - started
        output: list[Q2Candidate] = []
        for row in rows:
            certified = bool(row.get("certified", row.get("reception_certified", False)))
            metric = float(row.get("U", row.get("worst_D_upper_m", math.inf)))
            move = float(row.get("move_m", math.inf))
            output.append(Q2Candidate(
                position=tuple(map(float, row["position"])),
                robust_metric=metric,
                movement_distance_m=move,
                movement_time_s=float(row.get("move_s", row.get("move_time_s", move / 5.0))),
                guaranteed_reception=certified,
                reception_information={
                    key: value for key, value in row.items()
                    if "reception" in key or "certif" in key or "excess" in key
                },
                raw_record=dict(row),
            ))
        if cache_key is not None:
            self._GLOBAL_Q2_CACHE[cache_key] = tuple(output)
        return output

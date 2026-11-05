"""Fixed white-box search coverage backbone."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CoveragePoint:
    point_id: str
    position: tuple[float, float]


def coverage_backbone(r_cover: float) -> tuple[CoveragePoint, ...]:
    """Return center plus six equally spaced ring points.

    This function encodes the approved Q3 search-completeness backbone.  It does
    not claim or re-prove the physical coverage theorem.
    """
    if not 1150.0 <= float(r_cover) <= 1700.0:
        raise ValueError("r_cover must lie in [1150, 1700] m")
    points = [CoveragePoint("center", (0.0, 0.0))]
    for k in range(6):
        angle = k * math.pi / 3.0
        points.append(CoveragePoint(
            f"ring_{k}",
            (float(r_cover * math.cos(angle)), float(r_cover * math.sin(angle))),
        ))
    return tuple(points)


def required_coverage_ids(r_cover: float) -> frozenset[str]:
    return frozenset(p.point_id for p in coverage_backbone(r_cover))

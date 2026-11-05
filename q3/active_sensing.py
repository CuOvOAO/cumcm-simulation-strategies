"""Replaceable finite active-sensing candidate generator."""

from __future__ import annotations

import math
from typing import Iterable

from .policy_params import PolicyParams
from .state import ChannelState, MissionState


def generate_active_localization_candidates(
    state: MissionState,
    channel: ChannelState,
    params: PolicyParams,
    angle_count: int = 12,
) -> list[tuple[float, float]]:
    """Generate points inside the MEC-derived guaranteed reception disk.

    The scoring layer may later replace this finite proxy with information gain,
    certified worst-case shrink or rollout.  The safety disk itself remains a
    white-box constraint.
    """
    if angle_count < 3:
        raise ValueError("angle_count must be at least 3")
    if channel.mec_center is None or channel.mec_radius is None:
        return []
    if not math.isfinite(float(channel.mec_radius)):
        return []
    safe_radius = 1000.0 - float(channel.mec_radius) - 0.001
    if safe_radius <= 0.0:
        return []
    cx, cy = channel.mec_center
    ring = params.active_eta * safe_radius
    # Center and projection of the actual robot position onto the safe disk.
    points = [(cx, cy)]
    dx, dy = state.robot_position[0]-cx, state.robot_position[1]-cy
    distance = math.hypot(dx,dy)
    if distance <= safe_radius:
        points.append(state.robot_position)
    elif distance > 0:
        points.append((cx+dx*safe_radius/distance,cy+dy*safe_radius/distance))
    for k in range(angle_count):
        angle = 2.0 * math.pi * k / angle_count
        points.append((cx + ring * math.cos(angle), cy + ring * math.sin(angle)))
    history={o.position for o in channel.observations}
    unique=[]
    for point in points:
        if not all(math.isfinite(v) for v in point): continue
        if math.dist(point,(cx,cy))>safe_radius+1e-7: continue
        if any(math.dist(point,old)<=1e-6 for old in history): continue
        if not any(math.dist(point,old)<=1e-6 for old in unique): unique.append(point)
    return unique

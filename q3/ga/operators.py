"""Reproducible genetic operators over PolicyParams only."""

from __future__ import annotations

import random

from ..policy_params import PolicyParams


def random_params(rng: random.Random) -> PolicyParams:
    values = {}
    for name, spec in PolicyParams.SPECS.items():
        value = rng.uniform(spec.minimum, spec.maximum)
        values[name] = round(value) if spec.kind is int else value
    return PolicyParams.repair(values)


def crossover(a: PolicyParams, b: PolicyParams, rng: random.Random) -> PolicyParams:
    values = {}
    for name, spec in PolicyParams.SPECS.items():
        av, bv = getattr(a, name), getattr(b, name)
        if spec.kind is int:
            values[name] = av if rng.random() < 0.5 else bv
        else:
            alpha = rng.random()
            values[name] = alpha * av + (1.0 - alpha) * bv
    return PolicyParams.repair(values)


def mutate(
    params: PolicyParams,
    rng: random.Random,
    probability: float = 0.2,
    scale: float = 0.1,
) -> PolicyParams:
    values = params.to_dict()
    for name, spec in PolicyParams.SPECS.items():
        if rng.random() >= probability:
            continue
        span = spec.maximum - spec.minimum
        values[name] = float(values[name]) + rng.gauss(0.0, scale * span)
    return PolicyParams.repair(values)

"""Sufficient (deliberately incomplete) certificates using public regions only."""

from fractions import Fraction
import math
from typing import Optional

from .region import (ANGLE_EPS, BEARING_HALF_WIDTH_DEG, DISTANCE_EPS,
                     TARGET_RADIUS_M, FeasibleRegion, Point, _point)


# Decimal truncation: PI_LO < pi < PI_LO + 10**-40.
_PI_LO = Fraction("3.1415926535897932384626433832795028841971")
_PI_WIDTH = Fraction(1, 10**40)


def _trig_interval(degrees, cosine=False):
    """Rational Taylor enclosure, rounded OUT to a 10**-12 grid.

    Reduce to [-180, 180); |x| < 4. Taylor's theorem bounds the
    remainder by |x|**n/n!, and sin/cos are 1-Lipschitz in radians.
    No platform libm trigonometric accuracy assumption is required.
    """
    degrees = (degrees + 180) % 360 - 180
    x = degrees * _PI_LO / 180
    term = Fraction(1) if cosine else x
    total = term
    for k in range(1, 18):
        a = 2 * k - 1 if cosine else 2 * k
        term *= -x * x / (a * (a + 1))
        total += term
    n = 36 if cosine else 37
    error = abs(x) ** n / math.factorial(n) + abs(degrees) * _PI_WIDTH / 180
    scale = 10**12
    lo = max(Fraction(-1), Fraction(math.floor((total - error) * scale), scale))
    hi = min(Fraction(1), Fraction(math.ceil((total + error) * scale), scale))
    return lo, hi


def _sector_box(observation):
    (px, py), radius = _disk(observation.position, 1500.0)
    # Additional outward angular slack covers ordinary membership arithmetic.
    half = (Fraction(BEARING_HALF_WIDTH_DEG) + Fraction(ANGLE_EPS)
            + Fraction(1, 10**9))
    center = Fraction(observation.bearing_deg) % 360
    start, end = center - half, center + half
    xs, ys = [Fraction(0)], [Fraction(0)]  # Sector apex is always retained.
    for angle in (start, end):
        xs.extend(_trig_interval(angle, cosine=True))
        ys.extend(_trig_interval(angle))
    for angle, x, y in ((0, 1, 0), (90, 0, 1), (180, -1, 0), (270, 0, -1)):
        if (Fraction(angle) - start) % 360 <= end - start:
            xs.append(Fraction(x))
            ys.append(Fraction(y))
    return (px + radius * min(xs), px + radius * max(xs),
            py + radius * min(ys), py + radius * max(ys))


def _enclosing_box(region):
    disks = [_disk((0.0, 0.0), TARGET_RADIUS_M)]
    boxes = []
    for observation in region.constraints:
        if observation.result in ("near", "direction"):
            disks.append(_disk(observation.position,
                               5.0 if observation.result == "near" else 1500.0))
        if observation.result == "direction":
            boxes.append(_sector_box(observation))
    boxes.extend((x - r, x + r, y - r, y + r) for (x, y), r in disks)
    return (max(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), min(b[3] for b in boxes))


def _disk(position, radius):
    # Match the relaxed region threshold and also cover one hypot rounding ulp.
    radius = math.nextafter(radius + DISTANCE_EPS, math.inf)
    return tuple(map(Fraction, position)), Fraction(radius)


def _box_covered(bounds, point):
    """Exact squared farthest-corner bound; no inward comparison tolerance."""
    x, y = map(Fraction, point)
    left, right, bottom, top = bounds
    return (max(abs(left - x), abs(right - x)) ** 2
            + max(abs(bottom - y), abs(top - y)) ** 2 <= 400)


def reliable_clear_point(region: FeasibleRegion,
                         candidate: Optional[Point] = None) -> Optional[Point]:
    """Return a certified point or None, without taking any robot action.

    Positive observations supply disk and bounded-sector boxes. Their
    intersection encloses the feasible region, ignoring no_signal exclusions.
    A supplied candidate is checked as-is;
    otherwise try near centers and the box midpoint. At least one independent
    witness must pass the existing region membership check; failure is refused.
    None means uncertified, not proof that no covering disk exists.
    """
    if candidate is not None:
        candidate = _point(candidate)
    if not any(o.result in ("near", "direction") for o in region.constraints):
        return None
    left, right, bottom, top = _enclosing_box(region)
    if left > right or bottom > top:
        return None
    bounds = left, right, bottom, top
    candidates = ([candidate] if candidate is not None else
                  [o.position for o in region.constraints if o.result == "near"]
                  + [(float((left + right) / 2), float((bottom + top) / 2))])
    # Membership is a separate guard, not the coverage certificate. A clear
    # center need not itself be feasible, so use an independent witness too.
    witnesses = [o.position for o in region.constraints if o.result == "near"]
    witnesses += [(float((left + right) / 2), float((bottom + top) / 2))]
    if not any(region.contains(w) for w in witnesses):
        return None
    for point in candidates:
        if _box_covered(bounds, point):
            return point
    return None

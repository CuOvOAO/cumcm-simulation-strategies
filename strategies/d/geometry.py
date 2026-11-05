"""Conservative Q3 physical feasible sets, distinct from the pure Q1 region.

Only public arena/range bounds and actual direction observations are used.
All polygons are OUTER enclosures; no_signal is ignored for localization.
No change to FINAL_Q1_Q2's pure-bearing geometry or its definition is made.
"""
import math

SLACK = 1e-6  # outward metric slack per supporting line
ERROR_DEG = 1.005  # also covers nearest-0.01-degree rounding of a +/-1 reading


def clip(poly, a, b, c):
    """Clip by a*x+b*y <= c, relaxing the support outward by SLACK metres."""
    c += SLACK * math.hypot(a, b)
    result = []
    old = poly[-1]
    old_v = a*old[0]+b*old[1]-c
    for new in poly:
        new_v = a*new[0]+b*new[1]-c
        if (old_v > 0) != (new_v > 0):
            t = old_v/(old_v-new_v)
            result.append((old[0]+t*(new[0]-old[0]), old[1]+t*(new[1]-old[1])))
        if new_v <= 0:
            result.append(new)
        old, old_v = new, new_v
    if not result:
        raise RuntimeError('empty physical feasible enclosure: contract/numerical conflict')
    return result


def disk_clip(poly, p, radius, sides=48):
    # Tangent supports, NOT an inscribed polygon.
    for k in range(sides):
        t = k*2*math.pi/sides
        a, b = math.cos(t), math.sin(t)
        poly = clip(poly, a, b, radius+a*p[0]+b*p[1])
    return poly


def initial_region():
    return disk_clip([(-1801.,-1801.), (1801.,-1801.), (1801.,1801.), (-1801.,1801.)],
                     (0.,0.), 1800.)


def observe(poly, p, bearing):
    lo, hi = map(math.radians, (bearing-ERROR_DEG, bearing+ERROR_DEG))
    # cross(u_lo, G-P)>=0; cross(u_hi,G-P)<=0.
    a, b = math.sin(lo), -math.cos(lo)
    poly = clip(poly, a, b, a*p[0]+b*p[1])
    a, b = -math.sin(hi), math.cos(hi)
    poly = clip(poly, a, b, a*p[0]+b*p[1])
    return disk_clip(poly, p, 1500.)


def circle(poly):
    """Small deterministic minimum-circle search, with a checked outer radius.

    Every minimum enclosing circle has 2 or 3 boundary vertices. Incremental
    construction finds a candidate; the final max-distance check is the safety
    certificate even if floating-point arithmetic missed the exact optimum.
    """
    c, r = poly[0], 0.0
    def outside(p):
        return math.dist(c, p) > r+1e-9
    for i, p in enumerate(poly):
        if not outside(p):
            continue
        c, r = p, 0.0
        for j, q in enumerate(poly[:i]):
            if not outside(q):
                continue
            c = ((p[0]+q[0])/2, (p[1]+q[1])/2)
            r = math.dist(p, q)/2
            for s in poly[:j]:
                if not outside(s):
                    continue
                # Translated circumcenter avoids cancellation at world coordinates.
                ux, uy = q[0]-p[0], q[1]-p[1]
                vx, vy = s[0]-p[0], s[1]-p[1]
                det = 2*(ux*vy-uy*vx)
                if abs(det) < 1e-12:
                    pair = max(((p,q),(p,s),(q,s)), key=lambda ab:math.dist(*ab))
                    c = tuple((x+y)/2 for x,y in zip(*pair))
                else:
                    uu, vv = ux*ux+uy*uy, vx*vx+vy*vy
                    c = (p[0]+(uu*vy-vv*uy)/det, p[1]+(ux*vv-vx*uu)/det)
                r = max(math.dist(c, z) for z in (p,q,s))
    r = math.nextafter(max(math.dist(c, p) for p in poly)+SLACK, math.inf)
    if not all(math.isfinite(v) for v in (*c, r)):
        raise RuntimeError('nonfinite enclosure')
    return c, r


def contains(poly, point, tol=1e-5):
    # Only for independent offline evaluator/tests, never needed by planner.
    return all((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0])
               >= -tol*max(1.,math.dist(a,b)) for a,b in zip(poly,poly[1:]+poly[:1]))

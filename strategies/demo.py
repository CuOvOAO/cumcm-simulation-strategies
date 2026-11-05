"""Slow demonstration only. Not scheme A/B/C and not an optimized strategy."""
import math

def run(api, seed=0):
    cleared = set()
    # 900-m square lattice covers disk with nearest distance <= 637 m.
    # Points outside the target disk are allowed by the physical rules.
    for y in range(-1800, 1801, 900):
        for x in range(-1800, 1801, 900):
            for ch in range(1, 21):
                if ch in cleared:
                    continue
                p = (float(x), float(y))
                response = api.measure(p, ch)
                for _ in range(130):
                    kind = response['measure_result']
                    if kind == 'no_signal':
                        break
                    result = api.clear(p, ch)
                    if result['clear_result'] == 'success':
                        cleared.add(ch)
                        break
                    if kind == 'near':
                        raise RuntimeError('near followed by failed clear')
                    angle = math.radians(response['svd_deg'])
                    p = (p[0]+15*math.cos(angle), p[1]+15*math.sin(angle))
                    response = api.measure(p, ch)

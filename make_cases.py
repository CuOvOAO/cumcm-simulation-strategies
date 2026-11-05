"""Generate once, share the actual JSON files for paired comparisons."""
import argparse
import json
import math
from pathlib import Path
import random

p = argparse.ArgumentParser()
p.add_argument('--count', type=int, default=20)
p.add_argument('--seed', type=int, default=2026)
p.add_argument('--out', default='cases')
a = p.parse_args()
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
for i in range(a.count):
    rng = random.Random(a.seed + i)
    profile = ['uniform', 'edge', 'cluster', 'min_radius'][i % 4]
    sources = []
    for ch in rng.sample(list(range(1, 21)), rng.randint(10, 16)):
        angle = rng.uniform(0, 2*math.pi)
        radius = 1800 * math.sqrt(rng.random())
        if profile == 'edge':
            radius = rng.uniform(1650, 1800)
        if profile == 'cluster':
            radius = 200 * math.sqrt(rng.random())
        x, y = radius*math.cos(angle), radius*math.sin(angle)
        if profile == 'cluster':
            x += 1200
        sources.append(dict(channel=ch, x=x, y=y,
                            radius=1000 if profile == 'min_radius' else rng.uniform(1000, 1500)))
    case = dict(format_version=1, profile=profile, error_seed=a.seed+i+100000,
                sources=sources)
    (out / ('case_%03d.json' % i)).write_text(json.dumps(case, indent=2), encoding='utf-8')
print('Generated', a.count, 'cases in', out)

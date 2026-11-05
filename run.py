import argparse
import csv
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
from simulator import Simulator, RobotAPI, VERSION

p = argparse.ArgumentParser()
p.add_argument('--strategy', default='strategies.demo')
p.add_argument('--cases', default='cases')
p.add_argument('--out', default='results/demo')
p.add_argument('--seed', type=int, default=0, help='Strategy seed, independent of case generation')
a = p.parse_args()
strategy = importlib.import_module(a.strategy)
paths = sorted(Path(a.cases).glob('*.json')) if Path(a.cases).is_dir() else [Path(a.cases)]
if not paths:
    raise SystemExit('No cases found: run make_cases.py first')
out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
rows = []
for path in paths:
    raw = path.read_bytes()
    sim = Simulator(json.loads(raw))
    status, error = 'ok', ''
    sim.enter()
    try:
        strategy.run(RobotAPI(sim), a.seed)
    except Exception as e:
        status, error = 'error', repr(e)
    finally:
        if sim.active:
            sim.exit()
    row = dict(case=path.name, case_sha256=hashlib.sha256(raw).hexdigest(),
               strategy=a.strategy, strategy_seed=a.seed, status=status, error=error,
               **sim.report())
    rows.append(row)
    (out / (path.stem+'.jsonl')).write_text(
        '\n'.join(json.dumps(v) for v in sim.log)+'\n', encoding='utf-8')
    print(path.name, status, 'cleared', row['cleared'], '/', row['total_sources'],
          'virtual_seconds', round(row['virtual_time_s'], 2))
with (out/'summary.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
(out/'environment.json').write_text(json.dumps(dict(
    python=sys.version, platform=platform.platform(), simulator_version=VERSION,
    simulator_sha256=hashlib.sha256(Path('simulator.py').read_bytes()).hexdigest(),
    strategy_sha256=hashlib.sha256(Path(strategy.__file__).read_bytes()).hexdigest(),
    command=sys.argv), indent=2), encoding='utf-8')
print('Saved:', out / 'summary.csv')

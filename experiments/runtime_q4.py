"""Same-environment sequential, alternating-order wall-clock comparison."""
import json
from pathlib import Path
import platform
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from q4.controller import Controller,VARIANTS
from q4.simulator import Q4Simulator
from experiments.run_q4 import PublicAPI,stats


def main():
    cases=[json.loads(p.read_bytes()) for p in sorted((ROOT/'cases_extra/q4/development').glob('*.json'))[:8]]
    names=['Q4_BATCH','Q4_PURSUIT','Q4_FORK_VIEWS'];rows=[]
    for rep in range(5):
        for name in names if rep%2==0 else list(reversed(names)):
            start=time.perf_counter();times=[]
            for case in cases:
                sim=Q4Simulator(case);sim.enter()
                t=time.perf_counter();Controller(PublicAPI(sim),VARIANTS[name]).run()
                times.append(time.perf_counter()-t);sim.exit()
                assert len(sim.cleared)==len(case['sources']) and sim.counts['clear_fail']==0
            rows.append(dict(variant=name,rep=rep,warmup=rep==0,wall_total=time.perf_counter()-start,per_case=times))
    payload=dict(method='One sequential process, 8 development profiles, alternating order, 1 warmup + 4 measured repetitions; excludes disk/HTTP.',
        python=sys.version,platform=platform.platform(),rows=rows,
        summary={n:stats([t for r in rows if r['variant']==n and not r['warmup'] for t in r['per_case']]) for n in names})
    (ROOT/'experiments/q4_runtime.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
    print(json.dumps(payload['summary'],indent=2))


if __name__=='__main__':main()

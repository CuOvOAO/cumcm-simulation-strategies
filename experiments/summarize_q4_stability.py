"""Frozen-candidate statistics, paired uncertainty, cost decomposition and oracle bounds."""
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.run_q4_stability import aggregate,hashes
from experiments.run_q4 import quantile,PublicAPI
from experiments.bounds_q4 import held_karp
from experiments.analyze_q4_stability import decompose
from q4.controller import Controller as Baseline
from q4_stable.controller import Controller
from q4.simulator import Q4Simulator


def main():
    hold=json.loads((ROOT/'experiments/q4_stability_final_holdout.json').read_text())
    freeze=json.loads((ROOT/'experiments/q4_stability_freeze.json').read_text())
    assert hashes()==freeze['source_hashes']==hold['source_hashes']
    bs=[r for r in hold['rows'] if r['variant']=='Q4_FORK_VIEWS']
    ns=[r for r in hold['rows'] if r['variant']=='Q4_STABLE15']
    assert [r['sha256'] for r in bs]==[r['sha256'] for r in ns]
    b=[r['seconds_per_source'] for r in bs];n=[r['seconds_per_source'] for r in ns]
    rng=random.Random(937115);draws=[]
    for _ in range(2000):
        ids=rng.choices(range(len(bs)),k=len(bs));x=[b[i] for i in ids];y=[n[i] for i in ids]
        draws.append((statistics.fmean(x)-statistics.fmean(y),quantile(x,.95)-quantile(y,.95)))
    ci={key:[quantile([d[i] for d in draws],.025),quantile([d[i] for d in draws],.975)]
        for i,key in enumerate(('mean_improvement','p95_improvement'))}
    groups={str(k):dict(baseline=aggregate([r for r in bs if r['total_sources']==k]),
                        final=aggregate([r for r in ns if r['total_sources']==k])) for k in (10,11,15,16)}
    profiles={p:dict(baseline=aggregate([r for r in bs if r['profile']==p]),
                    final=aggregate([r for r in ns if r['profile']==p])) for p in sorted(set(r['profile'] for r in ns))}
    attacks=[]
    for mode in ('hash','positive','negative','checker','smooth'):
        attacks += json.loads((ROOT/f'experiments/q4_stability_attack_{mode}.json').read_text())['rows']
    kernel=json.loads((ROOT/'experiments/q4_stability_forced_kernel.json').read_text())
    old=json.loads((ROOT/'experiments/q4_tail_diagnosis.json').read_text())
    oldnew=json.loads((ROOT/'experiments/q4_stability_old_validation.json').read_text())
    oldnewmap={r['case']:r for r in oldnew['rows']}
    bounds=[]
    for name in old['top_10_percent']:
        r=next(r for r in old['rows'] if r['case']==name)
        case=json.loads((ROOT/'cases_extra/q4_stability/old_validation'/name).read_bytes())
        lb=held_karp(case)
        bounds.append(dict(set='old_top10percent',case=name,baseline=r['seconds_per_source'],final=oldnewmap[name]['seconds_per_source'],
            **lb,baseline_ratio=r['seconds_per_source']/lb['lb2_s_per_source'],
            final_ratio=oldnewmap[name]['seconds_per_source']/lb['lb2_s_per_source']))
        print('bound',name,flush=True)
    final_tail=[]
    for r in sorted(ns,key=lambda r:-r['seconds_per_source'])[:5]:
        case=json.loads((ROOT/r['case_path']).read_bytes())
        path=ROOT/'results/q4_stability_final_holdout/Q4_STABLE15/hash'/Path(r['case']).stem/'decisions.jsonl'
        es=[json.loads(l) for l in path.read_text().splitlines()]
        lb=held_karp(case)
        final_tail.append(dict(case=r['case'],profile=r['profile'],seconds_per_source=r['seconds_per_source'],
            **decompose(es,{s['channel']:s for s in case['sources']}),lower_bound=lb))
    # Serial, alternating order, same interpreter/hardware; five repeats.
    runtime={'baseline':[],'final':[]}
    for repeat in range(5):
        for row in bs[:24]:
            case=json.loads((ROOT/row['case_path']).read_bytes())
            for name,klass in ([('baseline',Baseline),('final',Controller)] if repeat%2==0 else [('final',Controller),('baseline',Baseline)]):
                sim=Q4Simulator(case);sim.enter();start=time.perf_counter()
                c=klass(PublicAPI(sim));c.run()
                runtime[name].append(time.perf_counter()-start)
                assert len(sim.cleared)==len(case['sources'])
    result=dict(holdout=hold['summary'],paired=dict(mean_improvement=statistics.fmean(b)-statistics.fmean(n),
        p95_improvement=quantile(b,.95)-quantile(n,.95),worst_improvement=max(b)-max(n),
        faster_cases=sum(y<x for x,y in zip(b,n)),bootstrap_95_percent_ci=ci,bootstrap_seed=937115,bootstrap_replicates=2000),
        by_source_count=groups,by_profile=profiles,attack=aggregate(attacks),forced_kernel=kernel['summary'],
        kernel_max_ratio=max(r['diagnostics']['max_kernel_ratio'] for r in kernel['rows']),
        kernel_sources=sum(r['diagnostics']['kernel_sources'] for r in kernel['rows']),
        kernel_rounds=sum(r['diagnostics']['kernel_rounds'] for r in kernel['rows']),
        final_natural_kernel_sources=sum(r['diagnostics']['kernel_sources'] for r in ns+attacks),
        old_validation=oldnew['summary'],old_tail_bounds=bounds,final_tail=final_tail,
        runtime=dict(python=sys.version,serial_cases_per_variant=len(runtime['final']),
            samples=runtime,summary={k:dict(mean=statistics.fmean(v),p95=quantile(v,.95),worst=max(v)) for k,v in runtime.items()}),
        candidate_hashes_match=True)
    (ROOT/'experiments/q4_stability_final_analysis.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k in ('paired','attack','kernel_max_ratio','kernel_sources','kernel_rounds','final_natural_kernel_sources','old_validation')},indent=2))


if __name__=='__main__':main()

"""Disjoint development/tuning/final holdout; paired evaluator, never planner truth."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments import run_q4 as original
from q4_stable.controller import Controller,VARIANTS

SEEDS={'development':16384201,'tuning':27593613,'holdout':39841729,'attack':52761389,'final_holdout':64519277}
PROFILES=original.PROFILES+('all_omni','boundary_inward','boundary_alternating','small_radius')


def generate(split,count):
    for i in range(count):
        seed=SEEDS[split]+i
        rng=random.Random(seed)
        profile=PROFILES[i%len(PROFILES)]
        n=(10,11,15,16)[(i//len(PROFILES)+i)%4]
        offset=rng.uniform(0,2*math.pi)
        sources=[]
        for j,ch in enumerate(rng.sample(range(1,21),n)):
            a=rng.uniform(0,2*math.pi);r=1800*math.sqrt(rng.random())
            if profile in ('edge_outward','tangent','boundary_inward','boundary_alternating'):
                r=rng.uniform(1790,1800)
            if profile=='center':r=400*math.sqrt(rng.random())
            if profile=='dispersed':r=rng.uniform(1400,1800);a=offset+j*2*math.pi/n
            x,y=r*math.cos(a),r*math.sin(a)
            if profile=='cluster':x,y=1200*math.cos(offset)+x*.12,1200*math.sin(offset)+y*.12
            prob=.2 if profile=='omni_majority' else 0. if profile=='all_omni' else 1. if profile in (
                'all_directional','edge_outward','tangent','boundary_inward','boundary_alternating') else .6
            typ='directional' if rng.random()<prob else 'omni'
            orientation=rng.uniform(0,360)
            if profile=='edge_outward':orientation=math.degrees(a)+rng.uniform(-5,5)
            if profile=='tangent':orientation=math.degrees(a)+90+(.001 if j%2 else -.001)
            if profile=='boundary_inward':orientation=math.degrees(a)+180
            if profile=='boundary_alternating':orientation=math.degrees(a)+(180 if j%2 else 0)
            sources.append(dict(channel=ch,x=x,y=y,radius=1000. if split=='attack' or i%3==0 or profile=='small_radius'
                else rng.uniform(1000,1500),type=typ,orientation=orientation if typ=='directional' else 0.))
        original.write_frozen(ROOT/'cases_extra/q4_stability'/split/f'case_{i:03d}.json',
            dict(format_version=2,split=split,profile=profile,generator_seed=seed,error_seed=seed+1000000,sources=sources))


def hashes():
    paths=sorted((ROOT/'q4').glob('*.py'))+sorted((ROOT/'q4_stable').glob('*.py'))
    paths+=sorted((ROOT/'q4_stable').glob('cover_*.json'))+[ROOT/'strategies/d/geometry.py']
    paths += [ROOT/'run_q4_stability_official.py',ROOT/'q3/official_http_api.py']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run_one(job):
    # The established evaluator owns all truth and the simulator. Registration
    # swaps only controller construction, preserving the independent audit path.
    if job[1] in VARIANTS:
        original.Controller=Controller
        original.VARIANTS=VARIANTS
    else:
        from q4.controller import Controller as Baseline,VARIANTS as BaseVariants
        original.Controller=Baseline;original.VARIANTS=BaseVariants
    return original.run_one(job)


def aggregate(rows):
    result=original.aggregate(rows)
    xs=[r['seconds_per_source'] for r in rows if r['p0']]
    if xs:
        result.update(p90=original.quantile(xs,.90),p99=original.quantile(xs,.99),
            cvar95=statistics.fmean(sorted(xs,reverse=True)[:max(1,math.ceil(len(xs)*.05))]))
    return result


def main(argv=None):
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--generate',choices=SEEDS)
    p.add_argument('--count',type=int,default=48)
    p.add_argument('--cases',type=Path,default=ROOT/'cases_extra/q4_stability/development')
    p.add_argument('--limit',type=int,default=0)
    p.add_argument('--variants',nargs='+',default=['Q4_FORK_VIEWS','Q4_STABLE'])
    p.add_argument('--out',type=Path,default=ROOT/'results/q4_stability_development')
    p.add_argument('--summary',type=Path)
    p.add_argument('--jobs',type=int,default=3)
    p.add_argument('--error-mode',choices=['hash','positive','negative','checker','smooth'],default='hash')
    args=p.parse_args(argv)
    if args.generate:generate(args.generate,args.count)
    paths=sorted(args.cases.glob('*.json')) if args.cases.is_dir() else [args.cases]
    if args.limit:paths=paths[:args.limit]
    if not paths:raise RuntimeError('no cases')
    jobs=[(str(path),v,str(args.out),args.error_mode) for v in args.variants for path in paths]
    if args.jobs==1:rows=list(map(run_one,jobs))
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:rows=list(pool.map(run_one,jobs))
    payload=dict(command=sys.argv,python=sys.version,platform=platform.platform(),source_hashes=hashes(),
        summary={v:aggregate([r for r in rows if r['variant']==v]) for v in args.variants},rows=rows)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'comparison.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
    if args.summary:args.summary.write_text(json.dumps(payload,indent=2),encoding='utf8')
    print(json.dumps({v:{k:s[k] for k in ('cases','complete_cases','mean','p95','worst')} for v,s in payload['summary'].items()},indent=2))
    return payload


if __name__=='__main__':main()

"""Local Q4 paired experiments; all hidden data access stays in this evaluator."""
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
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from q4.controller import Controller,VARIANTS
from q4.simulator import Q4Simulator
from q4.geometry import contains


class PublicAPI:
    __slots__=('measure','clear')
    def __init__(self,sim): self.measure,self.clear=sim.measure,sim.clear


PROFILES=('uniform_mixed','all_directional','omni_majority','edge_outward',
          'center','cluster','dispersed','tangent')


def write_frozen(path,payload):
    raw=json.dumps(payload,indent=2,ensure_ascii=False)+'\n'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_text(encoding='utf8')!=raw: raise RuntimeError('refusing to change existing case: '+str(path))
    else: path.write_text(raw,encoding='utf8')


def generate(split,count):
    seed={'development':491700,'validation':830100,'stress':290900}[split]
    for i in range(count):
        rng=random.Random(seed+i)
        profile=PROFILES[i%len(PROFILES)]
        n=10+(i//len(PROFILES)+i)%7
        sources=[]
        offset=rng.uniform(0,2*math.pi)
        for j,ch in enumerate(rng.sample(range(1,21),n)):
            a=rng.uniform(0,2*math.pi)
            r=1800*math.sqrt(rng.random())
            if profile in ('edge_outward','tangent'): r=rng.uniform(1770,1800)
            if profile=='center': r=400*math.sqrt(rng.random())
            if profile=='dispersed': r=rng.uniform(1400,1800);a=offset+j*2*math.pi/n
            x,y=r*math.cos(a),r*math.sin(a)
            if profile=='cluster': x,y=1200*math.cos(offset)+x*.12,1200*math.sin(offset)+y*.12
            prob=.2 if profile=='omni_majority' else 1. if profile in ('all_directional','edge_outward','tangent') else .6
            typ='directional' if rng.random()<prob else 'omni'
            orientation=rng.uniform(0,360)
            if profile=='edge_outward': orientation=math.degrees(a)+rng.uniform(-5,5)
            if profile=='tangent': orientation=math.degrees(a)+90+(.01 if j%2 else -.01)
            sources.append(dict(channel=ch,x=x,y=y,radius=1000. if split=='stress' or i%3==0 else rng.uniform(1000,1500),
                                type=typ,orientation=orientation if typ=='directional' else 0.))
        case=dict(format_version=2,split=split,profile=profile,generator_seed=seed+i,
                  error_seed=seed+1000000+i,sources=sources)
        write_frozen(ROOT/'cases_extra/q4'/split/f'case_{i:03d}.json',case)


def generate_fixed():
    for i,p in enumerate(sorted((ROOT/'cases').glob('*.json'))):
        case=json.loads(p.read_bytes())
        case.update(format_version=2,split='fixed_q4',profile='derived_mixed')
        rng=random.Random(701400+i)
        for j,s in enumerate(case['sources']):
            s.update(type='directional' if j%3 else 'omni',orientation=rng.uniform(0,360))
        write_frozen(ROOT/'cases_extra/q4/fixed_q4'/p.name,case)


def hashes():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT/'q4').glob('*.py'))+[ROOT/'strategies/d/geometry.py']}


def run_one(job):
    path,variant,out,mode=job
    path,out=Path(path).resolve(),Path(out).resolve()
    raw=path.read_bytes()
    case=json.loads(raw)
    if mode!='hash': case['error_mode']=mode
    sim=Q4Simulator(case)
    sim.enter()
    error=None
    c=None
    start=time.perf_counter()
    try:
        if variant=='D_Q3_UNCHANGED':
            from strategies.d.main import Controller as D
            c=D(PublicAPI(sim));c.run()
        else:
            c=Controller(PublicAPI(sim),VARIANTS[variant]);c.run()
    except Exception as exc: error=repr(exc)
    elapsed=time.perf_counter()-start
    sim.exit()
    report=sim.report()
    row=dict(case=path.name,case_path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(raw).hexdigest(),
             split=case.get('split','fixed_omni'),profile=case.get('profile','legacy'),variant=variant,error_mode=mode,
             **report,error=error,wall_s=elapsed,diagnostics=c.diagnostics if c else {})
    truth={s['channel']:(s['x'],s['y']) for s in case['sources']}
    audit=dict(missed_sources=len(set(truth)-sim.cleared),false_exclusions=0,uncertified_clears=0,
               failed_clears=report['clear_fail'],contract_errors=int(error is not None),truth_outside_enclosure=0,
               timing_errors=0)
    phase={k:0. for k in ('search','localization','reacquisition','shared_view','clear','fallback')}
    pos,current=(0.,0.),1
    near={}
    for event in c.events if c else []:
        ch,p=event['channel'],event['position']
        if ch in truth and event.get('polygon'):
            audit['truth_outside_enclosure']+=not contains(event['polygon'],truth[ch])
        response=event['response']
        action=event['action']
        dt=math.dist(pos,p)/5
        if action=='measure':
            dt+=5+(current!=ch)
            current=ch
            if response['measure_result']=='near': near[ch]=p
        else:
            dt+=5
            valid=(ch in near and math.dist(p,near[ch])<=15) or (
                bool(event.get('polygon')) and max(math.dist(p,v) for v in event['polygon'])<20)
            audit['uncertified_clears']+=not valid
        phase[event.get('phase','fallback')]+=dt
        pos=p
    if isinstance(c,Controller): audit['false_exclusions']=sum(ch in truth for ch in c.excluded)
    elif c and error is None: audit['false_exclusions']=sum(not c.sources[ch].cleared for ch in truth)
    if abs(sum(phase.values())-sim.virtual)>1e-5: audit['timing_errors']+=1
    row['audit']=audit
    row['phase_s']=phase
    row['p0']=not any(audit.values()) and error is None
    row['seconds_per_source']=sim.virtual/len(truth) if row['p0'] else None
    target=out/variant/mode/path.stem
    target.mkdir(parents=True,exist_ok=True)
    (target/'summary.json').write_text(json.dumps(row,indent=2),encoding='utf8')
    (target/'api.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in sim.log),encoding='utf8')
    (target/'decisions.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in c.events),encoding='utf8')
    print(f'{variant} {path.stem} {row["cleared"]}/{row["total_sources"]} '
          f'T/N={sim.virtual/len(truth):.2f} wall={elapsed:.2f} err={error}',flush=True)
    return row


def quantile(xs,q):
    xs=sorted(xs);k=(len(xs)-1)*q;i=int(k)
    return xs[i]+(k-i)*(xs[min(i+1,len(xs)-1)]-xs[i])


def stats(xs):
    return dict(mean=statistics.fmean(xs),median=statistics.median(xs),p75=quantile(xs,.75),p95=quantile(xs,.95),worst=max(xs))


def aggregate(rows):
    good=[r for r in rows if r['p0']]
    n=sum(r['total_sources'] for r in rows)
    result=dict(cases=len(rows),complete_cases=len(good),sources=n,cleared=sum(r['cleared'] for r in rows),
                audit={k:sum(r['audit'][k] for r in rows) for k in rows[0]['audit']})
    result['source_clear_rate']=result['cleared']/n
    if good:
        m=sum(r['total_sources'] for r in good)
        result.update(stats([r['seconds_per_source'] for r in good]))
        result['weighted']=sum(r['virtual_time_s'] for r in good)/m
        result['time_rank_valid']=len(good)==len(rows)
        result['totals']={k:sum(r[k] for r in good) for k in ('virtual_time_s','distance_m','measure','switch','clear_success','wall_s')}
        result['per_source']=dict(movement_s=sum(r['distance_m'] for r in good)/5/m,
            measure_s=5*sum(r['measure'] for r in good)/m,switch_s=sum(r['switch'] for r in good)/m,clear_s=5.)
        result['phase_per_source']={k:sum(r['phase_s'][k] for r in good)/m for k in good[0]['phase_s']}
        result['metrics_distribution']={k:stats([r[k] for r in good]) for k in
            ('virtual_time_s','distance_m','measure','switch','clear_success','wall_s')}
        result['phase_distribution']={k:stats([r['phase_s'][k] for r in good]) for k in good[0]['phase_s']}
    return result


def main(argv=None):
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--generate',choices=['development','validation','stress','fixed_q4'])
    p.add_argument('--count',type=int,default=48)
    p.add_argument('--cases',type=Path,default=ROOT/'cases_extra/q4/development')
    p.add_argument('--limit',type=int,default=0)
    p.add_argument('--variants',nargs='+',default=['Q4_JOINT_VIEWS'])
    p.add_argument('--out',type=Path,default=ROOT/'results/q4_development')
    p.add_argument('--summary',type=Path)
    p.add_argument('--jobs',type=int,default=1)
    p.add_argument('--error-mode',choices=['hash','positive','negative','checker','smooth'],default='hash')
    args=p.parse_args(argv)
    if args.generate:
        generate_fixed() if args.generate=='fixed_q4' else generate(args.generate,args.count)
    paths=sorted(args.cases.glob('*.json')) if args.cases.is_dir() else [args.cases]
    if args.limit: paths=paths[:args.limit]
    if not paths: raise RuntimeError('no cases')
    jobs=[(str(path),v,str(args.out),args.error_mode) for v in args.variants for path in paths]
    if args.jobs==1: rows=list(map(run_one,jobs))
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool: rows=list(pool.map(run_one,jobs))
    payload=dict(command=sys.argv,python=sys.version,platform=platform.platform(),source_hashes=hashes(),
                 summary={v:aggregate([r for r in rows if r['variant']==v]) for v in args.variants},rows=rows)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'comparison.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
    if args.summary: args.summary.write_text(json.dumps(payload,indent=2),encoding='utf8')
    print(json.dumps(payload['summary'],indent=2),flush=True)
    return payload


if __name__=='__main__': main()

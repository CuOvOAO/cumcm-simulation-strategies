"""Read-only analysis of baseline trajectories and already completed rehearsals."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent/'q4-research'
sys.path.insert(0,str(ROOT))
from experiments.run_q4 import quantile
from q4.geometry import cover


def decompose(events,truth=None):
    truth=truth or {}
    pos=(0.,0.);channel=1;time=0.
    result=dict(movement_m=0.,measure_count=0,switch_count=0,clear_count=0,no_signal=0,
                absent_measures=0,absent_fixed_s=0.,repeated_search_runs=0,local_overshoot_m=0.)
    phases={};first={};cleared={};scans=[];per={};last_scan=None;anchors={}
    known_positions={ch:(s['x'],s['y']) for ch,s in truth.items()}
    for e in events:
        ch,p,action=e['channel'],tuple(e['position']),e['action'];r=e['response']
        phase=e.get('phase','unknown');dist=math.dist(pos,p)
        fixed=5.+(ch!=channel) if action=='measure' else 5.
        dt=dist/5+fixed
        group=phases.setdefault(phase,dict(time_s=0.,movement_m=0.,actions=0))
        group['time_s']+=dt;group['movement_m']+=dist;group['actions']+=1
        result['movement_m']+=dist
        pc=per.setdefault(ch,dict(local_m=0.,measures=0,negatives=0,first=None,clear=None))
        if action=='measure':
            result['measure_count']+=1;result['switch_count']+=ch!=channel;pc['measures']+=1
            channel=ch;kind=r['measure_result']
            if kind=='no_signal': result['no_signal']+=1;pc['negatives']+=1
            if truth and ch not in truth: result['absent_measures']+=1;result['absent_fixed_s']+=fixed
            if kind!='no_signal' and ch not in first:
                first[ch]=time+dt;pc['first']=first[ch]
                if ch in truth: pc['first_distance_m']=math.dist(p,known_positions[ch])
            if phase=='search' and p!=last_scan: scans.append(p);last_scan=p
            if phase in ('localization','reacquisition'):
                if 'first_service_before_s' not in pc:
                    pc['first_service_before_s']=time
                    if ch in truth and ch in anchors:
                        anchor,b=anchors[ch];theta=math.radians(b)
                        t=(p[0]-anchor[0])*math.cos(theta)+(p[1]-anchor[1])*math.sin(theta)
                        d=math.dist(anchor,known_positions[ch])
                        pc['first_fork_projection_m']=t;pc['first_fork_true_distance_m']=d
                        pc['first_fork_overshoot_proxy_m']=max(0.,t-d)
                pc['local_m']+=dist
                if ch in truth:
                    result['local_overshoot_m']+=max(0.,dist-math.dist(pos,known_positions[ch]))
            if kind=='direction':anchors[ch]=(p,r['svd_deg'])
        else:
            result['clear_count']+=1;cleared[ch]=time+dt;pc['clear']=cleared[ch]
            pc.setdefault('first_service_before_s',time)
        time+=dt;pos=p
    result.update(total_s=time,phases=phases,source_latency_mean_s=statistics.fmean(cleared[ch]-first[ch] for ch in cleared),
        source_latency_max_s=max(cleared[ch]-first[ch] for ch in cleared),last_detection_s=max(first.values()),
        last_clear_s=max(cleared.values()),after_last_clear_s=time-max(cleared.values()),
        search_viewpoints=len(set(scans)),repeated_search_runs=len(scans)-len(set(scans)),per_channel=per)
    waits=[max(0.,pc['first_service_before_s']-pc['first']) for ch,pc in per.items() if ch in cleared]
    result['queue_wait_mean_s']=statistics.fmean(waits);result['queue_wait_max_s']=max(waits)
    if not truth:
        result['absent_measures']=None;result['absent_fixed_s']=None;result['local_overshoot_m']=None
    if truth:
        src=list(truth.values());dire=[s for s in src if s['type']=='directional']
        result.update(sources=len(src),directional_count=len(dire),boundary_fraction=sum(math.hypot(s['x'],s['y'])>=1700 for s in src)/len(src),
            radius_mean=statistics.fmean(s['radius'] for s in src),source_radius_mean=statistics.fmean(math.hypot(s['x'],s['y']) for s in src),
            outward_fraction=sum(s['x']*math.cos(math.radians(s['orientation']))+s['y']*math.sin(math.radians(s['orientation']))
                                 >.7*math.hypot(s['x'],s['y']) for s in dire)/len(src),
            first_distance_mean=statistics.fmean(pc['first_distance_m'] for pc in per.values() if 'first_distance_m' in pc))
        ps,_=cover()
        visible={s['channel']:sum(math.dist(p,(s['x'],s['y']))<=s['radius'] and (s['type']=='omni' or
            (p[0]-s['x'])*math.cos(math.radians(s['orientation']))+(p[1]-s['y'])*math.sin(math.radians(s['orientation']))>=-1e-10)
            for p in ps) for s in src}
        result['baseline_visibility_counts']=visible
        result['visibility_count_mean']=statistics.fmean(visible.values())
        result['first_fork_overshoot_proxy_m']=sum(pc.get('first_fork_overshoot_proxy_m',0) for pc in per.values())
    return result


def solve(a,b):
    n=len(b);a=[row[:]+[v] for row,v in zip(a,b)]
    for i in range(n):
        j=max(range(i,n),key=lambda j:abs(a[j][i]));a[i],a[j]=a[j],a[i]
        if abs(a[i][i])<1e-10: raise ValueError('singular fit')
        t=a[i][i];a[i]=[v/t for v in a[i]]
        for j in range(n):
            if j==i:continue
            t=a[j][i];a[j]=[v-t*w for v,w in zip(a[j],a[i])]
    return [r[-1] for r in a]


def regress(rows):
    names=['intercept','N','N_eq_16','boundary_fraction','directional_fraction']
    xs=[[1.,r['sources'],float(r['sources']==16),r['boundary_fraction'],r['directional_count']/r['sources']] for r in rows]
    ys=[r['total_s'] for r in rows]
    beta=solve([[sum(x[i]*x[j] for x in xs) for j in range(5)] for i in range(5)],
               [sum(x[i]*y for x,y in zip(xs,ys)) for i in range(5)])
    residual=sum((y-sum(v*w for v,w in zip(x,beta)))**2 for x,y in zip(xs,ys))
    return dict(coefficients=dict(zip(names,beta)),r_squared=1-residual/sum((y-statistics.fmean(ys))**2 for y in ys),
                interpretation='Associational cost decomposition; not a causal effect or physical lower bound.')


def main():
    baseline=json.loads((BASE/'experiments/q4_portability_py312.json').read_text())
    rows=[]
    for r in baseline['rows']:
        case=json.loads((BASE/r['case_path']).read_bytes())
        path=BASE/'results/q4_validation_py312/Q4_FORK_VIEWS/hash'/Path(r['case']).stem/'decisions.jsonl'
        es=[json.loads(l) for l in path.read_text().splitlines()]
        row=dict(case=r['case'],profile=r['profile'],seconds_per_source=r['seconds_per_source'],
            diagnostics=r['diagnostics'],
            **decompose(es,{s['channel']:s for s in case['sources']}))
        assert abs(row['total_s']-r['virtual_time_s'])<1e-6
        rows.append(row)
    ordered=sorted(rows,key=lambda r:-r['seconds_per_source']);slow=ordered[:math.ceil(.1*len(rows))]
    matched=[]
    for s in slow:
        candidates=[r for r in rows if r['sources']==s['sources'] and r not in slow]
        q=min(candidates,key=lambda r:(abs(r['directional_count']-s['directional_count']),abs(r['seconds_per_source']-567.5)))
        matched.append(dict(slow=s['case'],control=q['case'],sources=s['sources'],
            slow_directional=s['directional_count'],control_directional=q['directional_count'],
            difference_s_per_source=s['seconds_per_source']-q['seconds_per_source'],
            phase_difference_s_per_source={p:(s['phases'].get(p,{}).get('time_s',0)-q['phases'].get(p,{}).get('time_s',0))/s['sources']
                                          for p in ('search','localization','reacquisition','shared_view','clear')},
            boundary_fraction_difference=s['boundary_fraction']-q['boundary_fraction']))
    official=[]
    totals=[(14,8,6),(15,0,15),(10,4,6)]
    for i,path in enumerate(sorted((BASE/'results/q4_official_rehearsal').glob('*/certificates.jsonl'))):
        es=[json.loads(l) for l in path.read_text().splitlines()]
        info=decompose(es)
        user_counts=dict(zip(('sources','omni','directional'),totals[i])) if i<3 else None
        official.append(dict(run=path.parent.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            counts_user_reported=user_counts,**info))
    payload=dict(analysis_interpreter=sys.version,model=regress(rows),top_10_percent=[r['case'] for r in slow],
        top_five=[r['case'] for r in ordered[:5]],matched=matched,official=official,rows=rows)
    (ROOT/'experiments/q4_tail_diagnosis.json').write_text(json.dumps(payload,indent=2),encoding='utf8')
    print('MODEL',payload['model'])
    print('TOP',[(r['case'],r['sources'],r['profile'],round(r['seconds_per_source']),
                 {p:round(v['time_s']/r['sources']) for p,v in r['phases'].items()},round(r['after_last_clear_s'])) for r in ordered[:5]])
    print('OFFICIAL',[(r['run'],r['counts_user_reported'],round(r['total_s'],3),r['absent_measures'],r['search_viewpoints'],
         {p:round(v['time_s']) for p,v in r['phases'].items()},round(r['after_last_clear_s'])) for r in official])


if __name__=='__main__':main()

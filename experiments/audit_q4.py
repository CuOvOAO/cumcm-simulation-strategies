"""Independent 50-digit replay: API transcript + verified fork witnesses.

No truth, controller polygon or controller geometry routines are read. Trig
normals use Python libm; Decimal intersections are independent of float clips.
This is high-precision numerical replay, not interval-arithmetic verification.
"""
from decimal import Decimal as D,localcontext
import argparse
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def cut(poly,a,b,c):
    a,b,c=map(D,(a,b,c))
    c+=D('0.000001')*(a*a+b*b).sqrt()
    out=[]
    prev=poly[-1];vp=a*prev[0]+b*prev[1]-c
    for p in poly:
        v=a*p[0]+b*p[1]-c
        if (v>0)!=(vp>0):
            t=vp/(vp-v)
            out.append((prev[0]+t*(p[0]-prev[0]),prev[1]+t*(p[1]-prev[1])))
        if v<=0: out.append(p)
        prev,vp=p,v
    if not out: raise AssertionError('empty replay enclosure')
    return out


def disk(poly,p,r):
    for k in range(48):
        a,b=math.cos(k*math.pi/24),math.sin(k*math.pi/24)
        poly=cut(poly,a,b,D(r)+D(a)*D(p[0])+D(b)*D(p[1]))
    return poly


def replay(folder):
    api=[json.loads(l) for l in (folder/'api.jsonl').read_text(encoding='utf8').splitlines()]
    decisions=[json.loads(l) for l in (folder/'decisions.jsonl').read_text(encoding='utf8').splitlines()]
    assert len(api)==len(decisions)
    poly0=disk([(D(-1801),D(-1801)),(D(1801),D(-1801)),(D(1801),D(1801)),(D(-1801),D(1801))],(0,0),1800)
    polys={ch:list(poly0) for ch in range(1,21)}
    near={};positive={ch:[] for ch in range(1,21)};negatives={ch:[] for ch in range(1,21)}
    cleared=set();cuts=0
    points=[(0.,0.)]+[(999*math.cos(k*math.pi/6),999*math.sin(k*math.pi/6)) for k in range(12)]
    points += [(1864*math.cos((k+.5)*math.pi/6),1864*math.sin((k+.5)*math.pi/6)) for k in range(12)]
    # Independently check analytic cover constants and all triangle edges.
    assert 1864*math.cos(math.pi/12)>1800
    for k in range(12):
        for ids in ((0,1+k,1+(k+1)%12),(1+k,1+(k+1)%12,13+k),(13+(k-1)%12,13+k,1+k)):
            assert all(math.dist(points[a],points[b])<1000 for a in ids for b in ids)
    pos=(0.,0.);current=1;vt=0.
    for index,(row,event) in enumerate(zip(api,decisions)):
        assert all(row[k]==event[k] for k in ('action','position','channel','response'))
        p,ch=row['position'],row['channel'];resp=row['response']
        assert resp['accepted'] is True and ch not in cleared
        vt+=math.dist(pos,p)/5
        if row['action']=='measure':
            vt+=5+(ch!=current);current=ch
            kind=resp['measure_result']
            if kind=='direction':
                bearing=resp['svd_deg'];positive[ch].append((p,bearing))
                for angle,sign in ((bearing-1.005,1),(bearing+1.005,-1)):
                    t=math.radians(angle);a,b=sign*math.sin(t),-sign*math.cos(t)
                    polys[ch]=cut(polys[ch],a,b,D(a)*D(p[0])+D(b)*D(p[1]))
                polys[ch]=disk(polys[ch],p,1500)
            elif kind=='near': near[ch]=p
            else: assert kind=='no_signal';negatives[ch].append(p)
            if 'fork_cut' in event:
                w=event['fork_cut'];anchor=w['anchor'];bearing=w['bearing'];t=w['t'];width=w['w']
                assert any(a==anchor and b==bearing for a,b in positive[ch])
                assert kind=='no_signal' and index>0
                prev=api[index-1]
                assert prev['action']=='measure' and prev['channel']==ch and prev['response']['measure_result']=='no_signal'
                angle=math.radians(bearing);u=(math.cos(angle),math.sin(angle));v=(-u[1],u[0])
                # Validate all geometry hypotheses, not merely witness labels.
                assert t>1 and width>=t*math.tan(math.radians(1.005))+0.00009
                assert width**2+2*t*width*math.tan(math.radians(1.005))<t*t-1e-5
                expected=[(anchor[0]+t*u[0]+s*width*v[0],anchor[1]+t*u[1]+s*width*v[1]) for s in (-1,1)]
                assert max(min(math.dist(q,r) for r in (p,prev['position'])) for q in expected)<1e-8
                polys[ch]=cut(polys[ch],u[0],u[1],D(u[0])*D(anchor[0])+D(u[1])*D(anchor[1])+D(t))
                cuts+=1
        else:
            assert row['action']=='clear' and resp['clear_result']=='success'
            vt+=5
            if not (ch in near and math.dist(p,near[ch])<=15):
                assert positive[ch]
                x,y=map(D,p)
                assert max((a-x)**2+(b-y)**2 for a,b in polys[ch])<D(400),(folder,ch)
            cleared.add(ch)
        assert abs(vt-resp['virtual_time_s'])<1e-5
        pos=p
    known=set(ch for ch in positive if positive[ch])|set(near)|cleared
    for ch in range(1,21):
        if ch in cleared: continue
        assert ch not in known
        assert len(known)==16 or all(any(math.dist(p,q)<1e-8 for q in negatives[ch]) for p in points)
    return dict(clears=len(cleared),fork_cuts=cuts,actions=len(api),failures=0)


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('roots',nargs='+',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'experiments/q4_safety_audit.json')
    args=p.parse_args();rows=[]
    with localcontext() as ctx:
        ctx.prec=50
        for root in args.roots:
            root=root.resolve()
            for path in sorted(root.glob('Q4_FORK_VIEWS/*/*/api.jsonl')):
                rows.append(dict(path=str(path.parent.relative_to(ROOT)),**replay(path.parent)))
            print(str(root),len(rows),flush=True)
    if not rows: raise RuntimeError('no transcripts audited')
    result=dict(cases=len(rows),clears=sum(r['clears'] for r in rows),fork_cuts=sum(r['fork_cuts'] for r in rows),
                actions=sum(r['actions'] for r in rows),failures=0,precision=50,rows=rows)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))


if __name__=='__main__': main()

"""Offline truth-only lower bounds. No coordinates enter the controller."""
from array import array
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def held_karp(case):
    points=[(s['x'],s['y']) for s in case['sources']]
    n=len(points);size=1<<n
    edges=[[max(0.,math.dist(a,b)-40) for b in points] for a in points]
    dp=[array('d',[math.inf])*size for _ in points]
    for i,p in enumerate(points): dp[i][1<<i]=max(0.,math.hypot(*p)-20)
    for mask in range(1,size):
        left=(size-1)^mask
        if not left: continue
        active=mask
        while active:
            bit=active&-active;i=bit.bit_length()-1;active-=bit
            cost=dp[i][mask];remaining=left
            while remaining:
                bit=remaining&-remaining;j=bit.bit_length()-1;remaining-=bit
                dest=mask|bit;value=cost+edges[i][j]
                if value<dp[j][dest]: dp[j][dest]=value
    length=min(d[-1] for d in dp)
    return dict(sources=n,relaxed_path_m=length,lb0_s_per_source=length/5/n+5,
                lb2_s_per_source=length/5/n+10)


def main():
    rows=[]
    # Fixed selection made by name, not by achieved performance. 10..16 sources.
    paths=sorted((ROOT/'cases_extra/q4/development').glob('*.json'))[:16]
    for p in paths:
        r=dict(case=p.name,**held_karp(json.loads(p.read_bytes())))
        rows.append(r);print(r,flush=True)
    payload=dict(method='Exact Held-Karp open path on pairwise 20m-disc relaxed distances; not a realizable tour.',
         lb0='optimistic movement plus 5s/source clear',lb2='LB0 plus one 5s/source observation; certified policy class only',
         no_additive_search_bound='Search and localization movement overlap with visiting; no double-counted LB1/LB3 claimed.',rows=rows)
    (ROOT/'experiments/q4_oracle_bounds.json').write_text(json.dumps(payload,indent=2),encoding='utf8')


if __name__=='__main__': main()

"""Finite continuous-coverage certificates for compact viewpoint sets."""
from decimal import Decimal as D
from functools import lru_cache
import json
import math
from pathlib import Path


def points(inner=8):
    return ([(0.,0.)]+[(999*math.cos(k*2*math.pi/inner),999*math.sin(k*2*math.pi/inner)) for k in range(inner)]+
        [(1864*math.cos((k+.5)*math.pi/6),1864*math.sin((k+.5)*math.pi/6)) for k in range(12)])


def hull_ids(ps,ids):
    ids=sorted(set(ids),key=lambda i:ps[i])
    def cross(i,j,k):
        a,b,c=ps[i],ps[j],ps[k]
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lo=[];hi=[]
    for i in ids:
        while len(lo)>1 and cross(lo[-2],lo[-1],i)<=.01:lo.pop()
        lo.append(i)
    for i in reversed(ids):
        while len(hi)>1 and cross(hi[-2],hi[-1],i)<=.01:hi.pop()
        hi.append(i)
    return lo[:-1]+hi[:-1]


def rect(path):
    x,y,size=-1800.,-1800.,3600.
    for ch in path:
        k=int(ch);size/=2
        x+=(k%2)*size;y+=(k//2)*size
    return x,y,size


def corners(x,y,size):return [(x,y),(x+size,y),(x+size,y+size),(x,y+size)]


def outside(x,y,size):
    dx=max(x,-x-size,0);dy=max(y,-y-size,0)
    return dx*dx+dy*dy>1800**2


def generate_certificate(inner=8):
    ps=points(inner);leaves={};depth=0
    def visit(path):
        nonlocal depth
        x,y,size=rect(path);cs=corners(x,y,size)
        if outside(x,y,size):leaves[path]=None;return
        ids=[i for i,p in enumerate(ps) if max(math.dist(p,c) for c in cs)<1000-1e-4]
        hull=hull_ids(ps,ids)
        valid=len(hull)>=3 and all((ps[b][0]-ps[a][0])*(c[1]-ps[a][1])-
            (ps[b][1]-ps[a][1])*(c[0]-ps[a][0])>1e-5*math.dist(ps[a],ps[b])
            for a,b in zip(hull,hull[1:]+hull[:1]) for c in cs)
        if valid:leaves[path]=hull;depth=max(depth,len(path));return
        if len(path)>=19:raise RuntimeError(f'coverage unresolved at {path}: {cs}')
        for k in range(4):visit(path+str(k))
    visit('')
    return dict(inner=inner,points=ps,leaves=leaves,max_depth=depth)


def verify_certificate(cert):
    """Exact integer verification of the complete dyadic cell partition.

    A 1e-7 m point-coordinate perturbation is allowed in each axis, covering
    decimal/IEEE conversion. No sampled source positions or orientations.
    """
    decimals=[tuple(D(str(x)) for x in p) for p in cert['points']]
    digits=max(19,max(-x.as_tuple().exponent for p in decimals for x in p))
    scale=10**digits
    def integer(x):
        sign,ds,exponent=x.as_tuple()
        return (-1 if sign else 1)*int(''.join(map(str,ds)))*10**(digits+exponent)
    ps=[tuple(integer(x) for x in p) for p in decimals]
    eps=scale//10**7
    leaves=cert['leaves'];visited=set()
    def robust_left(a,b,c):
        dx,dy=b[0]-a[0],b[1]-a[1]
        ex,ey=c[0]-a[0],c[1]-a[1]
        # First-order and product perturbation bounds for both endpoints.
        return dx*ey-dy*ex > eps*(abs(dx)+abs(dy)+2*abs(ex)+2*abs(ey))+4*eps*eps
    def visit(path,x,y,size):
        if path not in leaves:
            if len(path)>=19:raise AssertionError('missing leaf')
            h=size//2
            for k in range(4):visit(path+str(k),x+(k%2)*h,y+(k//2)*h,h)
            return
        visited.add(path);ids=leaves[path]
        if ids is None:
            dx=max(x,-x-size,0);dy=max(y,-y-size,0)
            assert dx*dx+dy*dy>(1800*scale)**2
            return
        assert len(ids)>=3 and len(set(ids))==len(ids) and all(0<=i<len(ps) for i in ids)
        cs=corners(x,y,size)
        for a,b in zip(ids,ids[1:]+ids[:1]):
            pa,pb=ps[a],ps[b]
            assert all(robust_left(pa,pb,c) for c in cs)
            # Strict convexity also remains under endpoint perturbations.
            for i in ids:
                if i not in (a,b):
                    pc=ps[i]
                    cross=(pb[0]-pa[0])*(pc[1]-pa[1])-(pb[1]-pa[1])*(pc[0]-pa[0])
                    error=2*eps*sum(abs(v) for v in (pb[0]-pa[0],pb[1]-pa[1],pc[0]-pa[0],pc[1]-pa[1]))+8*eps*eps
                    assert cross>error
        for i in ids:
            for c in cs:
                assert (abs(ps[i][0]-c[0])+eps)**2+(abs(ps[i][1]-c[1])+eps)**2<(1000*scale)**2
    visit('',-1800*scale,-1800*scale,3600*scale)
    assert visited==set(leaves)
    assert cert['points']==[list(p) for p in points(cert['inner'])]
    return dict(leaves=len(leaves),covered=sum(v is not None for v in leaves.values()),
                max_depth=max(map(len,leaves)),arithmetic='exact integer',coordinate_margin_m=1e-7)


@lru_cache(maxsize=2)
def certified_points(inner=8):
    path=Path(__file__).resolve().with_name(f'cover_{inner}.json')
    cert=json.loads(path.read_text(encoding='utf8'))
    verify_certificate(cert)
    return [tuple(p) for p in cert['points']]

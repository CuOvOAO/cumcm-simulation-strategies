"""Geometric screening only, never used as a completeness certificate."""
import math


def hull(points):
    pts=sorted(set(points))
    if len(pts)<3:return pts
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lo=[];hi=[]
    for p in pts:
        while len(lo)>1 and cross(lo[-2],lo[-1],p)<=0:lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi)>1 and cross(hi[-2],hi[-1],p)<=0:hi.pop()
        hi.append(p)
    return lo[:-1]+hi[:-1]


def inside(h,p,tol=1e-8):
    return len(h)>=3 and all((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])>=-tol
        for a,b in zip(h,h[1:]+h[:1]))


def points(n,phase=15):
    return ([(0.,0.)]+[(999*math.cos(k*2*math.pi/n),999*math.sin(k*2*math.pi/n)) for k in range(n)]+
    [(1864*math.cos(math.radians(phase)+k*math.pi/6),1864*math.sin(math.radians(phase)+k*math.pi/6)) for k in range(12)])


def screen(ps):
    bad=[]
    for r in range(0,1801,10):
        for k in range(180):
            t=k*math.pi/90;p=(r*math.cos(t),r*math.sin(t))
            qs=[q for q in ps if math.dist(q,p)<=1000-1e-5]
            if not inside(hull(qs),p):
                bad.append((r,k*2));
                if len(bad)>=3:return bad
    return bad


if __name__=='__main__':
    for n in (6,7,8,9,10,11,12):
        for phase in (0,7.5,15):
            print(n,phase,screen(points(n,phase)),flush=True)

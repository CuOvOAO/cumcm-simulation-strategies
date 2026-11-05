"""Q4 visibility constructions. The frozen Q1/Q2 and D geometry are unchanged."""
import math
from strategies.d.geometry import initial_region, observe, circle, contains, clip, ERROR_DEG


def cover():
    """25 vertices, 36 triangles of diameter <1000, enclosing the arena disk.

    For G in a triangle, at least one vertex belongs to every CLOSED halfplane
    through G. Every vertex is within the triangle diameter of G. This is a
    simultaneous position/orientation certificate, not a sampled-angle check.
    """
    points = [(0., 0.)]
    points += [(999*math.cos(k*math.pi/6), 999*math.sin(k*math.pi/6)) for k in range(12)]
    points += [(1864*math.cos((k+.5)*math.pi/6), 1864*math.sin((k+.5)*math.pi/6)) for k in range(12)]
    triangles = []
    for k in range(12):
        i, j, o, prev = 1+k, 1+(k+1)%12, 13+k, 13+(k-1)%12
        triangles += [(0,i,j), (i,o,j), (prev,o,i)]
    assert 1864*math.cos(math.pi/12) > 1800
    assert max(math.dist(points[a],points[b]) for t in triangles for a in t for b in t) < 1000
    return points, triangles


def local_mesh(poly):
    """Shape-adapted rectangular cells, each of diameter <=990 m.

    K is inside the rectangle, and hence each possible source belongs to a
    cell whose vertices surround it and are within minimum reception radius.
    Extra transverse clearance improves bearing intersection conditioning.
    """
    c, r = circle(poly)
    a,b = max(((a,b) for a in poly for b in poly), key=lambda ab:math.dist(*ab))
    d = math.dist(a,b)
    if d < 1e-8:
        raise RuntimeError('degenerate mesh requested')
    u = ((b[0]-a[0])/d,(b[1]-a[1])/d)
    v = (-u[1],u[0])
    xy = [((p[0]-c[0])*u[0]+(p[1]-c[1])*u[1],
           (p[0]-c[0])*v[0]+(p[1]-c[1])*v[1]) for p in poly]
    pad = min(200., max(10.,r*.5))
    lo,hi = min(p[0] for p in xy)-pad*.1, max(p[0] for p in xy)+pad*.1
    bottom,top = min(p[1] for p in xy)-pad, max(p[1] for p in xy)+pad
    ny = max(1,math.ceil((top-bottom)/600))
    height=(top-bottom)/ny
    nx=max(1,math.ceil((hi-lo)/math.sqrt(990**2-height**2)))
    return [(c[0]+(lo+(hi-lo)*i/nx)*u[0]+(bottom+height*j)*v[0],
             c[1]+(lo+(hi-lo)*i/nx)*u[1]+(bottom+height*j)*v[1])
            for i in range(nx+1) for j in range(ny+1)]


def fork(poly,anchor,bearing):
    """A two-probe disjunction with an exact negative-feedback consequence.

    In anchor coordinates G=(x,y), |y|<=x*tan(alpha). Set Q+=(t,w),
    Q-=(t,-w). If x>=t, segment Q-Q+ intersects anchor--G, so at least
    one Q is in G's transmitting halfplane. BOTH Q are no farther from G
    than the known positive anchor whenever w*w+2*t*w*tan(alpha)<=t*t.
    Thus both negatives imply x<t, without knowing range/type/orientation.
    """
    theta=math.radians(bearing)
    u=(math.cos(theta),math.sin(theta));v=(-u[1],u[0])
    xs=[(p[0]-anchor[0])*u[0]+(p[1]-anchor[1])*u[1] for p in poly]
    ys=[(p[0]-anchor[0])*v[0]+(p[1]-anchor[1])*v[1] for p in poly]
    t=(min(xs)+max(xs))/2
    # A thin radial slice far from the anchor must not undergo infinitely many
    # negative radial cuts while its transverse width stays above clear range.
    # Put the cross-section BEFORE all K; the same theorem now guarantees a
    # positive result, giving a new nearby anchor and a narrow transverse wedge.
    if max(xs)-min(xs)<max(ys)-min(ys) and min(xs)>max(ys)-min(ys)+2:
        t=min(xs)-(max(ys)-min(ys))-1
    w=t*math.tan(math.radians(ERROR_DEG))+1e-4
    if t<=1 or w*w+2*t*w*math.tan(math.radians(ERROR_DEG))>=t*t:
        raise RuntimeError('fork range proof unavailable')
    points=[(anchor[0]+t*u[0]+sign*w*v[0],anchor[1]+t*u[1]+sign*w*v[1]) for sign in (-1,1)]
    return points,dict(anchor=anchor,bearing=bearing,t=t,w=w)


def fork_cut(poly,witness):
    theta=math.radians(witness['bearing']);a,b=math.cos(theta),math.sin(theta)
    p=witness['anchor']
    return clip(poly,a,b,a*p[0]+b*p[1]+witness['t'])


def route(start,jobs):
    """Open nearest-neighbor + 2-opt route. Only first job is executed."""
    pending=list(range(len(jobs)))
    order=[]
    p=start
    while pending:
        i=min(pending,key=lambda j:(math.dist(p,jobs[j][1]),j))
        pending.remove(i)
        order.append(i)
        p=jobs[i][1]
    for _ in range(12):
        best,change=-1e-6,None
        for i in range(len(order)-1):
            a=start if i==0 else jobs[order[i-1]][1]
            b=jobs[order[i]][1]
            for j in range(i+1,len(order)):
                c=jobs[order[j]][1]
                delta=math.dist(a,c)-math.dist(a,b)
                if j+1<len(order):
                    d=jobs[order[j+1]][1]
                    delta+=math.dist(b,d)-math.dist(c,d)
                if delta<best: best,change=delta,(i,j)
        if change is None: break
        i,j=change
        order[i:j+1]=reversed(order[i:j+1])
    return [jobs[i][0] for i in order]

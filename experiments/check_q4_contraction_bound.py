"""Exact rational sufficient inequalities for the real-arithmetic kernel proof."""
from fractions import Fraction as F
import json
from pathlib import Path


def add(*polys):return [sum(p[i] if i<len(p) else F(0) for p in polys) for i in range(max(map(len,polys)))]
def mul(p,q):
    out=[F(0)]*(len(p)+len(q)-1)
    for i,x in enumerate(p):
        for j,y in enumerate(q):out[i+j]+=x*y
    return out
def scale(p,s):return [v*s for v in p]
def square(p):return mul(p,p)


def main():
    # D = 19 + z, z >= 0. Positivity of every polynomial coefficient proves
    # the bound for every D in the infinite interval, not a sampled D grid.
    d=[F(19),F(1)];h=F('0.00006');delta=F('0.000001')
    alpha_hi=F('1.005')*F(22,7)/180
    alpha_lo=F('1.005')*F('3.14')/180
    assert alpha_hi<F('.018')
    assert alpha_hi/(1-alpha_hi**2/2)<F('.018')
    assert 1-alpha_hi**2/2>F('.9998')
    assert alpha_lo-alpha_hi**3/6>delta/h
    assert (F(1500)+delta)/(1-(F(22,7)/48)**2/2)<1504
    r=add(d,[h]);a=add(scale(d,F('.5')),[h]);w=add(scale(d,F('.009')),[F('.0001')])
    target=square(scale(d,F('.501')))
    positive_end=add(square(r),square(a),square(w),scale(mul(r,a),-2*F('.9998')),scale(mul(r,w),2*F('.018')))
    positive_start=add(square(a),square(w))
    x=add(scale(d,F('.5')),[delta]);y=scale(add(x,[h]),F('.018'))
    negative=add(square(x),square(y))
    margins={key:add(target,scale(poly,-1)) for key,poly in
             [('positive_endpoint',positive_end),('positive_origin',positive_start),('both_negative',negative)]}
    assert all(all(v>0 for v in p) for p in margins.values())
    bounds=[F(1504)]
    for _ in range(8):bounds.append(F('.51')*bounds[-1]+F('.001'))
    assert bounds[7]<F('19.99')
    distance=21*3730+16*(7000+15*1650+3100)
    measurements=21*20+16*20+16*32
    virtual=F(distance,5)+6*measurements+16*5
    assert virtual<140000<360000
    result=dict(arithmetic='exact rational coefficients; analytic sin/cos Taylor bounds',
        inequalities={k:[str(v) for v in p] for k,p in margins.items()},
        radius_upper_after_round=[float(x) for x in bounds],measurement_bound=measurements,
        total_action_bound=measurements+16,movement_bound_m=distance,virtual_time_bound_s=float(virtual),
        scope='Real-arithmetic geometry with relaxed support lines; not a formal certificate for IEEE/libm or HTTP availability.')
    path=Path(__file__).resolve().with_name('q4_contraction_bound.json')
    path.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()

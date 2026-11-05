"""Q4 stability candidate: certified cover and bounded contraction fallback.

Only inherited measure/clear public feedback enters the controller. Negative
observations cut K only after a witnessed two-probe visibility disjunction.
"""
from dataclasses import dataclass
import math
from q4.controller import Controller as Base, Config as BaseConfig
from q4 import geometry as g
from .coverage import certified_points


@dataclass(frozen=True)
class Config:
    name: str
    inner: int = 8
    fraction: float = .25
    target: str = 'center'
    normal_rounds: int = 8
    schedule: str = 'joint'


VARIANTS = {
    'Q4_COVER21': Config('Q4_COVER21', fraction=.5),
    'Q4_SHORT25': Config('Q4_SHORT25', inner=12),
    'Q4_SHORT25_15': Config('Q4_SHORT25_15', inner=12, fraction=.15),
    'Q4_STABLE': Config('Q4_STABLE'),
    'Q4_PROBE_ROUTE': Config('Q4_PROBE_ROUTE', target='probe'),
    'Q4_RADIAL': Config('Q4_RADIAL', normal_rounds=0),
    'Q4_SHORT15': Config('Q4_SHORT15', fraction=.15),
    'Q4_SHORT10': Config('Q4_SHORT10', fraction=.10),
    'Q4_SHORT075': Config('Q4_SHORT075', fraction=.075),
    'Q4_SHORT35': Config('Q4_SHORT35', fraction=.35),
    'Q4_BATCH21': Config('Q4_BATCH21', schedule='batch'),
    'Q4_STABLE15': Config('Q4_STABLE15', fraction=.15),
}
BEST_VARIANT = 'Q4_STABLE15'


def fork_geometry(poly, anchor, bearing, fraction=.25, radial=False):
    angle=math.radians(bearing)
    u=(math.cos(angle), math.sin(angle)); v=(-u[1],u[0])
    xs=[(p[0]-anchor[0])*u[0]+(p[1]-anchor[1])*u[1] for p in poly]
    ys=[(p[0]-anchor[0])*v[0]+(p[1]-anchor[1])*v[1] for p in poly]
    cap=max(math.dist(p,anchor) for p in poly)+1e-4
    if radial:
        t=cap/2
    else:
        t=min(xs)+fraction*(max(xs)-min(xs))
        if max(xs)-min(xs)<max(ys)-min(ys) and min(xs)>max(ys)-min(ys)+2:
            t=min(xs)-(max(ys)-min(ys))-1
        # Small/degenerate proposed steps use the proven contraction kernel.
        if t<=1: t=cap/2
    width=t*math.tan(math.radians(g.ERROR_DEG))+1e-4
    if t<=1 or width*width+2*t*width*math.tan(math.radians(g.ERROR_DEG))>=t*t:
        raise RuntimeError('fork visibility proof unavailable')
    probes=[(anchor[0]+t*u[0]+s*width*v[0], anchor[1]+t*u[1]+s*width*v[1]) for s in (-1,1)]
    return probes, dict(anchor=anchor,bearing=bearing,t=t,w=width),cap


class Controller(Base):
    def __init__(self,api,config=None):
        self.stable=config or VARIANTS[BEST_VARIANT]
        super().__init__(api,BaseConfig(self.stable.name, self.stable.schedule, True, 'fork'))
        if self.stable.inner!=12: self.points=certified_points(self.stable.inner)
        self.diagnostics.update(kernel_rounds=0,kernel_sources=0,max_kernel_ratio=0.)

    def measure(self,p,ch,phase,point_id=None):
        p=tuple(p)
        s=self.sources[ch]
        if s.cleared:raise RuntimeError('measurement after clear')
        self.action_context=dict(variant=self.config.name,phase=phase,channel=ch,virtual_time_before_s=self.time)
        response=self.api.measure(p,ch)
        self._timing(response,p,ch,'measure')
        kind=response.get('measure_result')
        if kind=='direction':
            b=response.get('svd_deg')
            if isinstance(b,bool) or not isinstance(b,(int,float)) or not math.isfinite(b) or not 0<=b<360:
                raise RuntimeError('invalid bearing')
            # Fixed error is promised at the SAME point, not at nearby points.
            index=next((i for i,(q,_) in enumerate(s.bearings) if p==q),None)
            if index is None:
                s.poly=g.observe(s.poly,p,b)
                s.bearings.append((p,b))
            else:
                old=s.bearings[index]
                if abs((old[1]-b+180)%360-180)>1e-8:raise RuntimeError('inconsistent repeated bearing')
                s.bearings.append(s.bearings.pop(index))
        elif kind=='near':s.near=p
        elif kind=='no_signal':
            if point_id is not None:s.negative_points.add(point_id)
        else:raise RuntimeError('invalid feedback')
        s.samples.append((p,kind))
        self.events.append(dict(action='measure',position=p,channel=ch,phase=phase,response=response,
            polygon=s.poly if s.bearings else None))
        return kind

    def clear(self,ch):
        s=self.sources[ch]
        if s.cleared: raise RuntimeError('duplicate clear')
        if s.near is not None: p,r,cert=s.near,5.,'near'
        elif s.bearings:
            p,r=g.circle(s.poly)
            anchor=s.bearings[-1][0]
            anchor_radius=max(math.dist(anchor,v) for v in s.poly)+1e-6
            if anchor_radius<r: p,r=anchor,anchor_radius
            if r>20-1e-4:return False
            cert='physical_outer_polygon'
        else:return False
        self.action_context=dict(variant=self.config.name,phase='clear',channel=ch,certificate=cert,
            virtual_time_before_s=self.time)
        response=self.api.clear(p,ch)
        self._timing(response,p,ch,'clear')
        if response.get('clear_result')!='success':raise RuntimeError('certified clear failed')
        s.cleared=True
        self.events.append(dict(action='clear',position=p,channel=ch,phase='clear',response=response,
            certificate=cert,radius=r,polygon=s.poly))
        return True

    def fork_step(self,ch,radial=False):
        s=self.sources[ch]
        anchor,b=s.bearings[-1]
        probes,witness,cap=fork_geometry(s.poly,anchor,b,self.stable.fraction,radial)
        probes.sort(key=lambda p:math.dist(self.pos,p))
        self.diagnostics['fork_rounds']+=1
        positive=False
        for i,p in enumerate(probes):
            if self.measure(p,ch,'localization' if i==0 else 'reacquisition')!='no_signal':
                positive=True
                break
        if not positive:
            s.poly=g.fork_cut(s.poly,witness)
            self.events[-1]['fork_cut']=witness
            self.events[-1]['polygon']=s.poly
            self.diagnostics['fork_negative_cuts']+=1
        if radial:
            self.diagnostics['kernel_rounds']+=1
            new_anchor=s.bearings[-1][0]
            new_cap=max(math.dist(p,new_anchor) for p in s.poly)+1e-4
            self.events[-1]['contraction']=dict(before=cap,after=new_cap,near=s.near is not None)
            if s.near is None:
                self.diagnostics['max_kernel_ratio']=max(self.diagnostics['max_kernel_ratio'],new_cap/cap)
                if new_cap>.51*cap+.001:
                    raise RuntimeError('contraction invariant conflict')

    def finish(self,ch):
        # At most eight heuristic rounds, then eight <0.51 contractions.
        # K is initially within 1500*sec(pi/48)+slack of its last positive anchor.
        for step in range(self.stable.normal_rounds+9):
            if self.clear(ch):
                self.diagnostics['max_local_steps']=max(self.diagnostics['max_local_steps'],step)
                self.views()
                return
            if step==self.stable.normal_rounds+8: break
            radial=step>=self.stable.normal_rounds
            if step==self.stable.normal_rounds: self.diagnostics['kernel_sources']+=1
            self.fork_step(ch,radial)
        self.diagnostics['emergency']+=1
        raise RuntimeError('bounded localization invariant failed; no uncertified clear')

    def target(self,ch):
        s=self.sources[ch]
        if s.near is not None: return s.near
        center,radius=g.circle(s.poly)
        if self.stable.target=='probe' and radius>20-1e-4:
            probes,_,_=fork_geometry(s.poly,*s.bearings[-1],self.stable.fraction)
            return min(probes,key=lambda p:math.dist(self.pos,p))
        return center

    def run(self):
        remaining=set(range(len(self.points)))
        while remaining or any(not self.sources[ch].cleared for ch in self.known()):
            if len(self.known())==16: remaining.clear()
            pending=[ch for ch in self.known() if not self.sources[ch].cleared]
            jobs=[(('scan',i),self.points[i]) for i in sorted(remaining)]
            if self.stable.schedule!='batch' or not remaining:
                jobs += [(('source',ch),self.target(ch)) for ch in pending]
            if not jobs: break
            kind,i=g.route(self.pos,jobs)[0]
            if kind=='scan': self.scan(i); remaining.remove(i)
            else: self.finish(i)
        return self.complete()

    def complete(self):
        for ch,s in self.sources.items():
            if s.cleared: continue
            if s.bearings or s.near is not None: raise RuntimeError('unresolved observed source')
            if len(self.known())==16: self.excluded[ch]='public_count_upper_bound'
            elif s.negative_points==set(range(len(self.points))): self.excluded[ch]='certified_visibility_cover'
            else: raise RuntimeError('incomplete absence certificate')
        return self.diagnostics


def run(api,seed=0):
    return Controller(api).run()

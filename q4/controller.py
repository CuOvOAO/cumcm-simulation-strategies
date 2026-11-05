"""Q4 mission controller. Runtime input is exactly measure/clear public feedback.

    Negative results never clip the source region. Absence requires the full
    25-vertex visibility certificate or the public 16-source upper bound.
"""
from dataclasses import dataclass,field
import math
from . import geometry as g


@dataclass(frozen=True)
class Config:
    name: str
    schedule: str = 'joint'
    shared_views: bool = True
    localizer: str = 'mesh'


VARIANTS={
    'Q4_BATCH':Config('Q4_BATCH','batch',False),
    'Q4_IMMEDIATE':Config('Q4_IMMEDIATE','immediate',False),
    'Q4_JOINT':Config('Q4_JOINT','joint',False),
    'Q4_JOINT_VIEWS':Config('Q4_JOINT_VIEWS'),
    'Q4_PURSUIT':Config('Q4_PURSUIT','joint',True,'pursuit'),
    'Q4_FORK_BATCH':Config('Q4_FORK_BATCH','batch',False,'fork'),
    'Q4_FORK_JOINT':Config('Q4_FORK_JOINT','joint',False,'fork'),
    'Q4_FORK_VIEWS':Config('Q4_FORK_VIEWS','joint',True,'fork'),
}
BEST_VARIANT='Q4_FORK_VIEWS'


@dataclass
class Channel:
    poly:list=field(default_factory=g.initial_region)
    bearings:list=field(default_factory=list)
    near:tuple=None
    cleared:bool=False
    negative_points:set=field(default_factory=set)
    samples:list=field(default_factory=list)


class Controller:
    def __init__(self,api,config=None):
        self.api=api
        self.config=config or VARIANTS[BEST_VARIANT]
        self.sources={ch:Channel() for ch in range(1,21)}
        self.points,self.triangles=g.cover()
        self.pos,self.channel,self.time=(0.,0.),1,0.
        self.events=[]
        self.action_context={}
        self.diagnostics=dict(reacquisition_calls=0,reacquisition_probes=0,max_local_steps=0,emergency=0,
                              fork_rounds=0,fork_negative_cuts=0)
        self.excluded={}

    def _timing(self,response,p,ch,action):
        if response.get('accepted') is not True: raise RuntimeError('action rejected')
        reported=response.get('virtual_time_s')
        if isinstance(reported,bool) or not isinstance(reported,(int,float)) or not math.isfinite(reported):
            raise RuntimeError('invalid response time')
        cost=math.dist(self.pos,p)/5+(5+(ch!=self.channel) if action=='measure' else 5)
        if abs(reported-self.time-cost)>1e-5: raise RuntimeError('timing conflict')
        self.pos,self.time=p,float(reported)
        if action=='measure': self.channel=ch

    def measure(self,p,ch,phase,point_id=None):
        p=tuple(p)
        s=self.sources[ch]
        if s.cleared: raise RuntimeError('measurement after clear')
        self.action_context=dict(variant=self.config.name,phase=phase,channel=ch,virtual_time_before_s=self.time)
        response=self.api.measure(p,ch)
        self._timing(response,p,ch,'measure')
        kind=response.get('measure_result')
        if kind=='direction':
            b=response.get('svd_deg')
            if isinstance(b,bool) or not isinstance(b,(int,float)) or not math.isfinite(b) or not 0<=b<360:
                raise RuntimeError('invalid bearing')
            old=next((e for e in s.bearings if math.dist(e[0],p)<1e-8),None)
            if old and abs((old[1]-b+180)%360-180)>1e-8: raise RuntimeError('inconsistent repeated bearing')
            if not old:
                s.poly=g.observe(s.poly,p,b)
                s.bearings.append((p,b))
        elif kind=='near': s.near=p
        elif kind=='no_signal':
            if point_id is not None: s.negative_points.add(point_id)
        else: raise RuntimeError('invalid feedback')
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
            if r>20-1e-4: return False
            cert='physical_outer_polygon'
        else: return False
        self.action_context=dict(variant=self.config.name,phase='clear',channel=ch,certificate=cert,
                                 virtual_time_before_s=self.time)
        response=self.api.clear(p,ch)
        self._timing(response,p,ch,'clear')
        if response.get('clear_result')!='success': raise RuntimeError('certified clear failed')
        s.cleared=True
        self.events.append(dict(action='clear',position=p,channel=ch,phase='clear',response=response,
                                certificate=cert,radius=r,polygon=s.poly))
        return True

    def reacquire(self,ch):
        s=self.sources[ch]
        self.diagnostics['reacquisition_calls']+=1
        points=g.local_mesh(s.poly)
        # Skip exact repeat samples; a previous positive still certifies
        # acquisition but supplies no new information, so never average it.
        points=[p for p in points if all(math.dist(p,q)>1e-7 for q,_ in s.samples)]
        for i in g.route(self.pos,[(i,p) for i,p in enumerate(points)]):
            self.diagnostics['reacquisition_probes']+=1
            if self.measure(points[i],ch,'reacquisition')!='no_signal': return
        raise RuntimeError('local mesh reception/progress conflict')

    def finish(self,ch):
        s=self.sources[ch]
        for step in range(40):
            if self.clear(ch):
                self.diagnostics['max_local_steps']=max(self.diagnostics['max_local_steps'],step)
                if self.config.shared_views: self.views()
                return
            c,r=g.circle(s.poly)
            if self.config.localizer=='fork':
                self.fork_step(ch)
                continue
            if self.config.localizer=='pursuit' and step<4:
                p,b=s.bearings[-1]
                t=math.radians(b)
                c=(p[0]+min(400.,r)*math.cos(t),p[1]+min(400.,r)*math.sin(t))
            if any(math.dist(c,p)<1e-7 for p,_ in s.samples):
                self.reacquire(ch)
            elif self.measure(c,ch,'localization')=='no_signal': self.reacquire(ch)
        self.diagnostics['emergency']+=1
        raise RuntimeError('localization action budget exhausted; mission incomplete')

    def fork_step(self,ch):
        s=self.sources[ch]
        anchor,b=s.bearings[-1]
        points,witness=g.fork(s.poly,anchor,b)
        points.sort(key=lambda p:math.dist(self.pos,p))
        self.diagnostics['fork_rounds']+=1
        for i,p in enumerate(points):
            if self.measure(p,ch,'localization' if i==0 else 'reacquisition')!='no_signal': return
        s.poly=g.fork_cut(s.poly,witness)
        self.events[-1]['fork_cut']=witness
        self.events[-1]['polygon']=s.poly
        self.diagnostics['fork_negative_cuts']+=1

    def views(self):
        for ch,s in self.sources.items():
            if not s.bearings or s.cleared or s.near is not None: continue
            c,r=g.circle(s.poly)
            if r<=20-1e-4 or math.dist(self.pos,c)+r>1000: continue
            if any(math.dist(self.pos,p)<25 for p,_ in s.samples): continue
            self.measure(self.pos,ch,'shared_view')

    def scan(self,i):
        p=self.points[i]
        for ch,s in self.sources.items():
            if s.cleared: continue
            if s.bearings:
                if not self.config.shared_views: continue
                c,r=g.circle(s.poly)
                if math.dist(p,c)-r>1500: continue
            self.measure(p,ch,'search',i)
            if s.near is not None: self.clear(ch)

    def known(self):
        return [ch for ch,s in self.sources.items() if s.bearings or s.near is not None or s.cleared]

    def run(self):
        remaining=set(range(25))
        while remaining or any(ch for ch in self.known() if not self.sources[ch].cleared):
            if len(self.known())==16: remaining.clear()
            pending=[ch for ch in self.known() if not self.sources[ch].cleared]
            if self.config.schedule=='batch' and remaining:
                jobs=[(('scan',i),self.points[i]) for i in sorted(remaining)]
            elif self.config.schedule=='immediate' and pending:
                jobs=[(('source',ch),g.circle(self.sources[ch].poly)[0]) for ch in pending]
            else:
                jobs=[(('scan',i),self.points[i]) for i in sorted(remaining)]
                jobs += [(('source',ch),self.sources[ch].near or g.circle(self.sources[ch].poly)[0]) for ch in pending]
            if not jobs: break
            kind,i=g.route(self.pos,jobs)[0]
            if kind=='scan': self.scan(i);remaining.remove(i)
            else: self.finish(i)
        return self.complete()

    def complete(self):
        for ch,s in self.sources.items():
            if s.cleared: continue
            if s.bearings or s.near is not None: raise RuntimeError('unresolved observed source')
            if len(self.known())==16: self.excluded[ch]='public_count_upper_bound'
            elif s.negative_points==set(range(25)): self.excluded[ch]='triangulated_visibility_cover'
            else: raise RuntimeError('incomplete absence certificate')
        return self.diagnostics


def run(api,seed=0):
    return Controller(api).run()

"""Truth-free Q3 prototypes: multi-view coverage and certified center homing."""
from dataclasses import dataclass, field
import math
from . import geometry as geo


@dataclass(frozen=True)
class Config:
    name: str = 'D_MULTIVIEW'
    ring: float = 1150.0
    multiview: bool = True
    interleave: bool = False
    detour_m: float = 500.0
    localizer: str = 'center'
    joint: bool = False
    local_views: bool = False


VARIANTS = {
    'D_BATCH': Config('D_BATCH', 1400., False),
    'D_SHORT': Config('D_SHORT', 1150., False),
    'D_MULTIVIEW': Config(),
    'D_INTERLEAVE': Config('D_INTERLEAVE', 1150., True, True),
    'D_PURSUIT': Config('D_PURSUIT', 1150., False, False, 500., 'pursuit'),
    'D_INSERT1000': Config('D_INSERT1000', 1150., True, True, 1000.),
    'D_INSERT2000': Config('D_INSERT2000', 1150., True, True, 2000.),
    'D_JOINT': Config('D_JOINT', joint=True),
    'D_JOINT_VIEWS': Config('D_JOINT_VIEWS', joint=True,local_views=True),
}
BEST_VARIANT = 'D_JOINT_VIEWS'


@dataclass
class Source:
    poly: list = field(default_factory=geo.initial_region)
    bearings: list = field(default_factory=list)
    near: tuple = None
    cleared: bool = False
    coverage: set = field(default_factory=set)


class Controller:
    def __init__(self, api, config=None):
        self.api, self.config = api, config or VARIANTS[BEST_VARIANT]
        self.sources = {ch:Source() for ch in range(1,21)}
        self.pos, self.channel, self.time = (0.,0.), 1, 0.
        self.events = []
        self.action_context = {}
        self.diagnostics = dict(center_steps=0, emergency=0, max_center_steps=0)
        self.points = [(0.,0.)]+[(self.config.ring*math.cos(k*math.pi/3),
                                 self.config.ring*math.sin(k*math.pi/3)) for k in range(6)]
        if not 1130 <= self.config.ring <= 1700:
            raise ValueError('ring outside certified cover range')
        # Max distance for the annulus [1000,1800], angular separation <=30deg.
        if max(math.sqrt(r*r+self.config.ring**2-2*r*self.config.ring*math.cos(math.pi/6))
               for r in (1000.,1800.)) >= 1000.-1e-4:
            raise ValueError('coverage certificate failed')

    def measure(self, p, ch, reason, point_id=None):
        p = tuple(p)
        source = self.sources[ch]
        if any(math.dist(p, old[0]) < 1e-8 for old in source.bearings):
            raise RuntimeError('duplicate same-source bearing point')
        self.action_context=dict(variant=self.config.name,reason=reason,channel=ch)
        response = self.api.measure(p, ch)
        if response.get('accepted') is not True:
            raise RuntimeError('measure rejected')
        cost = math.dist(self.pos,p)/5+5+(self.channel != ch)
        reported=response.get('virtual_time_s')
        if isinstance(reported,bool) or not isinstance(reported,(int,float)) or not math.isfinite(reported):
            raise RuntimeError('invalid measure time')
        if abs(float(reported)-self.time-cost)>1e-5:
            raise RuntimeError('measure timing conflict')
        self.pos, self.channel, self.time = p, ch, float(response['virtual_time_s'])
        kind = response.get('measure_result')
        if kind == 'direction':
            b = float(response['svd_deg'])
            if not math.isfinite(b) or not 0 <= b < 360:
                raise RuntimeError('invalid bearing')
            source.poly = geo.observe(source.poly,p,b)
            source.bearings.append((p,b))
        elif kind == 'near':
            source.near = p
        elif kind != 'no_signal':
            raise RuntimeError('invalid measure response')
        if point_id is not None:
            source.coverage.add(point_id)
        self.events.append(dict(action='measure', position=p, channel=ch, reason=reason,
                                response=response, polygon=source.poly if source.bearings else None))
        return kind

    def clear(self,ch):
        s = self.sources[ch]
        if s.cleared:
            raise RuntimeError('already cleared')
        if s.near is not None:
            p, r, certificate = s.near, 5., 'near'
        else:
            p, r = geo.circle(s.poly)
            if not s.bearings or r > 20.-1e-4:
                return False
            certificate = 'physical_outer_polygon'
        self.action_context=dict(variant=self.config.name,reason=certificate,channel=ch)
        response = self.api.clear(p,ch)
        if response.get('accepted') is not True or response.get('clear_result') != 'success':
            raise RuntimeError('certified clear contradicted')
        cost = math.dist(self.pos,p)/5+5
        reported=response.get('virtual_time_s')
        if isinstance(reported,bool) or not isinstance(reported,(int,float)) or not math.isfinite(reported):
            raise RuntimeError('invalid clear time')
        if abs(float(reported)-self.time-cost)>1e-5:
            raise RuntimeError('clear timing conflict')
        self.pos, self.time, s.cleared = p, float(response['virtual_time_s']), True
        self.events.append(dict(action='clear', position=p, channel=ch, reason=certificate,
                                radius=r, polygon=s.poly, response=response))
        return True

    def finish_source(self,ch):
        s = self.sources[ch]
        step, stride = 0, 500.
        while not self.clear(ch):
            if step >= 16:
                self.diagnostics['emergency'] += 1
                raise RuntimeError('homing failed finite contraction bound')
            c,r = geo.circle(s.poly)
            if r >= 1000:
                raise RuntimeError('homing lost guaranteed reception')
            if self.config.localizer == 'pursuit' and step < 8:
                p,b = s.bearings[-1]
                if len(s.bearings)>1:
                    old = s.bearings[-2][1]
                    if abs((b-old+180)%360-180)>90:
                        stride /= 2
                angle = math.radians(b)
                candidate = (p[0]+stride*math.cos(angle), p[1]+stride*math.sin(angle))
                # Revert to the center if a proposed pursuit step can lose signal.
                if max(math.dist(candidate,v) for v in s.poly) < 1000-1e-4:
                    c = candidate
            kind = self.measure(c,ch,'homing_'+self.config.localizer)
            step += 1
            self.diagnostics['center_steps'] += 1
            if kind == 'no_signal':
                raise RuntimeError('certified reception contradicted')
        self.diagnostics['max_center_steps'] = max(self.diagnostics['max_center_steps'],step)
        if self.config.local_views:
            self.local_views()

    def local_views(self):
        p=self.pos
        for ch,s in self.sources.items():
            if not s.bearings or s.cleared or s.near is not None:
                continue
            c,r=geo.circle(s.poly)
            if r <= 20.-1e-4 or math.dist(c,p)+r>1000.-1e-4:
                continue
            if any(math.dist(p,old[0])<25 for old in s.bearings):
                continue
            self.measure(p,ch,'local_multiview')

    def route(self, jobs):
        """Deterministic open nearest-neighbor + 2-opt, heuristic only."""
        pending=list(range(len(jobs)))
        order=[]
        p=self.pos
        while pending:
            j=min(pending,key=lambda j:(math.dist(p,jobs[j][1]),j))
            pending.remove(j)
            order.append(j)
            p=jobs[j][1]
        for _ in range(12):
            best=0.
            change=None
            for i in range(len(order)-1):
                a=self.pos if i==0 else jobs[order[i-1]][1]
                b=jobs[order[i]][1]
                for j in range(i+1,len(order)):
                    c=jobs[order[j]][1]
                    delta=math.dist(a,c)-math.dist(a,b)
                    if j+1<len(order):
                        d=jobs[order[j+1]][1]
                        delta+=math.dist(b,d)-math.dist(c,d)
                    if delta<best-1e-6:
                        best,change=delta,(i,j)
            if change is None:
                break
            i,j=change
            order[i:j+1]=reversed(order[i:j+1])
        return [jobs[i][0] for i in order]

    def run_joint(self):
        self.scan(0)
        remaining=set(range(1,7))
        while True:
            jobs=[(('scan',i),self.points[i]) for i in sorted(remaining)]
            jobs += [(('source',ch),geo.circle(s.poly)[0]) for ch,s in self.sources.items()
                     if s.bearings and not s.cleared]
            if not jobs:
                break
            kind,j=self.route(jobs)[0]
            if kind=='scan':
                self.scan(j)
                remaining.remove(j)
            else:
                self.finish_source(j)

    def scan(self, i):
        p = self.points[i]
        for ch,s in self.sources.items():
            if s.cleared:
                continue
            if s.bearings:
                if not self.config.multiview:
                    continue
                # A failed opportunistic observation is legal and retains history.
                c,r = geo.circle(s.poly)
                if math.dist(p,c)-r > 1500:
                    continue
            self.measure(p,ch,'coverage_multiview' if s.bearings else 'coverage',i)
            if s.near is not None:
                self.clear(ch)

    def run(self):
        if self.config.joint:
            self.run_joint()
            return self.complete()
        for i in range(7):
            self.scan(i)
            if self.config.interleave:
                next_p = self.points[i+1] if i<6 else None
                while True:
                    candidates=[]
                    for ch,s in self.sources.items():
                        if not s.bearings or s.cleared:
                            continue
                        c,r=geo.circle(s.poly)
                        detour = math.dist(self.pos,c)
                        if next_p is not None:
                            detour += math.dist(c,next_p)-math.dist(self.pos,next_p)
                        if detour <= self.config.detour_m or next_p is None:
                            candidates.append((detour,ch))
                    if not candidates:
                        break
                    self.finish_source(min(candidates)[1])
        while True:
            pending = [(math.dist(self.pos,geo.circle(s.poly)[0]),ch)
                       for ch,s in self.sources.items() if s.bearings and not s.cleared]
            if not pending:
                break
            self.finish_source(min(pending)[1])
        return self.complete()

    def complete(self):
        if any(not s.cleared and (s.bearings or s.near is not None or s.coverage != set(range(7)))
               for s in self.sources.values()):
            raise RuntimeError('incomplete source or exclusion certificate')
        return self.diagnostics


def run(api, seed=0):
    return Controller(api).run()

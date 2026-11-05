"""Meaningful Q4 contract, continuous construction and adversarial checks."""
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from q4 import geometry as g
from q4.controller import Controller,VARIANTS
from q4.simulator import Q4Simulator
from experiments.run_q4 import PublicAPI

ROOT=Path(__file__).resolve().parent


def fixture(x=1000.,y=0.,orientation=0.):
    return dict(error_seed=81713,sources=[dict(channel=i,x=x,y=y,radius=1000.,
         type='directional',orientation=orientation) for i in range(1,11)])


class Q4Tests(unittest.TestCase):
    def test_visibility_and_optical_independence(self):
        s=Q4Simulator(fixture());s.enter()
        self.assertEqual(s.measure((999,0),1)['measure_result'],'no_signal')
        self.assertEqual(s.measure((1000,1000),1)['measure_result'],'direction')
        self.assertEqual(s.measure((1005,0),1)['measure_result'],'near')
        s.measure((1500,0),2)
        self.assertEqual(s.clear((980,0),1)['clear_result'],'success')
        self.assertEqual(s.channel,2)

    def test_outer_mesh_all_orientations_analytic(self):
        points,triangles=g.cover()
        self.assertEqual(len(points),25)
        self.assertEqual(len(triangles),36)
        # Barycentric identity certifies n dot (P-G) cannot be negative
        # for every vertex, for ANY n. These samples check implementation.
        rng=random.Random(90202)
        for tri in triangles:
            for _ in range(20):
                w=[rng.random() for _ in tri];sw=sum(w)
                target=tuple(sum(wi*points[j][d] for wi,j in zip(w,tri))/sw for d in (0,1))
                for k in range(24):
                    n=(math.cos(k*math.pi/12),math.sin(k*math.pi/12))
                    self.assertTrue(any((points[j][0]-target[0])*n[0]+(points[j][1]-target[1])*n[1]>=-1e-8
                                        and math.dist(points[j],target)<1000 for j in tri))
        for k in range(360):
            target=(1800*math.cos(k*math.pi/180),1800*math.sin(k*math.pi/180))
            self.assertTrue(any(g.contains([points[i] for i in tri],target) for tri in triangles))

    def test_fork_range_and_halfplane_disjunction(self):
        rng=random.Random(715811)
        alpha=math.radians(1.005)
        for _ in range(500):
            t=rng.uniform(5,1490);x=rng.uniform(t,1500)
            y=x*math.tan(rng.uniform(-alpha,alpha))
            w=t*math.tan(alpha)+1e-4
            qs=[(t,-w),(t,w)]
            for q in qs: self.assertLessEqual(math.dist(q,(x,y)),math.hypot(x,y)+1e-8)
            # Normals on and within the halfplane that receives at the anchor.
            b=math.atan2(-y,-x)
            for a in (b-math.pi/2,b+math.pi/2,b+rng.uniform(-math.pi/2,math.pi/2)):
                self.assertGreaterEqual(max((q[0]-x)*math.cos(a)+(q[1]-y)*math.sin(a) for q in qs),-1e-8)

    def test_fork_negative_cut_keeps_truth(self):
        sim=Q4Simulator(fixture(300,0,180));sim.enter()
        c=Controller(PublicAPI(sim))
        c.measure((0.,0.),1,'test')
        c.fork_step(1)
        self.assertEqual(c.diagnostics['fork_negative_cuts'],1)
        self.assertTrue(g.contains(c.sources[1].poly,(300,0)))
        self.assertLess(max(p[0] for p in c.sources[1].poly),800)

    def test_thin_far_slice_does_not_stall(self):
        poly=g.observe(g.initial_region(),(0.,0.),0.)
        poly=g.clip(poly,-1,0,-1400)
        poly=g.clip(poly,1,0,1400.1)
        points,w=g.fork(poly,(0.,0.),0.)
        self.assertLess(w['t'],1400)
        self.assertTrue(any(p[0]<1400 for p in points))

    def test_uncertified_clear_never_calls_api(self):
        class API:
            def clear(self,*args): raise AssertionError('uncertified clear')
        self.assertFalse(Controller(API()).clear(1))

    def test_no_signal_alone_cannot_exclude(self):
        class API:
            def measure(self,p,ch): return dict(accepted=True,measure_result='no_signal',virtual_time_s=5.)
        c=Controller(API());c.measure((0.,0.),1,'search',0)
        with self.assertRaises(RuntimeError): c.complete()
        self.assertEqual(c.sources[1].poly,g.initial_region())

    def test_fixed_errors_do_not_get_averaged(self):
        sim=Q4Simulator(fixture(500,0,180));sim.enter()
        c=Controller(PublicAPI(sim));c.measure((0.,0.),1,'test')
        poly=c.sources[1].poly
        c.measure((0.,0.),1,'test')
        self.assertEqual(len(c.sources[1].bearings),1)
        self.assertEqual(c.sources[1].poly,poly)

    def test_malformed_rejected_contract(self):
        for resp in (dict(accepted=False),dict(accepted=True,measure_result='near',virtual_time_s=True),
                     dict(accepted=True,measure_result='direction',svd_deg=True,virtual_time_s=5.)):
            class API:
                def measure(self,*args): return resp
                def clear(self,*args): raise AssertionError('bad response clear')
            with self.assertRaises(RuntimeError): Controller(API()).measure((0.,0.),1,'test')

    def test_independent_replay_on_boundary_outward(self):
        from decimal import localcontext
        from experiments.audit_q4 import replay
        case=fixture(1800,0,0);case['error_mode']='positive'
        sim=Q4Simulator(case);sim.enter();c=Controller(PublicAPI(sim));c.run();sim.exit()
        self.assertEqual(sim.report()['cleared'],10)
        self.assertEqual(sim.counts['clear_fail'],0)
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/'api.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in sim.log))
            (folder/'decisions.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in c.events))
            with localcontext() as ctx:
                ctx.prec=50
                self.assertEqual(replay(folder)['clears'],10)

    def test_finite_progress_extreme_error_fields(self):
        for mode in ('positive','negative','checker','smooth'):
            case=fixture(0,0,90);case['error_mode']=mode
            sim=Q4Simulator(case);sim.enter();c=Controller(PublicAPI(sim));c.run();sim.exit()
            self.assertEqual(sim.report()['cleared'],10)
            self.assertEqual(c.diagnostics['emergency'],0)


if __name__=='__main__': unittest.main()

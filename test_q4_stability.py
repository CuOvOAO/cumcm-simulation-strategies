"""Coverage corruption, contraction, public-only execution and offline runner checks."""
import contextlib
from decimal import localcontext
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from q4 import geometry as g
from q4.simulator import Q4Simulator
from q4_stable.controller import Controller,Config
from q4_stable.coverage import verify_certificate,certified_points
from experiments.run_q4 import PublicAPI
from experiments.audit_q4_stability import replay
from test_q4 import fixture

ROOT=Path(__file__).resolve().parent


class StabilityTests(unittest.TestCase):
    def test_exact_coverage_certificate(self):
        cert=json.loads((ROOT/'q4_stable/cover_8.json').read_text())
        result=verify_certificate(cert)
        self.assertEqual(result['leaves'],9556)
        self.assertEqual(result['arithmetic'],'exact integer')
        self.assertEqual(len(certified_points()),21)

    def test_missing_coverage_leaf_rejected(self):
        cert=json.loads((ROOT/'q4_stable/cover_8.json').read_text())
        del cert['leaves'][max(cert['leaves'],key=len)]
        with self.assertRaises(AssertionError):verify_certificate(cert)

    def test_corrupt_coverage_witness_rejected(self):
        cert=json.loads((ROOT/'q4_stable/cover_8.json').read_text())
        key=next(k for k,v in cert['leaves'].items() if v is not None)
        cert['leaves'][key]=[0,0,0]
        with self.assertRaises(AssertionError):verify_certificate(cert)

    def test_forced_kernel_endpoints_and_error_fields(self):
        for mode in ('positive','negative','checker','smooth','hash'):
            for distance in (20.001,63.,300.,750.,1400.,1499.):
                case=fixture(distance,0,180)
                for s in case['sources']:s['radius']=1500.
                case['error_mode']=mode
                sim=Q4Simulator(case);sim.enter()
                c=Controller(PublicAPI(sim),Config('KERNEL_TEST',normal_rounds=0))
                self.assertEqual(c.measure((0.,0.),1,'test'),'direction')
                c.finish(1)
                self.assertIn(1,sim.cleared)
                self.assertLessEqual(c.diagnostics['kernel_rounds'],8)
                self.assertLessEqual(c.diagnostics['max_kernel_ratio'],.5101)
                self.assertEqual(c.diagnostics['emergency'],0)
                for event in c.events:
                    if event.get('polygon'):self.assertTrue(g.contains(event['polygon'],(distance,0)))

    def test_forced_kernel_on_thin_far_slice(self):
        sim=Q4Simulator(fixture(1400.,0.,180.));sim.sources[1]['radius']=1500.;sim.enter()
        c=Controller(PublicAPI(sim),Config('KERNEL_TEST',normal_rounds=0))
        c.measure((0.,0.),1,'test')
        c.sources[1].poly=g.clip(c.sources[1].poly,-1,0,-1399.9)
        c.sources[1].poly=g.clip(c.sources[1].poly,1,0,1400.1)
        c.finish(1)
        self.assertIn(1,sim.cleared)
        self.assertLessEqual(c.diagnostics['kernel_rounds'],8)

    def test_repeated_positive_becomes_current_anchor_without_averaging(self):
        sim=Q4Simulator(fixture(500,0,180));sim.enter();c=Controller(PublicAPI(sim))
        for p in ((0.,0.),(100.,1.),(0.,0.)):c.measure(p,1,'test')
        self.assertEqual(len(c.sources[1].bearings),2)
        self.assertEqual(c.sources[1].bearings[-1][0],(0.,0.))

    def test_distinct_nearby_points_may_have_distinct_fixed_errors(self):
        class DiscontinuousError(Q4Simulator):
            def _error(self,ch):return -1. if self.pos[0]==0 else 1.
        sim=DiscontinuousError(fixture(500,0,180));sim.enter();c=Controller(PublicAPI(sim))
        c.measure((0.,0.),1,'test');c.measure((1e-9,0.),1,'test')
        self.assertEqual(len(c.sources[1].bearings),2)
        self.assertTrue(g.contains(c.sources[1].poly,(500.,0.)))

    def test_small_anchor_ball_works_if_circle_candidate_is_poor(self):
        sim=Q4Simulator(fixture(100.,0.,180));sim.enter();c=Controller(PublicAPI(sim))
        c.measure((90.,0.),1,'test')
        c.sources[1].poly=[(99.,-1.),(101.,-1.),(101.,1.),(99.,1.)]
        with patch('q4_stable.controller.g.circle',return_value=((1e6,1e6),2e6)):
            self.assertTrue(c.clear(1))
        self.assertEqual(sim.counts['clear_fail'],0)

    def test_ten_observed_does_not_exclude_other_channels(self):
        c=Controller(Mock())
        for ch in range(1,11):c.sources[ch].cleared=True
        with self.assertRaises(RuntimeError):c.complete()

    def test_only_twenty_cover_points_cannot_certify_absence(self):
        c=Controller(Mock())
        for s in c.sources.values():s.negative_points=set(range(20))
        with self.assertRaises(RuntimeError):c.complete()

    def test_public_upper_bound_does_certify_absence(self):
        c=Controller(Mock())
        for ch in range(1,17):c.sources[ch].cleared=True
        c.complete()
        self.assertEqual(set(c.excluded),{17,18,19,20})

    def test_boundary_mission_independent_replay(self):
        case=fixture(1800,0,0);case['error_mode']='negative'
        sim=Q4Simulator(case);sim.enter();c=Controller(PublicAPI(sim));c.run();sim.exit()
        self.assertEqual(len(sim.cleared),10)
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/'api.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in sim.log))
            (folder/'decisions.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in c.events))
            with localcontext() as ctx:
                ctx.prec=50
                self.assertEqual(replay(folder)['clears'],10)


class StableRunnerTests(unittest.TestCase):
    def test_no_implicit_network(self):
        from run_q4_stability_official import main
        factory=Mock(side_effect=AssertionError('network'))
        with patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([],factory),2)
        factory.assert_not_called()

    def test_stale_freeze_blocks_before_network(self):
        from run_q4_stability_official import main
        factory=Mock(side_effect=AssertionError('network'))
        with patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),patch('run_q4_stability_official.hashes',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--exercise'],factory),2)
        factory.assert_not_called()

    def test_full_offline_adapter_mission(self):
        from run_q4_stability_official import main
        class Adapter:
            def __init__(self,**kwargs):self.sim=Q4Simulator(fixture(1800,0,0))
            def enter(self):return dict(self.sim.enter(),remaining_real_duration_s=1200.)
            def measure(self,*a):return self.sim.measure(*a)
            def clear(self,*a):return self.sim.clear(*a)
            def exit(self):return self.sim.exit()
            def set_action_context_provider(self,p):pass
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--exercise','--output-root',folder],Adapter),0)
            result=json.loads(next(Path(folder).glob('*/summary.json')).read_text())
            self.assertEqual(result['cleared'],10)
            self.assertTrue(result['normal_exit'])
            self.assertIsNone(result['total_source_truth'])

    def test_unknown_action_outcome_stops_without_exit(self):
        from run_q4_stability_official import main
        exited=[]
        class Adapter:
            def __init__(self,**kwargs):pass
            def enter(self):return dict(remaining_real_duration_s=1200.)
            def measure(self,*a):raise RuntimeError('uncertain transport')
            def exit(self):exited.append(True)
            def set_action_context_provider(self,p):pass
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--exercise','--output-root',folder],Adapter),1)
        self.assertFalse(exited)


if __name__=='__main__':unittest.main()

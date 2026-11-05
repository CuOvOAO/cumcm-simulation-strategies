"""Offline mocks only: never contact the official server."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from run_q4_official import main,DeadlineAPI
from q4.simulator import Q4Simulator
from test_q4 import fixture


class OfficialQ4Tests(unittest.TestCase):
    def test_no_network_without_explicit_launch(self):
        factory=Mock(side_effect=AssertionError('network'))
        with patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([],factory),2)
        factory.assert_not_called()

    def test_missing_identifier_no_network(self):
        factory=Mock(side_effect=AssertionError('network'))
        with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--exercise'],factory),2)
        factory.assert_not_called()

    def test_public_deadline_stops_before_action(self):
        adapter=Mock();api=DeadlineAPI(adapter,11,5)
        with self.assertRaises(RuntimeError): api.measure((0,0),1)
        adapter.measure.assert_not_called()

    def test_both_launch_flags_run_frozen_stable_candidate(self):
        class Adapter:
            def __init__(self,**kwargs): self.sim=Q4Simulator(fixture(1800,0,0))
            def enter(self): return dict(self.sim.enter(),remaining_real_duration_s=1200.)
            def measure(self,*a): return self.sim.measure(*a)
            def clear(self,*a): return self.sim.clear(*a)
            def exit(self): return self.sim.exit()
            def set_action_context_provider(self,p): pass
        traces=[]
        for flag in ('--exercise','--run'):
            with self.subTest(flag=flag),tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([flag,'--output-root',folder],Adapter),0)
                summary=json.loads(next(Path(folder).glob('*/summary.json')).read_text())
                self.assertEqual(summary['variant'],'Q4_STABLE15')
                self.assertEqual(summary['cleared'],10)
                self.assertTrue(summary['normal_exit'])
                self.assertIsNone(summary['source_clear_rate'])
                traces.append(next(Path(folder).glob('*/certificates.jsonl')).read_bytes())
        self.assertEqual(traces[0],traces[1])

    def test_canonical_entry_keeps_frozen_hash_guard(self):
        factory=Mock(side_effect=AssertionError('network'))
        with patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),patch('run_q4_stability_official.hashes',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--run'],factory),2)
        factory.assert_not_called()

    def test_unknown_transport_outcome_does_not_exit(self):
        exits=[]
        class Adapter:
            def __init__(self,**kwargs): pass
            def enter(self): return dict(remaining_real_duration_s=1200.)
            def measure(self,*a): raise RuntimeError('unknown outcome')
            def set_action_context_provider(self,p): pass
            def exit(self): exits.append(True)
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'CUMCM_ROBOT_ID':'TEST_ONLY'}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--exercise','--output-root',folder],Adapter),1)
        self.assertEqual(exits,[])


if __name__=='__main__': unittest.main()

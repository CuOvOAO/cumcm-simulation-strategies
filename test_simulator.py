import unittest
from simulator import Simulator

def case():
    return dict(error_seed=42, sources=[dict(channel=i,x=1000.0,y=0.0,radius=1000.0) for i in range(1,11)])
class Rules(unittest.TestCase):
    def setUp(self):
        self.s=Simulator(case());self.s.enter()
    def test_boundaries(self):
        self.assertEqual(self.s.measure((0,0),1)['measure_result'],'direction')
        self.assertEqual(self.s.measure((-0.001,0),1)['measure_result'],'no_signal')
        self.assertEqual(self.s.measure((995,0),1)['measure_result'],'near')
        self.assertEqual(self.s.measure((994.999,0),1)['measure_result'],'direction')
        self.assertEqual(self.s.clear((979.999,0),1)['clear_result'],'no_target_in_range')
        self.assertEqual(self.s.clear((980,0),1)['clear_result'],'success')
        self.assertEqual(self.s.clear((980,0),1)['clear_result'],'no_target_in_range')
        self.assertEqual(self.s.measure((980,0),1)['measure_result'],'no_signal')
    def test_timing(self):
        self.s.measure((300,400),1);self.s.measure((300,400),2)
        self.s.clear((300,0),3);self.s.measure((300,0),2)
        self.assertEqual(self.s.virtual,199);self.assertEqual(self.s.channel,2)
    def test_fixed_error(self):
        a=self.s.measure((0,0),1)['svd_deg'];self.s.measure((100,100),2)
        self.assertEqual(a,self.s.measure((0,0),1)['svd_deg'])
        s=Simulator(case());s.enter()
        self.assertEqual(a,s.measure((0,0),1)['svd_deg'])
    def test_invalid_atomic(self):
        with self.assertRaises(ValueError):self.s.measure((float('nan'),0),1)
        with self.assertRaises(ValueError):self.s.measure((100,0),21)
        self.assertEqual(self.s.virtual,0)
    def test_decomposition(self):
        self.s.measure((995,0),2);self.s.clear((995,0),2);self.s.clear((995,0),2)
        self.s.exit();r=self.s.report()
        self.assertAlmostEqual(r['virtual_time_s'],r['distance_m']/5+r['switch']+5*r['measure']+5*r['clear_success']+3*r['clear_fail'])
    def test_stop(self):
        self.s.exit()
        with self.assertRaises(RuntimeError):self.s.measure((0,0),1)
if __name__=='__main__':unittest.main()

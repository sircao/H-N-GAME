"""Regression, physics, independent-oracle and corruption-detection tests."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import run_experiments as model
import verify_results as independent


class PhysicsTests(unittest.TestCase):
    def test_invalid_inputs(self):
        for changes in ({'eta':0}, {'eta':1.1}, {'capacity':-1}, {'initial':41},
                        {'terminal':-1}, {'n':0}, {'n':2.5}, {'window':7},
                        {'paths':0}, {'seed':-1}, {'power':float('nan')},
                        {'deadline_hour':5}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                model.Case(**changes)

    def test_bad_prices(self):
        for prices in ([1]*5, [1]*7, [1,1,1,1,1,float('nan')], [-1]*6):
            with self.subTest(prices=prices), self.assertRaises(ValueError):
                model.solve(model.Case(), True, True, prices)

    def test_no_gain_control(self):
        c = model.Case(n=2, flat=True, paths=1, flexible=False)
        metrics = [model.solve(c,r,q)[0] for r,q in model.ARMS]
        self.assertTrue(all(m['status']=='optimal' for m in metrics))
        for m in metrics[1:]:
            self.assertAlmostEqual(m['objective_cny'],metrics[0]['objective_cny'])
            self.assertAlmostEqual(m['carbon_kg'],metrics[0]['carbon_kg'])

    def test_pure_time_shift_preserves_carbon_and_energy(self):
        c = model.Case()
        b = model.solve(c,False,False)[0]
        t = model.solve(c,False,True)[0]
        self.assertLess(t['bill_cny'],b['bill_cny'])
        self.assertAlmostEqual(t['grid_kwh'],b['grid_kwh'])
        self.assertAlmostEqual(t['carbon_kg'],b['carbon_kg'])

    def test_terminal_energy_not_counted_as_saving(self):
        c = model.Case(n=2)
        b = model.solve(c,False,True)[0]
        t = model.solve(replace(c,terminal=21),False,True)[0]
        self.assertAlmostEqual(t['grid_kwh']-b['grid_kwh'],c.n/c.eta)
        self.assertAlmostEqual(t['energy_residual_kwh'],0)

    def test_zero_charge_feasible(self):
        c = model.Case(n=2,terminal=17,capacity=0,power=0)
        energy,starts,wholesale,retail = model.inputs(c)
        with patch.object(model,'inputs',return_value=(np.array([3.,3.]),starts,wholesale,retail)):
            m,_ = model.solve(c,False,True)
        self.assertEqual(m['status'],'optimal')
        self.assertEqual(m['grid_kwh'],0)
        self.assertEqual(m['carbon_kg'],0)

    def test_infeasible_battery_and_site(self):
        for changes in ({'capacity':0},{'power':0},{'initial':39.9,'terminal':39.9},
                        {'departure_hour':0}):
            with self.subTest(changes=changes):
                m,d = model.solve(model.Case(n=2,**changes),True,True)
                self.assertEqual(m['status'],'infeasible')
                self.assertIsNone(d)

    def test_solver_limit_is_not_infeasibility(self):
        with patch.object(model,'milp',return_value=SimpleNamespace(status=1,message='time limit')):
            m,d = model.solve(model.Case(n=2),True,True)
        self.assertEqual(m['status'],'solver_limit')
        self.assertIsNone(d)

    def test_milp_against_independent_oracle(self):
        count=0
        for seed in [17,29,43]:
            for changes in ({},{'capacity':4},{'congestion':.8},
                            {'flat':True},{'paths':3},{'window':1}):
                c = model.Case(n=3,seed=seed,**changes)
                energy,starts,wholesale,retail=model.inputs(c)
                for route,charge in model.ARMS:
                    with self.subTest(seed=seed,changes=changes,route=route,charge=charge):
                        spec=dict(config=model.asdict(c),energy_kwh=energy.tolist(),start_slots=starts.tolist(),
                                  prices=retail.tolist(),route_enabled=route,charge_enabled=charge)
                        options=independent.independent_options(spec)
                        optimum=independent.tiny_optimum(spec,options)
                        m,_=model.solve(c,route,charge)
                        if np.isinf(optimum):
                            self.assertEqual(m['status'],'infeasible')
                        else:
                            self.assertEqual(m['status'],'optimal')
                            self.assertAlmostEqual(m['objective_cny'],optimum,places=6)
                        count+=1
        self.assertEqual(count,72)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='hgame_validation_')
        cls.root=Path(cls.temp.name)
        cls.first=cls.root/'first'
        cls.second=cls.root/'second'
        with contextlib.redirect_stdout(io.StringIO()):
            model.run(cls.first)
            model.run(cls.second)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_exports_and_infeasibility(self):
        result=independent.audit(self.first)
        self.assertTrue(result['passed'])
        self.assertEqual(result['runs'],387)
        self.assertEqual(result['independent_tiny_checks'],18)
        self.assertGreater(result['independent_infeasibility_checks'],0)

    def test_identical_inputs_reproduce_outputs(self):
        first=json.loads((self.first/'manifest.json').read_text())
        second=json.loads((self.second/'manifest.json').read_text())
        self.assertEqual(first,second)
        for name in first['output_sha256']:
            self.assertEqual((self.first/name).read_bytes(),(self.second/name).read_bytes(),name)

    def test_distinct_seeds_preserved(self):
        manifest=json.loads((self.first/'manifest.json').read_text())
        runs=[r for r in manifest['runs'] if r['experiment']=='E5' and r['config']['name']=='reference']
        self.assertEqual(len(runs),40)
        self.assertEqual({r['config']['seed'] for r in runs},set(model.SEEDS))
        energies={tuple(r['energy_kwh']) for r in runs}
        self.assertEqual(len(energies),10)

    def test_tampered_load_detected_by_physics(self):
        path=self.second/'plans_and_prices.json'
        original=path.read_bytes()
        try:
            data=json.loads(original)
            data[0]['load'][0]+=1
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'load'):
                independent.audit(self.second,check_hashes=False)
        finally:
            path.write_bytes(original)

    def test_tampered_economics_detected(self):
        path=self.second/'metrics.csv'
        original=path.read_bytes()
        try:
            with path.open(encoding='utf-8-sig',newline='') as f:
                rows=list(csv.DictReader(f))
            rows[0]['profit_cny']=float(rows[0]['profit_cny'])+1
            model.write_csv(path,rows)
            with self.assertRaisesRegex(ValueError,'profit_cny'):
                independent.audit(self.second,check_hashes=False)
        finally:
            path.write_bytes(original)

    def test_missing_output_detected_by_hash(self):
        path=self.second/'paired_effects.csv'
        original=path.read_bytes()
        try:
            path.write_bytes(original+b'corrupt')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):
                independent.audit(self.second)
        finally:
            path.write_bytes(original)


if __name__=='__main__':
    unittest.main(verbosity=2)

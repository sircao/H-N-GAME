import unittest
from dataclasses import replace
from copy import deepcopy
import numpy as np
from physical_model import Task, Route, solve, task_dict
from audit_revised import check_run, independent_reference


class RevisedTests(unittest.TestCase):
    def setUp(self):
        self.t=[Task(str(i),str(i),'S',5,5,15,0,3,3,4,5,.9,
                     (Route('fast',.2,2),Route('slow',.5,1))) for i in range(2)]
        self.st={'S':dict(power_kw=6.,connectors=1)}
        self.retail=[1.,.5,.8,1.];self.wholesale=[.7,.2,.5,.7]

    def run_case(self,tasks=None,stations=None,**kw):
        tasks=self.t if tasks is None else tasks;stations=self.st if stations is None else stations
        m,p=solve(tasks,stations,self.retail,self.wholesale,**kw)
        run=dict(tasks=[task_dict(t) for t in tasks],stations=stations,retail=self.retail,
                 wholesale=self.wholesale,dt=kw.get('dt',1.),beta=kw.get('beta',34.),gamma=.5703,
                 tau=kw.get('tau',40.),route_enabled=True,charge_enabled=True,metrics=m,plan=p)
        if m['status']=='optimal':check_run(run)
        return run

    def test_independent_reference(self):
        for n in (1,2,3):
            ts=[replace(self.t[0],task_id=str(i),vehicle_id=str(i)) for i in range(n)]
            run=self.run_case(tasks=ts)
            self.assertAlmostEqual(run['metrics']['objective_cny'],independent_reference(run),places=6)

    def test_connectors_and_power(self):
        for st in ({'S':dict(power_kw=0.,connectors=1)},{'S':dict(power_kw=6.,connectors=0)}):
            self.assertEqual(self.run_case(stations=st)['metrics']['status'],'infeasible')
        run=self.run_case();self.assertNotEqual(run['plan'][0]['slot'],run['plan'][1]['slot'])

    def test_battery_and_window(self):
        for ts in ([replace(t,initial_kwh=14.9,terminal_kwh=14.9) for t in self.t],
                   [replace(t,parking_start=2.1) for t in self.t]):
            self.assertEqual(self.run_case(tasks=ts)['metrics']['status'],'infeasible')

    def test_zero_charge(self):
        run=self.run_case(tasks=[replace(t,terminal_kwh=2) for t in self.t])
        self.assertEqual(run['metrics']['grid_kwh'],0)

    def test_non_hourly_intervals(self):
        ts=[replace(t,parking_end=1.5,departure=1.5,deadline=2.) for t in self.t]
        run=self.run_case(tasks=ts,dt=.5)
        self.assertEqual(run['metrics']['status'],'optimal')

    def test_carbon_constant_does_not_shift_equal_energy(self):
        low=self.run_case(tasks=[replace(t,routes=t.routes[:1]) for t in self.t],tau=0)
        high=self.run_case(tasks=[replace(t,routes=t.routes[:1]) for t in self.t],tau=100)
        self.assertEqual(sorted(p['slot'] for p in low['plan']),sorted(p['slot'] for p in high['plan']))
        self.assertAlmostEqual(low['metrics']['carbon_kg'],high['metrics']['carbon_kg'])

    def test_corruption_detected(self):
        original=self.run_case()
        for key in ('profit_cny','carbon_kg','grid_kwh'):
            r=deepcopy(original);r['metrics'][key]+=1
            with self.assertRaises(ValueError):check_run(r)
        r=deepcopy(original);r['plan'][0]['final_kwh']-=1
        with self.assertRaises(ValueError):check_run(r)

    def test_invalid_contract(self):
        for change in ({'efficiency':0},{'battery_kwh':float('nan')},{'parking_end':4},{'max_power_kw':-1}):
            with self.assertRaises(ValueError):self.run_case(tasks=[replace(self.t[0],**change)])


if __name__=='__main__':unittest.main()

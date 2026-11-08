"""Independent small references, invariants, multi-leg and corruption controls."""
import copy
import itertools
import math
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scientific_model import optimize,greedy,metrics
from scientific_audit import check,compare_metrics
from build_scientific_scenario import waypoint_polyline
import numpy as np


def tiny():
    points=[[0.,0.,0.],[100000.,0.,0.],[0.,0.,0.]]
    vehicles=[]
    for vid in ['a','b']:
        trips=[]
        for leg,dep in enumerate([6.,18.]):
            routes=[dict(route_id=f'{vid}:{leg}:r0',time_h=.2,energy_kwh=2.,distance_km=2.,path_points=points),
                    dict(route_id=f'{vid}:{leg}:r1',time_h=.4,energy_kwh=1.,distance_km=2.,path_points=points)]
            trips.append(dict(task_id=f'{vid}:{leg}',leg=leg,departure=dep,deadline=dep+1,routes=routes))
        vehicles.append(dict(vehicle_id=vid,initial_kwh=5.,terminal_kwh=5.,battery_kwh=10.,reserve_kwh=0.,
                             efficiency=1.,power_kw=1.,initial_position=points[0],trips=trips,
                             windows=[dict(start=0.,end=6.,station_id='S'),dict(start=7.,end=18.,station_id='S'),dict(start=19.,end=24.,station_id='S')]))
    return dict(dt=6.,retail=[1.,1.,.2,1.],wholesale=[.7,.7,.1,.7],beta=2.,gamma=.5,tau=0.,
                stations={'S':dict(connectors=1,power_kw=1.,connector_power_kw=1.,position=points[0])},vehicles=vehicles)


def integer_reference(s):
    """Exact exhaustive oracle for these integer-energy transport cases.

    At each fixed route/connector configuration, inventory/transport constraints
    have integral RHS and unit efficiencies, so a continuous LP optimum has an
    integral extreme point. This oracle does not call the production solver.
    """
    options=[]
    for v in s['vehicles']:
        candidates=[]
        for routes in itertools.product(*[t['routes'] for t in v['trips']]):
            need=sum(r['energy_kwh'] for r in routes)+v['terminal_kwh']-v['initial_kwh']
            for q0 in range(7):
                q2=need-q0
                if q2<0 or q2>6 or v['initial_kwh']+q0>v['battery_kwh']:continue
                b=v['initial_kwh']+q0-routes[0]['energy_kwh']
                if b<v['reserve_kwh'] or b+q2>v['battery_kwh']:continue
                if b+q2-routes[1]['energy_kwh']<v['reserve_kwh']:continue
                cost=s['beta']*sum(r['time_h'] for r in routes)+q0*s['retail'][0]+q2*s['retail'][2]
                candidates.append((q0,q2,cost))
        options.append(candidates)
    best=math.inf
    for combination in itertools.product(*options):
        if any(sum(c[h]>0 for c in combination)>s['stations']['S']['connectors'] or
               sum(c[h] for c in combination)>s['stations']['S']['power_kw']*6 for h in [0,1]):continue
        best=min(best,sum(c[2] for c in combination))
    return best


class ScientificTests(unittest.TestCase):
    def test_exact_od_order_with_revisited_road_nodes(self):
        nodes=np.array([[0.,0.,0.],[5.,0.,0.],[10.,0.,0.]])
        origin=[0.,1.,0.];destination=[5.,1.,0.]
        points=waypoint_polyline(nodes,[2,1,0],[0,1],[1,0,2],origin,destination,[10.,2.,0.],[10.,3.,0.])
        self.assertLess(points.index(origin),points.index(destination))
        reverse=list(reversed(points))
        self.assertLess(reverse.index(destination),reverse.index(origin))

    def test_multi_trip_against_independent_enumeration(self):
        for connectors in [0,1,2]:
            for price in [.2,1.,2.]:
                s=tiny();s['stations']['S']['connectors']=connectors;s['retail'][2]=price
                status,events=optimize(s)
                expected=integer_reference(s)
                if math.isinf(expected):self.assertEqual(status['status'],'infeasible')
                else:
                    self.assertEqual(status['status'],'optimal')
                    self.assertAlmostEqual(metrics(s,events)['user_objective_cny'],expected,places=6)
                    a=check(s,events);compare_metrics(metrics(s,events),a['metrics'])

    def test_invariants_and_terminal_inventory(self):
        s=tiny();s['stations']['S']['connectors']=2
        for v in s['vehicles']:
            for t in v['trips']:t['routes']=t['routes'][:1]
        _,a=optimize(s);base=metrics(s,a)
        s['retail']=[1.]*4;s['tau']=90
        _,b=optimize(s);other=metrics(s,b)
        self.assertAlmostEqual(base['grid_kwh'],other['grid_kwh'])
        self.assertAlmostEqual(base['carbon_kg'],other['carbon_kg'])
        for v in s['vehicles']:v['terminal_kwh']+=1
        _,c=optimize(s);self.assertAlmostEqual(metrics(s,c)['grid_kwh']-other['grid_kwh'],2)

    def test_detect_inventory_and_route_corruption(self):
        s=tiny();_,events=optimize(s)
        for field in ['energy_kwh','end']:
            corrupt=copy.deepcopy(events);corrupt[0][field]+=1
            with self.assertRaises(ValueError):check(s,corrupt)
        with self.assertRaises(ValueError):check(s,events[1:])
        wrong=metrics(s,events);wrong['operator_profit_cny']+=1
        with self.assertRaises(ValueError):compare_metrics(wrong,check(s,events)['metrics'])

    def test_no_pseudofeasibility_on_timeout(self):
        with patch('scientific_model.milp',return_value=SimpleNamespace(status=1,message='limit')):
            status,events=optimize(tiny())
            self.assertEqual(status['status'],'solver_limit');self.assertEqual(events,[])

    def test_invalid_overlap_and_capacity(self):
        s=tiny();s['vehicles'][0]['windows'][0]['end']=7
        with self.assertRaises(ValueError):optimize(s)
        s=tiny();s['stations']['S']['power_kw']=float('nan')
        with self.assertRaises(ValueError):optimize(s)

    def test_greedy_service_is_auditable(self):
        s=tiny();s['stations']['S']['connectors']=2
        status,events=greedy(s)
        self.assertEqual(status['status'],'feasible_rule');check(s,events)

    def test_no_opportunity_does_not_invent_benefit(self):
        s=tiny();s['stations']['S'].update(connectors=2,power_kw=2.)
        s['retail']=[1.]*4;s['wholesale']=[.7]*4
        for v in s['vehicles']:
            v['windows']=v['windows'][:1]
            for t in v['trips']:t['routes']=t['routes'][:1]
        _,baseline=greedy(s);_,joint=optimize(s)
        a,b=metrics(s,baseline),metrics(s,joint)
        for key in ['user_objective_cny','grid_kwh','carbon_kg','peak_kw']:
            self.assertAlmostEqual(a[key],b[key],places=6)


if __name__=='__main__':unittest.main()

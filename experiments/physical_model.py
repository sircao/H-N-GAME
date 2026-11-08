"""Explicit route/charging task model for controlled Game-derived experiments.

This centralized model is not a stochastic traffic equilibrium. Route times are
fixed inputs. Charge takes one complete discrete slot at a declared station.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import itertools
import math
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

TOL = 1e-6


@dataclass(frozen=True)
class Route:
    route_id: str
    travel_h: float
    traction_kwh: float


@dataclass(frozen=True)
class Task:
    task_id: str
    vehicle_id: str
    station_id: str
    initial_kwh: float
    terminal_kwh: float
    battery_kwh: float
    parking_start: float
    parking_end: float
    departure: float
    deadline: float
    max_power_kw: float
    efficiency: float
    routes: tuple[Route, ...]


def validate(tasks, stations, prices, dt):
    if not math.isfinite(dt) or dt <= 0 or not len(prices):
        raise ValueError('Positive dt and nonempty prices required')
    if not np.isfinite(prices).all() or np.any(np.asarray(prices) < 0):
        raise ValueError('Prices must be finite and nonnegative')
    if not tasks or len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError('Nonempty unique task IDs required')
    if len({t.vehicle_id for t in tasks}) != len(tasks):
        raise ValueError('This model supports exactly one task per vehicle')
    for s in stations.values():
        if (not math.isfinite(s['power_kw']) or s['power_kw'] < 0
                or type(s['connectors']) is not int or s['connectors'] < 0):
            raise ValueError('Invalid station power/connector limit')
    for t in tasks:
        nums = [t.initial_kwh, t.terminal_kwh, t.battery_kwh, t.parking_start,
                t.parking_end, t.departure, t.deadline, t.max_power_kw, t.efficiency]
        if not all(math.isfinite(x) for x in nums):
            raise ValueError('Nonfinite task input')
        if (t.battery_kwh <= 0 or not 0 <= t.initial_kwh <= t.battery_kwh
                or not 0 <= t.terminal_kwh <= t.battery_kwh
                or not 0 < t.efficiency <= 1 or t.max_power_kw < 0
                or not 0 <= t.parking_start <= t.parking_end <= t.departure
                or t.departure > t.deadline or t.station_id not in stations
                or not t.routes or t.deadline > len(prices)*dt + TOL):
            raise ValueError(f'Invalid task contract: {t.task_id}')
        for r in t.routes:
            if not all(math.isfinite(x) and x >= 0 for x in (r.travel_h, r.traction_kwh)):
                raise ValueError('Invalid route')


def options(tasks, stations, route_enabled, charge_enabled, prices, dt=1.):
    validate(tasks, stations, prices, dt)
    groups = []
    for t in tasks:
        group = []
        for r in t.routes if route_enabled else t.routes[:1]:
            grid = max(0., (t.terminal_kwh + r.traction_kwh - t.initial_kwh)/t.efficiency)
            before = t.initial_kwh + t.efficiency*grid
            after = before - r.traction_kwh
            if (before > t.battery_kwh + TOL or after < t.terminal_kwh - TOL
                    or t.departure+r.travel_h > t.deadline+TOL
                    or grid > t.max_power_kw*dt+TOL):
                continue
            if grid <= TOL:
                slots = [-1]
            else:
                slots = [h for h in range(len(prices))
                         if h*dt >= t.parking_start-TOL and (h+1)*dt <= t.parking_end+TOL]
                if not charge_enabled:
                    slots = slots[:1]
            for h in slots:
                group.append(dict(task_id=t.task_id, vehicle_id=t.vehicle_id,
                                  station_id=t.station_id, route_id=r.route_id,
                                  slot=h, grid_kwh=grid, traction_kwh=r.traction_kwh,
                                  travel_h=r.travel_h, initial_kwh=t.initial_kwh,
                                  final_kwh=after, pretrip_kwh=before,
                                  arrival=t.departure+r.travel_h))
        groups.append(group)
    return groups


def solve(tasks, stations, retail, wholesale, route_enabled=True, charge_enabled=True,
          dt=1., beta=34., gamma=.5703, tau=40., reference=False):
    retail, wholesale = np.asarray(retail, float), np.asarray(wholesale, float)
    if (retail.shape != wholesale.shape or not np.isfinite(wholesale).all()
            or np.any(wholesale < 0) or any(not math.isfinite(x) or x < 0 for x in (beta,gamma,tau))):
        raise ValueError('Invalid economic inputs')
    groups = options(tasks, stations, route_enabled, charge_enabled, retail, dt)
    if any(not g for g in groups):
        return {'status':'infeasible', 'reason':'individual_constraints'}, []
    flat = [o for g in groups for o in g]
    cost = lambda p: beta*p['travel_h'] + (retail[p['slot']] if p['slot']>=0 else 0)*p['grid_kwh'] + tau*gamma*p['grid_kwh']/1000
    costs = np.array([cost(p) for p in flat])
    station_keys = [(s,h) for s in stations for h in range(len(retail))]
    lookup = {key: i for i,key in enumerate(station_keys)}
    n = len(tasks)
    a = lil_matrix((n+2*len(station_keys),len(flat)))
    ids = {t.task_id:i for i,t in enumerate(tasks)}
    for j,p in enumerate(flat):
        a[ids[p['task_id']],j] = 1
        if p['slot']>=0:
            k = lookup[p['station_id'],p['slot']]
            a[n+k,j] = p['grid_kwh']/dt
            a[n+len(station_keys)+k,j] = 1
    lower = np.r_[np.ones(n), np.zeros(2*len(station_keys))]
    upper = np.r_[np.ones(n), [stations[s]['power_kw'] for s,h in station_keys],
                  [stations[s]['connectors'] for s,h in station_keys]]
    a = a.tocsr()
    if reference:
        if math.prod(map(len,groups))>1_000_000:
            raise ValueError('Reference restricted to small cases')
        selected, best = [], math.inf
        for combo in itertools.product(*groups):
            usage = {(s,h):[0.,0] for s,h in station_keys}
            for p in combo:
                if p['slot']>=0:
                    u=usage[p['station_id'],p['slot']];u[0]+=p['grid_kwh']/dt;u[1]+=1
            if any(v[0]>stations[s]['power_kw']+TOL or v[1]>stations[s]['connectors']
                   for (s,h),v in usage.items()): continue
            value=sum(cost(p) for p in combo)
            if value<best:
                best,selected=value,list(combo)
        if not selected: return {'status':'infeasible','reason':'shared_capacity'}, []
        gap=0.
    else:
        result=milp(costs, integrality=np.ones(len(flat)), bounds=Bounds(0,1),
                    constraints=LinearConstraint(a,lower,upper),
                    options={'time_limit':60.,'mip_rel_gap':0.})
        if result.status!=0:
            return {'status':{1:'solver_limit',2:'infeasible',3:'unbounded'}.get(result.status,'solver_error'),
                    'reason':str(result.message)}, []
        selected=[dict(p) for p,x in zip(flat,result.x) if x>.5]
        usage=a@result.x
        if max(np.max(lower-usage),np.max(usage-upper),np.max(np.abs(result.x-result.x.round())))>TOL:
            raise RuntimeError('Solver feasibility failed')
        gap=float(result.mip_gap)
    grid=sum(p['grid_kwh'] for p in selected)
    traction=sum(p['traction_kwh'] for p in selected)
    bill=sum(retail[p['slot']]*p['grid_kwh'] for p in selected if p['slot']>=0)
    purchase=sum(wholesale[p['slot']]*p['grid_kwh'] for p in selected if p['slot']>=0)
    carbon=gamma*grid; carbon_payment=tau*carbon/1000
    travel=sum(p['travel_h'] for p in selected)
    load=np.zeros(len(retail))
    for p in selected:
        if p['slot']>=0: load[p['slot']]+=p['grid_kwh']/dt
    metrics=dict(status='optimal', completion_rate=1., late_tasks=0,
                 travel_h=travel, traction_kwh=traction, grid_kwh=grid,
                 loss_kwh=sum(p['grid_kwh']*(1-t.efficiency) for t,p in zip(tasks,selected)),
                 bill_cny=float(bill), purchase_cny=float(purchase),
                 revenue_cny=float(bill), profit_cny=float(bill-purchase),
                 carbon_kg=carbon, carbon_payment_cny=carbon_payment,
                 resource_cost_cny=beta*travel+float(purchase),
                 objective_cny=beta*travel+float(bill)+carbon_payment,
                 peak_kw=float(load.max()), valley_kw=float(load.min()), mean_kw=float(load.mean()),
                 load_factor=float(load.mean()/load.max()) if load.max()>0 else 0., mip_gap=gap)
    return metrics,selected


def task_dict(t):
    return asdict(t)


def task_from_dict(d):
    return Task(**(d | {'routes':tuple(Route(**r) for r in d['routes'])}))

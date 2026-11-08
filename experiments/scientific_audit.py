"""Independent physical and economic checks for the finite multi-leg contract.

No solver or production metric implementation is imported.
"""
from collections import defaultdict
import math

TOL=2e-6


def check(spec,events):
    vehicles={v['vehicle_id']:v for v in spec['vehicles']};byvehicle=defaultdict(list)
    for e in events:
        if e['vehicle_id'] not in vehicles:raise ValueError('Unknown vehicle')
        byvehicle[e['vehicle_id']].append(e)
    if set(byvehicle)!=set(vehicles):raise ValueError('Vehicles removed from service')
    power=defaultdict(float);occupied=defaultdict(int);load=[0.]*len(spec['retail'])
    totals=dict(trips=0,travel_h=0.,traction_kwh=0.,grid_kwh=0.,loss_kwh=0.,user_bill_cny=0.,wholesale_cost_cny=0.)
    max_balance=0.;ledger=[];user_costs={};arrival_margins=[]
    for vid,v in vehicles.items():
        inventory=v['initial_kwh'];previous_end=0.;position=v['initial_position'];seen=set();grid=traction=travel=bill=0.
        tasks={t['task_id']:t for t in v['trips']}
        for e in sorted(byvehicle[vid],key=lambda e:e['start']):
            if e['start']<previous_end-TOL or not 0<=e['start']<e['end']<=24+TOL:raise ValueError('Event overlap/horizon')
            # Resolve geometry independently from the declared source route.
            if e['event_type']=='drive':
                if e['task_id'] not in tasks or e['task_id'] in seen:raise ValueError('Duplicate/unknown trip')
                t=tasks[e['task_id']];seen.add(e['task_id'])
                route=next((r for r in t['routes'] if r['route_id']==e['route_id']),None)
                if route is None:raise ValueError('Unknown route')
                if abs(e['start']-t['departure'])>TOL or abs(e['end']-e['start']-route['time_h'])>TOL or e['end']>t['deadline']+TOL:raise ValueError('Departure/travel/deadline mismatch')
                if abs(route['energy_kwh']-e['energy_kwh'])>TOL or abs(e['grid_kwh'])>TOL:raise ValueError('Traction mismatch')
                points=route['path_points']
                length=sum(math.dist(a,b) for a,b in zip(points,points[1:]))/100000
                if abs(length-route['distance_km'])>TOL:raise ValueError(f'Route geometry/energy distance mismatch: {vid}: {length} != {route["distance_km"]}')
                inventory-=route['energy_kwh'];traction+=route['energy_kwh'];travel+=route['time_h']
                arrival_margins.append(t['deadline']-e['end']);totals['trips']+=1
            elif e['event_type']=='charge':
                s=e['station_id'];points=[spec['stations'][s]['position']]*2
                dt=spec['dt'];h=round(e['start']/dt);q=e['grid_kwh']
                if q<0 or abs(e['end']-e['start']-dt)>TOL or abs(h*dt-e['start'])>TOL:raise ValueError('Charge slot mismatch')
                if not any(w['station_id']==s and e['start']>=w['start']-TOL and e['end']<=w['end']+TOL for w in v['windows']):raise ValueError('Charging outside physical parking access')
                limit=min(v['power_kw'],spec['stations'][s]['connector_power_kw'])
                if q/dt>limit+TOL:raise ValueError('Vehicle/connector power limit')
                inventory+=q*v['efficiency'];grid+=q;bill+=q*spec['retail'][h]
                totals['wholesale_cost_cny']+=q*spec['wholesale'][h]
                power[s,h]+=q/dt;occupied[s,h]+=1;load[h]+=q/dt
            else:raise ValueError('Unknown event type')
            if math.dist(position,points[0])>.02:raise ValueError('Unaccounted spatial teleport')
            if not v['reserve_kwh']-TOL<=inventory<=v['battery_kwh']+TOL:raise ValueError('Battery constraint violated')
            position=points[-1];previous_end=e['end']
        if seen!=set(tasks):raise ValueError('Incomplete trip service')
        residual=v['initial_kwh']+v['efficiency']*grid-traction-inventory
        max_balance=max(max_balance,abs(residual))
        if abs(inventory-v['terminal_kwh'])>TOL or abs(residual)>TOL:raise ValueError('Terminal inventory / energy closure')
        ledger.append(dict(vehicle_id=vid,trips=len(seen),initial_kwh=v['initial_kwh'],terminal_kwh=inventory,
                           terminal_requirement_kwh=v['terminal_kwh'],grid_kwh=grid,traction_kwh=traction,
                           loss_kwh=grid*(1-v['efficiency']),energy_residual_kwh=residual,service_complete=True))
        user_costs[vid]=spec['beta']*travel+bill+spec['tau']*spec['gamma']*grid/1000
        totals['travel_h']+=travel;totals['traction_kwh']+=traction;totals['grid_kwh']+=grid
        totals['loss_kwh']+=grid*(1-v['efficiency']);totals['user_bill_cny']+=bill
    for (s,h),p in power.items():
        if p>spec['stations'][s]['power_kw']+TOL or occupied[s,h]>spec['stations'][s]['connectors']:raise ValueError('Station capacity violation')
    carbon=totals['grid_kwh']*spec['gamma']
    totals.update(carbon_kg=carbon,carbon_payment_cny=carbon*spec['tau']/1000,
                  operator_revenue_cny=totals['user_bill_cny'],operator_profit_cny=totals['user_bill_cny']-totals['wholesale_cost_cny'],
                  resource_cost_cny=spec['beta']*totals['travel_h']+totals['wholesale_cost_cny'],
                  user_objective_cny=sum(user_costs.values()),peak_kw=max(load),mean_kw=sum(load)/len(load),
                  load_factor=(sum(load)/len(load))/max(load) if max(load)>0 else 0.,load_kw=load)
    if abs(sum(load)*spec['dt']-totals['grid_kwh'])>TOL:raise ValueError('Power/energy integral mismatch')
    return dict(passed=True,vehicles=len(vehicles),trips=totals['trips'],max_energy_residual_kwh=max_balance,
                min_arrival_margin_h=min(arrival_margins),metrics=totals,ledger=ledger,user_costs=user_costs)


def compare_metrics(reported,independent):
    for key,value in independent.items():
        if key=='load_kw':
            if len(reported[key])!=len(value) or any(abs(a-b)>TOL for a,b in zip(reported[key],value)):raise ValueError('Load sequence mismatch')
        elif abs(reported[key]-value)>TOL*max(1,abs(value)):raise ValueError('Metric mismatch: '+key)

"""Finite multi-trip-day physical optimization. Explicit simulation contract.

No game equilibrium or real-world validity is claimed. Charging q is grid kWh;
connector use is binary in each dt slot, and battery inventory links all trips.
"""
from __future__ import annotations
from collections import defaultdict
import math
import time
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix

TOL=1e-6


def validate(spec):
    dt=spec['dt'];n=len(spec['retail'])
    if not math.isfinite(dt) or dt<=0 or len(spec['wholesale'])!=n or not math.isclose(n*dt,24) or not spec['vehicles']:
        raise ValueError('Require full-day equal-size finite price curves and positive dt')
    for key in ['retail','wholesale']:
        if any(not math.isfinite(x) or x<0 for x in spec[key]):raise ValueError('Invalid price')
    if any(not math.isfinite(spec[k]) or spec[k]<0 for k in ['beta','gamma','tau']):raise ValueError('Invalid economic/carbon parameter')
    for s in spec['stations'].values():
        if (type(s['connectors']) is not int or s['connectors']<0 or
                not math.isfinite(s['power_kw']) or s['power_kw']<0 or
                not math.isfinite(s['connector_power_kw']) or s['connector_power_kw']<0):raise ValueError('Invalid station')
    ids=set()
    for v in spec['vehicles']:
        if v['vehicle_id'] in ids:raise ValueError('Duplicate vehicle')
        ids.add(v['vehicle_id'])
        if not 0<=v['reserve_kwh']<=v['initial_kwh']<=v['battery_kwh'] or not 0<=v['terminal_kwh']<=v['battery_kwh']:
            raise ValueError('Invalid battery inventory')
        if not 0<v['efficiency']<=1 or not math.isfinite(v['power_kw']) or v['power_kw']<0:
            raise ValueError('Invalid charging efficiency/power')
        previous=0.
        for j,t in enumerate(v['trips']):
            if t['leg']!=j or not previous<=t['departure']<t['deadline']<=24:
                raise ValueError('Invalid finite trip sequence')
            previous=t['deadline']
            if not t['routes']:raise ValueError('Missing route; do not drop service')
            for r in t['routes']:
                if any(not math.isfinite(r[k]) or r[k]<0 for k in ['time_h','energy_kwh','distance_km']):raise ValueError('Invalid route')
        for w in v['windows']:
            if not 0<=w['start']<=w['end']<=24 or w['station_id'] not in spec['stations']:raise ValueError('Invalid parking window')
            if any(max(w['start'],t['departure'])<min(w['end'],t['deadline'])-TOL for t in v['trips']):
                raise ValueError('Charging window overlaps reserved driving period')


def charge_slots(spec,v):
    dt=spec['dt'];slots={}
    for w in v['windows']:
        for h in range(len(spec['retail'])):
            if h*dt>=w['start']-TOL and (h+1)*dt<=w['end']+TOL:
                if h in slots and slots[h]!=w['station_id']:raise ValueError('Ambiguous station access')
                slots[h]=w['station_id']
    return slots


def optimize(spec,route_enabled=True,time_limit=120.):
    validate(spec)
    start=time.perf_counter();dt=spec['dt'];variables=[];lower=[];upper=[];integer=[];objective=[]
    def variable(meta,hi,cost,is_integer=False):
        idx=len(variables);variables.append(meta);lower.append(0.);upper.append(hi);integer.append(int(is_integer));objective.append(cost);return idx
    xs={};qs={};ys={};by_station=defaultdict(list);vx=defaultdict(list);vq=defaultdict(list);tx=defaultdict(list)
    for vi,v in enumerate(spec['vehicles']):
        for j,t in enumerate(v['trips']):
            for ri,r in enumerate(t['routes'] if route_enabled else t['routes'][:1]):
                if r['time_h']<=t['deadline']-t['departure']+TOL:
                    xs[vi,j,ri]=variable(('route',vi,j,ri),1,spec['beta']*r['time_h'],True)
                    vx[vi].append((j,ri,xs[vi,j,ri]));tx[vi,j].append(xs[vi,j,ri])
        for h,s in charge_slots(spec,v).items():
            q=variable(('charge',vi,h,s),min(v['power_kw'],spec['stations'][s]['connector_power_kw'])*dt,
                       spec['retail'][h]+spec['tau']*spec['gamma']/1000)
            y=variable(('occupancy',vi,h,s),1,0,True)
            qs[vi,h]=q;ys[vi,h]=y;by_station[s,h].append((q,y))
            vq[vi].append((h,q))
    rows=[];cols=[];values=[];lo=[];hi=[]
    def row(coefficients,a=-np.inf,b=np.inf):
        index=len(lo);lo.append(a);hi.append(b)
        for key,value in coefficients.items():
            if value:rows.append(index);cols.append(key);values.append(value)
    for vi,v in enumerate(spec['vehicles']):
        for j,t in enumerate(v['trips']):
            idx=tx[vi,j]
            if not idx:return dict(status='infeasible',reason=f'No deadline-feasible route: {v["vehicle_id"]}:{j}'),[]
            row(dict.fromkeys(idx,1),1,1)
        for h in charge_slots(spec,v):
            s=charge_slots(spec,v)[h]
            row({qs[vi,h]:1,ys[vi,h]:-min(v['power_kw'],spec['stations'][s]['connector_power_kw'])*dt},b=0)
        def inventory(hour,completed):
            coeff={q:v['efficiency'] for h,q in vq[vi] if (h+1)*dt<=hour+TOL}
            for j,r,idx in vx[vi]:
                if j<completed:coeff[idx]=-v['trips'][j]['routes'][r]['energy_kwh']
            return coeff
        for j,t in enumerate(v['trips']):
            before=inventory(t['departure'],j)
            row(before,b=v['battery_kwh']-v['initial_kwh'])
            after=before.copy()
            for jj,r,idx in vx[vi]:
                if jj==j:after[idx]=-t['routes'][r]['energy_kwh']
            row(after,a=v['reserve_kwh']-v['initial_kwh'])
        # Charging increases inventory monotonically within each reserved window;
        # checking each slot end covers the battery upper bound without sampling.
        for h in charge_slots(spec,v):
            completed=sum(t['deadline']<=h*dt+TOL for t in v['trips'])
            row(inventory((h+1)*dt,completed),b=v['battery_kwh']-v['initial_kwh'])
        terminal=inventory(24,len(v['trips']))
        target=v['terminal_kwh']-v['initial_kwh']
        row(terminal,target,target)
    for (s,h),items in by_station.items():
        row({q:1/dt for q,y in items},b=spec['stations'][s]['power_kw'])
        row({y:1 for q,y in items},b=spec['stations'][s]['connectors'])
    matrix=coo_matrix((values,(rows,cols)),shape=(len(lo),len(variables))).tocsc()
    result=milp(np.array(objective),integrality=np.array(integer),bounds=Bounds(lower,upper),
                constraints=LinearConstraint(matrix,lo,hi),
                options={'mip_rel_gap':1e-8,'time_limit':time_limit})
    status={0:'optimal',1:'solver_limit',2:'infeasible',3:'unbounded'}.get(result.status,'solver_error')
    info=dict(status=status,runtime_s=time.perf_counter()-start,reason=str(result.message),
              variables=len(variables),constraints=len(lo))
    if result.status!=0:return info,[]
    x=result.x
    violation=max(float(np.max(np.asarray(lo)-matrix@x)),float(np.max(matrix@x-np.asarray(hi))),
                  max((abs(x[i]-round(x[i])) for i in range(len(x)) if integer[i]),default=0))
    if violation>TOL:raise RuntimeError('MILP constraint/integer violation')
    info.update(mip_gap=float(result.mip_gap),dual_bound_cny=float(result.mip_dual_bound),constraint_residual=violation)
    events=[]
    for (vi,j,ri),idx in xs.items():
        if x[idx]>.5:
            v=spec['vehicles'][vi];t=v['trips'][j];r=t['routes'][ri]
            events.append(dict(vehicle_id=v['vehicle_id'],task_id=t['task_id'],event_type='drive',leg=j,
                               start=t['departure'],end=t['departure']+r['time_h'],deadline=t['deadline'],
                               route_id=r['route_id'],energy_kwh=r['energy_kwh'],grid_kwh=0.,
                               distance_km=r['distance_km'],path_points=r['path_points'],station_id=''))
    for (vi,h),idx in qs.items():
        if x[idx]>1e-8:
            v=spec['vehicles'][vi];s=charge_slots(spec,v)[h]
            point=spec['stations'][s]['position']
            events.append(dict(vehicle_id=v['vehicle_id'],task_id=f'{v["vehicle_id"]}:charge:{h}',event_type='charge',leg=-1,
                               start=h*dt,end=(h+1)*dt,deadline=(h+1)*dt,route_id='',energy_kwh=0.,
                               grid_kwh=float(x[idx]),distance_km=0.,path_points=[point,point],station_id=s))
    return info,events


def greedy(spec,route_enabled=False):
    """Earliest feasible charging; finite routes selected before scheduling.

    This is an explicit rule baseline, not an optimum or best response. Global
    resource use is committed in vehicle-ID order, and failures are retained.
    """
    validate(spec);dt=spec['dt'];events=[];power=defaultdict(float);occupancy=defaultdict(int)
    for v in spec['vehicles']:
        routes=[]
        for t in v['trips']:
            candidates=[r for r in (t['routes'] if route_enabled else t['routes'][:1]) if r['time_h']<=t['deadline']-t['departure']+TOL]
            if not candidates:return dict(status='infeasible',reason='baseline_deadline'),[]
            r=min(candidates,key=lambda r:spec['beta']*r['time_h']+(np.mean(spec['retail'])+spec['tau']*spec['gamma']/1000)*r['energy_kwh']) if route_enabled else candidates[0]
            routes.append(r)
        grid_need=(v['terminal_kwh']-v['initial_kwh']+sum(r['energy_kwh'] for r in routes))/v['efficiency']
        if grid_need<-TOL:return dict(status='infeasible',reason='terminal_exactness_no_v2g'),[]
        inventory=v['initial_kwh'];remaining=max(0.,grid_need)
        slots=charge_slots(spec,v)
        timeline=[(t['departure'],'drive',j) for j,t in enumerate(v['trips'])]+[(h*dt,'charge',h) for h in slots]
        for hour,kind,j in sorted(timeline):
            if kind=='drive':
                t=v['trips'][j];r=routes[j];inventory-=r['energy_kwh']
                if inventory<v['reserve_kwh']-TOL:return dict(status='infeasible',reason='baseline_soc'),[]
                events.append(dict(vehicle_id=v['vehicle_id'],task_id=t['task_id'],event_type='drive',leg=j,
                                   start=t['departure'],end=t['departure']+r['time_h'],deadline=t['deadline'],
                                   route_id=r['route_id'],energy_kwh=r['energy_kwh'],grid_kwh=0.,distance_km=r['distance_km'],
                                   path_points=r['path_points'],station_id=''))
            elif remaining>TOL:
                s=slots[j];station=spec['stations'][s]
                if occupancy[s,j]>=station['connectors']:continue
                amount=min(remaining,(v['battery_kwh']-inventory)/v['efficiency'],min(v['power_kw'],station['connector_power_kw'])*dt,
                           max(0.,station['power_kw']-power[s,j])*dt)
                if amount<=TOL:continue
                inventory+=amount*v['efficiency'];remaining-=amount;power[s,j]+=amount/dt;occupancy[s,j]+=1
                point=station['position']
                events.append(dict(vehicle_id=v['vehicle_id'],task_id=f'{v["vehicle_id"]}:charge:{j}',event_type='charge',leg=-1,
                                   start=hour,end=hour+dt,deadline=hour+dt,route_id='',energy_kwh=0.,grid_kwh=amount,
                                   distance_km=0.,path_points=[point,point],station_id=s))
        if remaining>TOL or abs(inventory-v['terminal_kwh'])>TOL:return dict(status='infeasible',reason='baseline_capacity_or_storage'),[]
    return dict(status='feasible_rule'),events


def metrics(spec,events):
    dt=spec['dt'];loads=np.zeros(len(spec['retail']));grid=energy=travel=bill=purchase=0.
    vm={v['vehicle_id']:v for v in spec['vehicles']};loss=0.
    for e in events:
        if e['event_type']=='drive':energy+=e['energy_kwh'];travel+=e['end']-e['start']
        else:
            h=round(e['start']/dt);q=e['grid_kwh'];grid+=q;loads[h]+=q/dt
            loss+=q*(1-vm[e['vehicle_id']]['efficiency']);bill+=q*spec['retail'][h];purchase+=q*spec['wholesale'][h]
    carbon=grid*spec['gamma'];tax=carbon*spec['tau']/1000
    return dict(trips=sum(e['event_type']=='drive' for e in events),travel_h=travel,traction_kwh=energy,grid_kwh=grid,
                loss_kwh=loss,carbon_kg=carbon,carbon_payment_cny=tax,user_bill_cny=bill,operator_revenue_cny=bill,
                wholesale_cost_cny=purchase,operator_profit_cny=bill-purchase,resource_cost_cny=spec['beta']*travel+purchase,
                user_objective_cny=spec['beta']*travel+bill+tax,peak_kw=float(loads.max()),mean_kw=float(loads.mean()),
                load_factor=float(loads.mean()/loads.max()) if loads.max()>0 else 0.,load_kw=loads.tolist())

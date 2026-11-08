"""Independent comparison of actual UE telemetry against the event contract.

Passing certifies software replay/accounting consistency, not independent city
traffic dynamics or observed human behavior.
"""
import argparse
import bisect
import csv
import gzip
import json
import math
from pathlib import Path
from collections import defaultdict


def audit(folder):
    with gzip.open(folder/'input.json.gz','rt') as f:spec=json.load(f)
    with gzip.open(folder/'events.json.gz','rt') as f:events=json.load(f)
    vehicles={v['vehicle_id']:v for v in spec['vehicles']};plans=defaultdict(list)
    for e in events:
        e=dict(e);points=e['path_points'];prefix=[0.]
        for a,b in zip(points,points[1:]):prefix.append(prefix[-1]+math.dist(a,b))
        e['arc']=prefix;plans[e['vehicle_id']].append(e)
    for es in plans.values():es.sort(key=lambda e:e['start'])
    def along(e,fraction):
        d=fraction*e['arc'][-1];i=bisect.bisect_left(e['arc'],d)
        if i==0:return e['path_points'][0]
        if i>=len(e['arc']):return e['path_points'][-1]
        a,b=e['path_points'][i-1:i+1];length=e['arc'][i]-e['arc'][i-1]
        ratio=(d-e['arc'][i-1])/length if length else 1
        return [x+(y-x)*ratio for x,y in zip(a,b)]
    max_energy=max_grid=max_soc_energy=max_position=0.;rows=0;last={};seen=set();station_usage=defaultdict(lambda:[0.,0])
    with (folder/'unreal_observations.csv').open(newline='',encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            hour=float(row['sim_hour']);vid=row['vehicle_id'];v=vehicles[vid];seen.add(vid)
            energy=grid=0.;position=v['initial_position']
            for e in plans[vid]:
                if hour<e['start']:break
                fraction=min(1.,max(0.,(hour-e['start'])/(e['end']-e['start'])))
                energy+=e['energy_kwh']*fraction;grid+=e['grid_kwh']*fraction;position=along(e,fraction)
            expected=v['initial_kwh']+v['efficiency']*grid-energy
            observed=float(row['soc'])*float(row['battery_kwh'])/100
            max_energy=max(max_energy,abs(float(row['cumulative_traction_kwh'])-energy))
            max_grid=max(max_grid,abs(float(row['cumulative_grid_kwh'])-grid))
            max_soc_energy=max(max_soc_energy,abs(observed-expected))
            max_position=max(max_position,math.dist(position,[float(row[k]) for k in ['x_cm','y_cm','z_cm']]))
            if not v['reserve_kwh']-.001<=observed<=v['battery_kwh']+.001:raise ValueError('Observed SOC constraint violated')
            power=float(row['charging_kw'])
            if power>1e-6:
                s=row['station_id'];u=station_usage[hour,s];u[0]+=power;u[1]+=1
            last[vid]=row;rows+=1
    if seen!=set(vehicles):raise ValueError('Incomplete Unreal vehicle observations')
    final=[]
    for vid,v in vehicles.items():
        row=last[vid];observed=float(row['soc'])*v['battery_kwh']/100
        if abs(float(row['sim_hour'])-24)>1e-6:raise ValueError('Unreal replay did not finish the day')
        error=observed-v['terminal_kwh']
        if abs(error)>.001:raise ValueError('Unreal terminal SOC mismatch')
        final.append(dict(vehicle_id=vid,final_kwh=observed,terminal_requirement_kwh=v['terminal_kwh'],error_kwh=error))
    for (hour,s),(power,count) in station_usage.items():
        if power>spec['stations'][s]['power_kw']+.001 or count>spec['stations'][s]['connectors']:
            raise ValueError('Observed station conflict')
    result=dict(passed=max(max_energy,max_grid,max_soc_energy)<=.001 and max_position<=2.,
                scope='C++/Python event-contract replay and physical/accounting consistency; not independent city/traffic validation',
                observation_rows=rows,vehicles=len(seen),horizon_end=24.,max_traction_error_kwh=max_energy,
                max_grid_error_kwh=max_grid,max_battery_inventory_error_kwh=max_soc_energy,max_position_error_cm=max_position,
                energy_tolerance_kwh=.001,position_tolerance_cm=2.)
    (folder/'execution_consistency.json').write_text(json.dumps(result,indent=2)+'\n')
    with (folder/'execution_final_inventory.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,list(final[0]));w.writeheader();w.writerows(final)
    if not result['passed']:raise ValueError('Replay error exceeds declared float32 tolerances')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir',type=Path)
    print(json.dumps(audit(p.parse_args().run_dir),indent=2))

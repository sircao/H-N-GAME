"""Independent reservation execution stress model; no optimization imports.

Declared artificial disturbances expose deadline/storage sensitivity. This is
neither a real-data validation nor an online-controller performance claim.
"""
import argparse
from collections import defaultdict
import csv
import gzip
import heapq
import json
from pathlib import Path
import numpy as np


def simulate(spec,events,seed,severity):
    rng=np.random.default_rng(seed);vs={v['vehicle_id']:v for v in spec['vehicles']}
    state={vid:dict(available=0.,battery=v['initial_kwh'],late=0,soc_violations=0,grid=0.,traction=0.,max_queue=0.) for vid,v in vs.items()}
    chargers={s:[0.]*min(st['connectors'],int(st['power_kw']//st['connector_power_kw'])) for s,st in spec['stations'].items()}
    for heap in chargers.values():heapq.heapify(heap)
    for e in sorted(events,key=lambda e:(e['start'],e['vehicle_id'],e['event_type'])):
        v=vs[e['vehicle_id']];x=state[e['vehicle_id']]
        start=max(e['start'],x['available'])
        if e['event_type']=='drive':
            multiplier=1. if severity==0 else float(np.exp(rng.normal(0,.2*severity)))
            delay=0. if severity==0 else float(rng.uniform(0,.1*severity))
            energy_factor=1. if severity==0 else max(.5,1+float(rng.normal(0,.05*severity)))
            end=start+(e['end']-e['start'])*multiplier+delay
            energy=e['energy_kwh']*energy_factor;x['battery']-=energy;x['traction']+=energy
            x['late']+=end>e['deadline']+1e-6;x['available']=end
            x['soc_violations']+=x['battery']<v['reserve_kwh']-1e-6
        else:
            heap=chargers[e['station_id']]
            if not heap:continue
            free=heapq.heappop(heap);begin=max(start,free)
            power=min(v['power_kw'],spec['stations'][e['station_id']]['connector_power_kw'])
            possible=max(0.,e['end']-begin)*power
            q=min(e['grid_kwh'],possible,max(0.,v['battery_kwh']-x['battery'])/v['efficiency'])
            if q>0:
                end=begin+q/power;x['available']=end;x['grid']+=q;x['battery']+=q*v['efficiency']
                x['max_queue']=max(x['max_queue'],begin-start);heapq.heappush(heap,end)
            else:heapq.heappush(heap,free)
    errors=[x['battery']-vs[vid]['terminal_kwh'] for vid,x in state.items()]
    return dict(seed=seed,severity=severity,vehicles=len(vs),trips=sum(len(v['trips']) for v in vs.values()),
                late_trips=sum(x['late'] for x in state.values()),soc_violations=sum(x['soc_violations'] for x in state.values()),
                fraction_vehicles_without_service_violation=sum(x['late']==0 and x['soc_violations']==0 for x in state.values())/len(vs),
                terminal_energy_error_mean_kwh=float(np.mean(errors)),terminal_energy_error_max_abs_kwh=max(map(abs,errors)),
                maximum_queue_h=max(x['max_queue'] for x in state.values()),
                generator='Artificial lognormal travel factor, uniform additive delay and normal traction-energy variation; severity scales all disturbances')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir',type=Path);args=p.parse_args()
    with gzip.open(args.run_dir/'input.json.gz','rt') as f:spec=json.load(f)
    with gzip.open(args.run_dir/'events.json.gz','rt') as f:events=json.load(f)
    rows=[simulate(spec,events,17,0)]
    for severity in [1.,4.]:
        rows.extend(simulate(spec,events,seed,severity) for seed in spec['protocol']['paired_seeds'])
    if rows[0]['late_trips'] or rows[0]['soc_violations'] or rows[0]['terminal_energy_error_max_abs_kwh']>1e-6:
        raise RuntimeError('Independent no-disturbance execution control failed')
    output=args.run_dir/'execution_stress.csv'
    with output.open('w',newline='') as f:
        w=csv.DictWriter(f,list(rows[0]));w.writeheader();w.writerows(rows)
    print('Independent execution control + 20 artificial stress cases:',output)

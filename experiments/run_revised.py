"""Run transparent controlled experiments using the saved Game network/vehicles.

Missing authoritative task fields are reported, never represented as measured.
The resulting centralized study uses explicitly declared task assumptions.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import replace, asdict
import hashlib
import json
import platform
from pathlib import Path
import sys
import time
import numpy as np
import pandas as pd
import scipy

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'unreal-map-master/Plugins/StackelbergEVOptimization/Python'
sys.path.insert(0,str(PLUGIN))
import nested_game_optimizer as original
from physical_model import Task, Route, solve, task_dict, task_from_dict


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def dump(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def csv_write(path,rows):
    if not rows:return
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        fields=list(dict.fromkeys(k for row in rows for k in row))
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def prepare(out,stamp):
    source=ROOT/'unreal-map-master/Saved/EVTrafficSamples'
    paths={k:source/f'{k}_{stamp}.csv' for k in original.REQUIRED_PREFIXES}
    vehicle=pd.read_csv(paths['datalist'],dtype={'vehicle_id':str})
    ordered=vehicle.sort_values(['vehicle_id','elapsed_sec'])
    first=ordered.groupby('vehicle_id',sort=True).first().reset_index()
    missing=sorted({'parking_start_hour','parking_end_hour','arrival_deadline_hour',
                    'terminal_soc_pct','station_id','charging_efficiency'}-set(vehicle.columns))
    report=dict(stamp=stamp,rows=len(vehicle),vehicles=len(first),
                observed_sim_hour=[float(vehicle.sim_hour.min()),float(vehicle.sim_hour.max())],
                missing_authoritative_fields=missing,
                original_full_task_experiment_ready=not missing,
                source_type='saved baseline simulation, not real-world measurements')
    dump(out/'input_validation.json',report)
    print('Input validation:',report,flush=True)
    cfg=original.ModelConfig(k_paths=5,default_capacity=30,max_iterations=5000)
    graph,ods,nodes=original.build_empirical_network(vehicle,cfg)
    print(f'Network reconstructed: {len(graph)} nodes, {sum(map(len,graph.values()))} edges',flush=True)
    paths_template=original.build_path_set(graph,ods,nodes,cfg)
    by_od={}
    for p in paths_template:by_od.setdefault(p.od_id,[]).append(p)
    # Use common fixed free-flow route times for the four-arm experiment.
    # Endogenous BPR/MNL behavior is evaluated separately below.
    routes_by_vehicle={}
    for od,ids in ods.items():
        for vid in ids:
            routes=[]
            for p in by_od[od]:
                edges=[graph[a][b] for a,b in zip(p.nodes,p.nodes[1:])]
                routes.append(Route(p.path_id,sum(e.free_time_h for e in edges),sum(e.energy_kwh for e in edges)))
            routes_by_vehicle[vid]=tuple(routes)
    tasks=[]
    for row in first.itertuples(index=False):
        vid=str(row.vehicle_id)
        depart=float(row.departure_time)
        initial=float(row.battery_capacity_kWh)*float(row.soc)/100
        routes=routes_by_vehicle[vid]
        # Experimental assumptions, not reconstructed real parking/charging access.
        origin=original.quantize(*original.parse_od_point(row.od_origin),cfg.grid_cm)
        tasks.append(Task(f'{stamp}:{vid}',vid,f'ASSUMED_ORIGIN_{origin[0]}_{origin[1]}',
                          initial,initial,float(row.battery_capacity_kWh),max(0.,depart-6),
                          depart,depart,min(24.,depart+max(.25,2*routes[0].travel_h)),20.,.9,routes))
    stations={t.station_id:{'power_kw':60.,'connectors':3} for t in tasks}
    # Retail and wholesale curves are explicit study assumptions, not inferred tariffs.
    wholesale=[.35 if h<7 or h>=22 else 1.1 if 17<=h<22 else .65 for h in range(24)]
    retail=[x+.25 for x in wholesale]
    assumptions=[
        'One first-OD trip per source vehicle; not the full multi-leg source day.',
        'Virtual chargers available at each quantized origin; source station locations/access are unverified.',
        'Parking lasts six hours immediately before departure, including pre-06:00 where needed.',
        'Initial battery inventory is taken from the first source sample and held constant before departure.',
        'Terminal energy requirement equals initial inventory; deadline is departure + max(0.25h, 2x baseline free-flow travel time).',
        'Charging efficiency 0.9, vehicle power 20kW, three connectors and 60kW per virtual origin station.',
        'Charging uses one complete one-hour slot before departure; no en-route charging or queue model.',
        'Four-arm times are fixed free-flow inputs; MNL/BPR diagnostics are a separate experiment.',
        'Graph is trajectory-reconstructed, quantized to 5m, with reverse links assumed; coverage relative to full map is unverified.',
        'Edge energy rates inherit the original vehicle-type distance model; tariffs and carbon factor are assumed.',
        'Accounting covers hours 0–24; all input changes in sensitivity are deterministic, not random replicates.'
    ]
    spec=dict(stamp=stamp,tasks=[task_dict(t) for t in tasks],stations=stations,
              wholesale=wholesale,retail=retail,dt=1.,beta=34.,gamma=.5703,tau=40.,assumptions=assumptions,
              network=dict(nodes=len(graph),directed_edges=sum(map(len,graph.values())),
                           od_pairs=len(ods),candidate_routes=len(paths_template)),
              inputs={k:dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for k,p in paths.items()},
              software=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,pandas=pd.__version__))
    dump(out/'scenario_manifest.json',spec)
    csv_write(out/'tasks.csv',[{k:v for k,v in task_dict(t).items() if k!='routes'} for t in tasks])
    csv_write(out/'stations.csv',[dict(station_id=s,**v) for s,v in stations.items()])
    diagnostics=[]
    for k,alpha,tau in [(1,.15,40),(3,.15,40),(5,.15,40),(5,0,40),(5,.15,0),(5,.15,90)]:
        conf=replace(cfg,k_paths=k,bpr_alpha=alpha,tolerance=1e-5)
        template=[p for candidates in by_od.values() for p in candidates[:k]]
        start=time.perf_counter()
        solved,_,iterations,gap=original.solve_follower_equilibrium(graph,template,conf,tau,float(np.mean(retail)))
        edge_flow={}
        for p in solved:
            for a,b in zip(p.nodes,p.nodes[1:]):edge_flow[a,b]=edge_flow.get((a,b),0)+p.flow
        residual=0.
        for od in ods:
            subset=[p for p in solved if p.od_id==od]
            c=np.array([p.generalized_cost for p in subset]);weights=np.exp(-conf.mnl_theta*(c-c.min()));weights/=weights.sum()
            residual+=sum(abs(p.flow-len(ods[od])*w) for p,w in zip(subset,weights))
        diagnostics.append(dict(k=k,bpr_alpha=alpha,tau=tau,iterations=iterations,
                                absolute_fixed_point_residual=gap,normalized_l1_residual=residual/len(tasks),
                                demand_residual=max(abs(sum(p.flow for p in solved if p.od_id==od)-len(ids)) for od,ids in ods.items()),
                                converged=gap<=conf.tolerance,runtime_s=time.perf_counter()-start,
                                travel_h=sum(p.flow*p.travel_time_h for p in solved),
                                traction_kwh=sum(p.flow*p.energy_kwh for p in solved)))
        print('MNL diagnostic:',diagnostics[-1],flush=True)
    csv_write(out/'original_mnl_diagnostics.csv',diagnostics)
    return spec


def run(out,stamp,reuse_manifest=False):
    out.mkdir(parents=True,exist_ok=True)
    if reuse_manifest:
        previous=json.loads((out/'artifact_manifest.json').read_text())
        spec=json.loads((out/'scenario_manifest.json').read_text())
        if spec['stamp']!=stamp:raise ValueError('Cached input stamp differs')
        for entry in spec['inputs'].values():
            if sha(ROOT/entry['path'])!=entry['sha256']:raise ValueError('Cached source input changed')
        diagnostic=out/'original_mnl_diagnostics.csv'
        if sha(diagnostic)!=previous['outputs'][diagnostic.name]:raise ValueError('Cached routing diagnostics changed')
        spec.setdefault('routing_diagnostics_provenance',dict(
            runner_sha256=previous['source_hashes']['experiments/run_revised.py'],
            source_sha256=previous['source_hashes'][str((PLUGIN/'nested_game_optimizer.py').relative_to(ROOT))],
            output_sha256=sha(diagnostic),note='Retained prior original-routing diagnostics; centralized experiments rerun from frozen inputs.'))
        dump(out/'scenario_manifest.json',spec)
    else:
        spec=prepare(out,stamp)
    tasks=[task_from_dict(t) for t in spec['tasks']]
    runs=[];metrics=[]
    def execute(experiment,scenario,ts,stations,retail,route,charge,tau=40.,reference=False):
        run_id=f'{experiment}_{scenario}_{len(runs):04d}'
        started=time.perf_counter()
        m,plan=solve(ts,stations,retail,spec['wholesale'],route,charge,tau=tau,reference=reference)
        row=dict(run_id=run_id,experiment=experiment,scenario=scenario,route_enabled=route,
                 charge_enabled=charge,runtime_s=time.perf_counter()-started,**m)
        metrics.append(row)
        runs.append(dict(run_id=run_id,experiment=experiment,scenario=scenario,
                         tasks=[task_dict(t) for t in ts],stations=stations,retail=list(retail),
                         wholesale=spec['wholesale'],dt=1.,beta=34.,gamma=.5703,tau=tau,
                         route_enabled=route,charge_enabled=charge,reference=reference,metrics=m,plan=plan))
        print(run_id,m['status'],flush=True)
        return m,plan
    arms=[(False,False),(True,False),(False,True),(True,True)]
    for r,c in arms:execute('E1','reference',tasks,spec['stations'],spec['retail'],r,c)
    for i,prices in enumerate([spec['retail'],[min(1.5,p+.1) for p in spec['retail']],
                               [min(1.5,p+(.2 if h>=17 else 0)) for h,p in enumerate(spec['retail'])]]):
        execute('E2',f'price_candidate_{i}',tasks,spec['stations'],prices,True,True)
    # Deterministic scenario changes, no fabricated uncertainty intervals.
    for name,window,k,connectors,power in [('short_window',1,5,3,60),('medium_window',3,5,3,60),
            ('single_route',6,1,3,60),('three_routes',6,3,3,60),
            ('tight_connectors',6,5,1,20),('ample_capacity',6,5,6,120),('zero_capacity',6,5,0,0)]:
        ts=[replace(t,parking_start=max(0.,t.departure-window),routes=t.routes[:k]) for t in tasks]
        stations={s:dict(connectors=connectors,power_kw=power) for s in spec['stations']}
        for r,c in arms:execute('E5',name,ts,stations,spec['retail'],r,c)
    for tau in [0.,30.,60.,90.]:
        execute('carbon',f'tau_{tau:g}',tasks,spec['stations'],spec['retail'],True,True,tau=tau)
    # Tiny references exercise the exact same revised model and capacity constraints.
    tiny=[Task(str(i),str(i),'S',10,10,20,0,3,3,4,6,.9,
               (Route('fast',.3,2),Route('efficient',.5,1))) for i in range(2)]
    st={'S':dict(power_kw=6.,connectors=1)}
    validation=[]
    for name,ts,ss,prices in [
            ('basic',tiny,st,spec['retail']),
            ('flat',tiny,st,[.9]*24),
            ('no_flex',[replace(t,parking_end=1,departure=1,deadline=2) for t in tiny],st,spec['retail']),
            ('no_route',[replace(t,routes=t.routes[:1]) for t in tiny],st,spec['retail']),
            ('zero_capacity',tiny,{'S':dict(power_kw=0.,connectors=0)},spec['retail']),
            ('battery_bound',[replace(t,initial_kwh=19.5,terminal_kwh=19.5) for t in tiny],st,spec['retail']),
            ('zero_charge',[replace(t,terminal_kwh=7) for t in tiny],st,spec['retail'])]:
        m,_=execute('E4',name,ts,ss,prices,True,True)
        ref,_=execute('E4',name+'_enumeration',ts,ss,prices,True,True,reference=True)
        passed=m['status']==ref['status'] and (m['status']=='infeasible' or abs(m['objective_cny']-ref['objective_cny'])<1e-6)
        validation.append(dict(case=name,passed=passed,status=m['status'],reference_status=ref['status'],
                               objective_gap=abs(m['objective_cny']-ref['objective_cny']) if m['status']=='optimal' and ref['status']=='optimal' else None))
    csv_write(out/'metrics.csv',metrics);csv_write(out/'correctness_results.csv',validation)
    dump(out/'runs.json',runs)
    dump(out/'artifact_manifest.json',dict(source_hashes={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),Path(__file__).with_name('physical_model.py'),PLUGIN/'nested_game_optimizer.py']},
        outputs={name:sha(out/name) for name in ['input_validation.json','scenario_manifest.json','tasks.csv',
            'stations.csv','original_mnl_diagnostics.csv','metrics.csv','correctness_results.csv','runs.json']}))
    if not all(r['passed'] for r in validation):raise RuntimeError('Reference mismatch')
    return metrics


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stamp',default='20260916_025623')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'experiments/results')
    parser.add_argument('--reuse-manifest',action='store_true',help='Rerun dispatch from hashed frozen inputs and retain original-routing diagnostics with provenance')
    args=parser.parse_args();run(args.output_dir,args.stamp,args.reuse_manifest)

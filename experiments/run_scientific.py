"""Reproducible full-map/full-finite-day experiments under a frozen protocol."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import platform
import time
import numpy as np
import scipy
from scientific_model import optimize,greedy,metrics
from scientific_audit import check,compare_metrics
from scientific_io import save_json_gz,write_csv,export_event_csv

ROOT=Path(__file__).resolve().parents[1]
ARMS=['baseline','route_only','charge_only','joint']


def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def scenario(base,name,seed=None):
    s=copy.deepcopy(base)
    if name=='single_route':
        for v in s['vehicles']:
            for t in v['trips']:t['routes']=t['routes'][:1]
    elif name=='short_parking':
        for v in s['vehicles']:
            for w in v['windows']:w['start']=max(w['start'],w['end']-1.)
    elif name in ['tight_capacity','zero_capacity']:
        for station in s['stations'].values():
            station['connectors']=1 if name=='tight_capacity' else 0
            station['power_kw']=station['connector_power_kw'] if name=='tight_capacity' else 0.
    elif name=='high_travel_time':
        for v in s['vehicles']:
            for t in v['trips']:
                for r in t['routes']:r['time_h']*=1.5
    elif name=='flat_tariff':
        s['wholesale']=[.75]*len(s['wholesale']);s['retail']=[1.]*len(s['retail'])
    elif name=='auxiliary_energy':
        for v in s['vehicles']:
            for t in v['trips']:
                for r in t['routes']:r['energy_kwh']+=r['time_h'] # explicit 1kW auxiliary load
    elif name=='paired_input':
        rng=np.random.default_rng(seed)
        for v in s['vehicles']:
            shift=float(rng.uniform(-.02,.02));delta=float(rng.uniform(-.02,.02))*v['battery_kwh']
            v['initial_kwh']=min(v['battery_kwh'],max(v['reserve_kwh'],v['initial_kwh']+delta))
            v['terminal_kwh']=v['initial_kwh']
            for t in v['trips']:t['departure']+=shift;t['deadline']+=shift
            for w in v['windows']:
                if w['start']!=0:w['start']+=shift
                if w['end']!=24:w['end']+=shift
    elif name!='reference':raise ValueError(name)
    return s


def run(out,robustness=True):
    out.mkdir(parents=True,exist_ok=True)
    base_path=out.parent/'canonical_scenario.json';base=json.loads(base_path.read_text())
    source_files=[Path(__file__),ROOT/'experiments/scientific_model.py',ROOT/'experiments/scientific_audit.py',
                  ROOT/'experiments/scientific_io.py',ROOT/'experiments/scientific_protocol.json',
                  ROOT/'experiments/build_scientific_scenario.py']
    frozen={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    manifest=dict(protocol=base['protocol'],canonical_sha256=hashlib.sha256(base_path.read_bytes()).hexdigest(),
                  source_hashes=frozen,software=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),runs=[])
    summary=[];ledgers=[];pairs=[];per_user=[]
    def execute(spec,experiment,name,arm,seed=None):
        rid=f'{experiment}_{name}_{arm}'+(f'_{seed}' if seed is not None else '')
        folder=out/rid;folder.mkdir(exist_ok=True)
        inputhash=digest(spec);start=time.perf_counter()
        if arm in ['baseline','route_only']:status,events=greedy(spec,route_enabled=arm=='route_only')
        else:status,events=optimize(spec,route_enabled=arm=='joint')
        status.setdefault('runtime_s',time.perf_counter()-start)
        row=dict(run_id=rid,experiment=experiment,scenario=name,arm=arm,seed=seed,input_hash=inputhash,**status)
        save_json_gz(folder/'input.json.gz',spec)
        if events:
            m=metrics(spec,events);audit=check(spec,events);compare_metrics(m,audit['metrics'])
            row.update({k:v for k,v in m.items() if k!='load_kw'})
            row.update(audit_passed=True,vehicles=audit['vehicles'],completed_trips=audit['trips'],completion_rate=1.,
                       max_energy_residual_kwh=audit['max_energy_residual_kwh'])
            save_json_gz(folder/'events.json.gz',events)
            (folder/'load.json').write_text(json.dumps(m['load_kw']))
            for l in audit['ledger']:ledgers.append(dict(run_id=rid,**l))
            for vid,cost in audit['user_costs'].items():per_user.append(dict(run_id=rid,vehicle_id=vid,user_cost_cny=cost))
            if experiment=='E1':export_event_csv(folder/'scientific_plan.csv',spec,events)
        else:row['audit_passed']=None
        (folder/'result.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n')
        record=dict(run_id=rid,input_hash=inputhash,files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()})
        manifest['runs'].append(record);summary.append(row)
        write_csv(out/'metrics.csv',summary)
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n')
        print(rid,row['status'],f"{row['runtime_s']:.2f}s",flush=True)
        return row
    def four(s,experiment,name,seed=None):
        rows=[execute(s,experiment,name,arm,seed) for arm in ARMS]
        if len({r['input_hash'] for r in rows})!=1:raise RuntimeError('Unpaired input comparison')
        b=rows[0]
        for t in rows[1:]:
            comparable=b['status'] in ['optimal','feasible_rule'] and t['status'] in ['optimal','feasible_rule']
            p=dict(experiment=experiment,scenario=name,seed=seed,arm=t['arm'],
                   baseline_status=b['status'],treatment_status=t['status'],both_feasible=comparable)
            if comparable:
                for key in ['resource_cost_cny','grid_kwh','carbon_kg','peak_kw','user_objective_cny']:
                    p[key+'_change']=t[key]-b[key]
                bc={r['vehicle_id']:r['user_cost_cny'] for r in per_user if r['run_id']==b['run_id']}
                tc={r['vehicle_id']:r['user_cost_cny'] for r in per_user if r['run_id']==t['run_id']}
                p['fraction_users_worse_off']=sum(tc[k]>bc[k]+1e-6 for k in bc)/len(bc)
            pairs.append(p)
        # Fixed-route offline optimum is a stronger comparison than the rule baseline.
        if rows[2]['status']=='optimal' and rows[3]['status']=='optimal' and rows[3]['user_objective_cny']>rows[2]['user_objective_cny']+1e-5:
            raise RuntimeError('Nested candidate sets violate optimum ordering')
    four(base,'E1','reference')
    for i,prices in enumerate([base['retail'],[min(1.5,p+.1) for p in base['retail']],
                               [min(1.5,p+(.2 if 17<=h*base['dt']<22 else 0)) for h,p in enumerate(base['retail'])]]):
        spec=copy.deepcopy(base);spec['retail']=prices;execute(spec,'E2',f'candidate_{i}','joint')
    if robustness:
        for name in ['single_route','short_parking','tight_capacity','zero_capacity','high_travel_time','flat_tariff','auxiliary_energy']:
            four(scenario(base,name),'E5',name)
        for seed in base['protocol']['paired_seeds']:four(scenario(base,'paired_input',seed),'E5_random','paired_input',seed)
        for tau in [0.,30.,60.,90.]:
            spec=copy.deepcopy(base);spec['tau']=tau;execute(spec,'carbon',f'tau_{tau:g}','joint')
    write_csv(out/'vehicle_energy_ledger.csv',ledgers);write_csv(out/'user_costs.csv',per_user);write_csv(out/'paired_effects.csv',pairs)
    # Percentile bootstrap describes the declared random input generator only.
    uncertainty=[];rng=np.random.default_rng(20261103)
    for arm in ARMS[1:]:
        p=[x for x in pairs if x['experiment']=='E5_random' and x['arm']==arm and x['both_feasible']]
        for metric in ['resource_cost_cny_change','grid_kwh_change','peak_kw_change']:
            data=np.array([x[metric] for x in p])
            if len(data)>=2:
                boot=rng.choice(data,size=(10000,len(data)),replace=True).mean(axis=1)
                uncertainty.append(dict(arm=arm,metric=metric,n=len(data),mean=float(data.mean()),
                    bootstrap_low=float(np.quantile(boot,.025)),bootstrap_high=float(np.quantile(boot,.975)),
                    interpretation='Conditional on declared random SOC/departure perturbation generator; not field-population uncertainty'))
    write_csv(out/'input_uncertainty.csv',uncertainty)
    for path in source_files:
        if hashlib.sha256(path.read_bytes()).hexdigest()!=frozen[str(path.relative_to(ROOT))]:raise RuntimeError('Source changed during experiment; rerun required')
    manifest['summary_files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,default=ROOT/'experiments/scientific/final_results')
    p.add_argument('--main-only',action='store_true');args=p.parse_args();run(args.output_dir,not args.main_only)

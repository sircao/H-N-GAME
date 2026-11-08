"""Recheck all frozen run files, inputs and physical results independently."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from scientific_io import load_json_gz
from scientific_audit import check,compare_metrics

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(out):
    manifest=json.loads((out/'manifest.json').read_text())
    for name,value in manifest['source_hashes'].items():
        if sha(ROOT/name)!=value:raise ValueError('Source changed since run: '+name)
    canonical=out.parent/'canonical_scenario.json'
    if sha(canonical)!=manifest['canonical_sha256']:raise ValueError('Canonical input changed')
    for name,value in manifest['summary_files'].items():
        if sha(out/name)!=value:raise ValueError('Summary changed: '+name)
    total_vehicles=total_trips=feasible=optimal=infeasible=other=0;maximum=0.;groups=defaultdict(list)
    cached_hash=None;spec=None;details=[]
    for i,record in enumerate(manifest['runs']):
        folder=out/record['run_id']
        for name,value in record['files'].items():
            if sha(folder/name)!=value:raise ValueError('Run file changed: '+str(folder/name))
        filehash=record['files']['input.json.gz']
        if filehash!=cached_hash:spec=load_json_gz(folder/'input.json.gz');cached_hash=filehash
        result=json.loads((folder/'result.json').read_text())
        if result['status'] in ['optimal','feasible_rule']:
            events=load_json_gz(folder/'events.json.gz');checked=check(spec,events)
            compare_metrics(result|{'load_kw':json.loads((folder/'load.json').read_text())},checked['metrics'])
            feasible+=1;optimal+=result['status']=='optimal';total_vehicles+=checked['vehicles'];total_trips+=checked['trips']
            maximum=max(maximum,checked['max_energy_residual_kwh'])
            details.append(dict(run_id=record['run_id'],passed=True,vehicles=checked['vehicles'],trips=checked['trips']))
            if result['status']=='optimal' and (result['mip_gap']>1e-8+1e-10 or result['constraint_residual']>1e-6):raise ValueError('Solver quality mismatch')
        elif result['status']=='infeasible':infeasible+=1
        else:other+=1
        if result['experiment'] in ['E1','E5','E5_random']:
            groups[result['experiment'],result['scenario'],result['seed']].append((result,filehash))
        if i%10==0:print('Independent full-day audit',i+1,'/',len(manifest['runs']),flush=True)
    for key,group in groups.items():
        if len(group)!=4 or len({h for r,h in group})!=1:raise ValueError('Unequal/incomplete four-arm input')
        joint=next(r for r,h in group if r['arm']=='joint')
        if joint['status']=='optimal':
            for r,h in group:
                if r['status'] in ['optimal','feasible_rule'] and joint['user_objective_cny']>r['user_objective_cny']+1e-5:
                    raise ValueError('Joint feasible set/optimum ordering violated')
    result=dict(passed=True,runs=len(manifest['runs']),feasible=feasible,certified_optimal=optimal,infeasible=infeasible,
                other_statuses=other,audited_vehicle_days=total_vehicles,audited_trips=total_trips,
                equal_input_four_arm_groups=len(groups),max_energy_residual_kwh=maximum,
                scope='Frozen finite simulation contracts; no empirical or coupled-equilibrium certification',details=details)
    (out/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return {k:v for k,v in result.items() if k!='details'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=ROOT/'experiments/scientific/final_results')
    print(json.dumps(audit(p.parse_args().results),indent=2))

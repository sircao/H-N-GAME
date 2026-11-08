"""Independent arithmetic/constraint audit; does not import the optimizer."""
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import argparse

TOL=1e-6


def require(condition,message):
    if not condition:raise ValueError(message)


def check_run(run):
    tasks={t['task_id']:t for t in run['tasks']}
    stations=run['stations'];dt=run['dt'];retail=run['retail'];wholesale=run['wholesale']
    m=run['metrics'];plan=run['plan']
    if m['status']!='optimal':
        require(not plan,'Nonoptimal run exports a plan')
        return None
    require(len(plan)==len(tasks) and {p['task_id'] for p in plan}==set(tasks),'Task service mismatch')
    usage={};grid=traction=travel=bill=purchase=loss=0.;max_balance=0.
    for p in plan:
        t=tasks[p['task_id']]
        require(p['vehicle_id']==t['vehicle_id'] and p['station_id']==t['station_id'],'Vehicle/station mismatch')
        choices=t['routes'] if run['route_enabled'] else t['routes'][:1]
        r=next((r for r in choices if r['route_id']==p['route_id']),None)
        require(r is not None,'Route not permitted')
        energy=max(0.,(t['terminal_kwh']+r['traction_kwh']-t['initial_kwh'])/t['efficiency'])
        close=lambda a,b:abs(a-b)<=TOL
        require(close(energy,p['grid_kwh']) and close(r['traction_kwh'],p['traction_kwh']),'Grid/traction mismatch')
        before=t['initial_kwh']+t['efficiency']*energy
        after=before-r['traction_kwh']
        require(before<=t['battery_kwh']+TOL and after>=t['terminal_kwh']-TOL,'Battery bound violated')
        require(close(before,p['pretrip_kwh']) and close(after,p['final_kwh']),'Battery ledger mismatch')
        require(close(p['initial_kwh'],t['initial_kwh']),'Initial inventory mismatch')
        require(close(p['travel_h'],r['travel_h']) and close(p['arrival'],t['departure']+r['travel_h']), 'Travel mismatch')
        require(p['arrival']<=t['deadline']+TOL,'Deadline violated')
        h=p['slot']
        if energy>TOL:
            require(type(h)is int and 0<=h<len(retail),'Invalid charge slot')
            require(h*dt>=t['parking_start']-TOL and (h+1)*dt<=min(t['parking_end'],t['departure'])+TOL,'Parking window violated')
            require(energy/dt<=t['max_power_kw']+TOL,'Vehicle power violated')
            if not run['charge_enabled']:
                first=next((s for s in range(len(retail)) if s*dt>=t['parking_start']-TOL and (s+1)*dt<=t['parking_end']+TOL),None)
                require(h==first,'Baseline charging policy violated')
            load,count=usage.get((t['station_id'],h),(0.,0))
            usage[t['station_id'],h]=(load+energy/dt,count+1)
            bill+=energy*retail[h];purchase+=energy*wholesale[h]
        else:require(h==-1,'Zero energy must not occupy a connector')
        grid+=energy;traction+=r['traction_kwh'];travel+=r['travel_h'];loss+=energy*(1-t['efficiency'])
        max_balance=max(max_balance,abs(t['initial_kwh']+t['efficiency']*energy-r['traction_kwh']-p['final_kwh']))
    loads=[0.]*len(retail)
    for (s,h),(power,count) in usage.items():
        require(power<=stations[s]['power_kw']+TOL and count<=stations[s]['connectors'],'Station power/occupancy violated')
        loads[h]+=power
    carbon=run['gamma']*grid
    expected=dict(completion_rate=1.,late_tasks=0,grid_kwh=grid,traction_kwh=traction,travel_h=travel,
                  loss_kwh=loss,bill_cny=bill,purchase_cny=purchase,revenue_cny=bill,profit_cny=bill-purchase,
                  carbon_kg=carbon,carbon_payment_cny=run['tau']*carbon/1000,
                  resource_cost_cny=run['beta']*travel+purchase,
                  objective_cny=run['beta']*travel+bill+run['tau']*carbon/1000,
                  peak_kw=max(loads),valley_kw=min(loads),mean_kw=sum(loads)/len(loads),
                  load_factor=(sum(loads)/len(loads))/max(loads) if max(loads)>0 else 0.)
    for key,value in expected.items():
        require(abs(m[key]-value)<=TOL*max(1,abs(value)),f'Metric mismatch: {key}')
    require(abs(sum(loads)*dt-grid)<=TOL,'Load integral mismatch')
    return dict(tasks=len(plan),max_energy_residual_kwh=max_balance)


def independent_reference(run):
    """Reconstruct tiny candidate sets without calling production option code."""
    all_options=[];dt=run['dt']
    for t in run['tasks']:
        options=[]
        for r in t['routes'] if run['route_enabled'] else t['routes'][:1]:
            e=max(0.,(t['terminal_kwh']+r['traction_kwh']-t['initial_kwh'])/t['efficiency'])
            if (t['initial_kwh']+t['efficiency']*e>t['battery_kwh']+TOL or
                    e>t['max_power_kw']*dt+TOL or t['departure']+r['travel_h']>t['deadline']+TOL):continue
            slots=[-1] if e<=TOL else [h for h in range(len(run['retail'])) if h*dt>=t['parking_start']-TOL and (h+1)*dt<=t['parking_end']+TOL]
            if not run['charge_enabled']:slots=slots[:1]
            options.extend((t['station_id'],h,e,run['beta']*r['travel_h']+(run['retail'][h] if h>=0 else 0)*e+run['tau']*run['gamma']*e/1000) for h in slots)
        all_options.append(options)
    require(math.prod(map(len,all_options))<=1_000_000,'Reference too large')
    best=math.inf
    for combo in itertools.product(*all_options):
        load={};count={}
        for s,h,e,c in combo:
            if h>=0:load[s,h]=load.get((s,h),0)+e/dt;count[s,h]=count.get((s,h),0)+1
        if any(p>run['stations'][s]['power_kw']+TOL or count[s,h]>run['stations'][s]['connectors'] for (s,h),p in load.items()):continue
        best=min(best,sum(p[3] for p in combo))
    return best


def audit(root):
    runs=json.loads((root/'runs.json').read_text());records=0;max_residual=0.;tiny=0
    for run in runs:
        checked=check_run(run)
        if checked:records+=checked['tasks'];max_residual=max(max_residual,checked['max_energy_residual_kwh'])
        if len(run['tasks'])<=3:
            expected=independent_reference(run);m=run['metrics']
            require((math.isinf(expected) and m['status']=='infeasible') or
                    (m['status']=='optimal' and abs(m['objective_cny']-expected)<=TOL),'Independent reference mismatch')
            tiny+=1
    # Equal inputs across each four-arm comparison.
    groups={}
    for run in runs:
        if run['experiment'] in ('E1','E5'):groups.setdefault((run['experiment'],run['scenario']),[]).append(run)
    for key,group in groups.items():
        require(len(group)==4,'Incomplete four-arm comparison')
        for r in group[1:]:
            for k in ['tasks','stations','retail','wholesale','dt','beta','gamma','tau']:
                require(r[k]==group[0][k],f'Unequal comparison input: {k}')
    manifest=json.loads((root/'artifact_manifest.json').read_text())
    project=Path(__file__).resolve().parents[1]
    for name,expected in manifest['source_hashes'].items():
        require(hashlib.sha256((project/name).read_bytes()).hexdigest()==expected,f'Source changed since run: {name}')
    for name,expected in manifest['outputs'].items():
        require(hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,f'Artifact changed: {name}')
    result=dict(passed=True,runs=len(runs),feasible=sum(r['metrics']['status']=='optimal' for r in runs),
                infeasible=sum(r['metrics']['status']=='infeasible' for r in runs),
                other_statuses=sum(r['metrics']['status'] not in ('optimal','infeasible') for r in runs),
                audited_vehicle_records=records,independent_tiny_references=tiny,
                paired_four_arm_groups=len(groups),max_energy_residual_kwh=max_residual,
                limitations='Controlled original-network-derived tasks with declared assumptions; not full original-day or independent Unreal validation.')
    (root/'audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=Path(__file__).parent/'results')
    print(json.dumps(audit(p.parse_args().results),indent=2))

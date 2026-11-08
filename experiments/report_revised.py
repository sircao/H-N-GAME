"""Generate auditable experiment tables and a standalone figure."""
import csv
import hashlib
import json
from pathlib import Path
import argparse
import os
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).parent/'.matplotlib'))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def report(root):
    runs=json.loads((root/'runs.json').read_text())
    audit=json.loads((root/'audit.json').read_text())
    spec=json.loads((root/'scenario_manifest.json').read_text())
    validation=json.loads((root/'input_validation.json').read_text())
    e1=[r for r in runs if r['experiment']=='E1']
    names={(False,False):'Baseline',(True,False):'Route only',(False,True):'Charge only',(True,True):'Joint'}
    lines=['# Revised Game experiment results','',
           '**Scope:** controlled tasks derived from the saved Game network and 800 baseline vehicles. This is a centralized route/charging study, not full-day Game equilibrium or independent Unreal execution validation.','',
           f"Input batch: `{spec['stamp']}`. Source rows: {validation['rows']:,}; source time coverage: {validation['observed_sim_hour']}. Accounting horizon for the constructed study: 00:00–24:00.",'',
           'Authoritative source fields still absent: '+', '.join(validation['missing_authoritative_fields'])+'.','',
           '## Fixed-price four-arm comparison (E1)','',
           '|Arm|Status|Travel h|Traction kWh|Grid kWh|Peak kW|User bill CNY|Resource cost CNY|CO2 kg|',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    ledger=[];distributions=[]
    for r in e1:
        m=r['metrics'];label=names[r['route_enabled'],r['charge_enabled']]
        if m['status']=='optimal':
            lines.append('|'+label+'|optimal|'+'|'.join(f'{m[k]:.6f}' for k in ['travel_h','traction_kwh','grid_kwh','peak_kw','bill_cny','resource_cost_cny','carbon_kg'])+'|')
        else:lines.append(f"|{label}|{m['status']}|—|—|—|—|—|—|—|")
    baseline=e1[0]['metrics'];joint=e1[-1]['metrics']
    if baseline['status']==joint['status']=='optimal':
        lines+=['',f"Joint versus baseline: resource cost changes by {(joint['resource_cost_cny']/baseline['resource_cost_cny']-1)*100:.4f}%; grid energy changes by {(joint['grid_kwh']/baseline['grid_kwh']-1)*100:.4f}%. These effects apply only to the constructed task contract.",
                'Charging-only has the same energy and bill as baseline here. Peak power can increase because the objective values time and user cost, not peak load; equal-cost schedules can have different load shapes. A lower bill or a larger feasible set does not guarantee peak reduction.']
    for r in runs:
        taskmap={t['task_id']:t for t in r['tasks']}
        for p in r['plan']:
            t=taskmap[p['task_id']];grid=p['grid_kwh'];h=p['slot']
            bill=grid*r['retail'][h] if h>=0 else 0
            ledger.append(dict(run_id=r['run_id'],experiment=r['experiment'],**p,
                               terminal_requirement_kwh=t['terminal_kwh'],efficiency=t['efficiency'],
                               loss_kwh=grid*(1-t['efficiency']),user_bill_cny=bill,
                               carbon_kg=grid*r['gamma'],energy_residual_kwh=t['initial_kwh']+grid*t['efficiency']-p['traction_kwh']-p['final_kwh']))
        if r['plan']:
            costs=[r['beta']*p['travel_h']+(r['retail'][p['slot']] if p['slot']>=0 else 0)*p['grid_kwh']+r['tau']*r['gamma']*p['grid_kwh']/1000 for p in r['plan']]
            distributions.append(dict(run_id=r['run_id'],user_cost_p50=float(np.quantile(costs,.5)),user_cost_p95=float(np.quantile(costs,.95)),user_cost_max=max(costs)))
    lines+=['','## Price candidates (E2)','',
            'Finite retail-price candidates; each candidate recomputes centralized dispatch. Carbon price stays external. No continuous-price or Stackelberg optimality is claimed.','',
            '|Candidate|Status|User bill CNY|Operator profit CNY|Resource cost CNY|',
            '|---|---|---:|---:|---:|']
    price_runs=[r for r in runs if r['experiment']=='E2']
    for r in price_runs:
        m=r['metrics']
        vals='|'.join(f'{m[k]:.6f}' for k in ['bill_cny','profit_cny','resource_cost_cny']) if m['status']=='optimal' else '—|—|—'
        lines.append(f"|{r['scenario']}|{m['status']}|{vals}|")
    feasible=[r for r in price_runs if r['metrics']['status']=='optimal']
    if feasible:
        chosen=max(feasible,key=lambda r:r['metrics']['profit_cny'])
        lines+=['',f"Highest profit among tested candidates: `{chosen['scenario']}`; ties use candidate order."]
    groups={}
    for r in runs:
        if r['experiment']=='E5':groups.setdefault(r['scenario'],[]).append(r)
    effects=[]
    for name,group in groups.items():
        base=next(r for r in group if not r['route_enabled'] and not r['charge_enabled'])
        for r in group:
            if r is base:continue
            b,m=base['metrics'],r['metrics']
            status='both_feasible' if b['status']==m['status']=='optimal' else 'baseline_infeasible' if b['status']=='infeasible' and m['status']=='optimal' else 'treatment_infeasible' if b['status']=='optimal' and m['status']=='infeasible' else 'both_infeasible' if b['status']==m['status']=='infeasible' else 'solver_failure_or_limit'
            e=dict(scenario=name,arm=names[r['route_enabled'],r['charge_enabled']],comparison_status=status)
            if status=='both_feasible':
                e['resource_cost_change_cny']=m['resource_cost_cny']-b['resource_cost_cny']
                e['grid_change_kwh']=m['grid_kwh']-b['grid_kwh']
                def costs(run):
                    return {p['task_id']:run['beta']*p['travel_h']+(run['retail'][p['slot']] if p['slot']>=0 else 0)*p['grid_kwh']+run['tau']*run['gamma']*p['grid_kwh']/1000 for p in run['plan']}
                cb,ct=costs(base),costs(r)
                e['fraction_users_worse_off']=sum(ct[k]>cb[k]+1e-6 for k in cb)/len(cb)
            effects.append(e)
    lines+=['','## Validation and limits','',
            f"Audit passed: **{audit['passed']}**. Runs: {audit['runs']}; feasible: {audit['feasible']}; infeasible: {audit['infeasible']}; other solver statuses: {audit['other_statuses']}.",
            f"Audited task records: {audit['audited_vehicle_records']:,}; independent small-case checks: {audit['independent_tiny_references']}; equal-input four-arm groups: {audit['paired_four_arm_groups']}.",
            f"Maximum energy-balance residual: {audit['max_energy_residual_kwh']:.3g} kWh.",'',
            'Scenario changes are deterministic sensitivity cases; no confidence intervals or statistical significance are claimed. Infeasible settings retain their status and have no zero-filled cost. The original MNL/BPR diagnostics are in `original_mnl_diagnostics.csv`; they do not validate the centralized charging model as an equilibrium.','',
            'At fixed carbon intensity, equal grid energy gives equal emissions. Retail revenue and user payment are transfers; operator profit is not a physical resource saving.','',
            '## Explicit assumptions','']+['- '+a for a in spec['assumptions']]
    lines+=['','## Remaining original-project requirements','',
            'Supply authoritative per-task parking windows, deadlines, terminal energy and station access/efficiency before claiming the original full-day experiment is complete. Independent execution observations are still required for E6; opening Unreal does not supply those observations.']
    (root/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    def write(name,rows):
        if not rows:return
        keys=list(dict.fromkeys(k for r in rows for k in r))
        with (root/name).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rows)
    write('energy_service_ledger.csv',ledger);write('user_distribution.csv',distributions);write('paired_effects.csv',effects)
    ok=[r for r in e1 if r['metrics']['status']=='optimal']
    if ok:
        fig,axes=plt.subplots(1,3,figsize=(13,4),layout='constrained')
        labels=[names[r['route_enabled'],r['charge_enabled']] for r in ok]
        for ax,key,label in zip(axes,['resource_cost_cny','grid_kwh','peak_kw'],['Resource cost (CNY)','Grid energy (kWh)','Peak EV load (kW)']):
            ax.bar(labels,[r['metrics'][key] for r in ok],color=['#64748b','#2583b8','#39a583','#db9b32'][:len(ok)])
            ax.set_ylabel(label);ax.tick_params(axis='x',rotation=30);ax.spines[['top','right']].set_visible(False)
        fig.suptitle('Game-derived controlled tasks — explicit assumptions; fixed route times')
        fig.savefig(root/'overview.png',dpi=160);fig.savefig(root/'overview.svg');plt.close(fig)
    manifest_path=root/'artifact_manifest.json'
    manifest=json.loads(manifest_path.read_text())
    project=Path(__file__).resolve().parents[1]
    for name in ['audit_revised.py','report_revised.py','test_revised.py']:
        path=Path(__file__).with_name(name)
        manifest['source_hashes'][str(path.relative_to(project))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ['energy_service_ledger.csv','paired_effects.csv','user_distribution.csv','RESULTS.md','overview.png','overview.svg']:
        path=root/name
        if path.exists():manifest['outputs'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    return root/'RESULTS.md'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=Path(__file__).parent/'results')
    print(report(p.parse_args().results))

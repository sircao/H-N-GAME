"""Post-hoc diagnostic: peak load is not fixed by a cost-only optimum.

Uses the frozen production constraint matrix, adds a primary-cost bound, then
optimizes peak/minimum or load in the prespecified baseline peak slot. This is
a diagnostic, not a preregistered treatment or a replacement of primary results.
"""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import csc_matrix,hstack,vstack,coo_matrix
import scientific_model as model
from scientific_audit import check,compare_metrics
from scientific_io import load_json_gz,save_json_gz


def run(folder):
    spec=load_json_gz(folder/'input.json.gz')
    reference=json.loads((folder/'result.json').read_text())
    primary_bound=reference['user_objective_cny'];dt=spec['dt'];qslots={};cursor=0
    for v in spec['vehicles']:
        for t in v['trips']:cursor+=sum(r['time_h']<=t['deadline']-t['departure']+1e-6 for r in t['routes'])
        for h in model.charge_slots(spec,v):qslots[cursor]=h;cursor+=2
    baseline=json.loads((folder.parent/'E1_reference_baseline/load.json').read_text())
    peak_slot=int(np.argmax(baseline));details=[]
    for mode in ['minimum_peak','maximum_baseline_peak_slot']:
        secondary={}
        def solve(c,*,integrality,bounds,constraints,options):
            n=len(c)
            if n!=cursor:raise ValueError('Variable order changed')
            a=hstack([constraints.A,csc_matrix((constraints.A.shape[0],1))],format='csc')
            primary=np.r_[c,0.]
            rows=[];cols=[];vals=[]
            for idx,h in qslots.items():rows.append(h);cols.append(idx);vals.append(1/dt)
            for h in range(len(spec['retail'])):rows.append(h);cols.append(n);vals.append(-1.)
            peak=coo_matrix((vals,(rows,cols)),shape=(len(spec['retail']),n+1)).tocsc()
            a=vstack([a,csc_matrix(primary.reshape(1,-1)),peak],format='csc')
            lo=np.r_[constraints.lb,-np.inf,np.full(len(spec['retail']),-np.inf)]
            hi=np.r_[constraints.ub,primary_bound+1e-6,np.zeros(len(spec['retail']))]
            objective=np.zeros(n+1)
            if mode=='minimum_peak':objective[-1]=1
            else:
                for idx,h in qslots.items():
                    if h==peak_slot:objective[idx]=-1/dt
            res=milp(objective,integrality=np.r_[integrality,0],bounds=Bounds(np.r_[bounds.lb,0],np.r_[bounds.ub,np.inf]),
                     constraints=LinearConstraint(a,lo,hi),options={'time_limit':120.,'mip_rel_gap':1e-8})
            secondary.update(status=int(res.status),secondary_mip_gap=float(res.mip_gap) if res.status==0 else None)
            if res.status==0:
                res.x=res.x[:-1]
                value=float(c@res.x)
                res.mip_dual_bound=reference['dual_bound_cny']
                res.mip_gap=max(0.,value-res.mip_dual_bound)/max(abs(value),1e-12)
            return res
        with patch.object(model,'milp',solve):status,events=model.optimize(spec)
        row=dict(mode=mode,post_hoc=True,primary_cost_tolerance_cny=1e-6,baseline_peak_slot=peak_slot,**secondary)
        if events:
            m=model.metrics(spec,events);a=check(spec,events);compare_metrics(m,a['metrics'])
            row.update(primary_user_objective_cny=m['user_objective_cny'],peak_kw=m['peak_kw'],target_slot_load_kw=m['load_kw'][peak_slot])
            save_json_gz(folder/(mode+'_events.json.gz'),events)
        details.append(row);print(row,flush=True)
    (folder/'peak_tie_diagnostic.json').write_text(json.dumps(details,indent=2)+'\n')
    return details


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_dir',type=Path);run(p.parse_args().run_dir)

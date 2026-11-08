"""Render standalone scientific figures from audited results."""
import argparse
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from verify_results import audit


def draw(directory):
    audit(directory)
    with (directory/'metrics.csv').open(encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    with (directory/'paired_effects.csv').open(encoding='utf-8-sig') as f:
        paired=list(csv.DictReader(f))
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    fig.suptitle('H-GAME controlled synthetic experiments | E1-E5',fontsize=17,fontweight='bold')
    colors=['#8c9aa9','#356a96','#43a08b','#db9c47']
    labels=['Baseline','Route only','Charge only','Joint']
    main=[r for r in rows if r['experiment']=='E1']
    x=np.arange(4)
    a=axes[0,0]
    a.bar(x,[float(r['resource_cost_cny']) for r in main],color=colors)
    a.set(xticks=x,xticklabels=labels,ylabel='Time value + wholesale cost (CNY)',title='E1 | Physical resource cost')
    a=axes[0,1]
    a.bar(x,[float(r['grid_kwh']) for r in main],color=colors)
    a.set(xticks=x,xticklabels=labels,ylabel='Grid energy (kWh)',title='E3 | Faster routes consume more energy')
    a=axes[1,0]
    e2=[r for r in rows if r['experiment']=='E2']
    for i,(field,label) in enumerate([('bill_cny','User payment'),('profit_cny','Operator profit'),('resource_cost_cny','Resource cost')]):
        a.bar(np.arange(2)+.24*(i-1),[float(r[field]) for r in e2],width=.24,label=label)
    a.set(xticks=[0,1],xticklabels=['Fixed tariff','Tariff search'],ylabel='CNY',title='E2 | Profit increase is not resource saving')
    a.legend(fontsize=8)
    a=axes[1,1]
    data=[r for r in paired if r['arm']=='route1_charge1']
    names=[r['case'].replace('_',' ') for r in data]
    for i,r in enumerate(data):
        if int(r['paired_n']):
            mean,lo,hi=[float(r[k]) for k in ('mean_saving_cny','min_saving_cny','max_saving_cny')]
            a.errorbar(mean,i,xerr=[[mean-lo],[hi-mean]],fmt='o',capsize=3,color='#356a96')
            a.annotate(' n='+r['paired_n'],(hi+.2,i),va='center',fontsize=8)
        else:
            recovered=int(r['baseline_infeasible_only'])
            both=int(r['both_infeasible'])
            label=f'Joint feasible / baseline infeasible: {recovered}/10' if recovered else f'Both infeasible: {both}/10'
            a.text(.5,i,label,va='center',fontsize=8,color='#a04b43')
    a.set(yticks=np.arange(len(data)),yticklabels=names,xlabel='Baseline - joint resource cost (CNY)',
          title='E5 | Paired mean and observed range (not CI)',xlim=(-1,34))
    a.invert_yaxis()
    fig.text(.01,.005,'Synthetic centralized scheduling; external congestion; fixed carbon factor. No real-city or Unreal validation.',fontsize=9,color='#555555')
    for suffix in ('png','svg'):
        fig.savefig(directory/f'experiment_overview.{suffix}',dpi=180,bbox_inches='tight')
    plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-dir',type=Path,default=Path(__file__).parent/'results')
    draw(parser.parse_args().results_dir)

"""Scientific figure exports from the frozen final experiment summaries."""
from pathlib import Path
import json
import os
import numpy as np
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).parent/'.matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

out=Path(__file__).parent
data=json.loads((out/'visualization_data.json').read_text())
arms=data['e1'];base=arms[0]
names={'baseline':'Baseline','route_only':'Route only','charge_only':'Charging only','joint':'Joint'}
colors={'baseline':'#677786','route_only':'#cc8437','charge_only':'#4a9370','joint':'#3e78b8'}
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})

def save(fig,name):
    fig.savefig(out/(name+'.png'),dpi=180,bbox_inches='tight')
    fig.savefig(out/(name+'.svg'),bbox_inches='tight')
    plt.close(fig)


fig=plt.figure(figsize=(13,8),layout='constrained')
grid=fig.add_gridspec(2,3,height_ratios=[1,1.15])
for i,(key,label) in enumerate([('user_objective_cny','User objective change (CNY)'),('resource_cost_cny','Resource cost change (CNY)'),('grid_kwh','Grid energy change (kWh)')]):
    ax=fig.add_subplot(grid[0,i]);values=[r[key]-base[key] for r in arms[1:]]
    ax.barh([names[r['arm']] for r in arms[1:]],values,color=[colors[r['arm']] for r in arms[1:]],alpha=.8)
    ax.axvline(0,color='#9b9b9b',lw=.7);ax.set_xlabel(label);ax.invert_yaxis()
    for j,value in enumerate(values):ax.annotate(f'{value:+.4f}',(value,j),xytext=(5,0),textcoords='offset points',va='center')
    low,high=min(values+[0]),max(values+[0]);span=max(high-low,.1);ax.set_xlim(low-.15*span,high+.45*span)
ax=fig.add_subplot(grid[1,:])
styles=['--',':','-.','-']
for r,style in zip(arms,styles):
    ax.step(np.arange(97)/4,r['load']+[r['load'][-1]],where='post',label=names[r['arm']],color=colors[r['arm']],ls=style,lw=1.5)
ax.set(xlim=(0,24),xlabel='Simulation clock (hour)',ylabel='EV charging power (kW)')
ax.set_xticks(range(0,25,4));ax.legend(ncol=4,frameon=False,loc='upper right')
fig.suptitle('Four-arm comparison · full finite Game day\n800 vehicles / 6,084 trips; fixed tariffs; equal per-vehicle initial and terminal energy',fontsize=13)
save(fig,'01-four-arm-and-load')

fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
price=data['e2'];x=np.arange(3)
for offset,key,label,color in [(-.24,'user_bill_cny','User electricity bill','#3e78b8'),(0,'operator_profit_cny','Operator profit','#4a9370'),(.24,'resource_cost_cny','Resource cost','#8b8b8b')]:
    axes[0,0].bar(x+offset,[r[key]-price[0][key] for r in price],width=.22,label=label,color=color)
axes[0,0].set_xticks(x,['Fixed','Uniform +0.10','Peak +0.20']);axes[0,0].set_ylabel('Change vs fixed retail candidate (CNY)');axes[0,0].legend(frameon=False)
axes[0,0].set_title('Pricing: payment transfer versus resources')
scenarios=[r for r in data['scenarios'] if r['change'] is not None]
labels={'single_route':'Single route','short_parking':'Short parking','tight_capacity':'Tight capacity','high_travel_time':'Higher travel time','flat_tariff':'Flat tariff','auxiliary_energy':'Auxiliary energy'}
axes[0,1].barh([labels[r['name']] for r in scenarios],[r['change'] for r in scenarios],color=colors['joint'],alpha=.8)
axes[0,1].invert_yaxis();axes[0,1].set_xlabel('Joint − baseline resource cost (CNY)');axes[0,1].set_title('Scenario sensitivity · zero capacity: all infeasible')
unc=[r for r in data['uncertainty'] if r['metric']=='resource_cost_cny_change']
for i,r in enumerate(unc):
    axes[1,0].errorbar(r['mean'],i,xerr=[[max(0,r['mean']-r['bootstrap_low'])],[max(0,r['bootstrap_high']-r['mean'])]],fmt='o',capsize=4,color=colors[r['arm']])
axes[1,0].set_yticks(range(3),[names[r['arm']] for r in unc]);axes[1,0].invert_yaxis();axes[1,0].axvline(0,color='#9b9b9b',lw=.7)
axes[1,0].set_xlabel('Resource-cost change (CNY)');axes[1,0].set_title('10 paired input cases · mean and 95% bootstrap interval')
joint=arms[-1];alternative=next(r for r in data['peak'] if r['status']==0)
axes[1,1].bar(['Primary joint plan','Maximum baseline-slot load'],[joint['peak_kw'],alternative['peak_kw']],color=[colors['joint'],'#8b8b8b'])
axes[1,1].set_ylabel('Peak EV load (kW)');axes[1,1].set_title('Post-hoc ambiguity · same user objective, different peaks')
axes[1,1].text(.5,-.16,'Minimum-peak diagnostic: 120 s limit; no certified result',transform=axes[1,1].transAxes,ha='center',va='top',fontsize=9)
fig.suptitle('Economic transfers, conditions and non-unique cost optima\nExplicit simulation inputs; intervals do not describe real-city population uncertainty',fontsize=13)
save(fig,'02-pricing-and-conditions')

fig=plt.figure(figsize=(13,8),layout='constrained');grid=fig.add_gridspec(2,2,height_ratios=[1.1,1])
for col,(key,ylabel,title) in enumerate([('late_trips','Late trips (count)','Deadline failures'),('terminal_energy_error_max_abs_kwh','Maximum absolute terminal deviation (kWh)','Terminal storage under execution stress')]):
    ax=fig.add_subplot(grid[0,col])
    for i,severity in enumerate([0,1,4]):
        group=[r for r in data['stress'] if r['severity']==severity];values=[r[key] for r in group]
        ax.scatter(np.linspace(i-.06,i+.06,len(values)),values,color=colors['joint'],s=25,alpha=.7)
        ax.plot([i,i],[min(values),max(values)],color=colors['joint'],lw=1)
    ax.set_xticks([0,1,2],['None','Moderate (1)','Severe (4)']);ax.set_xlabel('Artificial disturbance severity');ax.set_ylabel(ylabel);ax.set_title(title)
ax=fig.add_subplot(grid[1,:]);ax.axis('off');rt=data['runtime'];a=data['audit']
rows=[['Primary settings',f"{a['runs']} = {a['feasible']} feasible + {a['infeasible']} infeasible",'Audited'],
      ['Trip records',f"{a['audited_trips']:,}",'Audited'],['Tests',str(data['tests']),'Passed'],
      ['Energy-closure residual',f"{a['max_energy_residual_kwh']:.3g} kWh",'Passed'],
      ['Unreal battery error',f"{rt['max_battery_inventory_error_kwh']:.3g} kWh",'Limit: 0.001 kWh'],
      ['Unreal position error',f"{rt['max_position_error_cm']:.4g} cm",'Limit: 2 cm']]
table=ax.table(cellText=rows,colLabels=['Evidence','Observed','Result / acceptance limit'],loc='center',cellLoc='left',colLoc='left',colWidths=[.3,.4,.3]);table.auto_set_font_size(False);table.set_fontsize(10);table.scale(1,1.5)
for cell in table.get_celld().values():cell.set_edgecolor('#cccccc');cell.set_linewidth(.4)
fig.suptitle('Execution stress and independent audit evidence\nCompiled replay consistency; artificial stress; no independent city-traffic validation claim',fontsize=13)
save(fig,'03-execution-and-audits')
print('Saved three scientific figures as PNG and SVG in',out.resolve())

"""Reproducible publication figures, using only frozen data in this package."""
from pathlib import Path
import csv
import hashlib
import json
import os
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent
RAW = DATA / '01_final_results'
os.environ.setdefault('MPLCONFIGDIR', str(HERE / '.matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':9,
    'axes.titlesize':10, 'axes.labelsize':9, 'legend.fontsize':8,
    'axes.spines.top':False, 'axes.spines.right':False,
    'axes.linewidth':0.7, 'xtick.direction':'out', 'ytick.direction':'out',
    'pdf.fonttype':42, 'ps.fonttype':42, 'svg.fonttype':'none',
    'savefig.facecolor':'white'})
COLORS = ['#737B85','#D58B25','#009E73','#3579B8']
ARMS = ['baseline','route_only','charge_only','joint']
LABELS = ['Baseline','Route only','Charging only','Joint']
sources = set()
outputs = []

def read_csv(path):
    sources.add(path)
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def read_json(path):
    sources.add(path)
    return json.loads(path.read_text(encoding='utf-8'))

def save(fig,name):
    for ext in ['png','pdf','svg']:
        path=HERE/f'{name}.{ext}'
        fig.savefig(path,dpi=600 if ext=='png' else None,bbox_inches='tight',pad_inches=.08)
        outputs.append(path)
    plt.close(fig)

def panel(ax,letter,title):
    ax.set_title(f'({letter}) {title}',loc='left',pad=10,fontweight='bold')
    ax.grid(axis='y',alpha=.16,lw=.5)
    ax.set_axisbelow(True)

rows=read_csv(RAW/'metrics.csv')
e1=[next(r for r in rows if r['run_id']==f'E1_reference_{arm}') for arm in ARMS]
b=e1[0]

# Small changes are shown as signed differences, without truncated bar baselines.
fig,axes=plt.subplots(1,3,figsize=(10.2,3.25),layout='constrained')
for ax,letter,key,title,unit in zip(axes,'abc',
        ['user_objective_cny','resource_cost_cny','grid_kwh'],
        ['User objective','Resource cost','Grid energy'],['CNY','CNY','kWh']):
    vals=[float(r[key])-float(b[key]) for r in e1[1:]]
    ax.barh(np.arange(3),vals,color=COLORS[1:],height=.55)
    ax.set_yticks(np.arange(3),LABELS[1:]);ax.invert_yaxis()
    ax.axvline(0,color='#333333',lw=.7)
    ax.set_xlabel(f'Change from baseline ({unit})')
    panel(ax,letter,title)
    span=max(max(vals+[0])-min(vals+[0]),.01)
    ax.set_xlim(min(vals+[0])-.39*span,max(vals+[0])+.42*span)
    for j,v in enumerate(vals):
        ax.annotate(f'{v:+.4f}',(v,j),xytext=(-5 if v<0 else 5,0),
                    textcoords='offset points',ha='right' if v<0 else 'left',va='center',fontsize=8)
save(fig,'Fig01_four_arm_effects')

fig,axes=plt.subplots(1,2,figsize=(9,3.35),layout='constrained',width_ratios=[1.6,1])
for r,label,color,style in zip(e1,LABELS,COLORS,['-',':','--','-.']):
    load=read_json(RAW/r['run_id']/'load.json')
    assert len(load)==96 and abs(sum(load)*.25-float(r['grid_kwh']))<1e-6
    axes[0].stairs(load,np.arange(97)/4,label=label,color=color,ls=style,lw=1.25)
axes[0].set(xlim=(0,24),xlabel='Simulation time (h)',ylabel='EV charging power (kW)')
axes[0].set_xticks(range(0,25,4));axes[0].legend(frameon=False,ncol=2)
panel(axes[0],'a','Full-day charging profiles')
axes[1].bar(np.arange(4),[float(r['peak_kw']) for r in e1],color=COLORS,width=.6)
axes[1].set_xticks(np.arange(4),['Baseline','Route\nonly','Charging\nonly','Joint'])
axes[1].set(ylabel='Point-solution peak (kW)',ylim=(0,850))
for i,r in enumerate(e1): axes[1].text(i,float(r['peak_kw'])+15,f'{float(r["peak_kw"]):.1f}',ha='center',fontsize=8)
panel(axes[1],'b','Peaks of exported schedules')
save(fig,'Fig02_load_profiles')

e2=[r for r in rows if r['experiment']=='E2']
fig,axes=plt.subplots(1,2,figsize=(8.4,3.35),layout='constrained')
for offset,key,label,color in [(-.24,'user_bill_cny','User bill',COLORS[3]),(0,'operator_profit_cny','Operator profit',COLORS[2]),(.24,'resource_cost_cny','Resource cost',COLORS[0])]:
    delta=[float(r[key])-float(e2[0][key]) for r in e2]
    axes[0].bar(np.arange(3)+offset,delta,width=.22,label=label,color=color)
axes[0].set_xticks(range(3),['Candidate 0','Candidate 1','Candidate 2'])
axes[0].set(ylabel='Change from candidate 0 (CNY)',ylim=(-3,77))
axes[0].legend(frameon=False,fontsize=7,loc='upper right')
panel(axes[0],'a','Pricing and payment transfers')
diag=read_json(RAW/'E1_reference_joint/peak_tie_diagnostic.json')
# Accept the source diagnostic's list or wrapper representation.
if isinstance(diag,dict):
    candidates=[v for v in diag.values() if isinstance(v,list)]
    diag=candidates[0] if candidates else [diag]
alt=next(d for d in diag if d.get('mode')=='maximum_baseline_peak_slot')
peak=[float(e1[3]['peak_kw']),alt['peak_kw']]
axes[1].bar([0,1],peak,color=[COLORS[3],COLORS[1]],width=.55)
axes[1].set_xticks([0,1],['Primary joint','Alternative optimum'])
axes[1].set(ylabel='Peak EV power (kW)',ylim=(0,1330))
for i,v in enumerate(peak):axes[1].text(i,v+25,f'{v:.1f}',ha='center')
axes[1].text(.5,.96,'Same user objective: 6188.078969 CNY',transform=axes[1].transAxes,ha='center',va='top',fontsize=8)
panel(axes[1],'b','Cost-optimum peak ambiguity')
save(fig,'Fig03_pricing_and_peak_ambiguity')

scenarios=['single_route','short_parking','tight_capacity','high_travel_time','flat_tariff','auxiliary_energy']
names=['Single route','Short parking','Tight capacity','Higher travel time','Flat tariff','Auxiliary energy']
fig,axes=plt.subplots(1,2,figsize=(9,3.75),layout='constrained')
for ax,letter,key,title,unit in zip(axes,'ab',['resource_cost_cny','grid_kwh'],['Resource-cost sensitivity','Energy sensitivity'],['CNY','kWh']):
    for i,s in enumerate(scenarios):
        group=[r for r in rows if r['experiment']=='E5' and r['scenario']==s]
        base=next(r for r in group if r['arm']=='baseline')
        joint=next(r for r in group if r['arm']=='joint')
        v=float(joint[key])-float(base[key])
        ax.scatter(v,i,color=COLORS[3],s=35,zorder=3)
        ax.annotate(f'{v:+.3f}',(v,i),xytext=(6,0),textcoords='offset points',va='center',fontsize=8)
    ax.set_yticks(range(6),names);ax.invert_yaxis();ax.axvline(0,color='#999',lw=.6)
    lo,hi=ax.get_xlim();ax.set_xlim(lo-(hi-lo)*.08,hi+(hi-lo)*.4)
    ax.set_xlabel(f'Joint minus baseline ({unit})');panel(ax,letter,title)
save(fig,'Fig04_scenario_sensitivity')

unc=read_csv(RAW/'input_uncertainty.csv')
fig,axes=plt.subplots(1,2,figsize=(8.5,3.1),layout='constrained')
for ax,letter,key,title,unit in zip(axes,'ab',['resource_cost_cny_change','grid_kwh_change'],['Resource-cost effect','Grid-energy effect'],['CNY','kWh']):
    for i,arm in enumerate(ARMS[1:]):
        r=next(r for r in unc if r['arm']==arm and r['metric']==key)
        m,lo,hi=[float(r[k]) for k in ['mean','bootstrap_low','bootstrap_high']]
        ax.errorbar(m,i,xerr=[[max(0,m-lo)],[max(0,hi-m)]],fmt='o',capsize=4,color=COLORS[i+1])
    ax.set_yticks(range(3),LABELS[1:]);ax.set_ylim(2.5,-.5);ax.axvline(0,color='#999',lw=.6)
    ax.set_xlabel(f'Change from baseline ({unit})');panel(ax,letter,title)
save(fig,'Fig05_paired_input_uncertainty')

stress=read_csv(RAW/'E1_reference_joint/execution_stress.csv')
fig,axes=plt.subplots(1,2,figsize=(8.5,3.3),layout='constrained')
for ax,letter,key,title,ylabel in zip(axes,'ab',['late_trips','terminal_energy_error_max_abs_kwh'],['Deadline sensitivity','Terminal inventory sensitivity'],['Late trips (count)','Maximum terminal-energy deviation (kWh)']):
    for i,severity in enumerate([0,1,4]):
        values=[float(r[key]) for r in stress if float(r['severity'])==severity]
        ax.scatter(i+np.linspace(-.085,.085,len(values)),values,s=23,color=COLORS[3],alpha=.75,zorder=3)
        ax.plot([i,i],[min(values),max(values)],color=COLORS[3],lw=.8)
    ax.set_xticks(range(3),['0 (n=1)','1 (n=10)','4 (n=10)'])
    ax.set(xlabel='Artificial disturbance severity',ylabel=ylabel,xlim=(-.4,2.4))
    if key=='late_trips':ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    panel(ax,letter,title)
save(fig,'Fig06_execution_stress')

# A light contact sheet for visual review (not a paper figure).
from PIL import Image, ImageOps, ImageDraw
sheet=Image.new('RGB',(1500,1500),'#eeeeee')
for i,path in enumerate([p for p in outputs if p.suffix=='.png']):
    im=Image.open(path);im.thumbnail((730,450))
    x=10+(i%2)*750;y=10+(i//2)*500
    sheet.paste(im,(x,y+25));ImageDraw.Draw(sheet).text((x,y),path.stem,fill='black')
sheet.save(HERE/'preview_all.png')
manifest={'source_files':[{'path':str(p.relative_to(DATA)), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(sources)],
          'outputs':[p.name for p in outputs], 'scope':'Visualization of frozen final results; no experiments rerun.'}
(HERE/'figure_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(f'Exported {len(outputs)} files and preview_all.png')

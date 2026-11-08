"""Final evidence report; refuses to certify unfinished/failed audit gates."""
import argparse
from collections import defaultdict
import csv
import json
import os
from pathlib import Path
import re
import numpy as np
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).parent/'.matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def report(out):
    audit=json.loads((out/'audit.json').read_text())
    scene=json.loads((out.parent/'scene_contract_audit.json').read_text())
    runtime=json.loads((out/'E1_reference_joint/execution_consistency.json').read_text())
    if not all(x['passed'] for x in [audit,scene,runtime]):raise ValueError('A required audit gate failed')
    rows=read_csv(out/'metrics.csv');e1=[r for r in rows if r['experiment']=='E1'];e2=[r for r in rows if r['experiment']=='E2']
    baseline=e1[0];joint=e1[-1];charge=e1[2]
    percent=lambda key:100*(float(joint[key])/float(baseline[key])-1)
    number=lambda r,k:f'{float(r[k]):.6f}'
    tests=[]
    for name in ['tests_scientific_and_revised.log','tests_legacy_routing.log','tests_supplementary.log']:
        text=(out.parent/name).read_text();match=re.search(r'Ran (\d+) tests',text)
        if not match or not text.rstrip().endswith('OK'):raise ValueError('Tests incomplete: '+name)
        tests.append(int(match.group(1)))
    lines=['# Scientific revision: final experiment evidence','',
           '**Status: all implemented experimental audit gates passed for the revised finite-day simulation study (review Route A).** This does not establish the historical coupled-equilibrium, universal-benefit or real-city claims; those claims are withdrawn.','',
           f"The stored Game map supplies **{scene['source_vehicles']} vehicles, {scene['actual_charger_cabinets']} physical charger cabinets and {scene['finite_trips']:,} finite trips**, on {scene['road_nodes']:,} nodes and {scene['directed_road_links']:,} directed generator links. Exact source OD waypoint order and finite trip counts were independently checked. Source trajectories were not used to prune the road network.",'',
           'The authoritative study inputs are the declared simulation contract in `../canonical_scenario.json` and `../../scientific_protocol.json`. Missing physical-policy choices are explicit simulation parameters, including initial placement at actual cabinets, cabinet driveways, terminal inventory, reserve, efficiency, tariffs and road speeds. They are not relabeled as measured/calibrated field data.','',
           '## 1. Fixed-price four-arm comparison (E1)','',
           '|Arm|Method|Travel h|Grid kWh|User objective CNY|Resource cost CNY|CO2 kg|Point-solution peak kW|',
           '|---|---|---:|---:|---:|---:|---:|---:|']
    labels={'baseline':'Shortest-time + earliest feasible charging','route_only':'Time/energy route rule + earliest feasible charging',
            'charge_only':'Fixed shortest-time routes + offline charging MILP','joint':'Joint offline route/charging MILP'}
    for r in e1:
        lines.append('|'+r['arm']+'|'+labels[r['arm']]+'|'+'|'.join(number(r,k) for k in ['travel_h','grid_kwh','user_objective_cny','resource_cost_cny','carbon_kg','peak_kw'])+'|')
    lines+=['',f"Joint versus the rule baseline: user objective changes by **{percent('user_objective_cny'):.6f}%**, resource cost by **{percent('resource_cost_cny'):.6f}%**, and grid energy by **{percent('grid_kwh'):.6f}%**. These are small conditional effects, not a 156.59% efficiency improvement.",
            f"Compared with the stronger charge-only offline optimum, joint scheduling changes user objective by {float(joint['user_objective_cny'])-float(charge['user_objective_cny']):.6f} CNY and resource cost by {float(joint['resource_cost_cny'])-float(charge['resource_cost_cny']):.6f} CNY. Lower user cost therefore does not imply lower resource cost or peak power.",
            'Every feasible arm serves all 6,084 declared trips with the same per-vehicle initial/terminal inventory requirements. Its 100% completion is a model constraint, not an observed real-world success rate. The rule methods and optimizers have the same full-day input information.','',
            '## 2. Price-feedback increment (E2)','',
            '|Candidate|User electricity bill CNY|Operator profit CNY|Resource cost CNY|Grid kWh|',
            '|---|---:|---:|---:|---:|']
    for r in e2:lines.append('|'+r['scenario']+'|'+'|'.join(number(r,k) for k in ['user_bill_cny','operator_profit_cny','resource_cost_cny','grid_kwh'])+'|')
    selected=max(e2,key=lambda r:float(r['operator_profit_cny']))
    lines+=['',f"Highest profit among the three tested candidates: **{selected['scenario']}**. Relative to fixed-price joint dispatch, operator profit changes by {float(selected['operator_profit_cny'])-float(joint['operator_profit_cny']):.6f} CNY and user electricity payment by {float(selected['user_bill_cny'])-float(joint['user_bill_cny']):.6f} CNY, while resource cost changes by {float(selected['resource_cost_cny'])-float(joint['resource_cost_cny']):.6f} CNY. This exposes the transfer-payment mechanism; it does not demonstrate a resource saving or universal user benefit.",
            'Every price candidate recomputes the complete physical dispatch. Retail and wholesale prices are distinct; wholesale prices are fixed in E2. Carbon price is an external parameter. The finite search is not a continuous-price optimum or a Stackelberg-equilibrium proof.','',
            '## 3. Accounting and correctness (E3–E4)','',
            f"The final matrix contains **{audit['runs']} settings: {audit['feasible']} feasible, {audit['infeasible']} infeasible, {audit['other_statuses']} solver failures/limits**. Among feasible settings, {audit['certified_optimal']} have MILP optimality certificates; the remaining feasible settings are rule schedules, not claimed optima.",
            f"The independent artifact audit rechecked **{audit['audited_vehicle_days']:,} vehicle-days and {audit['audited_trips']:,} trips**, plus {audit['equal_input_four_arm_groups']} complete equal-input four-arm groups. Maximum energy-closure residual was **{audit['max_energy_residual_kwh']:.3g} kWh**. All prices, loads, carbon quantities and economic metrics were recalculated independently.",
            f"**{sum(tests)} tests passed** ({' + '.join(map(str,tests))} across the revised/scientific, original-routing and supplementary test suites). Scientific reference tests include nine independent exhaustive cases, a combined no-opportunity control, multi-leg inventory/terminal changes, carbon invariance, station/battery constraints, corruption detection, timeout classification and the revisited-node waypoint regression.",
            'At fixed gamma, equal grid energy has equal CO2 under time shifts. Only changing grid energy changes emissions in this model. Carbon price is not an emissions metric; grid purchases and traction energy are not counted twice. Infeasible results retain their failure classification and never receive zero-filled savings.','',
            '## 4. Conditions, uncertainty and distribution (E5)','',
            '|Scenario|Baseline|Route only|Charge only|Joint|Joint resource-cost change vs baseline CNY|',
            '|---|---|---|---|---|---:|']
    groups=defaultdict(dict)
    for r in rows:
        if r['experiment']=='E5':groups[r['scenario']][r['arm']]=r
    for name,g in groups.items():
        b,j=g['baseline'],g['joint'];diff=number({'difference':float(j['resource_cost_cny'])-float(b['resource_cost_cny'])},'difference') if b['resource_cost_cny'] and j['resource_cost_cny'] else 'not comparable'
        lines.append('|'+name+'|'+'|'.join(g[a]['status'] for a in ['baseline','route_only','charge_only','joint'])+'|'+diff+'|')
    lines+=['','Capacity, parking duration, candidate routes, imposed travel times, flat tariffs and an auxiliary-energy model were varied. Zero capacity correctly produces infeasibility in every arm. Uniform travel-time inflation is an input sensitivity, not an endogenous congestion model.','',
            'Ten paired seeds perturb initial SOC and departure times while preserving common inputs within each comparison. `input_uncertainty.csv` contains paired effect estimates and 95% percentile-bootstrap intervals. Those intervals describe the specified artificial input generator only. Narrow/zero-width intervals may simply mean the tested perturbations do not change that outcome; they are not evidence of universal precision. Deterministic scenarios are not repeated as statistical samples.','',
            '`user_costs.csv` and `paired_effects.csv` retain user distributions and fractions worse off; failures remain in the scenario table. The carbon-price scan includes 0, 30, 60 and 90 CNY/tonne. It does not support the old claim of a special 60-CNY threshold.','',
            '## 5. Unreal execution and stress (E6)','',
            f"The corrected C++ event runtime was compiled and ran the joint plan over the entire day for **{runtime['vehicles']} vehicles**, producing **{runtime['observation_rows']:,} telemetry rows**. Python independently compared the observed battery inventory, cumulative grid/traction energy, station use and actor positions with the event contract.",
            f"Maximum battery-inventory error was {runtime['max_battery_inventory_error_kwh']:.6g} kWh; maximum position error was {runtime['max_position_error_cm']:.6g} cm. Both satisfy the declared 0.001-kWh and 2-cm float/geometry tolerances. Runtime time/energy arithmetic uses double precision; engine stepping uses 64 Hz. No battery clamp or day-wrap hides inventory errors or resets the finite task sequence.",
            'This is software execution/accounting consistency of prescribed motion. It is not independent city-traffic or human-behavior validation.','']
    stress=read_csv(out/'E1_reference_joint/execution_stress.csv')
    lines+=['|Artificial disturbance severity|Cases|Late trips: min–max|Maximum terminal-energy deviation kWh|',
            '|---|---:|---:|---:|']
    for severity in sorted({float(r['severity']) for r in stress}):
        group=[r for r in stress if float(r['severity'])==severity]
        lines.append(f"|{severity:g}|{len(group)}|{min(int(r['late_trips']) for r in group)}–{max(int(r['late_trips']) for r in group)}|{max(float(r['terminal_energy_error_max_abs_kwh']) for r in group):.6f}|")
    lines+=['','The independent no-disturbance execution control closes the terminal inventory. Artificial travel/energy disturbances reveal deadline and storage deviations. Therefore the offline plan is not advertised as a robust online controller; no reoptimization/real-time guarantee is inferred from replay.','',
            '## 6. Peak-load ambiguity: post-hoc diagnostic','']
    ties=json.loads((out/'E1_reference_joint/peak_tie_diagnostic.json').read_text())
    lines+=['|Cost-constrained diagnostic|Status|User objective CNY|Peak kW|','|---|---|---:|---:|',
            f"|Primary joint point solution|optimal|{float(joint['user_objective_cny']):.6f}|{float(joint['peak_kw']):.6f}|"]
    for r in ties:
        if r['status']==0:lines.append(f"|{r['mode']}|optimal|{r['primary_user_objective_cny']:.6f}|{r['peak_kw']:.6f}|")
        else:lines.append(f"|{r['mode']}|solver limit / no certified diagnostic exported|—|—|")
    lines+=['','Certified diagnostic plans satisfy the same primary-cost bound within 0.000001 CNY. The second diagnostic maximizes load in the baseline peak slot; it is not a proof of the globally largest possible peak. The minimum-peak diagnostic reached its 120-second limit in the final run; that limit is recorded, not called infeasibility or hidden. Comparing the successful maximum-slot diagnostic with the primary joint point solution is already sufficient to show that a cost-only optimum does not identify a unique peak. The reported primary point-solution peaks must not be promoted to a general peak-reduction claim. An explicit peak objective or secondary policy is required when peak control is the application goal. This diagnostic is labeled post hoc and does not replace the primary experiment outcomes.','',
            '## 7. What the review now supports','',
            '- E1–E5 have complete, reproducible comparisons, accounting, reference checks, scenario/input sensitivity and negative results for the revised finite simulation contract.',
            '- E6 now has compiled integration evidence, telemetry-error analysis and separate artificial stress cases. The stronger independent traffic-validation claim is explicitly withdrawn.',
            '- The active optimizer and launcher use the corrected physical contract. The historical incomplete pricing/mean-SOC pipeline is disabled as an entry point, and the old replay manager is not selected by scientific mode.',
            '- Scientific claims are limited to this simulation scope. Field calibration, real-city validity, new equilibrium theory, novel-algorithm superiority and online robustness are not claimed. Straight-line driveway access and generator road directions remain declared model assumptions.',
            '- The original manuscript was not supplied for direct editing; use this report and `../../SCIENTIFIC_METHODS.md` to replace its experimental methods/results and remove retired claims.','',
            '## 8. Verification trail','',
            'Core files: `manifest.json`, `metrics.csv`, `vehicle_energy_ledger.csv`, `user_costs.csv`, `paired_effects.csv`, `input_uncertainty.csv`, `audit.json`, and the per-run frozen inputs/events/results. The actual scene export, source-contract audit, test logs and build log are one directory above. Superseded geometry and failed first-runtime diagnostics are retained for transparency; they are not the final evidence set.']
    (out/'SCIENTIFIC_RESULTS.md').write_text('\n'.join(lines)+'\n')
    closure='''# Experimental review closure

This closes the experimental issues under the review's Route A (finite simulated scheduling/mechanism analysis). It does not certify all 72 manuscript issues or support retired Route B/game-theory claims. The original manuscript was not supplied for direct editing.

|Review item|Resolution|Evidence|
|---|---|---|
|P01: contradictory implementation status|Active optimizer/runtime share the finite physical contract; historical incomplete entry point is disabled|Plugin README, `SCIENTIFIC_METHODS.md`, actual entry-point run and compiled replay|
|P47–P50: data, scale, topology, calibration|Actual scene export and full generator graph; all new simulation choices explicit|`../scene.json`, `../scene_contract_audit.json`, canonical contract and protocol|
|P13, P30–P33: tasks, parking, inventory, facilities|All finite trips hard-constrained; exact source waypoints, cabinet access, linked storage, car/station/connector limits|Source-contract audit, per-run events, vehicle energy ledger|
|E1 / P51–P52|Complete fixed-price four arms, same inputs and information; stronger charge-only offline reference|`metrics.csv`, `paired_effects.csv`, equal-input audit|
|E2 / P14, P27, P39, P44|Bounded finite retail candidates, full physical response each time, fixed wholesale cost; separate users/operator/resources|E2 rows, per-user costs; no Stackelberg-equilibrium claim|
|E3 / P28, P31, P34–P38|Full-day battery/service/energy/loss/carbon closure; purchases not double counted with traction; fixed gamma invariance|Independent audit and reference/invariance tests|
|E4 / P18, P40–P43, P55|Independent exhaustive references, no-opportunity controls, invalid inputs and timeout distinctions; actual MIP bounds/gaps|Test logs and `result.json` in every optimized run; old MNL helpers tested separately|
|E5 / P21, P24, P26, P49, P53–P54, P63–P64|Full-source candidate graph; candidate/window/capacity/time/tariff/energy variations; ten paired input cases, uncertainty and harms|Scenario table, `input_uncertainty.csv`, `user_costs.csv`; no universal/causal extrapolation|
|E6 / P07, P56|Compiled full-day C++ replay and independent telemetry errors, plus separate execution stress; online/independent-traffic claims withdrawn|`execution_consistency.json`, `execution_stress.csv`, build logs|
|P11–P12, P57–P62, P65–P69: metrics and figures|One explicit user objective; separate resource/physical/economic metrics, full units/time horizon and raw precision; arbitrary score/targets retired|Final report and unit-bearing figure; peak-tie diagnostic explicitly post hoc|
|P04: closest methods|Three primary-source methodological comparisons with clear non-reproduction/novelty limits|`SCIENTIFIC_METHODS.md`|
|Unproved zero-sum/strict-benefit/full-equilibrium/156.59% claims|Withdrawn; not salvaged by favorable numerical examples|Protocol retired-claim list and final methods/results|

No field observation or empirical calibration is fabricated. Straight-line cabinet access, road-direction convention, speed/efficiency/reserve/terminal policies and the perturbation generator remain explicit model assumptions. Independent city validation, full dynamic equilibrium and an online controller are outside the revised claims, as permitted by the review's scope-reduction route.
'''
    (out/'REVIEW_CLOSURE.md').write_text(closure)
    # Independent, unit-bearing physical/economic figure; no arbitrary target score.
    fig,axes=plt.subplots(1,3,figsize=(13,4),layout='constrained')
    for ax,key,label in zip(axes,['user_objective_cny','grid_kwh','resource_cost_cny'],['User objective (CNY)','Grid energy (kWh)','Resource cost (CNY)']):
        ax.bar([r['arm'].replace('_',' ') for r in e1],[float(r[key]) for r in e1],color=['#66778a','#2589bd','#31997d','#d99a2d'])
        ax.set_ylabel(label);ax.tick_params(axis='x',rotation=30);ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Full finite Game day — 800 vehicles / 6,084 trips / explicit simulation inputs')
    fig.savefig(out/'scientific_overview.png',dpi=160);fig.savefig(out/'scientific_overview.svg');plt.close(fig)
    return out/'SCIENTIFIC_RESULTS.md'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=ROOT/'experiments/scientific/final_results')
    print(report(p.parse_args().results))

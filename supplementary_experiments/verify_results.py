"""Independent physical and accounting audit. Does not import the experiment solver."""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path

EPS = 1e-6


def close(a, b, label):
    if not math.isfinite(float(a)) or abs(float(a)-float(b)) > EPS:
        raise ValueError(f'{label}: {a} != {b}')


def check(condition, label):
    if not condition:
        raise ValueError(label)


def independent_options(spec):
    """Rebuild choices directly from exported task inputs, not exported plans."""
    c = spec['config']
    result = []
    for vehicle in range(c['n']):
        options = []
        start = spec['start_slots'][vehicle]
        end = min(6, start+c['window']) if spec['charge_enabled'] and c['flexible'] else start+1
        for route in range(c['paths'] if spec['route_enabled'] else 1):
            traction = spec['energy_kwh'][vehicle]*(1+.12*route)
            grid = (c['terminal']-c['initial']+traction)/c['eta']
            travel = .4+.025*route+c['congestion']*(c['n']/8)**2/(route+1)
            if grid < 0 or grid > c['power']+EPS:
                continue
            if c['initial']+c['eta']*grid > c['battery']+EPS:
                continue
            if c['departure_hour']+travel > c['deadline_hour']+EPS:
                continue
            for hour in range(start, end):
                if hour+1 <= c['departure_hour']+EPS:
                    options.append((route, hour, grid, travel, traction))
        result.append(options)
    return result


def independently_feasible(spec, options):
    # For feasibility only, keep the least grid energy at each slot. Route times
    # already satisfy deadlines and no other route-sharing constraint exists.
    groups = []
    for options_i in options:
        by_hour = {}
        for route, hour, grid, travel, traction in options_i:
            by_hour[hour] = min(by_hour.get(hour, math.inf), grid)
        if not by_hour:
            return False
        groups.append(list(by_hour.items()))
    groups.sort(key=len)
    load = [0.]*6
    cap = spec['config']['capacity']
    def visit(i):
        if i == len(groups):
            return True
        for hour, grid in groups[i]:
            if load[hour]+grid <= cap+EPS:
                load[hour] += grid
                if visit(i+1):
                    return True
                load[hour] -= grid
        return False
    return visit(0)


def tiny_optimum(spec, options):
    best = math.inf
    for combo in itertools.product(*options):
        load = [0.]*6
        for route, hour, grid, travel, traction in combo:
            load[hour] += grid
        if max(load) <= spec['config']['capacity']+EPS:
            value = sum(20*p[3]+spec['prices'][p[1]]*p[2] for p in combo)
            best = min(best, value)
    return best


def audit(directory, check_hashes=True):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    with (directory/'metrics.csv').open(encoding='utf-8-sig', newline='') as f:
        metrics = list(csv.DictReader(f))
    details = json.loads((directory/'plans_and_prices.json').read_text(encoding='utf-8'))
    with (directory/'vehicle_energy_service_ledger.csv').open(encoding='utf-8-sig', newline='') as f:
        ledger = list(csv.DictReader(f))
    specs = {r['run_id']:r for r in manifest['runs']}
    plans = {r['run_id']:r for r in details}
    check(len(specs)==len(manifest['runs'])==len(metrics), 'duplicate or missing input/metric runs')
    check(len(plans)==len(details), 'duplicate plan runs')
    check(set(plans)=={r['run_id'] for r in metrics if r['status']=='optimal'}, 'plan/metric run coverage')
    by_id = {r['run_id']:r for r in metrics}
    check(len(by_id)==len(metrics) and set(by_id)==set(specs), 'metric ID coverage')
    if check_hashes:
        for filename, expected in manifest['output_sha256'].items():
            check(hashlib.sha256((directory/filename).read_bytes()).hexdigest()==expected, 'hash mismatch: '+filename)
        check(hashlib.sha256((Path(__file__).parent/'run_experiments.py').read_bytes()).hexdigest()==manifest['source_sha256'], 'source hash mismatch')
    ledger_index = {}
    for row in ledger:
        key = row['run_id'], int(row['vehicle'])
        check(key not in ledger_index, 'duplicate ledger vehicle')
        ledger_index[key] = row
    total_vehicles = 0
    max_residual = 0.
    infeasible_verified = 0
    tiny_verified = 0
    for run_id, spec in specs.items():
        r = by_id[run_id]
        c = spec['config']
        check(r['case']==c['name'] and int(r['seed'])==c['seed'] and r['arm']==spec['arm'], run_id+' metadata')
        check(r['status'] in ('optimal', 'infeasible'), run_id+' unresolved solver status')
        options = independent_options(spec)
        if r['status']=='infeasible':
            check(not independently_feasible(spec, options), run_id+' false infeasibility')
            infeasible_verified += 1
            if spec['experiment']=='E4':
                check(math.isinf(tiny_optimum(spec, options)), run_id+' infeasible tiny oracle')
                tiny_verified += 1
            continue
        d = plans[run_id]
        check(d['prices']==spec['prices'], run_id+' exported prices differ')
        check(sorted(p['vehicle'] for p in d['selected'])==list(range(c['n'])), run_id+' missing/duplicate task')
        load = [0.]*6
        user_costs, energy, traction, travel = [], 0., 0., 0.
        for p in d['selected']:
            v = p['vehicle']
            candidates = [x for x in options[v] if x[0]==p['route'] and x[1]==p['hour']]
            check(len(candidates)==1, run_id+' invalid path, parking slot, energy or deadline')
            route, hour, grid, duration, consumption = candidates[0]
            for field, expected in [('grid',grid),('travel',duration),('traction',consumption),
                ('initial_kwh',c['initial']),('terminal_kwh',c['terminal']),
                ('pretrip_kwh',c['initial']+c['eta']*grid),('arrival_hour',c['departure_hour']+duration)]:
                close(p[field], expected, run_id+' '+field)
            residual = c['initial']+c['eta']*grid-consumption-c['terminal']
            max_residual = max(max_residual, abs(residual))
            close(residual, 0, run_id+' battery closure')
            load[hour] += grid
            user_cost = 20*duration+spec['prices'][hour]*grid
            close(p['user_cost_cny'], user_cost, run_id+' user cost')
            user_costs.append(user_cost)
            energy += grid
            traction += consumption
            travel += duration
            key = run_id, v
            check(key in ledger_index, run_id+' missing ledger row')
            l = ledger_index[key]
            for key_i, value in p.items():
                close(l[key_i], value, run_id+' ledger '+key_i)
            check(l['arm']==spec['arm'] and l['case']==c['name'], run_id+' ledger metadata')
        total_vehicles += c['n']
        for h in range(6):
            close(d['load'][h], load[h], run_id+' load')
            check(load[h] <= c['capacity']+EPS, run_id+' station power')
        bill = sum(load[h]*spec['prices'][h] for h in range(6))
        purchase = sum(load[h]*spec['wholesale'][h] for h in range(6))
        expected = dict(users=c['n'], completion_rate=1, late_users=0,
            grid_kwh=energy, traction_kwh=traction, travel_h=travel,
            loss_kwh=(1-c['eta'])*energy, initial_kwh=c['n']*c['initial'],
            terminal_kwh=c['n']*c['terminal'], energy_residual_kwh=0,
            peak_kw=max(load), bill_cny=bill, revenue_cny=bill,
            purchase_cny=purchase, profit_cny=bill-purchase,
            resource_cost_cny=20*travel+purchase, carbon_kg=c['factor']*energy,
            objective_cny=sum(user_costs))
        # Independently compute linear interpolation quantiles without numpy.
        ordered = sorted(user_costs)
        for q, field in [(.5,'user_cost_p50'),(.95,'user_cost_p95')]:
            index = (len(ordered)-1)*q
            lower = math.floor(index)
            expected[field] = ordered[lower]+(index-lower)*(ordered[math.ceil(index)]-ordered[lower])
        for field, value in expected.items():
            close(r[field], value, run_id+' metric '+field)
        for field in ('constraint_residual','integrality_residual','mip_gap'):
            check(0 <= float(r[field]) <= EPS, run_id+' '+field)
        close(r['dual_bound_cny'], r['objective_cny'], run_id+' optimum bound')
        if spec['experiment']=='E4':
            close(r['objective_cny'], tiny_optimum(spec, options), run_id+' independent optimum')
            tiny_verified += 1
    check(len(ledger_index)==total_vehicles, 'orphan ledger rows')
    # Treatment groups share exactly the same primitive inputs, prices and tasks.
    groups = {}
    for spec in specs.values():
        if spec['experiment'] in ('E1','E5'):
            groups.setdefault((spec['experiment'],spec['config']['name'],spec['config']['seed']), []).append(spec)
    for key, group in groups.items():
        check(len(group)==4 and len({s['arm'] for s in group})==4, str(key)+' missing ablation arm')
        for s in group[1:]:
            for field in ('config','energy_kwh','start_slots','wholesale','prices'):
                check(s[field]==group[0][field], str(key)+' unfair inputs '+field)
        arms = {s['arm']:by_id[s['run_id']] for s in group}
        for small, large in [('route0_charge0','route1_charge0'),('route0_charge0','route0_charge1'),
                             ('route1_charge0','route1_charge1'),('route0_charge1','route1_charge1')]:
            a,b = arms[small],arms[large]
            if a['status']=='optimal':
                check(b['status']=='optimal', str(key)+' nested feasibility')
                check(float(b['objective_cny']) <= float(a['objective_cny'])+EPS, str(key)+' nested optimum')
    candidates = [r for r in metrics if r['experiment']=='E2_candidates' and r['status']=='optimal']
    chosen = next(r for r in metrics if r['experiment']=='E2' and r['arm']=='finite_tariff_search')
    best = max(candidates,key=lambda r:float(r['profit_cny']))
    close(chosen['profit_cny'], best['profit_cny'], 'tariff search profit')
    check(specs[chosen['run_id']]['prices']==specs[best['run_id']]['prices'], 'tariff selection/tie policy')
    with (directory/'paired_effects.csv').open(encoding='utf-8-sig', newline='') as f:
        summaries = list(csv.DictReader(f))
    expected_keys = {(s['config']['name'],s['arm']) for s in specs.values()
                     if s['experiment']=='E5' and s['arm']!='route0_charge0'}
    check(len(summaries)==len(expected_keys), 'paired summary row count')
    check({(s['case'],s['arm']) for s in summaries}==expected_keys, 'paired summary coverage')
    treatments = {(r['case'],int(r['seed']),r['arm']):r for r in metrics if r['experiment']=='E5'}
    for summary in summaries:
        effects, grid_changes, user_fractions = [], [], []
        counts = dict(baseline_infeasible_only=0, treatment_infeasible_only=0,
                      both_infeasible=0, solver_errors=0)
        for seed in manifest['seeds']:
            b = treatments[summary['case'],seed,'route0_charge0']
            t = treatments[summary['case'],seed,summary['arm']]
            if b['status']==t['status']=='optimal':
                effects.append(float(b['resource_cost_cny'])-float(t['resource_cost_cny']))
                grid_changes.append(float(t['grid_kwh'])-float(b['grid_kwh']))
                bcost = {v['vehicle']:v['user_cost_cny'] for v in plans[b['run_id']]['selected']}
                users = plans[t['run_id']]['selected']
                user_fractions.append(sum(v['user_cost_cny'] < bcost[v['vehicle']]-1e-7 for v in users)/len(users))
            elif b['status']==t['status']=='infeasible':
                counts['both_infeasible']+=1
            elif b['status']=='infeasible':
                counts['baseline_infeasible_only']+=1
            else:
                counts['treatment_infeasible_only']+=1
        close(summary['paired_n'],len(effects),'paired count')
        for field,value in counts.items():
            close(summary[field],value,'paired '+field)
        stats = dict(mean_saving_cny=sum(effects)/len(effects), min_saving_cny=min(effects),
                     max_saving_cny=max(effects), mean_grid_change_kwh=sum(grid_changes)/len(grid_changes),
                     mean_user_improved_fraction=sum(user_fractions)/len(user_fractions)) if effects else {}
        for field in ('mean_saving_cny','min_saving_cny','max_saving_cny',
                      'mean_grid_change_kwh','mean_user_improved_fraction'):
            if effects:
                close(summary[field],stats[field],'paired '+field)
            else:
                check(summary[field]=='','infeasible comparison must have blank effect')
    return dict(passed=True, runs=len(metrics), feasible_plans=len(details), vehicle_records=total_vehicles,
                independent_infeasibility_checks=infeasible_verified, independent_tiny_checks=tiny_verified,
                paired_input_groups=len(groups), max_energy_residual_kwh=max_residual,
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                limitation='Audits exported synthetic model; not original MNL/MSA or Unreal execution.')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-dir', type=Path, default=Path(__file__).parent/'results')
    directory = parser.parse_args().results_dir
    try:
        result = audit(directory)
    except (ValueError, KeyError, OSError) as exc:
        result = dict(passed=False, error=str(exc))
    (directory/'verification.json').write_text(json.dumps(result,indent=2), encoding='utf-8')
    print(json.dumps(result))
    if not result['passed']:
        raise SystemExit(1)

"""Synthetic controlled scheduling experiments for E1--E5; no UE validation claim."""
from __future__ import annotations
import argparse
import csv
import hashlib
import itertools
import json
import math
import platform
from dataclasses import dataclass, replace, asdict
from pathlib import Path
import numpy as np
import scipy
from scipy.optimize import milp, Bounds, LinearConstraint

TOL = 1e-7
SEEDS = [17, 29, 43, 61, 79, 97, 113, 131, 151, 173]
ARMS = [(False, False), (True, False), (False, True), (True, True)]


@dataclass(frozen=True)
class Case:
    name: str = 'reference'
    n: int = 8
    seed: int = 17
    congestion: float = .20
    capacity: float = 20.
    window: int = 4
    paths: int = 2
    flat: bool = False
    flexible: bool = True
    eta: float = .90
    battery: float = 40.
    initial: float = 20.
    terminal: float = 20.
    power: float = 6.
    factor: float = .5703
    departure_hour: float = 6.
    deadline_hour: float = 7.

    def __post_init__(self):
        for name in ('n', 'window', 'paths'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer')
        if self.window > 6 or type(self.seed) is not int or self.seed < 0:
            raise ValueError('window must be <= 6 and seed a nonnegative integer')
        for name in ('congestion', 'capacity', 'eta', 'battery', 'initial',
                     'terminal', 'power', 'factor', 'departure_hour', 'deadline_hour'):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f'{name} must be finite and nonnegative')
        if not 0 < self.eta <= 1 or self.battery <= 0:
            raise ValueError('eta must be in (0, 1], battery must be positive')
        if max(self.initial, self.terminal) > self.battery:
            raise ValueError('initial and terminal energy must fit battery')
        if self.deadline_hour < self.departure_hour:
            raise ValueError('deadline precedes departure')


def inputs(case):
    rng = np.random.default_rng(case.seed)
    energy = rng.uniform(2.4, 3.4, case.n)
    starts = rng.integers(0, 3, case.n)
    wholesale = np.full(6, .65) if case.flat else np.array([.85, 1.10, .75, .35, .40, .55])
    return energy, starts, wholesale, wholesale + .25


def plans(case, route, charge):
    energy, starts, wholesale, retail = inputs(case)
    choices = []
    for i in range(case.n):
        hours = list(range(int(starts[i]), min(6, int(starts[i]) + case.window)))
        if not case.flexible or not charge:
            hours = hours[:1]
        group = []
        for r in range(case.paths if route else 1):
            traction = float(energy[i] * (1 + .12*r))
            grid = (case.terminal - case.initial + traction) / case.eta
            travel = .40 + .025*r + case.congestion*(case.n/8)**2/(r+1)
            if grid < 0 or grid > case.power + TOL:
                continue
            if case.initial + case.eta*grid > case.battery + TOL:
                continue
            for h in hours:
                if h + 1 <= case.departure_hour + TOL and case.departure_hour + travel <= case.deadline_hour + TOL:
                    group.append(dict(vehicle=i, route=r, hour=h, traction=traction,
                                      grid=grid, travel=travel))
        choices.append(group)
    return choices, wholesale, retail


def solve(case, route, charge, prices=None, reference=False):
    choices, wholesale, fixed = plans(case, route, charge)
    prices = np.asarray(fixed if prices is None else prices, dtype=float)
    if prices.shape != (6,) or not np.all(np.isfinite(prices)) or np.any(prices < 0):
        raise ValueError('prices must contain six finite nonnegative values')
    engine = 'enumeration' if reference else 'scipy_highs_milp'
    empty = dict(status='infeasible', case=case.name, solver=engine)
    if any(not g for g in choices):
        return dict(empty, reason='no_individual_feasible_plan'), None
    flat = [p for group in choices for p in group]
    costs = np.array([20*p['travel'] + prices[p['hour']]*p['grid'] for p in flat])
    a = np.zeros((case.n+6, len(flat)))
    for j, p in enumerate(flat):
        a[p['vehicle'], j] = 1
        a[case.n+p['hour'], j] = p['grid']
    lo = np.r_[np.ones(case.n), np.zeros(6)]
    hi = np.r_[np.ones(case.n), np.full(6, case.capacity)]
    if reference:
        if math.prod(map(len, choices)) > 1_000_000:
            raise ValueError('enumeration restricted to <= 1,000,000 combinations')
        best = None
        for combo in itertools.product(*choices):
            load = np.zeros(6)
            for p in combo:
                load[p['hour']] += p['grid']
            if max(load) > case.capacity + TOL:
                continue
            cost = sum(20*p['travel'] + prices[p['hour']]*p['grid'] for p in combo)
            if best is None or cost < best[0]:
                best = cost, combo
        if best is None:
            return dict(empty, reason='shared_capacity'), None
        objective, combo = best
        selected = [dict(p) for p in combo]
        residual = integrality_residual = mip_gap = 0.
        dual_bound = objective
    else:
        result = milp(costs, integrality=np.ones(len(flat)), bounds=Bounds(0, 1),
                      constraints=LinearConstraint(a, lo, hi),
                      options={'mip_rel_gap': 0., 'time_limit': 30.})
        if result.status != 0:
            status = {1: 'solver_limit', 2: 'infeasible', 3: 'unbounded'}.get(result.status, 'solver_failure')
            return dict(case=case.name, status=status, solver=engine,
                        reason='shared_capacity' if result.status == 2 else str(result.message)), None
        selected = [dict(p) for p, x in zip(flat, result.x) if x > .5]
        objective = float(result.fun)
        residual = float(max(np.max(lo-a@result.x), np.max(a@result.x-hi), 0))
        integrality_residual = float(np.max(np.abs(result.x-np.round(result.x))))
        mip_gap = float(result.mip_gap)
        dual_bound = float(result.mip_dual_bound)
    load = np.zeros(6)
    for p in selected:
        load[p['hour']] += p['grid']
        p.update(initial_kwh=case.initial, terminal_kwh=case.terminal,
                 pretrip_kwh=case.initial + case.eta*p['grid'],
                 arrival_hour=case.departure_hour+p['travel'],
                 user_cost_cny=20*p['travel']+prices[p['hour']]*p['grid'])
    traction = sum(p['traction'] for p in selected)
    grid = sum(p['grid'] for p in selected)
    travel = sum(p['travel'] for p in selected)
    bill, purchase = float(load@prices), float(load@wholesale)
    users = [p['user_cost_cny'] for p in selected]
    balance = case.n*case.initial + case.eta*grid - traction - case.n*case.terminal
    metrics = dict(case=case.name, status='optimal', solver=engine, users=len(selected),
        completion_rate=len({p['vehicle'] for p in selected})/case.n,
        late_users=sum(p['arrival_hour'] > case.deadline_hour+TOL for p in selected),
        travel_h=travel, traction_kwh=traction, grid_kwh=grid, loss_kwh=(1-case.eta)*grid,
        initial_kwh=case.n*case.initial, terminal_kwh=case.n*case.terminal,
        energy_residual_kwh=balance, constraint_residual=residual,
        integrality_residual=integrality_residual, mip_gap=mip_gap, dual_bound_cny=dual_bound,
        peak_kw=float(max(load)), bill_cny=bill, purchase_cny=purchase,
        revenue_cny=bill, profit_cny=bill-purchase, resource_cost_cny=20*travel+purchase,
        carbon_kg=case.factor*grid, objective_cny=float(objective),
        user_cost_p50=float(np.quantile(users, .5)), user_cost_p95=float(np.quantile(users, .95)))
    if abs(balance) > TOL or max(residual, integrality_residual) > TOL:
        raise RuntimeError('solution failed energy or integer feasibility check')
    return metrics, dict(selected=selected, load=load.tolist(), prices=prices.tolist())


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summarize_pairs(rows, details):
    lookup = {(r['case'], r['seed'], r['arm']): r for r in rows if r['experiment']=='E5'}
    plans_by_id = {d['run_id']: d for d in details}
    summaries = []
    for name in sorted({key[0] for key in lookup}):
        for arm in ('route1_charge0', 'route0_charge1', 'route1_charge1'):
            effects, changes, improved = [], [], []
            counts = dict(baseline_infeasible_only=0, treatment_infeasible_only=0,
                          both_infeasible=0, solver_errors=0)
            for seed in SEEDS:
                b, t = lookup[name, seed, 'route0_charge0'], lookup[name, seed, arm]
                if any(r['status'] not in ('optimal', 'infeasible') for r in (b, t)):
                    counts['solver_errors'] += 1
                elif b['status'] == t['status'] == 'optimal':
                    effects.append(b['resource_cost_cny']-t['resource_cost_cny'])
                    changes.append(t['grid_kwh']-b['grid_kwh'])
                    bv = {p['vehicle']: p['user_cost_cny'] for p in plans_by_id[b['run_id']]['selected']}
                    tv = plans_by_id[t['run_id']]['selected']
                    improved.append(sum(p['user_cost_cny'] < bv[p['vehicle']]-TOL for p in tv)/len(tv))
                elif b['status'] == t['status'] == 'infeasible':
                    counts['both_infeasible'] += 1
                elif b['status'] == 'infeasible':
                    counts['baseline_infeasible_only'] += 1
                else:
                    counts['treatment_infeasible_only'] += 1
            summaries.append(dict(case=name, arm=arm, paired_n=len(effects), **counts,
                mean_saving_cny=float(np.mean(effects)) if effects else '',
                min_saving_cny=min(effects) if effects else '', max_saving_cny=max(effects) if effects else '',
                mean_grid_change_kwh=float(np.mean(changes)) if changes else '',
                mean_user_improved_fraction=float(np.mean(improved)) if improved else ''))
    return summaries


def report(out, rows, validations):
    labels = {'route0_charge0':'基线', 'route1_charge0':'仅路径', 'route0_charge1':'仅充电', 'route1_charge1':'联合'}
    lines = ['# 补充实验结果（自动生成；受控合成数据）', '',
             f'共 {len(rows)} 次求解，{sum(r["status"]=="optimal" for r in rows)} 个可行最优结果；'
             f'{len(validations)} 组 MILP/穷举比较通过。E5 使用 {len(SEEDS)} 个配对种子。', '',
             '|组别|出行时间 h|购电 kWh|用户支出 元|资源成本 元|碳排 kg|',
             '|---|---:|---:|---:|---:|---:|']
    for r in rows:
        if r['experiment']=='E1':
            lines.append(f'|{labels[r["arm"]]}|{r["travel_h"]:.4f}|{r["grid_kwh"]:.4f}|{r["bill_cny"]:.4f}|{r["resource_cost_cny"]:.4f}|{r["carbon_kg"]:.4f}|')
    fixed, feedback = [r for r in rows if r['experiment']=='E2']
    lines += ['', '价格搜索前后：', '',
        f'- 用户支出：{fixed["bill_cny"]:.4f} → {feedback["bill_cny"]:.4f} 元。',
        f'- 运营利润：{fixed["profit_cny"]:.4f} → {feedback["profit_cny"]:.4f} 元。',
        f'- 资源成本：{fixed["resource_cost_cny"]:.4f} → {feedback["resource_cost_cny"]:.4f} 元。',
        '', '路径方案在本模型中以额外耗电换取时间。纯充电移时不自动节电或减排；利润增长也不等于资源节约。',
        '', 'E5 的 paired_effects.csv 分别记录基线不可行、处理组不可行、两组均不可行及求解器错误。'
        '仅在两组均可行时计算成本效应，不能把“没有可比较样本”解读为零效果。观察最小最大值不是置信区间。',
        '', '这些结果只检验简化的集中调度模块，未验证原 MNL/MSA、真实城市效果或 Unreal 执行偏差。'
        '独立审计结果见 verification.json；它由 verify_results.py 单独生成。']
    (out/'实验结果摘要.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


def run(out):
    out.mkdir(parents=True, exist_ok=True)
    rows, details, validations, runs = [], [], [], []
    base = Case()
    def record(experiment, case, route, charge, prices=None, reference=False, label=''):
        metrics, detail = solve(case, route, charge, prices, reference)
        run_id = f'run_{len(rows):04d}'
        arm = label or f'route{int(route)}_charge{int(charge)}'
        metrics.update(run_id=run_id, experiment=experiment, arm=arm, seed=case.seed)
        rows.append(metrics)
        energy, starts, wholesale, retail = inputs(case)
        run_input = dict(run_id=run_id, experiment=experiment, arm=arm, config=asdict(case),
            route_enabled=route, charge_enabled=charge, reference=reference,
            energy_kwh=energy.tolist(), start_slots=starts.tolist(), wholesale=wholesale.tolist(),
            prices=(retail if prices is None else np.asarray(prices)).tolist())
        runs.append(run_input)
        if detail:
            details.append(dict(run_id=run_id, experiment=experiment, case=case.name,
                                arm=arm, seed=case.seed, **detail))
        return metrics, detail
    for route, charge in ARMS:
        record('E1', base, route, charge)
    record('E2', base, True, True, label='fixed_price')
    retail = inputs(base)[3]
    candidates = []
    for delta in [-.15, 0., .15]:
        prices = retail + delta*np.array([-1, -1, 0, 0, 1, 1])
        metrics, detail = record('E2_candidates', base, True, True, prices, label=f'delta_{delta}')
        if detail:
            candidates.append((metrics['profit_cny'], delta, prices))
    # Ties use candidate order (-.15, 0, .15). No optimistic follower tie handling is claimed.
    best = max(candidates, key=lambda x:x[0])[2]
    record('E2', base, True, True, best, label='finite_tariff_search')
    small = replace(base, n=2)
    checks = [('two_paths', small), ('no_spread', replace(small, flat=True)),
        ('no_flexibility', replace(small, flexible=False)), ('no_congestion', replace(small, congestion=0)),
        ('no_gain', replace(small, paths=1, flat=True, flexible=False)),
        ('capacity_infeasible', replace(small, capacity=0)),
        ('power_infeasible', replace(small, power=0)),
        ('battery_infeasible', replace(small, initial=39.9, terminal=39.9)),
        ('different_terminal', replace(small, terminal=21.))]
    for name, case in checks:
        case = replace(case, name='tiny_'+name)
        m, _ = record('E4', case, True, True, label=name+'_milp')
        ref, _ = record('E4', case, True, True, reference=True, label=name+'_enumeration')
        gap = abs(m['objective_cny']-ref['objective_cny']) if m['status']==ref['status']=='optimal' else None
        ok = bool(m['status']==ref['status'] and (m['status']=='infeasible' or gap is not None and gap<TOL))
        validations.append(dict(check=name, passed=ok, milp_status=m['status'],
                                enumeration_status=ref['status'], objective_gap_cny=gap))
        if not ok:
            raise RuntimeError(f'reference mismatch: {name}')
    scenarios = [('reference', {}), ('low_congestion', {'congestion':0}),
        ('high_congestion', {'congestion':.8}), ('scarce_charging', {'capacity':4}),
        ('binding_charging', {'capacity':8}), ('ample_charging', {'capacity':40}),
        ('short_window', {'window':1}), ('one_path', {'paths':1}), ('three_paths', {'paths':3})]
    for name, changes in scenarios:
        for seed in SEEDS:
            case = replace(base, name=name, seed=seed, **changes)
            for route, charge in ARMS:
                record('E5', case, route, charge)
    write_csv(out/'metrics.csv', rows)
    write_csv(out/'vehicle_energy_service_ledger.csv', [dict(run_id=d['run_id'], experiment=d['experiment'],
        case=d['case'], seed=d['seed'], arm=d['arm'], **p) for d in details for p in d['selected']])
    write_csv(out/'validation.csv', validations)
    write_csv(out/'paired_effects.csv', summarize_pairs(rows, details))
    (out/'plans_and_prices.json').write_text(json.dumps(details, indent=2), encoding='utf-8')
    report(out, rows, validations)
    outputs = ['metrics.csv', 'vehicle_energy_service_ledger.csv', 'validation.csv',
               'paired_effects.csv', 'plans_and_prices.json', '实验结果摘要.md']
    manifest = dict(schema_version=2, data_kind='synthetic controlled scenarios', seeds=SEEDS,
        software=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), runs=runs,
        output_sha256={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in outputs},
        E6='Not performed: independent execution observations and task boundaries required.')
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(dict(runs=len(rows), feasible=len(details), reference_checks=len(validations), output=str(out))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent/'results')
    run(parser.parse_args().output_dir)

"""Export exact numeric plot inputs, preserving frozen sources and precision."""
import csv
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / '01_final_results'
OUT = HERE / '绘图数据'


def read(name):
    with (RAW / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write(folder, name, rows):
    assert rows, name
    with (folder / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def group(name, sources, note):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    for source in sources:
        shutil.copy2(RAW / source, folder / Path(source).name)
    (folder / '说明.md').write_text(f'# {name}\n\n{note}\n\n原始来源（相对 data/01_final_results）：\n\n' + '\n'.join(f'- `{s}`' for s in sources) + '\n\nCSV采用UTF-8 BOM，不舍入数值。change=处理组−基准；负值表示减少。图中显示的小数位不改变此处的原始精度。\n', encoding='utf-8')
    return folder


def main():
    rows = read('metrics.csv')
    arms = ['baseline', 'route_only', 'charge_only', 'joint']
    e1 = [next(r for r in rows if r['run_id'] == f'E1_reference_{a}') for a in arms]
    base = e1[0]
    folder = group('Fig01_four_arm_effects', [], '对应图1三个面板：用户目标费用、资源成本和电网购电量相对baseline的绝对变化。费用单位CNY，能量单位kWh。')
    write(folder, 'source_four_arm_metrics.csv', e1)
    effects = []
    for r in e1[1:]:
        for panel, key in zip('abc', ['user_objective_cny', 'resource_cost_cny', 'grid_kwh']):
            b, value = float(base[key]), float(r[key])
            effects.append(dict(panel=panel, arm=r['arm'], metric=key, baseline=b, value=value, change=value-b))
    write(folder, 'plotted_changes.csv', effects)

    folder = group('Fig02_load_profiles', [], '图2a为96个15分钟时段的阶梯负荷，start_h/end_h单位h，power_kw单位kW；图2b为当前导出方案的峰值。阶梯边界由start_h/end_h确定，不对时段中心做线性插值。')
    loads = []
    for r in e1:
        data = json.loads((RAW / r['run_id'] / 'load.json').read_text())
        assert len(data) == 96
        assert abs(sum(data)*.25-float(r['grid_kwh'])) < 1e-6
        for i, power in enumerate(data):
            loads.append(dict(arm=r['arm'], slot=i, start_h=i*.25, end_h=(i+1)*.25, power_kw=power))
    write(folder, 'panel_a_load_profiles.csv', loads)
    write(folder, 'panel_b_peaks.csv', [dict(arm=r['arm'], peak_kw=r['peak_kw'], grid_kwh=r['grid_kwh']) for r in e1])

    folder = group('Fig03_pricing_and_peak_ambiguity', ['E1_reference_joint/peak_tie_diagnostic.json'], '图3a：相对candidate_0的电费、利润及资源成本差值（CNY）。图3b：相同用户目标下两个方案的峰值（kW）。最小峰值诊断超时，无有效峰值；其状态保存在原始JSON中，未补零。')
    e2 = [r for r in rows if r['experiment'] == 'E2']
    write(folder, 'source_pricing_metrics.csv', e2)
    write(folder, 'panel_a_payment_changes.csv', [dict(candidate=r['scenario'], metric=key, value=float(r[key]), reference=float(e2[0][key]), change=float(r[key])-float(e2[0][key])) for r in e2 for key in ['user_bill_cny', 'operator_profit_cny', 'resource_cost_cny']])
    diag = json.loads((folder / 'peak_tie_diagnostic.json').read_text())
    alt = next(r for r in diag if r['mode'] == 'maximum_baseline_peak_slot')
    write(folder, 'panel_b_peak_comparison.csv', [dict(schedule='primary_joint', user_objective_cny=e1[3]['user_objective_cny'], peak_kw=e1[3]['peak_kw']), dict(schedule='maximum_baseline_peak_slot', user_objective_cny=alt['primary_user_objective_cny'], peak_kw=alt['peak_kw'])])

    folder = group('Fig04_scenario_sensitivity', [], '图4a资源成本变化（CNY），图4b购电变化（kWh）。绘图采用6个可行场景；零容量四组均不可行，只保留状态，不计算虚构收益。')
    write(folder, 'source_scenario_metrics.csv', [r for r in rows if r['experiment'] == 'E5'])
    scenarios = ['single_route', 'short_parking', 'tight_capacity', 'high_travel_time', 'flat_tariff', 'auxiliary_energy']
    effects = []
    for scenario in scenarios:
        g = [r for r in rows if r['experiment'] == 'E5' and r['scenario'] == scenario]
        b = next(r for r in g if r['arm'] == 'baseline')
        j = next(r for r in g if r['arm'] == 'joint')
        for panel, key in zip('ab', ['resource_cost_cny', 'grid_kwh']):
            effects.append(dict(panel=panel, scenario=scenario, metric=key, baseline=float(b[key]), joint=float(j[key]), change=float(j[key])-float(b[key])))
    write(folder, 'plotted_scenario_effects.csv', effects)

    folder = group('Fig05_paired_input_uncertainty', ['input_uncertainty.csv'], '图5保留10组配对人工输入的均值及95%百分位bootstrap区间。panel_a为资源成本（CNY），panel_b为购电（kWh）。区间仅对声明的人工扰动成立。原表含其他指标，绘图实际使用的6行另存于plotted_intervals.csv。')
    selected = [r for r in read('input_uncertainty.csv') if r['metric'] in ['resource_cost_cny_change', 'grid_kwh_change']]
    assert len(selected) == 6
    write(folder, 'plotted_intervals.csv', selected)

    folder = group('Fig06_execution_stress', ['E1_reference_joint/execution_stress.csv'], '图6a迟到次数；图6b每个案例的最大绝对末端电量偏差（kWh）。severity为人工扰动强度。21个点分别对应强度0的1个控制与强度1/4各10个案例。plot_x含仅用于分开重叠点的横向抖动，不是观测值。竖线为观察范围，不是置信区间。')
    stress = read('E1_reference_joint/execution_stress.csv')
    points, ranges = [], []
    for i, severity in enumerate([0, 1, 4]):
        g = [r for r in stress if float(r['severity']) == severity]
        for n, r in enumerate(g):
            x = i-.085 + (n*.17/(len(g)-1) if len(g)>1 else 0)
            points.append(dict(seed=r['seed'], severity=severity, plot_x=x, late_trips=r['late_trips'], terminal_energy_error_max_abs_kwh=r['terminal_energy_error_max_abs_kwh']))
        for key in ['late_trips', 'terminal_energy_error_max_abs_kwh']:
            values = [float(r[key]) for r in g]
            ranges.append(dict(severity=severity, n=len(g), metric=key, minimum=min(values), maximum=max(values)))
    assert len(points) == 21
    write(folder, 'plotted_points.csv', points)
    write(folder, 'plotted_ranges.csv', ranges)
    (OUT / 'README.md').write_text('# 每幅图的绘图数据\n\n六个子文件夹与同级Fig01–Fig06的PNG/PDF/SVG逐一对应。每个文件夹有实际绘图数值CSV及说明；必要的源表/诊断JSON一并保留。\n\n重新导出：`python data/08_publication_figures/export_plot_data.py`。本操作不重跑实验、不改图像。总来源为data/01_final_results；全字段单位见data/字段字典.csv。\n', encoding='utf-8')
    files = [p for p in OUT.rglob('*') if p.is_file() and p.name != 'data_manifest.json']
    (OUT / 'data_manifest.json').write_text(json.dumps({'files':[dict(path=p.relative_to(OUT).as_posix(), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(files)]}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Exported {len(files)} files into six figure-specific folders: {OUT}')


if __name__ == '__main__':
    main()

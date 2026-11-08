"""Package frozen final study artifacts and derived paper tables without rerunning."""
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data'
FINAL = ROOT / 'experiments/scientific/final_results'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(exist_ok=True)
    records = []

    def copy(source, target):
        dest = OUT / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and digest(dest) != digest(source):
            raise RuntimeError(f'Refusing to overwrite different existing file: {dest}')
        shutil.copy2(source, dest)
        assert digest(source) == digest(dest), dest
        records.append({'path': target.replace('\\', '/'), 'source': str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source), 'bytes': dest.stat().st_size, 'sha256': digest(dest), 'kind': 'copied'})

    for source in sorted(FINAL.rglob('*')):
        if source.is_file():
            copy(source, '01_final_results/' + source.relative_to(FINAL).as_posix())
    for name in ['canonical_scenario.json', 'scene.json', 'topology_and_tasks.json', 'scene_contract_audit.json']:
        copy(ROOT / 'experiments/scientific' / name, '02_inputs/' + name)
    copy(ROOT / 'experiments/scientific_protocol.json', '02_inputs/scientific_protocol.json')
    for name in ['unreal_final_execution.log', 'build_final.log', 'tests_scientific_and_revised.log', 'tests_legacy_routing.log', 'tests_supplementary.log', 'delivery_manifest.json']:
        copy(ROOT / 'experiments/scientific' / name, '03_evidence/' + name)
    for name in ['SCIENTIFIC_METHODS.md', 'SCIENTIFIC_README.md', 'Ubuntu最新结果整理.md']:
        copy(ROOT / 'experiments' / name, '05_documents/' + name)
    review = Path('C:/Users/cchio/Downloads/H_GAME_导师审阅与修改建议.md')
    if review.exists():
        copy(review, '05_documents/H_GAME_导师审阅与修改建议.md')
    for source in sorted((ROOT / 'experiments/visualizations').iterdir()):
        if source.suffix in {'.png', '.svg', '.json', '.md', '.py'}:
            copy(source, '04_figures/' + source.name)
    # Keep the shared solver, audit, report and packaging source alongside the data.
    for source in sorted((ROOT / 'experiments').glob('*.py')):
        copy(source, '07_code/experiments/' + source.name)
    copy(ROOT / 'experiments/requirements.txt', '07_code/experiments/requirements.txt')
    with (FINAL / 'metrics.csv').open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    assert len(rows) == 79
    assert Counter(r['status'] for r in rows) == {'optimal': 41, 'feasible_rule': 34, 'infeasible': 4}
    for name, selected in {
        'table_E1_four_arm.csv': [r for r in rows if r['experiment'] == 'E1'],
        'table_E2_pricing.csv': [r for r in rows if r['experiment'] == 'E2'],
        'table_E5_scenarios.csv': [r for r in rows if r['experiment'] == 'E5' and r['scenario'] != 'random_paired_input'],
        'table_E5_paired_inputs.csv': [r for r in rows if r['experiment'] == 'E5_random'],
        'table_carbon_price.csv': [r for r in rows if r['run_id'].startswith('carbon_tau_')],
    }.items():
        write_csv(OUT / '06_paper_tables' / name, selected, fields)
    baseline = next(r for r in rows if r['run_id'] == 'E1_reference_baseline')
    assert sum(r['experiment'] == 'E5_random' for r in rows) == 40
    effects = []
    for r in rows:
        if r['experiment'] != 'E1':
            continue
        for metric in ['travel_h', 'grid_kwh', 'carbon_kg', 'user_objective_cny', 'resource_cost_cny', 'peak_kw']:
            b, value = float(baseline[metric]), float(r[metric])
            effects.append(dict(run_id=r['run_id'], metric=metric, baseline=b, value=value, change=value-b, change_pct=(value-b)/b*100))
    write_csv(OUT / '06_paper_tables/table_E1_changes.csv', effects, ['run_id', 'metric', 'baseline', 'value', 'change', 'change_pct'])
    units = {'runtime_s': 's', 'trips': '次', 'completed_trips': '次', 'vehicles': '辆', 'travel_h': '车辆累计 h', 'completion_rate': '比例 0–1', 'load_factor': '比例', 'mip_gap': '比例', 'seed': '无', 'variables': '个', 'constraints': '个', 'constraint_residual': '模型约束残差（混合单位）'}
    meanings = {
        'run_id': '唯一实验标识，可连接同名目录及车辆台账', 'experiment': '实验分组 E1/E2/E5/碳价扫描', 'scenario': '输入场景名称', 'arm': 'baseline/route_only/charge_only/joint', 'seed': '人工扰动种子；确定性实验留空', 'input_hash': '同输入对照的合同标识；文件字节校验使用 manifest.json', 'status': 'optimal=认证最优；feasible_rule=规则可行；infeasible=不可行', 'runtime_s': '保存的单次求解耗时，非跨平台性能基准', 'trips': '合同要求行程数', 'travel_h': '所有车辆累计行驶时间', 'traction_kwh': '电池侧行驶耗电', 'grid_kwh': '电网侧购电量', 'loss_kwh': '充电损耗=(1−效率)×购电', 'carbon_kg': '购电量×固定排放因子', 'carbon_payment_cny': '排放kg×碳价元/吨÷1000', 'user_bill_cny': '逐时购电量×零售电价之和', 'operator_revenue_cny': '运营商售电收入，等于用户电费', 'wholesale_cost_cny': '逐时购电量×批发电价之和', 'operator_profit_cny': '售电收入−批发购电支出', 'resource_cost_cny': '时间价值×行驶小时+批发购电支出', 'user_objective_cny': '时间价值×行驶小时+用户电费+碳支付', 'peak_kw': '当前导出点解的 EV 负荷峰值', 'mean_kw': '完整24小时EV负荷平均值', 'load_factor': '平均负荷÷峰值', 'audit_passed': '该结果保存的独立审计状态', 'vehicles': '车辆数', 'completed_trips': '完成行程数', 'completion_rate': '完成行程÷要求行程；硬约束结果', 'max_energy_residual_kwh': '逐车能量闭合残差最大绝对值', 'reason': '终止原因或不可行原因', 'variables': 'MILP变量数；规则方案空缺', 'constraints': 'MILP约束数', 'mip_gap': '求解器报告相对最优间隙', 'dual_bound_cny': '目标函数下界', 'constraint_residual': '求解器约束残差',
    }
    dictionary = []
    for field in fields:
        unit = units.get(field, '元 CNY' if field.endswith('_cny') else 'kWh' if field.endswith('_kwh') else 'kW' if field.endswith('_kw') else 'kg CO₂' if field.endswith('_kg') else '无/文本')
        dictionary.append(dict(field=field, unit=unit, meaning=meanings[field]))
    write_csv(OUT / '字段字典.csv', dictionary, ['field', 'unit', 'meaning'])
    readme = '''# 论文数据说明

本数据包整理于 2026-11-08，采用 2026-11-03 最终交付的 Ubuntu/Linux 仿真实验。整理过程没有重新运行优化器或 Unreal。导师审阅文件作为论文修订背景保存，不作为执行命令，也不表示其中所有建议均已完成。

## 研究范围与版本

采用导师建议的路线 A：同服务与初末储能条件下的有限日路径—充电调度及机制分析。800辆车、127个物理充电柜、6,084次行程；5,829节点、12,828有向生成链接。时间域0–24小时，充电间隔0.25小时。场景来自项目地图；效率、价格、路速、末端库存等是公开声明的仿真参数，不是城市实测或标定数据。

唯一主结果为 `01_final_results/`；历史受控实验、修正OD顺序前的结果及失败的首次运行诊断未混入。原项目中的历史证据仍保留在原处。

## 目录和使用顺序

|目录/文件|内容和用途|
|---|---|
|01_final_results/|完整最终结果，79个实验目录及汇总指标、能量台账、用户费用、配对效应、审计和报告；另保留联合方案的执行、扰动及事后峰值诊断|
|02_inputs/|场景导出、完整canonical合同、路网和任务、协议参数及源合同审计|
|03_evidence/|最终Linux运行、编译、39项测试日志和原交付哈希清单|
|04_figures/|三套论文结果图，PNG与可编辑SVG、绘图输入JSON及生成代码|
|05_documents/|方法、工作流、最终结果中文整理及导师审阅背景；最终英文报告在01_final_results中|
|06_paper_tables/|从原始metrics.csv直接筛选的论文表；E1变化表为唯一新增计算，不对原始数值补零或改写|
|07_code/experiments/|本项目实验构建、求解、审计、报告与打包脚本及依赖清单；为参考源代码快照|
|字段字典.csv|metrics.csv全部字段的中文含义和单位|
|manifest.json|本数据包逐文件来源、大小、SHA-256及复制/派生分类|
|verify_data.py|本数据包完整性和汇总表一致性检查脚本|

建议先读本说明及 `05_documents/Ubuntu最新结果整理.md`，再使用 `06_paper_tables/` 写论文；追溯到 `01_final_results/metrics.csv` 和同名run_id目录。全部CSV为逗号分隔；新增CSV采用UTF-8 BOM，原始CSV保持原字节。路径中的相对链接以本数据目录为基准。

## 论文问题与证据对应

|论文部分/导师关切|数据入口|解释|
|---|---|---|
|场景、物理约束、参数 P13/P31/P47|02_inputs/，05_documents/SCIENTIFIC_METHODS.md|公开假设、任务和初末库存，避免将假设写成观测|
|四组消融 E1/P51–P52|06_paper_tables/table_E1_four_arm.csv、table_E1_changes.csv|同任务、同输入、同初末电量；基准与仅路径为规则解，仅充电与联合为MILP|
|定价机制 E2/P27/P29|table_E2_pricing.csv|三个候选均重算调度；利润增加不等于资源节约|
|能量/碳核算 E3/P31–P39|01_final_results/vehicle_energy_ledger.csv、audit.json|初始+效率×购电−行驶−末端=0；排放仅核算电网购电|
|正确性 E4/P55|03_evidence/tests_*.log、07_code/experiments/test_*.py|保存39项测试通过记录；独立审计覆盖60,000车辆日、456,300行程|
|场景敏感性 E5/P53|table_E5_scenarios.csv、paired_effects.csv|保留零容量不可行；负向结果和权衡不得删除|
|输入不确定性|table_E5_paired_inputs.csv、01_final_results/input_uncertainty.csv|10配对种子；95%百分位bootstrap区间仅对应人工输入生成器|
|碳价 P34/P36/P64|table_carbon_price.csv|0/30/60/90元每吨；不支持60元阈值|
|执行 E6/P56|01_final_results/E1_reference_joint/execution_consistency.json、unreal_observations.csv、execution_stress.csv|800辆车、176,800遥测行；预设运动的软件一致性，不是独立交通实证|
|峰值解释|E1_reference_joint/peak_tie_diagnostic.json|事后诊断；最小峰值求解超时，不能把费用点解峰值当普遍削峰保证|

上表未带目录前缀的table_*.csv在06_paper_tables中，paired_effects.csv在01_final_results中。文献引用核查、最近邻方法比较、理论创新及论文正文修订不由本数据包证明完成。

## 表结构、连接与计量

- `metrics.csv`：一行一个run_id，共79行。`result.json`与该行对应。`input.json.gz`为该运行冻结合同，`events.json.gz`为事件方案，`load.json`为负荷。gzip文件可用Python gzip.open读取；不可行运行没有可执行事件，不应人为补齐。
- `vehicle_energy_ledger.csv`：一行一个run_id与vehicle_id，60,000行，保留initial/terminal/grid/traction/loss/energy_residual_kwh及service_complete。连接键为(run_id, vehicle_id)。
- `user_costs.csv`：逐run_id、vehicle_id的user_cost_cny；`paired_effects.csv`为场景内相对baseline的差值及用户变差比例；`both_feasible`决定是否可比较。
- `input_uncertainty.csv`：arm、metric、样本数n、均值及bootstrap上下界。不是实测人口置信区间。
- 联合目录的 `scientific_plan.csv`：vehicle_id、task_id、事件类型、起止时刻、deadline、能量、station_id、路径与电池参数；时刻单位小时。`unreal_observations.csv`为运行时遥测，以原表头为准；误差汇总见execution_consistency.json。
- 路径、车辆和站点编号是仿真标识，不推导真实身份或地址。`input_hash`用于同输入分组；字节完整性以本包manifest中的SHA-256为准。
- 金额为CNY；能量为kWh，功率为kW。峰值只含EV负荷。平均负荷为24小时总购电量/24，负荷率=平均/峰值。
- 效率0.90、固定碳因子0.5703 kg/kWh、基准碳价40元/吨、时间价值34元/小时。变体以各运行input合同为准。
- 用户目标=时间价值×累计行驶h+零售电费+碳支付；资源成本=时间价值×累计行驶h+批发购电费；运营商利润=零售收入−批发支出；碳支付=排放kg×碳价/1000。资源成本不含用户与运营商之间的转移支付。
- 差值=处理组−基准，百分比=差值/基准×100%；成本、能量的负值表示减少。费用多目标之间不能互相替代。
- 空值表示不适用或没有有效方案，不能视为0。optimal是认证最优，feasible_rule是规则可行；infeasible是不可能满足该合同，不是零成本。主矩阵41最优、34规则可行、4不可行；主矩阵无求解失败/时限。事后最小峰值诊断超时单独记录。

## 可写入论文的结果与边界

联合相对基准用户目标费用下降0.008577%、资源成本下降0.007217%、购电下降0.064764%。相对仅充电，联合用户目标少0.073792元，但资源成本多0.020946元。candidate_1使利润及用户电费同时增加53.585403元，资源成本不变。四组可行方案100%完成是硬约束的结果，不是外部实测成功率。

固定碳因子下，等量购电的纯移时不减排。仅费用最优可能对应不同峰值。强人工扰动产生24–31次迟到及最高约0.505408kWh末端电量偏差，不支持在线鲁棒性保证。

不得以本包支持“156.59%系统效率提升”、普遍严格获益、完整Stackelberg/MNL耦合均衡、真实城市有效性或新算法优越性。最近邻对照和实证校准仍需单独开展。

## 校验与复现

在项目根目录运行 `python data/verify_data.py` 检查本包哈希和汇总表。该检查不等于重新求解或重跑39项测试。

在原项目根目录运行 `python experiments/package_paper_data.py` 可重新整理；已有复制文件内容不一致时脚本停止，防止覆盖修改。完整实验复现使用05_documents/SCIENTIFIC_README.md：需要原项目目录结构、Linux UE4.27、地图、插件与环境。本包不包含庞大的引擎二进制和.umap，也不声称可独立启动Unreal；03_evidence/delivery_manifest.json是原项目路径的历史校验清单，不是本包路径清单。源代码快照用于理解和追溯，完整运行请在原项目中进行。

本包没有推定对外发布许可；导师评阅内容和项目来源的公开授权需另行确定。manifest不对自身计算哈希，其余全部数据文件纳入校验。
'''
    (OUT / '数据说明.md').write_text(readme, encoding='utf-8')
    (OUT / 'verify_data.py').write_text('''import csv, hashlib, json
from pathlib import Path
from collections import Counter
root = Path(__file__).resolve().parent
manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
errors = []
for item in manifest['files']:
    path = root/item['path']
    if not path.is_file():
        errors.append('Missing: '+item['path']); continue
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576), b''): h.update(b)
    if h.hexdigest() != item['sha256']: errors.append('Changed: '+item['path'])
def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f: return list(csv.DictReader(f))
rows = read(root/'01_final_results/metrics.csv')
assert len(rows)==79
assert Counter(r['status'] for r in rows)=={'optimal':41,'feasible_rule':34,'infeasible':4}
index = {r['run_id']:r for r in rows}
for table in (root/'06_paper_tables').glob('*.csv'):
    if table.name=='table_E1_changes.csv':
        for r in read(table):
            b=float(index['E1_reference_baseline'][r['metric']]); v=float(index[r['run_id']][r['metric']])
            assert abs(float(r['change'])-(v-b))<1e-10
            assert abs(float(r['change_pct'])-(v-b)/b*100)<1e-10
    else:
        for r in read(table): assert r==index[r['run_id']], table
if errors: raise SystemExit('\\n'.join(errors))
print('PASS:',len(manifest['files']),'files hashed; 79 runs; paper tables match frozen metrics.')
''', encoding='utf-8')
    known = {r['path'] for r in records}
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and path.name != 'manifest.json' and path.relative_to(OUT).as_posix() not in known:
            records.append(dict(path=path.relative_to(OUT).as_posix(), source='Derived from frozen final metrics / documentation of packaging', bytes=path.stat().st_size, sha256=digest(path), kind='derived'))
    (OUT / 'manifest.json').write_text(json.dumps(dict(package_version='1.0', packaged_date='2026-11-08', experiment_delivery_date='2026-11-03', no_experiments_rerun=True, files=records), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Packaged {len(records)} files; {sum(r["bytes"] for r in records)/1024**2:.1f} MiB into {OUT}')


if __name__ == '__main__':
    main()

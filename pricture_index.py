import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# 设置全局字体和风格
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'sans-serif'] # 论文常用字体
plt.rcParams['axes.unicode_minus'] = False # 解决负号显示问题
plt.rcParams['font.size'] = 11

# ==========================================
# 图1：左侧柱状图数据准备
# ==========================================
optimization_data = [
    ('Route flow', 'Time-energy balance', 'fp', 3.433310333327621,
     3.4347116468211354, -0.040815229544244325, 5.0, 15.0, 'Below target'),
    ('Charging schedule', 'Minimize charging cost', 'ti', 554.9715000000004,
     119.87976, 78.39893399931348, 30.0, 50.0, 'Above target'),
    ('Charging load', 'Peak shaving and valley filling', 'ti', 480.0,
     100.0, 79.16666666666666, 60.0, 90.0, 'On target'),
    ('Time-of-use price', 'Revenue-carbon tradeoff', 'p(t)', 1.315097317201473,
     1.3677012098895318, 3.9999999999999813, 10.0, 30.0, 'Below target'),
    ('Carbon price', 'Minimize carbon emissions', 'tau', 422.00032860000033,
     87.65054760000001, 79.22974423010913, 5.0, 15.0, 'Above target'),
    ('System efficiency', 'Multi-objective', 'fp, ti, p(t), tau', 1.0,
     2.5658783670381315, 156.58783670381317, 10.0, 20.0, 'Above target'),
]

# 反转后使 System efficiency 显示在最上方。
optimization_data = optimization_data[::-1]
indicators = [row[0] for row in optimization_data]
actual_improvement = [row[5] for row in optimization_data]
target_lower_bound = [row[6] for row in optimization_data]
target_upper_bound = [row[7] for row in optimization_data]

# 自定义颜色：除了Charging load用青色，其余用橙色
colors = ['#D97706' if ind != 'Charging load' else '#0D7E72' for ind in indicators]

# ==========================================
# 图2：右侧折线图数据准备（这里使用模拟数据，你需要替换为真实数据）
# ==========================================
# 模拟时间轴 (0 到 24小时)
time = np.linspace(0, 24, 200)
# 模拟优化前负荷 (红色): 早晚高峰
np.random.seed(42)
before_load = np.zeros_like(time)
for i, t in enumerate(time):
    if 6 <= t <= 10:
        before_load[i] = 400 * np.exp(-((t - 8)**2) / 2) + np.random.normal(0, 20)
    elif 15 <= t <= 20:
        before_load[i] = 200 * np.exp(-((t - 17.5)**2) / 3) + np.random.normal(0, 15)
    else:
        before_load[i] = 50 + np.random.normal(0, 10)
before_load = np.clip(before_load, 0, 500)

# 模拟优化后负荷 (青色): 削峰填谷，平滑分布
after_load = np.zeros_like(time)
for i, t in enumerate(time):
    if 1 <= t <= 7 or 21 <= t <= 23:
        after_load[i] = 100 + np.random.normal(0, 10) # 夜间充电
    else:
        after_load[i] = 30 + np.random.normal(0, 5)
after_load = np.clip(after_load, 0, 500)

# ==========================================
# 开始绘图
# ==========================================
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6), constrained_layout=True)
fig.patch.set_facecolor('white')

# ----- 绘制左侧柱状图 -----
bars = ax1.barh(indicators, actual_improvement, color=colors, height=0.6, alpha=0.9)

# 绘制目标下限和上限
for i, (lower, upper) in enumerate(zip(target_lower_bound, target_upper_bound)):
    ax1.plot([lower, lower], [i - 0.3, i + 0.3], color='black', linewidth=3, zorder=5)
    ax1.plot([upper, upper], [i - 0.3, i + 0.3], color='black', linewidth=2,
             linestyle='--', zorder=5)

# 添加数值标签
for bar in bars:
    width = bar.get_width()
    # 处理负数标签位置
    label_x = width + 2 if width >= 0 else width - 8
    label_align = 'left' if width >= 0 else 'right'
    ax1.text(label_x, bar.get_y() + bar.get_height()/2, 
             f'{width:.1f}%', ha=label_align, va='center', fontsize=10, fontweight='bold')

# 美化左侧图
ax1.set_xlim(-10, 175)
ax1.set_title('Optimization performance and target ranges', fontsize=14, pad=15, fontweight='bold')
ax1.set_xlabel('Improvement (%)', fontsize=12)
ax1.grid(axis='x', linestyle='--', alpha=0.5)
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)
ax1.spines['left'].set_visible(False)
ax1.tick_params(axis='y', length=0, labelsize=11)

# 添加图例说明黑线
import matplotlib.lines as mlines
target_line = mlines.Line2D([], [], color='black', linewidth=3, label='Target lower bound')
target_upper_line = mlines.Line2D([], [], color='black', linewidth=2,
                                 linestyle='--', label='Target upper bound')
ax1.legend(handles=[target_line, target_upper_line], loc='lower right',
           frameon=False, fontsize=11)

# ----- 绘制右侧折线图 -----
# 填充颜色区域，增加视觉冲击力
ax2.fill_between(time, before_load, color='#D35400', alpha=0.1)
ax2.fill_between(time, after_load, color='#0D7E72', alpha=0.2)

# 绘制线条
ax2.plot(time, before_load, color='#D35400', linewidth=2.5, label='Before')
ax2.plot(time, after_load, color='#0D7E72', linewidth=2.5, label='After')

# 美化右侧图
ax2.set_title('Charging load profile', fontsize=14, pad=15, fontweight='bold')
ax2.set_xlabel('Elapsed time (h)', fontsize=12)
ax2.set_ylabel('Charging load (kW)', fontsize=12)
ax2.set_xlim(0, 24)
ax2.set_ylim(0, 500)
ax2.grid(axis='both', linestyle='--', alpha=0.5)
ax2.spines['top'].set_visible(False)
ax2.spines['right'].set_visible(False)
ax2.legend(loc='upper right', frameon=False, fontsize=12)

# ==========================================
# 保存图片
# ==========================================
output_path = Path(__file__).resolve().parent / "optimization_performance_beautified.png"
fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
print(f"图片已保存到：{output_path}（{output_path.stat().st_size} 字节）")
plt.show()
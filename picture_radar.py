import numpy as np
import matplotlib.pyplot as plt

# 1. 优化结果数据
optimization_data = [
    {
        'category': 'Route flow', 'objective': 'Time-energy balance',
        'variable': 'fp', 'before': 3.433310333327621,
        'after': 3.4347116468211354, 'improvement': -0.040815229544244325,
        'lower': 5.0, 'upper': 15.0, 'status': 'Below target',
    },
    {
        'category': 'Charging schedule', 'objective': 'Minimize charging cost',
        'variable': 'ti', 'before': 554.9715000000004,
        'after': 119.87976, 'improvement': 78.39893399931348,
        'lower': 30.0, 'upper': 50.0, 'status': 'Above target',
    },
    {
        'category': 'Charging load', 'objective': 'Peak shaving',
        'variable': 'ti', 'before': 480.0, 'after': 100.0,
        'improvement': 79.16666666666666, 'lower': 60.0,
        'upper': 90.0, 'status': 'On target',
    },
    {
        'category': 'Time-of-use price', 'objective': 'Revenue-carbon tradeoff',
        'variable': 'p(t)', 'before': 1.315097317201473,
        'after': 1.3677012098895318, 'improvement': 3.9999999999999813,
        'lower': 10.0, 'upper': 30.0, 'status': 'Below target',
    },
    {
        'category': 'Carbon price', 'objective': 'Minimize carbon emissions',
        'variable': 'tau', 'before': 422.00032860000033,
        'after': 87.65054760000001, 'improvement': 79.22974423010913,
        'lower': 5.0, 'upper': 15.0, 'status': 'Above target',
    },
    {
        'category': 'System efficiency', 'objective': 'Multi-objective',
        'variable': 'fp, ti, p(t), tau', 'before': 1.0,
        'after': 2.5658783670381315, 'improvement': 156.58783670381317,
        'lower': 10.0, 'upper': 20.0, 'status': 'Above target',
    },
]

categories = [item['category'] for item in optimization_data]
actual_improvement = [item['improvement'] for item in optimization_data]
target_lower_bound = [item['lower'] for item in optimization_data]
target_upper_bound = [item['upper'] for item in optimization_data]

# 数据归一化（核心步骤！）
# 因为 156.59 和 -0.04 差距太大，为了防止图形畸变，我们使用对数或自定义截断。
# 这里我们采用简单的最大值归一化，让所有数据落在 0-1 之间。
max_val = 160.0  # 设定一个统一的视觉上限（略大于156.59）
actual_norm = [max(v, 0.0) / max_val for v in actual_improvement]
target_norm = [v / max_val for v in target_lower_bound]
target_upper_norm = [v / max_val for v in target_upper_bound]

# 2. 角度计算
N = len(categories)
angles = [n / float(N) * 2 * np.pi for n in range(N)]
angles += angles[:1]  # 闭合图形

# 数据闭合
actual_norm += actual_norm[:1]
target_norm += target_norm[:1]
target_upper_norm += target_upper_norm[:1]

# 3. 初始化画布（纯白背景）
fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True), facecolor='white')
ax.set_facecolor('white')  # 内部绘图区也设为纯白

# 4. 绘制网格与轴标签
plt.xticks(angles[:-1], categories, color='#333333', size=12)
ax.set_rlabel_position(30)
plt.yticks([0.2, 0.4, 0.6, 0.8, 1.0], ["32", "64", "96", "128", "160"], color="gray", size=9)
plt.ylim(0, 1.0)  # 设置极坐标范围

# 5. 绘制“实际改善”区域（深青色半透明）
ax.plot(angles, actual_norm, linewidth=2, linestyle='solid', color='#0D7E72', label='Actual improvement')
ax.fill(angles, actual_norm, color='#0D7E72', alpha=0.3)

# 6. 绘制目标区间（橙色）
ax.plot(angles, target_norm, linewidth=1.5, linestyle='dashed', color='#D47724', label='Target lower bound')
ax.plot(angles, target_upper_norm, linewidth=1.5, linestyle='dotted', color='#D47724', label='Target upper bound')
ax.fill_between(angles, target_norm, target_upper_norm, color='#D47724', alpha=0.15)

# 7. 设置图例位置在底部（模仿图3风格）
plt.legend(loc='upper center', bbox_to_anchor=(0.5, -0.05), ncol=3, frameon=False, fontsize=10)

# 8. 保存图片（纯白背景，高分辨率）
plt.tight_layout()
plt.savefig('radar_chart_white_bg.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.show()
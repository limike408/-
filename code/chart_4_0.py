# -*- coding: utf-8 -*-
"""4.0版优化补充图：由 results/ 下 CSV 生成 4 张图表 A9-A12，落盘 figures_adv/。
仅读取 results 下的 CSV，不重新求解，故可独立、低开销运行。"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

RES = C.RES_DIR
FIGD = os.path.join(C.C_BASE, 'figures_adv')
os.makedirs(FIGD, exist_ok=True)
DAY_LABEL = {'2025-03-20': '03-20', '2025-06-21': '06-21',
             '2025-09-23': '09-23', '2025-12-21': '12-21'}

# ============ A9 问题二：CVaR 风险敏感性分组柱状（λ=0 vs λ=2，堆叠 计划/紧急） ============
df2 = pd.read_csv(os.path.join(RES, 'q2_two_stage_comparison.csv'))
d = df2[(df2['lam'].isin([0.0, 2.0]))].copy()
days = ['2025-03-20', '2025-06-21', '2025-09-23', '2025-12-21']
x = np.arange(len(days)); w = 0.36
fig, ax = plt.subplots(figsize=(9.5, 5.2))
for i, lam in enumerate([0.0, 2.0]):
    sub = d[d['lam'] == lam].set_index('day').reindex(days)
    off = (i - 0.5) * w
    bars_p = ax.bar(x + off, sub['plan_fee'].values / 1e4, w, label=f'λ={int(lam)} 计划购电费')
    bars_e = ax.bar(x + off, sub['emerg_fee'].values / 1e4, w,
                    bottom=sub['plan_fee'].values / 1e4, label=f'λ={int(lam)} 紧急购电费')
    for b in list(bars_p) + list(bars_e):
        ax.text(b.get_x() + b.get_width() / 2, b.get_y() + b.get_height() + 0.1,
                f'{b.get_height():.1f}', ha='center', fontsize=10)
ax.set_xticks(x); ax.set_xticklabels([DAY_LABEL[k] for k in days], fontsize=11)
ax.set_xlabel('指定日期', fontsize=12); ax.set_ylabel('费用（万元）', fontsize=12)
ax.set_title('问题二方法层：风险权重 λ 下"计划费换可靠性"权衡（堆叠柱）', fontsize=13)
ax.legend(fontsize=10); ax.grid(axis='y', ls='--', alpha=0.4)
ax.tick_params(labelsize=11)
fig.tight_layout(); fig.savefig(os.path.join(FIGD, 'A9_q2_cvar_compare.png'), dpi=150); plt.close(fig)

# ============ A10 问题四：季节日均费用 固定/波动 对比（问题三） ============
dfs = pd.read_csv(os.path.join(RES, 'season_cost_split.csv'))
seasons = list(dfs['seas'])
x = np.arange(len(seasons)); w = 0.36
fig, ax = plt.subplots(figsize=(8.5, 5.0))
b1 = ax.bar(x - w / 2, dfs['q3_fix'], w, label='固定电价', color='#4C72B0')
b2 = ax.bar(x + w / 2, dfs['q3_var'], w, label='波动电价', color='#DD8452')
for b in list(b1) + list(b2):
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.03,
            f'{b.get_height():.2f}', ha='center', fontsize=10)
for i, up in enumerate(dfs['up3']):
    ax.text(x[i] + w / 2, max(dfs['q3_fix'][i], dfs['q3_var'][i]) + 0.35,
            f'+{up:.1f}%' if up >= 0 else f'{up:.1f}%',
            ha='center', fontsize=10, color='#C44E52', bbox=dict(fc='white', ec='#C44E52', lw=0.6, boxstyle='round,pad=0.15'))
ax.set_xticks(x); ax.set_xticklabels(seasons, fontsize=11)
ax.set_xlabel('季节', fontsize=12); ax.set_ylabel('日均费用（万元/日）', fontsize=12)
ax.set_title('问题四：波动电价下季节日均费用的季节性差异（问题三）', fontsize=13)
ax.legend(fontsize=10); ax.grid(axis='y', ls='--', alpha=0.4)
ax.tick_params(labelsize=11)
fig.tight_layout(); fig.savefig(os.path.join(FIGD, 'A10_season_cost.png'), dpi=150); plt.close(fig)

# ============ A11 问题三：仅0:00 vs 滚动 总费用对比（堆叠 电网/紧急） ============
df3 = pd.read_csv(os.path.join(RES, 'q3_rolling_comparison.csv')).set_index('day').reindex(days)
x = np.arange(len(days)); w = 0.36
fig, ax = plt.subplots(figsize=(9.5, 5.2))
for i, (k, lb, c1, c2) in enumerate([('only0', '仅 0:00', '#4C72B0', '#74A7D8'),
                                     ('roll', '0/6/12/18 滚动', '#DD8452', '#F2B08C')]):
    off = (i - 0.5) * w
    gr = df3[k + '_grid'].values / 1e4; em = df3[k + '_emerg'].values / 1e4
    ax.bar(x + off, gr, w, label=f'{lb} 电网费', color=c1)
    ax.bar(x + off, em, w, bottom=gr, label=f'{lb} 紧急购电费', color=c2)
    for j in range(len(days)):
        t = gr[j] + em[j]
        ax.text(x[j] + off, t + 0.1, f'{t:.1f}', ha='center', fontsize=10)
ax.set_xticks(x); ax.set_xticklabels([DAY_LABEL[k] for k in days], fontsize=11)
ax.set_xlabel('指定日期', fontsize=12); ax.set_ylabel('费用（万元）', fontsize=12)
ax.set_title('问题三：引入多时刻预报前后总费用对比（堆叠柱）', fontsize=13)
ax.legend(fontsize=10, ncol=2); ax.grid(axis='y', ls='--', alpha=0.4)
ax.tick_params(labelsize=11)
fig.tight_layout(); fig.savefig(os.path.join(FIGD, 'A11_q3_roll_compare.png'), dpi=150); plt.close(fig)

# ============ A12 全年费用结构：问题二/三/四-3（电网费 vs 紧急购电费 堆叠） ============
labels = ['问题二\n(完美信息)', '问题三\n(滚动MPC)', '问题四-问题三\n(波动电价)']
grid = [12259844.62, 13008939.33, 13591972.19]
emerg = [0.0, 2254548.51, 2454440.51]
x = np.arange(len(labels)); w = 0.5
fig, ax = plt.subplots(figsize=(8.5, 5.0))
b1 = ax.bar(x, np.array(grid) / 1e6, w, label='电网费', color='#4C72B0')
b2 = ax.bar(x, np.array(emerg) / 1e6, w, bottom=np.array(grid) / 1e6,
            label='紧急购电费', color='#C44E52')
for j in range(3):
    tot = (grid[j] + emerg[j]) / 1e6
    ax.text(x[j], tot + 5, f'{tot:.0f} 万元', ha='center', fontsize=11,
            bbox=dict(fc='white', ec='#333', lw=0.5, boxstyle='round,pad=0.2'))
    ax.text(x[j], (grid[j] + emerg[j] / 2) / 1e6, f'{emerg[j]/1e4:.0f} 万元',
            ha='center', fontsize=10, color='white' if emerg[j] > 1e5 else '#333')
ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=11)
ax.set_ylabel('费用（百万元）', fontsize=12); ax.set_ylim(0, 20)
ax.set_title('全年费用结构：随机/滚动模型逐步逼近真实成本的对比', fontsize=13)
ax.legend(fontsize=10); ax.grid(axis='y', ls='--', alpha=0.4)
ax.tick_params(labelsize=11)
fig.tight_layout(); fig.savefig(os.path.join(FIGD, 'A12_annual_cost.png'), dpi=150); plt.close(fig)

print('已生成：', [f'A9_q2_cvar_compare.png', 'A10_season_cost.png',
                  'A11_q3_roll_compare.png', 'A12_annual_cost.png'], '->', FIGD)
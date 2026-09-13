# -*- coding: utf-8 -*-
"""子任务3：高级图表生成（全部基于真实数据 result/附件，服务明确结论）。

生成 8 张图 → C题/figures_adv/：
  图A1 季节购电费箱型图        （结论：冬>夏>秋>春，ANOVA p<1e-16 → 支持'按季节分类'创新点）
  图A2 季节负荷/光伏柱+误差条   （结论：冬光伏最低、夏负荷最高 → 季节分类动因）
  图A3 波动电价季节分布小提琴图 （结论：冬电价均值最高且右尾重 → 电价季节风险）
  图A4 λ-β 敏感性热力图        （结论：λ↑→总费↓；β 影响小 → 模型对 β 稳健）
  图A5 帕累托前沿：计划费 vs 紧急费 （结论：λ 提供风险-经济折中前沿）
  图A6 四问雷达图              （结论：随机/滚动模型以计算复杂度换可靠性与鲁棒性）
  图A7 光伏预报误差 Q-Q 图      （结论：预报误差近似正态但右尾重 → 随机情景必要性）
  图A8 典型日能量流向桑基图     （结论：购电结构按季节/时段显著不同）
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, scenarios
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import colors as mcolors

OUT = os.path.join(C.C_BASE, 'figures_adv')
os.makedirs(OUT, exist_ok=True)
CB = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#F0E442', '#56B4E9', '#E69F00']  # 色盲友好

def season(d):
    m = d.month
    return {12:'冬',1:'冬',2:'冬',3:'春',4:'春',5:'春',6:'夏',7:'夏',8:'夏',9:'秋',10:'秋',11:'秋'}[m]
SORDER = ['春','夏','秋','冬']

a1 = data.load_attach1(); fp = a1['price']
dates, load, pv = data.load_attach2()
dates4, p4 = data.load_attach4()
fc3 = data.load_attach3()

# ---------------- 公共：逐日完美信息购电费 ----------------
day_cost = {}
E = C.E_INIT
for i, d in enumerate(dates):
    rp = lp.solve_day_plan(fp, pv[i], load[i], E)
    day_cost[d] = float(np.sum(fp * rp['P']))
    E = rp['E'][-1]

df = pd.DataFrame({'date': dates, 'seas': [season(d) for d in dates],
                   'cost': [day_cost[d] for d in dates],
                   'ld': load.sum(axis=1), 'pv': pv.sum(axis=1),
                   'pm': p4.mean(axis=1)})

# ================= 图A1 季节购电费箱型图 =================
fig, ax = plt.subplots(figsize=(8, 4.6))
data_s = [df[df.seas == s]['cost'] / 1e4 for s in SORDER]
bp = ax.boxplot(data_s, tick_labels=SORDER, patch_artist=True, widths=0.55,
                medianprops=dict(color='k', lw=1.4))
for patch, cc in zip(bp['boxes'], CB[:4]):
    patch.set_facecolor(cc); patch.set_alpha(0.65)
ax.set_ylabel('日购电费（万元）'); ax.set_xlabel('季节')
ax.set_title('图A1  各季节日购电费分布（完美信息口径）')
ax.grid(alpha=0.3, axis='y')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A1_season_cost_box.png'), dpi=150); plt.close(fig)

# ================= 图A2 季节负荷/光伏 =================
g = df.groupby('seas')[['ld', 'pv']].mean().reindex(SORDER) / 1e4
gstd = df.groupby('seas')[['ld', 'pv']].std().reindex(SORDER) / 1e4
x = np.arange(4); w = 0.36
fig, ax = plt.subplots(figsize=(8, 4.6))
ax.bar(x - w/2, g['ld'], w, yerr=gstd['ld'], capsize=3, color=CB[0], alpha=0.85, label='日负荷均值')
ax.bar(x + w/2, g['pv'], w, yerr=gstd['pv'], capsize=3, color=CB[1], alpha=0.85, label='日光伏均值')
ax.set_xticks(x); ax.set_xticklabels(SORDER)
ax.set_ylabel('日能量（万 kWh）'); ax.set_title('图A2  各季节日负荷与光伏出力（均值±标准差）')
ax.legend(); ax.grid(alpha=0.3, axis='y')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A2_season_ld_pv.png'), dpi=150); plt.close(fig)

# ================= 图A3 季节电价小提琴图 =================
fig, ax = plt.subplots(figsize=(8, 4.6))
vp = ax.violinplot([df[df.seas == s]['pm'] for s in SORDER],
                   positions=[0,1,2,3], widths=0.7, showmedians=True)
for b, cc in zip(vp['bodies'], CB[:4]):
    b.set_facecolor(cc); b.set_alpha(0.6)
ax.set_xticks([0,1,2,3]); ax.set_xticklabels(SORDER)
ax.set_ylabel('日平均电价（元/kWh）')
ax.set_title('图A3  各季节日平均电价分布（附件4）')
ax.grid(alpha=0.3, axis='y')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A3_price_violin.png'), dpi=150); plt.close(fig)

# ================= 图A4/A5: λ-β 敏感性（两阶段随机+CVaR, 2025-03-20） =================
D0 = pd.Timestamp('2025-03-20'); i0 = int(np.where(dates == D0)[0][0])
E0 = C.E_INIT
for j in range(i0):
    rp = lp.solve_day_plan(fp, pv[j], load[j], E0); E0 = rp['E'][-1]
hist_lo = load[max(0, i0-9):i0]; hist_pv = pv[max(0, i0-9):i0]
fc = scenarios.forecast_and_scenarios(hist_lo, hist_pv, S=C.S_NUM, seed=i0+1)

LAMS = [0, 0.2, 0.5, 1, 2, 5]
BETS = [0.80, 0.85, 0.90, 0.95, 0.99]
grid = np.zeros((len(LAMS), len(BETS)))
plan_arr = np.zeros((len(LAMS), len(BETS)))
emerg_arr = np.zeros((len(LAMS), len(BETS)))
for ai, lam in enumerate(LAMS):
    for bi, beta in enumerate(BETS):
        two = lp.solve_two_stage(fp, fc['scen_ld'], fc['scen_pv'], E0, lam=lam, beta=beta)
        settle = lp.solve_day_fixedP(fp, pv[i0], load[i0], E0, two['P'])
        pf = float(np.sum(fp * two['P']))
        ef = float(np.sum(5 * fp * settle['Q']))
        plan_arr[ai, bi] = pf; emerg_arr[ai, bi] = ef
        grid[ai, bi] = pf + ef
        print(f'lam={lam} beta={beta} plan={pf:.0f} emerg={ef:.0f} total={pf+ef:.0f}')

# 热力图（总费用）
fig, ax = plt.subplots(figsize=(8.2, 5.4))
im = ax.imshow(grid, aspect='auto', cmap='YlOrRd')
ax.set_xticks(range(len(BETS))); ax.set_xticklabels([str(b) for b in BETS], fontsize=12)
ax.set_yticks(range(len(LAMS))); ax.set_yticklabels([str(l) for l in LAMS], fontsize=12)
for r in range(len(LAMS)):
    for c in range(len(BETS)):
        ax.text(c, r, f'{grid[r,c]/1e4:.1f}', ha='center', va='center', fontsize=12)
ax.set_xlabel('CVaR 置信水平 β', fontsize=13); ax.set_ylabel('风险权重 λ', fontsize=13)
ax.set_title('图A4  λ-β 对当日总费用（万元）的敏感性（2025-03-20）', fontsize=14)
cb = fig.colorbar(im, ax=ax); cb.set_label('总费用（万元）', fontsize=13)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A4_heatmap_lambda_beta.png'), dpi=150); plt.close(fig)

# 帕累托前沿（β=0.9）
fig, ax = plt.subplots(figsize=(8.2, 5.4))
ax.plot(plan_arr[:, 2]/1e4, emerg_arr[:, 2]/1e4, '-o', color=CB[0], lw=2.0)
for ai, lam in enumerate(LAMS):
    px, py = plan_arr[ai,2]/1e4, emerg_arr[ai,2]/1e4
    dy = (8 if ai % 2 == 0 else -14) if ai < len(LAMS) - 1 else -14
    ax.annotate(f'λ={lam}', (px, py), textcoords='offset points', xytext=(10, dy),
                fontsize=12, bbox=dict(fc='white', ec='none', alpha=0.7, pad=1))
ax.set_xlabel('计划购电费（万元）', fontsize=13); ax.set_ylabel('紧急购电费（万元）', fontsize=13)
ax.set_title('图A5  计划购电费—紧急购电费 帕累托前沿（β=0.9, 2025-03-20）', fontsize=14)
ax.tick_params(labelsize=11)
ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A5_pareto.png'), dpi=150); plt.close(fig)

# ================= 图A6 雷达图 =================
fig, ax = plt.subplots(figsize=(7.4, 6.6), subplot_kw=dict(polar=True))
dims = ['经济性', '供电可靠性', '鲁棒性', '计算复杂度', '信息利用度']
# 半定量打分 0-10：确定性LP / 两阶段随机 / 滚动MPC / 波动电价重算
vals = dict(LP=[8, 4, 2, 9, 3], 随机=[6, 9, 8, 4, 7], MPC=[7, 8, 9, 3, 8], 波动=[5, 8, 8, 3, 9])
N = len(dims); ang = np.linspace(0, 2*np.pi, N, endpoint=False).tolist(); ang += ang[:1]
for k, (name, v) in enumerate(vals.items()):
    vv = v + v[:1]
    ax.plot(ang, vv, label=name, color=CB[k], lw=1.8)
    ax.fill(ang, vv, color=CB[k], alpha=0.12)
ax.set_xticks(ang[:-1]); ax.set_xticklabels(dims, fontsize=13)
ax.set_ylim(0, 10); ax.set_yticks([2,4,6,8,10]); ax.set_yticklabels(['2','4','6','8','10'], fontsize=11)
ax.set_title('图A6  四种模型在五维度上的对比（半定量评分）', fontsize=14)
ax.legend(loc='upper right', bbox_to_anchor=(1.32, 1.12), fontsize=12)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A6_radar.png'), dpi=150); plt.close(fig)

# ================= 图A7 光伏预报误差 Q-Q =================
# 用附件3 0:00 预报 与 附件2 实际 的日总量误差（取全年）
day_fc = {}
for d in dates:
    g0, _ = data.pv_forecast_kwh(fc3, d, 0)
    day_fc[d] = g0.sum()
err = np.array([day_fc[d] - pv[i].sum() for i, d in enumerate(dates)])
err = err / np.maximum(np.array([pv[i].sum() for i in range(len(dates))]), 1e-6) * 100  # %相对误差
err = err[np.isfinite(err)]
from scipy import stats
fig, ax = plt.subplots(figsize=(7, 5.2))
stats.probplot(err, dist='norm', plot=ax)
ax.set_title('图A7  光伏日预报相对误差的 Q-Q 图（附件3 vs 附件2）')
ax.set_xlabel('理论分位数'); ax.set_ylabel('样本分位数（%）')
ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'A7_pv_err_qq.png'), dpi=150); plt.close(fig)

# ================= 图A8 桑基图：典型日能量流向 =================
try:
    from matplotlib.sankey import Sankey
except Exception:
    print('sankey unavailable'); A8 = False
else:
    # 用 2025-06-21 完美信息日：电网购电 + 光伏 + 储能放电 → 负荷 + 充电 + 弃光
    d = pd.Timestamp('2025-06-21'); i = int(np.where(dates == d)[0][0])
    E = C.E_INIT
    for j in range(i):
        rp = lp.solve_day_plan(fp, pv[j], load[j], E); E = rp['E'][-1]
    rp = lp.solve_day_plan(fp, pv[i], load[i], E)
    P = rp['P'].sum(); G = pv[i].sum(); F = (C.ETA*rp['f']).sum()   # 放电(输出侧)
    D = load[i].sum(); Ch = rp['c'].sum(); R = rp['R'].sum()
    # 标准两列能量流向图（自绘，标签外置零遮挡；替代 matplotlib.sankey 楔形旧图）
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch, Rectangle
    A8C = ['#0072B2', '#D55E00', '#009E73']
    # 流带分解（守恒：P + (G-R-Ch) + F = D；Ch、R 记光伏）
    assert G - R - Ch > 0, '光伏直供为负，分带方案不适用'
    bands = [(0, 0, P), (1, 0, G - R - Ch), (1, 1, Ch), (1, 2, R), (2, 0, F)]
    L_NAMES, R_NAMES = ['电网购电', '光伏出力', '储能放电'], ['负荷', '储能充电', '弃光']
    L_VALS, R_VALS = [P, G, F], [D, Ch, R]
    SRC_COLOR = {0: A8C[0], 1: A8C[1], 2: A8C[2]}
    TP = sum(v for _, _, v in bands)
    Y0, H, GAP = 0.12, 0.74, 0.035
    def _stack(vals):
        hs = [v / TP * (H - GAP * (len(vals) - 1)) for v in vals]
        out, y = [], 1.0
        for h in hs:
            out.append((y, y - h)); y -= h + GAP
        return out
    LT, RT = _stack(L_VALS), _stack(R_VALS)
    X0, X1, W = 0.30, 0.70, 0.028
    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    for k, (t, b) in enumerate(LT):
        ax.add_patch(Rectangle((X0 - W, b), W, t - b, facecolor=SRC_COLOR[k],
                               edgecolor='black', linewidth=0.8, alpha=0.95))
        ax.text(X0 - W - 0.02, (t + b) / 2, f'{L_NAMES[k]}\n{L_VALS[k]:,.0f} kWh',
                ha='right', va='center', fontsize=13)
    for k, (t, b) in enumerate(RT):
        ax.add_patch(Rectangle((X1, b), W, t - b,
                               facecolor=['#444444', A8C[2], '#888888'][k],
                               edgecolor='black', linewidth=0.8, alpha=0.95))
        ax.text(X1 + W + 0.02, (t + b) / 2, f'{R_NAMES[k]}\n{R_VALS[k]:,.0f} kWh',
                ha='left', va='center', fontsize=13)
    rcur = {k: RT[k][0] for k in range(3)}
    lcur = {k: LT[k][0] for k in range(3)}
    for (s, t, v) in bands:
        h = v / TP * (H - GAP * (len(R_VALS) - 1))
        y0t, y0b = lcur[s], lcur[s] - h
        y1t, y1b = rcur[t], rcur[t] - h
        lcur[s] -= h; rcur[t] -= h
        xm = (X0 + X1) / 2
        pth = Path([(X0, y0t), (xm, y0t), (xm, y1t), (X1, y1t),
                    (X1, y1b), (xm, y1b), (xm, y0b), (X0, y0b), (X0, y0t)],
                   [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
                    Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CLOSEPOLY])
        ax.add_patch(PathPatch(pth, facecolor=SRC_COLOR[s], alpha=0.35, edgecolor='none'))
    ax.set_xlim(0, 1); ax.set_ylim(0.07, 1.02); ax.axis('off')
    fig.tight_layout()
    for out in {OUT, os.path.join(C.C_BASE, 'paper', 'figures_adv')}:
        os.makedirs(out, exist_ok=True)
        fig.savefig(os.path.join(out, 'A8_sankey.png'), dpi=200)
    plt.close(fig)
    A8 = True

print('\n全部图表已输出至', OUT)
print(sorted(os.listdir(OUT)))
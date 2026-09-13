# -*- coding: utf-8 -*-
"""问题1：确定性 MILP/LP 日计划（附件1 完美信息）。

储能日循环：storage 日末回到日初(6000 kWh)，保证可长期重复运行；
目标：最小化当日购电费用(电价 p·购电量)，约束含 能量平衡、储能上下限、充放电功率上限、
      光伏/负载(附件1 预报)已知。输出 result1.xlsx(两张表) + 计划图。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import config as C
C.setup_plot_style()
import matplotlib.pyplot as plt
import data, lp, results as R


def run(outfile='result1.xlsx'):
    a1 = data.load_attach1()
    price = a1['price']
    rp = lp.solve_day_plan(price, a1['pv'], a1['load'], C.E_INIT, force_end=C.E_INIT)
    P, c, f, E = rp['P'], rp['c'], rp['f'], rp['E']
    cost = float(np.sum(price * P))
    path = os.path.join(C.RES_DIR, outfile)
    R.write_result1(path, P, c, f, C.E_INIT, E[-1], price)
    print('已写出', path)
    print(f'[Q1 确定性日计划] 购电量合计={P.sum():.2f} kWh，购电费={cost:.2f} 元，'
          f'0:00 储电={C.E_INIT}，24:00 储电={E[-1]:.2f}')
    return dict(price=price, P=P, c=c, f=f, E=E, cost=cost)


def plot(P, c, f, E, price, path=None):
    """计划购电/充电/放电/储电量/电价 可视化。"""
    x = np.arange(C.T_IN_DAY)
    fig, ax1 = plt.subplots(figsize=(13, 5.5))
    ax1.bar(x, P, width=0.6, alpha=0.7, label='购电量(kWh)', color='tab:blue')
    ax1.bar(x, c, width=0.6, alpha=0.5, label='充电量(kWh)', color='tab:green')
    ax1.bar(x, f, width=0.6, alpha=0.5, label='放电量(kWh)', color='tab:orange')
    ax1.set_xlabel('时段(每10min)', fontsize=13); ax1.set_ylabel('能量(kWh)', fontsize=13)
    ax1.set_xlim(0, C.T_IN_DAY)
    ax1.set_xticks(range(0, C.T_IN_DAY + 1, 12))
    ax1.legend(loc='upper left', fontsize=12); ax1.grid(alpha=0.3)
    ax1.tick_params(labelsize=11)

    ax2 = ax1.twinx()
    ax2.plot(x, E, color='tab:red', lw=1.6, label='储电量(kWh)')
    ax2.axhline(C.SOC_HIGH_BOUND, color='gray', ls=':', lw=1)
    ax2.axhline(C.SOC_MIN, color='gray', ls=':', lw=1)
    ax2.set_ylabel('储电量(kWh)', fontsize=13); ax2.legend(loc='upper right', fontsize=12)
    ax2.set_ylim(0, C.SOC_MAX)
    ax2.tick_params(labelsize=11)
    plt.title('问题1：单日最优运营计划（储能日循环）', fontsize=14)
    fig.tight_layout()
    path = path or os.path.join(C.FIG_DIR, 'q1_plan.png')
    fig.savefig(path, dpi=150); plt.close(fig)
    print('图已存', path)


def dp_cost_day(price, G, D, E_start=C.E_INIT, E_end=C.E_INIT, h=120.0):
    """状态空间动态规划精确求解单日最小购电费（网格步长 h，验证 LP 全局最优性）。

    状态 = 时段末储电量 E ∈ {1200, 1200+h, ..., 10800}；
    转移 E→E'：若 Δ=E'-E>0 则 c=Δ/η、f=0；Δ<0 则 f=-Δ、c=0；
    购电 P = max(D-G-η·f+c, 0)（弃光免费）；V_t(E)=min_{E'}(p_t·P+V_{t+1}(E'))，
    终端 V_{144}(E_end)=0，起点 V_0(E_start) 即最优费用。向量化：每时段对
    |Δ|≤min(E_FMAX, η·E_CMAX) 的网格位移求 min。
    """
    T = C.T_IN_DAY
    grid = np.arange(C.SOC_MIN, C.SOC_HIGH_BOUND + 1e-9, h)
    n = len(grid)
    idx = {round(float(e), 6): i for i, e in enumerate(grid)}
    if round(float(E_start), 6) not in idx or round(float(E_end), 6) not in idx:
        raise ValueError('起/止储电量不在 DP 网格上（请选网格 h 整除 1200..10800）')
    K = int(np.floor(min(C.E_FMAX, C.ETA * C.E_CMAX) / h))
    ks = np.arange(-K, K + 1)
    dE = ks * h
    f = np.maximum(-dE, 0.0)             # 放电量
    c = np.maximum(dE / C.ETA, 0.0)      # 充电量
    Pk = np.maximum(D[:, None] - G[:, None] - C.ETA * f[None, :] + c[None, :], 0.0)  # (T, 2K+1)
    INF = np.inf
    V = np.full(n, INF)
    V[idx[round(float(E_end), 6)]] = 0.0
    for t in range(T - 1, -1, -1):
        cand = np.full((n, 2 * K + 1), INF)
        for k2, k in enumerate(ks):
            j = np.arange(n) + k
            ok = (j >= 0) & (j < n)
            cand[ok, k2] = price[t] * Pk[t, k2] + V[j[ok]]
        V = cand.min(axis=1)
    return float(V[idx[round(float(E_start), 6)]])


def dp_report(price=None):
    """问题1 LP 最优性动态规划验证。

    (1) 附件1 典型日：网格 h∈{120,60,30,15} 的 DP 费用收敛到 LP 解（h=15 偏差 ≤ 0.5%），
        验证 LP 全局最优；
    (2) 附件2 全年逐日：h=15 下 DP 与 LP（均 E_0=E_144=6000 日循环）费用差，
        报告最大/平均相对偏差（网格离散化误差）。
    写 report/q1_dp_verification.csv 与 paper/figures_adv/A13_q1_dp.png。
    """
    a1 = data.load_attach1()
    price = a1['price'] if price is None else price
    G, D = a1['pv'], a1['load']
    rp = lp.solve_day_plan(price, G, D, C.E_INIT, force_end=C.E_INIT)
    lp_cost = float(np.sum(price * rp['P']))

    rows = []
    print(f'[Q1 DP 验证] 附件1 典型日：网格收敛（LP 解 = {lp_cost:,.2f} 元）')
    conv = {}
    for h in (120.0, 60.0, 30.0, 15.0):
        dp = dp_cost_day(price, G, D, h=h)
        conv[h] = dp
        rows.append(dict(day='附件1典型日', grid_h=h, lp_cost=lp_cost,
                         dp_cost=dp, gap_pct=(dp - lp_cost) / lp_cost * 100))
        print(f'  h={h:g}: DP={dp:,.2f} 元  gap={(dp - lp_cost) / lp_cost * 100:.4f}%')

    dates, load, pv = data.load_attach2()
    gaps = []
    for i in range(len(dates)):
        rpi = lp.solve_day_plan(price, pv[i], load[i], C.E_INIT, force_end=C.E_INIT)
        lpi = float(np.sum(price * rpi['P']))
        dpi = dp_cost_day(price, pv[i], load[i], h=15.0)
        gaps.append(dpi - lpi)
        rows.append(dict(day=str(dates[i].date()), grid_h=15, lp_cost=round(lpi, 4),
                         dp_cost=round(dpi, 4), gap_pct=(dpi - lpi) / lpi * 100))
    gaps = np.asarray(gaps)
    gap_p = gaps / np.asarray([r['lp_cost'] for r in rows if r['day'] != '附件1典型日']) * 100
    print(f'[Q1 DP 验证] 附件2 全年 {len(dates)} 日（h=15）：max gap = {gaps.max():.2f} 元 '
          f'({gap_p.max():.3f}%)，mean gap = {gaps.mean():.2f} 元 ({gap_p.mean():.3f}%)')
    path = os.path.join(C.RES_DIR, 'q1_dp_verification.csv')
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')
    print('已写', path)

    # A13 图：左=网格收敛，右=全年逐日偏差分布
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.3))
    hs = sorted(conv)
    ax1.plot(hs, [conv[h] for h in hs], '-o', color='tab:blue')
    ax1.axhline(lp_cost, color='tab:red', ls='--', lw=1.2, label=f'LP 最优 = {lp_cost:,.2f} 元')
    ax1.set_xscale('log', base=2); ax1.invert_xaxis()
    ax1.set_xticks(list(hs)); ax1.set_xticklabels([f'{h:g}' for h in hs], fontsize=12)
    ax1.set_xlabel('DP 网格步长 h (kWh)', fontsize=13)
    ax1.set_ylabel('最小购电费 (元)', fontsize=13)
    ax1.set_title('(a) 附件1 典型日：DP 网格收敛', fontsize=14)
    ax1.legend(fontsize=12); ax1.grid(alpha=0.3)
    ax1.tick_params(labelsize=11)
    gp = np.asarray([r['gap_pct'] for r in rows if r['day'] != '附件1典型日'])
    ax2.hist(gp, bins=30, color='tab:green', alpha=0.75, edgecolor='w')
    ax2.axvline(gp.mean(), color='k', ls='--', lw=1.2, label=f'平均 = {gp.mean():.3f}%')
    ax2.set_xlabel('DP 相对 LP 偏差 (%)', fontsize=13)
    ax2.set_ylabel('天数', fontsize=13)
    ax2.set_title('(b) 附件2 全年逐日偏差分布 (h=15)', fontsize=14)
    ax2.legend(fontsize=12); ax2.grid(alpha=0.3, axis='y')
    ax2.tick_params(labelsize=11)
    fig.tight_layout()
    out = os.path.join(C.C_BASE, 'paper', 'figures_adv', 'A13_q1_dp.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=150); plt.close(fig)
    print('图已存', out)
    return rows


if __name__ == '__main__':
    A = run()
    plot(A['P'], A['c'], A['f'], A['E'], A['price'])
    dp_report(A['price'])
# -*- coding: utf-8 -*-
"""问题1：确定性 MILP/LP 日计划（附件1 完美信息）。

储能日循环：storage 日末回到日初(6000 kWh)，保证可长期重复运行；
目标：最小化当日购电费用(电价 p·购电量)，约束含 能量平衡、储能上下限、充放电功率上限、
      光伏/负载(附件1 预报)已知。输出 result1.xlsx(两张表) + 计划图。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
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
    ax1.set_xlabel('时段(每10min)', fontsize=12); ax1.set_ylabel('能量(kWh)', fontsize=12)
    ax1.set_xlim(0, C.T_IN_DAY)
    ax1.set_xticks(range(0, C.T_IN_DAY + 1, 12))
    ax1.legend(loc='upper left', fontsize=11); ax1.grid(alpha=0.3)
    ax1.tick_params(labelsize=11)

    ax2 = ax1.twinx()
    ax2.plot(x, E, color='tab:red', lw=1.6, label='储电量(kWh)')
    ax2.axhline(C.SOC_HIGH_BOUND, color='gray', ls=':', lw=1)
    ax2.axhline(C.SOC_MIN, color='gray', ls=':', lw=1)
    ax2.set_ylabel('储电量(kWh)', fontsize=12); ax2.legend(loc='upper right', fontsize=11)
    ax2.set_ylim(0, C.SOC_MAX)
    ax2.tick_params(labelsize=11)
    plt.title('问题1：单日最优运营计划（储能日循环）', fontsize=14)
    fig.tight_layout()
    path = path or os.path.join(C.FIG_DIR, 'q1_plan.png')
    fig.savefig(path, dpi=150); plt.close(fig)
    print('图已存', path)


if __name__ == '__main__':
    A = run()
    plot(A['P'], A['c'], A['f'], A['E'], A['price'])
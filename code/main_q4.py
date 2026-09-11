# -*- coding: utf-8 -*-
"""问题4：波动电价(附件4)重算 问题2/问题3 → result4-2.xlsx / result4-3.xlsx + 对比图。

附件2(负载/光伏实际)、附件4(波动电价) 均为 全年366×144 矩阵，日期必须对齐。
口径沿用：
  Q4-2 = 问题2 确定性完美信息两阶段计划，仅把固定电价(附件1)换成当日波动电价；
  Q4-3 = 问题3 滚动随机 MPC(0/6/12/18 调整 + 违约50%/超购150% 惩罚)，按当日波动电价结算。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
from main_q3 import _load_fc_point
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
TAU = [0, 6, 12, 18]


# ---------------- Q4-2：波动电价 + 问题2 完美信息 ----------------
def run_q42():
    dates4, price4 = data.load_attach4()          # price4[365,144]
    dates, load, pv = data.load_attach2()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        pr = price4[i]
        rp = lp.solve_day_plan(pr, pv[i], load[i], E_start)
        rec[dates[i]] = dict(P=rp['P'], Q=np.zeros(C.T_IN_DAY), c=rp['c'], f=rp['f'],
                             E_start=E_start, E_end=rp['E'][-1])
        E_start = rp['E'][-1]
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, 'result4-2.xlsx')
    R.write_result2(path, dates_out, P, Q, c, f, E0, Ee, tpl_name='result4-2.xlsx')
    idx_of = {d: i for i, d in enumerate(dates)}
    cost = sum(float(np.sum(price4[idx_of[d]] * rec[d]['P'])) for d in dates_out)
    print('已写出', path)
    print(f'[Q4-2 波动电价+完美信息] 计划总购电费 = {cost:.2f} 元，紧急购电 = 0 kWh')
    return dict(dates=dates, load=load, pv=pv, price4=price4,
                rec=rec, dates_out=dates_out, cost=cost)


# ---------------- Q4-3：波动电价 + 滚动 MPC ----------------
def _adjust(price, P, A, Q):
    u = np.maximum(P - A, 0.0)
    w = np.maximum(A - P, 0.0)
    grid_fee = float(np.sum(price * np.minimum(P, A) + C.DEFAULT_MULT * price * u + C.EXCESS_MULT * price * w))
    emerg_fee = float(np.sum(C.EMERG_MULT * price * Q))
    return grid_fee, emerg_fee


def _rolling(price_day, load_act, pv_act, fc3, d, E_start, K=7):
    """price_day: 当日 144 价格；负载/光伏 为当日实际；返回 dict。"""
    D_known = load_act
    G0 = data.pv_forecast_kwh(fc3, d, 0)[0]
    plan = lp.solve_day_plan(price_day, G0, D_known, E_start)
    P = plan['P']
    E_plan = plan['E'].copy()
    A = P.copy()
    for tau in TAU[1:]:
        t0 = tau * 6
        G_tau = data.pv_forecast_kwh(fc3, d, tau)[0]
        E_tau = E_plan[t0 - 1] if t0 > 0 else E_start
        rp = lp.solve_adjust(price_day, G_tau, D_known, E_tau, P, t0)
        A[t0:] = rp['A']
        if rp['E'].size:
            E_plan[t0:] = rp['E']
    settle = lp.solve_day_fixedP(price_day, pv_act, load_act, E_start, A)
    grid_fee, emerg_fee = _adjust(price_day, P, A, settle['Q'])
    return dict(P=P, A=A, Q=settle['Q'], c=settle['c'], f=settle['f'],
                grid_fee=grid_fee, emerg_fee=emerg_fee, E_end=settle['E'][-1])


def run_q43():
    dates4, price4 = data.load_attach4()
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        pr = price4[i]
        res = _rolling(pr, load[i], pv[i], fc3, dates[i], E_start)
        res['E_start'] = E_start
        rec[dates[i]] = res
        E_start = res['E_end']
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    A = {d: rec[d]['A'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, 'result4-3.xlsx')
    R.write_result3(path, dates_out, P, A, Q, c, f, E0, Ee, tpl_name='result4-3.xlsx')
    tot_grid = sum(rec[d]['grid_fee'] for d in dates_out)
    tot_emerg = sum(rec[d]['emerg_fee'] for d in dates_out)
    print('已写出', path)
    print(f'[Q4-3 波动电价+滚动MPC] 电网费={tot_grid:.2f} 紧急费={tot_emerg:.2f} 合计={tot_grid + tot_emerg:.2f} 元')
    return dict(dates=dates, dates_out=dates_out, rec=rec,
                tot_grid=tot_grid, tot_emerg=tot_emerg)


def shell():
    q42 = run_q42()
    q43 = run_q43()
    dates4, price4 = data.load_attach4()
    mean_p = price4.mean(axis=1)
    x = np.arange(len(mean_p))
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(x, mean_p, lw=1.2, label='附件4 波动电价(日均)')
    ax.axhline(C.EMERG_MULT * np.median(mean_p), color='r', ls='--', lw=1,
               label='固定电价(附件1,均值省略)')
    ax.set_xlabel('日期索引(1.1起)'); ax.set_ylabel('平均电价(元/kWh)')
    ax.set_title('问题4：波动电价(附件4)与求解区间示意')
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q4_price.png'), dpi=150); plt.close(fig)
    print('图已存', os.path.join(C.FIG_DIR, 'q4_price.png'))


if __name__ == '__main__':
    shell()
# -*- coding: utf-8 -*-
"""问题3：滚动随机 MPC + 调整惩罚。

0:00 用 附件1 电价 + 0:00 光伏预报(附件3) + 负载点预报(历史)制定计划购电 P；
6/12/18 用最新光伏预报在"违约50%/超购1.5倍"目标下滚动重解剩余时段调整购电 A；
结算：固定最终 A 对当日实际(附件2 负载/光伏)重调度，得到紧急购电 Q 与日末储电。
费用口径：cost_t = p·min(P,A) + 0.5p·(P-A)^+ + 1.5p·(A-P)^+ + 5p·Q_t。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
TAU = [0, 6, 12, 18]


def _load_fc_point(hist, K=7):
    n = len(hist)
    if n == 0:
        return np.zeros(C.T_IN_DAY)
    return np.mean(hist[-min(K, n):], axis=0)


def _adjust(price, P, A, Q):
    """按费用口径计算：电网费用 + 紧急购电费用。返回 (grid_fee, emerg_fee, fee_vec)。"""
    u = np.maximum(P - A, 0.0)
    w = np.maximum(A - P, 0.0)
    grid_fee = float(np.sum(price * np.minimum(P, A) + C.DEFAULT_MULT * price * u + C.EXCESS_MULT * price * w))
    emerg_fee = float(np.sum(C.EMERG_MULT * price * Q))
    base = price * np.minimum(P, A) + C.DEFAULT_MULT * price * u + C.EXCESS_MULT * price * w + C.EMERG_MULT * price * Q
    return grid_fee, emerg_fee, base


def _rolling(price, load, pv, dates, fc3, i, E_start, K=7):
    """单日滚动。load 视为已知(附件2)；光伏不确定：计划/调整用 附件3 预报，结算用 附件2 实际。
    返回 dict(...)。"""
    load_act = load[i]; pv_act = pv[i]; d = dates[i]
    D_known = load_act                       # 负载已知
    G0 = data.pv_forecast_kwh(fc3, d, 0)[0]  # 0:00 光伏预报
    plan = lp.solve_day_plan(price, G0, D_known, E_start)
    P = plan['P']
    E_plan = plan['E'].copy()
    A = P.copy()
    for tau in TAU[1:]:
        t0 = tau * 6
        G_tau = data.pv_forecast_kwh(fc3, d, tau)[0]
        E_tau = E_plan[t0 - 1] if t0 > 0 else E_start
        rp = lp.solve_adjust(price, G_tau, D_known, E_tau, P, t0)
        A[t0:] = rp['A']
        if rp['E'].size:
            E_plan[t0:] = rp['E']
    # 结算(固定购电 A，实际光伏)
    settle = lp.solve_day_fixedP(price, pv_act, load_act, E_start, A)
    grid_fee, emerg_fee, _ = _adjust(price, P, A, settle['Q'])
    return dict(P=P, A=A, Q=settle['Q'], c=settle['c'], f=settle['f'],
                grid_fee=grid_fee, emerg_fee=emerg_fee, E_end=settle['E'][-1])


def run(outfile='result3.xlsx'):
    a1 = data.load_attach1()
    price = a1['price']
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        d = dates[i]
        res = _rolling(price, load, pv, dates, fc3, i, E_start)
        res['E_start'] = E_start
        rec[d] = res
        E_start = res['E_end']

    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    A = {d: rec[d]['A'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, outfile)
    R.write_result3(path, dates_out, P, A, Q, c, f, E0, Ee)

    tot_grid = sum(rec[d]['grid_fee'] for d in dates_out)
    tot_emerg = sum(rec[d]['emerg_fee'] for d in dates_out)
    tot = tot_grid + tot_emerg
    print('已写出', path)
    print(f'[Q3 滚动MPC] 计划+调整电网费={tot_grid:.2f} 元, 紧急购电费={tot_emerg:.2f} 元, 合计={tot:.2f} 元')
    return dict(price=price, dates=dates, load=load, pv=pv, fc3=fc3, rec=rec, dates_out=dates_out)


def analysis(price, dates, load, pv, fc3, rec):
    """是否需要其他时刻预报：比较 仅0:00(不调整) vs 0/6/12/18 滚动。"""
    rows = []
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        i = int(np.where(dates == d)[0][0])
        E_start = rec[d]['E_start']
        G0 = data.pv_forecast_kwh(fc3, d, 0)[0]
        plan = lp.solve_day_plan(price, G0, load[i], E_start)
        st = lp.solve_day_fixedP(price, pv[i], load[i], E_start, plan['P'])
        g0, e0, _ = _adjust(price, plan['P'], plan['P'], st['Q'])
        r = _rolling(price, load, pv, dates, fc3, i, E_start)
        rows.append(dict(day=dd, only0_grid=g0, only0_emerg=e0, only0_total=g0 + e0,
                         roll_grid=r['grid_fee'], roll_emerg=r['emerg_fee'],
                         roll_total=r['grid_fee'] + r['emerg_fee']))
    df = pd.DataFrame(rows)
    print('\n[Q3 调整时点分析]')
    print(df.to_string(index=False))
    df.to_csv(os.path.join(C.RES_DIR, 'q3_rolling_comparison.csv'), index=False, encoding='utf-8-sig')
    x = np.arange(len(df))
    w = 0.32
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w / 2, df.only0_total, w, label='仅0:00(不调整)')
    ax.bar(x + w / 2, df.roll_total, w, label='0/6/12/18 滚动')
    ax.set_xticks(x); ax.set_xticklabels(df.day)
    ax.set_ylabel('总购电费用(元)'); ax.set_title('问题3：是否引入多时刻预报')
    ax.legend(); ax.grid(alpha=0.4, axis='y')
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q3_forecast_time.png'), dpi=150); plt.close(fig)


if __name__ == '__main__':
    A = run()
    analysis(A['price'], A['dates'], A['load'], A['pv'], A['fc3'], A['rec'])
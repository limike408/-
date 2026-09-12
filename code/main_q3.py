# -*- coding: utf-8 -*-
"""问题3：滚动随机 MPC + 调整惩罚（18.0 因果严谨版）。

0:00 用 附件1 电价 + 0:00 光伏预报(附件3) + 负荷点预报(历史逐槽均值, K=15)制定计划购电 P；
6/12/18 用最新光伏预报在"违约50%/超购1.5倍"目标下做**情景鲁棒滚动再计划**（随机 MPC）：
  以 scenarios.pv_scenarios 生成 S=30 个光伏情景，一阶段购电 A 共用、各情景独立电池调度
  （允许情景内紧急购电 5p 保证可行），目标 = 期望电网费（lam=0）；
  调整时点储能用**实际 SOC 回放**（以已承诺购电 A[:t0] + 当日实际负荷/光伏回放至 t0）；
结算**去后见之明**：逐时段 t 以 [0..t] 前缀（固定购电 A[:t+1]、实际负荷/光伏到 t）重解电池，
  取末段 c/f/Q/E 结转，替代"全天实际重优化"。
费用口径：cost_t = p·min(P,A) + 0.5p·(P-A)^+ + 1.5p·(A-P)^+ + 5p·Q_t。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
import scenarios
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
TAU = [0, 6, 12, 18]
SEED = 2026            # 情景抽样种子基数：2026 + 日序（与 Q2 对齐，确定性可复现）
K_LOAD = 15            # 负荷点预报窗口（与 Q2 K_L 交叉验证结论对齐）


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


def causal_settle(price, pv_act, load_act, E_start, A):
    """去后见之明结算（替代全天实际重优化）。

    逐时段 t：以 [0..t] 前缀 LP —— 固定购电 A[:t+1]（已承诺）、当日实际负荷/光伏只用到 t ——
    重解电池充放电，取末段 c/f/Q/R/E 作为 t 时段的真实运行量并结转储能。
    全程只用 t 及之前的信息，不借用未来实际光伏/负荷。
    返回 dict(c,f,Q,R,E_end)。
    """
    T = C.T_IN_DAY
    c = np.zeros(T); f = np.zeros(T); Q = np.zeros(T); R = np.zeros(T)
    E_carry = E_start
    for t in range(T):
        res = lp.solve_day(price[:t + 1], pv_act[:t + 1], load_act[:t + 1], E_carry,
                           T=t + 1, fixed_P=A[:t + 1], allow_P=False, emult=C.EMERG_MULT)
        c[t] = res['c'][-1]; f[t] = res['f'][-1]
        Q[t] = res['Q'][-1]; R[t] = res['R'][-1]
        E_carry = res['E'][-1]
    return dict(c=c, f=f, Q=Q, R=R, E_end=E_carry)


def _cold_load():
    """冷启动负荷预报：2025-01-01 无历史，用附件1 典型日负荷剖面（与 Q2 口径一致）。"""
    return data.load_attach1()['load']


def _rolling_day(price_day, load_act, pv_act, load_hist, pv_hist, fc3, d, E_start,
                 K=K_LOAD):
    """单日滚动核心（18.0 因果严谨版）。

    - 计划/调整用负荷点预报 D_known（load_hist 前 K 天逐槽均值，K=15，与 Q2 对齐；
      首日无历史时用附件1 典型日剖面冷启动）；
    - 0:00 计划：solve_day_plan(点预报负荷, 0:00 光伏预报)；
    - 6/12/18 情景鲁棒再计划：pv_scenarios(G_tau, 历史) 生成 S=30 光伏情景，
      solve_adjust_scen 共用一阶段购电 A；调整时点储能为实际 SOC 回放；
    - 结算：causal_settle 逐段去后见之明。
    price_day:(144) 当日电价；load_act/pv_act:(144) 当日实际；load_hist/pv_hist:(i,144) 截至前一日历史。
    返回 dict(...)。
    """
    D_known = scenarios.point_forecast(load_hist, K)   # 负荷预报化（历史逐槽均值）
    if len(load_hist) == 0:
        D_known = _cold_load()                         # 冷启动：附件1 典型日剖面
    G0 = data.pv_forecast_kwh(fc3, d, 0)[0]            # 0:00 光伏预报
    plan = lp.solve_day_plan(price_day, G0, D_known, E_start)
    P = plan['P']
    A = P.copy()
    for tau in TAU[1:]:
        t0 = tau * 6
        G_tau = data.pv_forecast_kwh(fc3, d, tau)[0]
        # 实际 SOC 回放：已承诺购电 A[:t0] + 当日实际负荷/光伏至 t0
        pre = lp.solve_day(price_day[:t0], pv_act[:t0], load_act[:t0], E_start,
                           T=t0, fixed_P=A[:t0], allow_P=False, emult=C.EMERG_MULT)
        E_tau = pre['E'][-1]
        # 情景鲁棒滚动再计划（随机 MPC）：光伏情景 S=30，负荷用点预报
        scenG = scenarios.pv_scenarios(G_tau, pv_hist, S=C.S_NUM,
                                       seed=SEED + int(d.dayofyear))
        rp = lp.solve_adjust_scen(price_day, scenG, D_known, E_tau, P, t0, lam=0.0)
        A[t0:] = rp['A']
    # 结算去后见之明
    settle = causal_settle(price_day, pv_act, load_act, E_start, A)
    grid_fee, emerg_fee, _ = _adjust(price_day, P, A, settle['Q'])
    return dict(P=P, A=A, Q=settle['Q'], c=settle['c'], f=settle['f'],
                grid_fee=grid_fee, emerg_fee=emerg_fee, E_end=settle['E_end'])


def _rolling(price, load, pv, dates, fc3, i, E_start, K=K_LOAD):
    """单日滚动（18.0 因果严谨版，按日期索引取数后委托 _rolling_day）。"""
    return _rolling_day(price, load[i], pv[i], load[:i], pv[:i], fc3, dates[i],
                        E_start, K=K)


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

    # 逐日费用 CSV（供 season_split / 论文季节表，覆盖全年含预热月）
    drow = [dict(date=str(d.date()), grid_fee=round(rec[d]['grid_fee'], 2),
                 emerg_fee=round(rec[d]['emerg_fee'], 2),
                 total=round(rec[d]['grid_fee'] + rec[d]['emerg_fee'], 2)) for d in dates]
    pd.DataFrame(drow).to_csv(os.path.join(C.RES_DIR, 'q3_daily_cost.csv'),
                              index=False, encoding='utf-8-sig')
    return dict(price=price, dates=dates, load=load, pv=pv, fc3=fc3, rec=rec, dates_out=dates_out)


def analysis(price, dates, load, pv, fc3, rec):
    """是否需要其他时刻预报：比较 仅0:00(不调整) vs 0/6/12/18 滚动（均用因果结算）。"""
    rows = []
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        i = int(np.where(dates == d)[0][0])
        E_start = rec[d]['E_start']
        D_known = scenarios.point_forecast(load[:i], K_LOAD)
        G0 = data.pv_forecast_kwh(fc3, d, 0)[0]
        plan = lp.solve_day_plan(price, G0, D_known, E_start)
        st = causal_settle(price, pv[i], load[i], E_start, plan['P'])
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
    ax.set_xticks(x); ax.set_xticklabels(df.day, fontsize=11)
    ax.set_ylabel('总购电费用(元)', fontsize=12); ax.set_title('问题3：是否引入多时刻预报', fontsize=13)
    ax.legend(fontsize=11); ax.grid(alpha=0.4, axis='y')
    ax.tick_params(labelsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q3_forecast_time.png'), dpi=150); plt.close(fig)


if __name__ == '__main__':
    A = run()
    analysis(A['price'], A['dates'], A['load'], A['pv'], A['fc3'], A['rec'])
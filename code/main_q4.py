# -*- coding: utf-8 -*-
"""问题4：波动电价(附件4)重算 问题2/问题3 → result4-2.xlsx / result4-3.xlsx + 对比图。

口径沿用（与 15.0 之后的 Q2/Q3 v2 完全一致）：
  Q4-2 = 问题2 预报式两阶段随机规划（K_L=15/K_P=7，整日成对残差 bootstrap，S=30，
         风险权衡 λ=λ* 与 Q2 官方一致），仅把固定电价(附件1)换成当日波动电价(附件4)；
  Q4-3 = 问题3 因果滚动随机 MPC（负荷预报化 + 附件3 预报情景 + SOC 实际轨迹 + 情景鲁棒调整），
         按当日波动电价结算，λ=0（滚动预报更新本身对冲不确定性，同 Q3）。
附件2(负载/光伏实际)与附件4 全年日期必须逐日对齐。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
import scenarios
import main_q2
import main_q3
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

Q2_LAM = main_q2.LAM_OFFICIAL   # 与 Q2 官方链同一风险权重（由 q2_lambda_sweep 数据驱动选定）


# ---------------- Q4-2：波动电价 + 预报式两阶段随机（同 Q2 新口径） ----------------
def run_q42():
    dates4, price4 = data.load_attach4()          # price4[365,144]
    dates, load, pv = data.load_attach2()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    a1 = data.load_attach1()
    S = C.S_NUM
    KL, KP, _ = main_q2.cross_validate_K(dates, load, pv)   # 与 Q2 官方链同源的 K
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        d = dates[i]
        if i == 0:
            scen_ld = np.tile(a1['load'], (S, 1))
            scen_pv = np.tile(a1['pv'], (S, 1))
        else:
            fc = scenarios.residual_scenarios(load[:i], pv[:i], (KL, KP),
                                              S=S, seed=main_q2._seed_for_day(d))
            scen_ld, scen_pv = fc['scen_ld'], fc['scen_pv']
        two = lp.solve_two_stage(price4[i], scen_ld, scen_pv, E_start,
                                 lam=Q2_LAM, beta=C.BETA)
        settle = lp.solve_day_fixedP(price4[i], pv[i], load[i], E_start, two['P'])
        E_t = np.asarray(settle['E'], float)
        assert np.all(E_t >= C.SOC_MIN - 1e-6) and np.all(E_t <= C.SOC_HIGH_BOUND + 1e-6), \
            f'{d.date()} 储能越界'
        rec[d] = dict(P=two['P'], Q=settle['Q'], c=settle['c'], f=settle['f'],
                      E_start=float(E_start), E_end=float(E_t[-1]))
        E_start = float(E_t[-1])
        if (i + 1) % 30 == 0:
            print(f'  Q4-2 进度 {i+1}/{len(dates)} 日（{d.date()}）E={E_start:8.1f} kWh', flush=True)
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, 'result4-2.xlsx')
    R.write_result2(path, dates_out, P, Q, c, f, E0, Ee, tpl_name='result4-2.xlsx')
    path = R.strip_personal_meta(path)
    idx_of = {d: i for i, d in enumerate(dates)}
    plan_fee = sum(float(np.sum(price4[idx_of[d]] * rec[d]['P'])) for d in dates_out)
    emerg_fee = sum(float(np.sum(C.EMERG_MULT * price4[idx_of[d]] * rec[d]['Q'])) for d in dates_out)
    emerg_kwh = sum(float(rec[d]['Q'].sum()) for d in dates_out)
    print('已写出', path)
    print(f'[Q4-2 波动电价+预报式两阶段随机 λ={Q2_LAM}] 计划费={plan_fee:,.2f} 元, '
          f'紧急费={emerg_fee:,.2f} 元（{emerg_kwh:,.0f} kWh）, 合计={plan_fee + emerg_fee:,.2f} 元')
    return dict(dates=dates, load=load, pv=pv, price4=price4, rec=rec,
                dates_out=dates_out, plan_fee=plan_fee, emerg_fee=emerg_fee)


# ---------------- Q4-3：波动电价 + 因果滚动随机 MPC（复用 main_q3） ----------------
def run_q43():
    dates4, price4 = data.load_attach4()
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    a1 = data.load_attach1()
    FC3_HIST = main_q3.build_fc3_hist(fc3, dates)
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        res = main_q3._rolling(price4[i], load, pv, dates, fc3, i, E_start, a1, FC3_HIST)
        res['E_start'] = E_start
        rec[dates[i]] = res
        E_start = res['E_end']
        if (i + 1) % 30 == 0:
            print(f'  Q4-3 进度 {i+1}/{len(dates)} 日（{dates[i].date()}）E={E_start:8.1f} kWh', flush=True)
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
    path = R.strip_personal_meta(path)
    tot_grid = sum(rec[d]['grid_fee'] for d in dates_out)
    tot_emerg = sum(rec[d]['emerg_fee'] for d in dates_out)
    print('已写出', path)
    print(f'[Q4-3 波动电价+因果滚动随机MPC] 电网费={tot_grid:.2f} 紧急费={tot_emerg:.2f} '
          f'合计={tot_grid + tot_emerg:.2f} 元')
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
    ax.set_xlabel('日期索引(1.1起)', fontsize=12); ax.set_ylabel('平均电价(元/kWh)', fontsize=12)
    ax.set_title('问题4：波动电价(附件4)与求解区间示意', fontsize=13)
    ax.legend(fontsize=11); ax.grid(alpha=0.3)
    ax.tick_params(labelsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q4_price.png'), dpi=150); plt.close(fig)
    print('图已存', os.path.join(C.FIG_DIR, 'q4_price.png'))


if __name__ == '__main__':
    shell()

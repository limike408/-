# -*- coding: utf-8 -*-
"""问题2：两阶段随机规划 + CVaR。

A) 官方结果 result2.xlsx：
   "每天 0:00 制定计划"，把当日实际负载/光伏(附件2)视作已获得 → 确定性完美信息
   LP → 最小购电费、紧急购电=0。论文中说明该口径。
B) 方法层（论文用，不计入结果文件）：
   两阶段随机规划 + CVaR 在 表3 指定日期(3.20/6.21/9.23/12.21)对比确定性，
   用历史(前 K 天)生成负载/光伏情景，再对当日实际结算紧急购电，做 λ(CVaR 权重)
   敏感性，说明风险厌恶以计划费换紧急购电削减。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
import scenarios


def _perfect_info_loop(price, load, pv, dates):
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        rp = lp.solve_day_plan(price, pv[i], load[i], E_start)
        rec[dates[i]] = dict(P=rp['P'], Q=np.zeros(C.T_IN_DAY), c=rp['c'], f=rp['f'],
                             E_start=E_start, E_end=rp['E'][-1])
        E_start = rp['E'][-1]
    return rec


def run(outfile='result2.xlsx'):
    a1 = data.load_attach1()
    price = a1['price']
    dates, load, pv = data.load_attach2()
    rec = _perfect_info_loop(price, load, pv, dates)
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, outfile)
    R.write_result2(path, dates_out, P, Q, c, f, E0, Ee)
    cost = sum(float(np.sum(price * rec[d]['P'])) for d in dates_out)
    print('已写出', path)
    print(f'[Q2-A 完美信息] 计划总购电费 = {cost:.2f} 元，紧急购电 = 0 kWh')
    return dict(price=price, dates=dates, load=load, pv=pv, rec=rec,
                dates_out=dates_out, cost=cost)


def method_analysis(price, dates, load, pv, rec):
    """两阶段随机 + CVaR 对比（论文/图/表3 紧急购电）。"""
    rows = []
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        i = int(np.where(dates == d)[0][0])
        E_start = rec[d]['E_start']
        hist_lo = load[max(0, i - 9):i]; hist_pv = pv[max(0, i - 9):i]
        fc = scenarios.forecast_and_scenarios(hist_lo, hist_pv, S=C.S_NUM, seed=i + 1)
        for lam in [0.0, 0.5, 1.0, 2.0, 5.0]:
            two = lp.solve_two_stage(price, fc['scen_ld'], fc['scen_pv'], E_start, lam=lam, beta=C.BETA)
            settle = lp.solve_day_fixedP(price, pv[i], load[i], E_start, two['P'])
            plan_fee = float(np.sum(price * two['P']))
            emerg_fee = float(np.sum(C.EMERG_MULT * price * settle['Q']))
            rows.append(dict(day=dd, lam=lam, plan_fee=plan_fee, emerg_fee=emerg_fee,
                             total=plan_fee + emerg_fee, emerg_kwh=float(settle['Q'].sum())))
    df = pd.DataFrame(rows)
    print('\n[Q2-B 两阶段随机+CVaR]')
    print(df.to_string(index=False))
    df.to_csv(os.path.join(C.RES_DIR, 'q2_two_stage_comparison.csv'), index=False, encoding='utf-8-sig')

    import matplotlib
    matplotlib.use('Agg')
    C.setup_plot_style()
    import matplotlib.pyplot as plt
    df20 = df[df.day == C.SPEC_DAYS[0]].sort_values('lam')
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(df20.lam, df20.plan_fee, '-o', label='计划购电费')
    ax.plot(df20.lam, df20.emerg_fee, '-s', label='紧急购电费')
    ax.plot(df20.lam, df20.total, '--^', label='合计')
    ax.set_xlabel('CVaR 权重 λ'); ax.set_ylabel('费用(元)')
    ax.set_title(f'问题2 两阶段随机+CVaR：{C.SPEC_DAYS[0]} 风险-费用权衡')
    ax.legend(); ax.grid(alpha=0.4)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q2_cvar_tradeoff.png'), dpi=150); plt.close(fig)


if __name__ == '__main__':
    A = run()
    method_analysis(A['price'], A['dates'], A['load'], A['pv'], A['rec'])
# -*- coding: utf-8 -*-
"""问题四季节费用拆分（v2 口径）：固定/波动电价 × 季节 的日费用。

口径与官方链一致：
  Q2 列 = 预报式两阶段随机规划（K_L=15/K_P=7、成对残差 bootstrap、λ=λ* 同 Q2 官方）；
  Q3 列 = 因果滚动随机 MPC（main_q3._rolling v2，λ=0）。
输出 report/season_cost_split.csv（供 R 绘制 A10）+ 全年汇总打印。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp
import scenarios
import main_q2
import main_q3

SORDER = ['春', '夏', '秋', '冬']


def season(d):
    m = d.month
    return {12: '冬', 1: '冬', 2: '冬', 3: '春', 4: '春', 5: '春',
            6: '夏', 7: '夏', 8: '夏', 9: '秋', 10: '秋', 11: '秋'}[m]


def q2_chain(price_day, dates, load, pv, a1, lam, label):
    """预报式两阶段随机全年链（同 Q2 官方口径），price_day(dates[i]) 返回当日 144 电价。
    返回 {date: 日总费用}。"""
    S = C.S_NUM
    KL, KP = 15, 7          # 与 Q2 官方链一致的 K
    cost = {}
    E = C.E_INIT
    for i, d in enumerate(dates):
        if i == 0:
            scen_ld = np.tile(a1['load'], (S, 1))
            scen_pv = np.tile(a1['pv'], (S, 1))
        else:
            fc = scenarios.residual_scenarios(load[:i], pv[:i], (KL, KP), S=S,
                                              seed=main_q2._seed_for_day(d))
            scen_ld, scen_pv = fc['scen_ld'], fc['scen_pv']
        pr = price_day(i)
        two = lp.solve_two_stage(pr, scen_ld, scen_pv, E, lam=lam, beta=C.BETA)
        settle = lp.solve_day_fixedP(pr, pv[i], load[i], E, two['P'])
        cost[d] = float(np.sum(pr * two['P']) + np.sum(C.EMERG_MULT * pr * settle['Q']))
        E = float(settle['E'][-1])
        if (i + 1) % 90 == 0:
            print(f'  [{label}] {i+1}/{len(dates)} 日（{d.date()}）', flush=True)
    return cost


def main():
    a1 = data.load_attach1()
    fp = a1['price']
    dates, load, pv = data.load_attach2()
    dates4, p4 = data.load_attach4()
    fc3 = data.load_attach3()
    FC3_HIST = main_q3.build_fc3_hist(fc3, dates)
    lam = main_q2.LAM_OFFICIAL

    print(f'[Q2 固定电价 预报式两阶段随机 λ={lam}]')
    cost_fix2 = q2_chain(lambda i: fp, dates, load, pv, a1, lam, 'Q2固定')
    print(f'[Q2 波动电价 λ={lam}]')
    cost_var2 = q2_chain(lambda i: p4[i], dates, load, pv, a1, lam, 'Q2波动')

    cost_fix3, cost_var3 = {}, {}
    E = C.E_INIT
    print('[Q3 固定电价 因果滚动随机MPC]')
    for i, d in enumerate(dates):
        r = main_q3._rolling(fp, load, pv, dates, fc3, i, E, a1, FC3_HIST)
        cost_fix3[d] = r['grid_fee'] + r['emerg_fee']
        E = r['E_end']
        if (i + 1) % 90 == 0:
            print(f'  [Q3固定] {i+1}/{len(dates)} 日（{d.date()}）', flush=True)
    E = C.E_INIT
    print('[Q3 波动电价 因果滚动随机MPC]')
    for i, d in enumerate(dates):
        r = main_q3._rolling(p4[i], load, pv, dates, fc3, i, E, a1, FC3_HIST)
        cost_var3[d] = r['grid_fee'] + r['emerg_fee']
        E = r['E_end']
        if (i + 1) % 90 == 0:
            print(f'  [Q3波动] {i+1}/{len(dates)} 日（{d.date()}）', flush=True)

    rows = []
    for s in SORDER:
        idx = [d for d in dates if season(d) == s]
        a = np.array([cost_fix2[d] for d in idx]); b = np.array([cost_var2[d] for d in idx])
        c = np.array([cost_fix3[d] for d in idx]); e = np.array([cost_var3[d] for d in idx])
        rows.append(dict(seas=s, n=len(idx),
                         q2_fix=a.mean() / 1e4, q2_var=b.mean() / 1e4,
                         q3_fix=c.mean() / 1e4, q3_var=e.mean() / 1e4,
                         up3=(e.mean() - c.mean()) / c.mean() * 100))
    out = pd.DataFrame(rows)
    print(out.round(2).to_string(index=False))
    out.to_csv(os.path.join(C.RES_DIR, 'season_cost_split.csv'), index=False, encoding='utf-8-sig')

    do = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    print('\n[全年总（2.1-12.31，万元）]')
    for name, dd in [('Q2固定', cost_fix2), ('Q2波动', cost_var2),
                     ('Q3固定', cost_fix3), ('Q3波动', cost_var3)]:
        print(f'  {name}: {sum(dd[d] for d in do)/1e4:,.1f}')


if __name__ == '__main__':
    main()

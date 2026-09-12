# -*- coding: utf-8 -*-
"""Q3 全年 only0 基准链 + 结果拆分（诊断/论文对比用）。

only0 = 0:00 两阶段随机计划 P（与 Q3 滚动链同情景同种子），固定 P 结算，无 6/12/18 调整。
另从 result3.xlsx 读回，拆分滚动链电网费的构成：Σp·min(P,A) / 违约退款 0.5p·u / 超额惩罚 1.5p·w。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import openpyxl
import config as C
import data, lp, main_q3, scenarios

a1 = data.load_attach1()
price = a1['price']
dates, load, pv = data.load_attach2()
fc3 = data.load_attach3()
FC3_HIST = main_q3.build_fc3_hist(fc3, dates)

# ---- only0 全年链 ----
rec = {}
E_start = C.E_INIT
S = main_q3.S_Q3
for i, d in enumerate(dates):
    seed = main_q3._seed_for_day(d)
    if i == 0:
        scen_ld = np.tile(a1['load'], (S, 1))
        scen_pv = np.tile(FC3_HIST[0][0], (S, 1))
    else:
        fc = scenarios.residual_scenarios_fc3(load[:i], pv[:i], FC3_HIST[0][:i],
                                              FC3_HIST[0][i], main_q3.KL_Q3, S=S, seed=seed)
        scen_ld, scen_pv = fc['scen_ld'], fc['scen_pv']
    plan = lp.solve_two_stage(price, scen_ld, scen_pv, E_start, lam=0.0, beta=C.BETA)
    st = lp.solve_day_fixedP(price, pv[i], load[i], E_start, plan['P'])
    rec[d] = dict(grid=float(np.sum(price * plan['P'])),
                  emerg=float(np.sum(C.EMERG_MULT * price * st['Q'])))
    E_start = float(st['E'][-1])
    if (i + 1) % 90 == 0:
        print(f'  only0 {i+1}/{len(dates)} 日（{d.date()}）', flush=True)

do = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
g0 = sum(rec[d]['grid'] for d in do)
e0 = sum(rec[d]['emerg'] for d in do)
print(f'\n[Q3 only0 全年(2.1-12.31)] 电网费={g0:,.2f} 紧急费={e0:,.2f} 合计={g0+e0:,.2f}')

# ---- 滚动链拆分（读 result3.xlsx）----
def read_mat(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[sheet]
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None or isinstance(row[0], str):
            continue
        dt = pd.to_datetime(row[0])
        out[dt] = np.array([float(v or 0.0) for v in row[1:1 + C.T_IN_DAY]])
    wb.close()
    return out

P = read_mat(os.path.join(C.RES_DIR, 'result3.xlsx'), '计划购电量')
A = read_mat(os.path.join(C.RES_DIR, 'result3.xlsx'), '调整购电量')
base = refund = over = 0.0
for dt in P:
    u = np.maximum(P[dt] - A[dt], 0.0)
    w = np.maximum(A[dt] - P[dt], 0.0)
    base += float(np.sum(price * np.minimum(P[dt], A[dt])))
    refund += float(np.sum(0.5 * price * u))
    over += float(np.sum(1.5 * price * w))
print(f'[Q3 滚动链电网费拆分] Σp·min(P,A)={base:,.2f} + 违约退款={refund:,.2f} + 超额惩罚={over:,.2f} = {base+refund+over:,.2f}')

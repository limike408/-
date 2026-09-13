# -*- coding: utf-8 -*-
"""验证方案A全年费用（论文口径，独立演进储能）：仅0:00计划，A=P不调整，
结算去后见之明，缺电 5p 紧急购电。用于核对正文"方案B较方案A上浮43.8%"。

22.0 追加：同一循环内计算 方案C（每时刻按实际净需求修改计划，0.5p/1.5p 结算）
与能量守恒恒等式核对（D-G = P + ηf + Q - c - R），输出 ener22 汇总。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import config as C
import data, lp, scenarios
from main_q3 import causal_settle, _adjust, _cold_load, K_LOAD

a1 = data.load_attach1()
price = a1['price']
dates, load, pv = data.load_attach2()
fc3 = data.load_attach3()

tot_grid = 0.0
tot_emerg = 0.0
tot_C = 0.0
E_start = C.E_INIT
day_rows = []
for i in range(len(dates)):
    d = dates[i]
    D_known = scenarios.point_forecast(load[:i], K_LOAD)
    if i == 0:
        D_known = _cold_load()
    G0 = data.pv_forecast_kwh(fc3, d, 0)[0]
    plan = lp.solve_day_plan(price, G0, D_known, E_start)
    P = plan['P']
    settle = causal_settle(price, pv[i], load[i], E_start, P)
    g, e, _ = _adjust(price, P, P, settle['Q'])   # A=P：无违约/超额调整费
    tot_grid += g
    tot_emerg += e
    # —— 方案C：每时刻按实际净需求修改计划（储能不参与，A=n）——
    L, G = load[i], pv[i]
    net = np.maximum(L - G, 0.0)
    uC = np.maximum(P - net, 0.0); wC = np.maximum(net - P, 0.0)
    costC = float(np.sum(price * np.minimum(P, net) + C.DEFAULT_MULT * price * uC
                         + C.EXCESS_MULT * price * wC))
    tot_C += costC
    # —— 能量守恒恒等式核对（方案A回放）：Σ(D-G) = Σ(P+ηf+Q-c-R) ——
    lhs = float(np.sum(L - G))
    rhs = float(np.sum(P + C.ETA * settle['f'] + settle['Q']
                       - settle['c'] - settle['R']))
    cerr = abs(lhs - rhs) / max(abs(lhs), 1.0)
    day_rows.append(dict(date=str(d.date()), grid=round(g, 2), emerg=round(e, 2),
                         Q_kwh=round(float(settle['Q'].sum()), 2),
                         costC=round(costC, 2), cons_err=cerr))
    E_start = settle['E_end']

tot = tot_grid + tot_emerg
print(f'[方案A 全年] 计划费={tot_grid:.2f} 紧急费={tot_emerg:.2f} 合计={tot:.2f} 元')
print(f'[方案B 全年] 22460575.77+75922.06 = 22536497.83 元')
diff = 22536497.83 - tot
print(f'方案B-方案A 增量 = {diff:.2f} 元, 相对方案A上浮 = {diff/tot*100:.3f}%')
print(f'[方案C 全年] 每时刻修改计划 = {tot_C:,.2f} 元')
print(f'方案A − 方案C 差额（C更贵） = {tot_C-tot:,.2f} 元 (相对方案C {(tot_C-tot)/tot_C:.1%}, '
      f'相对方案A {(tot_C/tot-1):.1%})')
df = pd.DataFrame(day_rows)
df.to_csv(os.path.join(C.RES_DIR, 'q3_planA_daily_cost.csv'), index=False,
          encoding='utf-8-sig')
print('紧急购电日数(方案A):', int((df.emerg > 0).sum()), '/', len(df),
      ' 全年紧急购电 kWh:', round(df.Q_kwh.sum(), 1))
print(f'能量守恒核对: 逐日最大相对残差 {df.cons_err.max():.2e}, 均值 {df.cons_err.mean():.2e}')
summ = (f'[能量守恒验证 22.0]\n'
        f'方案A(紧急购电, 全年365天): 计划费 {tot_grid:,.2f} + 紧急费 {tot_emerg:,.2f} = {tot:,.2f} 元\n'
        f'  紧急购电 {df.Q_kwh.sum():,.1f} kWh, 触发日 {int((df.emerg>0).sum())} 天\n'
        f'方案C(每时刻修改计划, 全年365天): {tot_C:,.2f} 元\n'
        f'方案C − 方案A = {tot_C-tot:,.2f} 元 (相对方案C {(tot_C-tot)/tot_C:.1%})\n'
        f'方案B(Q3实际滚动, 2.1-12.31): 22,536,497.83 元\n'
        f'能量守恒恒等式逐日最大残差 {df.cons_err.max():.2e}')
print(summ)
with open(os.path.join(C.RES_DIR, 'ener22_summary.txt'), 'w', encoding='utf-8') as f:
    f.write(summ + '\n')

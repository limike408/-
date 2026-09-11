# -*- coding: utf-8 -*-
"""问题四季节费用拆分：固定/波动电价 × 季节 的日费用（真实计算）。"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp
import main_q3 as M3
import main_q4 as M4

def season(d):
    m = d.month
    return {12:'冬',1:'冬',2:'冬',3:'春',4:'春',5:'春',6:'夏',7:'夏',8:'夏',9:'秋',10:'秋',11:'秋'}[m]
SORDER = ['春','夏','秋','冬']

a1 = data.load_attach1(); fp = a1['price']
dates, load, pv = data.load_attach2()
dates4, p4 = data.load_attach4()
fc3 = data.load_attach3()

# 固定电价 Q2 完美信息
cost_fix2 = {}; E = C.E_INIT
for i, d in enumerate(dates):
    rp = lp.solve_day_plan(fp, pv[i], load[i], E)
    cost_fix2[d] = float(np.sum(fp*rp['P'])); E = rp['E'][-1]
# 波动电价 Q2
cost_var2 = {}; E = C.E_INIT
for i, d in enumerate(dates):
    rp = lp.solve_day_plan(p4[i], pv[i], load[i], E)
    cost_var2[d] = float(np.sum(p4[i]*rp['P'])); E = rp['E'][-1]
# 固定电价 Q3 滚动
cost_fix3 = {}; E = C.E_INIT
for i, d in enumerate(dates):
    r = M3._rolling(fp, load, pv, dates, fc3, i, E)
    cost_fix3[d] = r['grid_fee'] + r['emerg_fee']; E = r['E_end']
# 波动电价 Q3 滚动
cost_var3 = {}; E = C.E_INIT
for i, d in enumerate(dates):
    r = M4._rolling(p4[i], load[i], pv[i], fc3, dates[i], E)
    cost_var3[d] = r['grid_fee'] + r['emerg_fee']; E = r['E_end']

rows = []
for s in SORDER:
    idx = [d for d in dates if season(d) == s]
    a = np.array([cost_fix2[d] for d in idx]); b = np.array([cost_var2[d] for d in idx])
    c = np.array([cost_fix3[d] for d in idx]); e = np.array([cost_var3[d] for d in idx])
    rows.append(dict(seas=s, n=len(idx),
                     q2_fix=a.mean()/1e4, q2_var=b.mean()/1e4,
                     q3_fix=c.mean()/1e4, q3_var=e.mean()/1e4,
                     up3=(e.mean()-c.mean())/c.mean()*100))
out = pd.DataFrame(rows)
print(out.round(2).to_string(index=False))
out.to_csv(os.path.join(C.RES_DIR, 'season_cost_split.csv'), index=False, encoding='utf-8-sig')

# 全年总（2.1-12.31，与论文口径一致）
do = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
for name, dd in [('Q2固定', cost_fix2), ('Q2波动', cost_var2), ('Q3固定', cost_fix3), ('Q3波动', cost_var3)]:
    print(name, round(sum(dd[d] for d in do)/1e4, 1), '万元')
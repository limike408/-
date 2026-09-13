# -*- coding: utf-8 -*-
"""季节差异实证：负荷/光伏/优化结果按季节分组统计，评估'按季节分类'创新点可行性。"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp

def season(d):
    m = d.month
    return {12:'冬',1:'冬',2:'冬',3:'春',4:'春',5:'春',6:'夏',7:'夏',8:'夏',9:'秋',10:'秋',11:'秋'}[m]

a1 = data.load_attach1()
dates, load, pv = data.load_attach2()   # kWh/时段 (365,144)
dates4, p4 = data.load_attach4()

# 1) 季节负荷/光伏总量
day_ld = load.sum(axis=1)   # kWh/日
day_pv = pv.sum(axis=1)
seas = [season(d) for d in dates]
df = pd.DataFrame({'seas': seas, 'ld': day_ld, 'pv': day_pv})
g = df.groupby('seas').agg(ld_mean=('ld','mean'), ld_std=('ld','std'),
                           pv_mean=('pv','mean'), pv_std=('pv','std')).reindex(['春','夏','秋','冬'])
print('=== 季节负荷/光伏(日 kWh) ===')
print(g.round(1).to_string())

# 2) 季节日内峰谷特征（平均日负荷曲线峰值/谷值）
day_peak = load.max(axis=1); day_trough = load.min(axis=1)
df['pk'] = day_peak; df['tr'] = day_trough
g2 = df.groupby('seas')[['pk','tr']].mean().reindex(['春','夏','秋','冬'])
print('\n=== 季节平均日峰/谷负荷(kWh/时段) ===')
print(g2.round(1).to_string())

# 3) 完美信息(Q2口径) 下季节购电费
cost_seas = {}
E = C.E_INIT
for i, d in enumerate(dates):
    rp = lp.solve_day_plan(a1['price'], pv[i], load[i], E)
    cost_seas.setdefault(season(d), []).append(float(np.sum(a1['price']*rp['P'])))
    E = rp['E'][-1]
rows = []
for s in ['春','夏','秋','冬']:
    a = np.array(cost_seas[s])
    rows.append(dict(seas=s, n=len(a), mean=a.mean(), std=a.std(),
                     mn=a.min(), mx=a.max()))
g3 = pd.DataFrame(rows)
print('\n=== 季节日购电费分布(元) ===')
print(g3.round(0).to_string(index=False))

# 4) 波动电价季节均值
p_mean = p4.mean(axis=1)
df['pm'] = p_mean
g4 = df.groupby('seas')['pm'].mean().reindex(['春','夏','秋','冬'])
print('\n=== 季节平均电价(元/kWh) ===')
print(g4.round(4).to_string())

# 5) 光伏季节日峰值时刻（负荷峰谷错位程度）
# 光伏正午最高、负荷晚峰，计算 负荷峰谷比
ratio = day_peak / np.maximum(day_trough, 1e-6)
df['ratio'] = ratio
g5 = df.groupby('seas')['ratio'].mean().reindex(['春','夏','秋','冬'])
print('\n=== 季节日负荷峰谷比 ===')
print(g5.round(2).to_string())

print('\nANOVA(季节间购电费差异显著性):')
from scipy import stats
f, p = stats.f_oneway(cost_seas['春'], cost_seas['夏'], cost_seas['秋'], cost_seas['冬'])
print(f'F={f:.1f}, p={p:.2e}  ->', '季节差异显著' if p < 0.05 else '差异不显著')
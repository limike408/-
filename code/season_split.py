# -*- coding: utf-8 -*-
"""问题四季节费用拆分：固定/波动电价 × 季节 的日费用（18.0：直接聚合官方逐日费用 CSV）。

数据来源（各主脚本运行时生成，口径与官方结果完全一致）：
  q2_daily_cost.csv      Q2 预报式两阶段随机规划（固定电价，λ=λ*）
  q4_2_daily_cost.csv    Q4-2 同口径波动电价
  q3_daily_cost.csv      Q3 因果滚动随机 MPC（固定电价）
  q4_3_daily_cost.csv    Q4-3 同口径波动电价
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C

RES = C.RES_DIR


def _load(path):
    df = pd.read_csv(os.path.join(RES, path))
    return {pd.Timestamp(r['date']): float(r['total']) for _, r in df.iterrows()}


def season(d):
    m = d.month
    return {12: '冬', 1: '冬', 2: '冬', 3: '春', 4: '春', 5: '春',
            6: '夏', 7: '夏', 8: '夏', 9: '秋', 10: '秋', 11: '秋'}[m]


SORDER = ['春', '夏', '秋', '冬']

cost_fix2 = _load('q2_daily_cost.csv')
cost_var2 = _load('q4_2_daily_cost.csv')
cost_fix3 = _load('q3_daily_cost.csv')
cost_var3 = _load('q4_3_daily_cost.csv')
dates = sorted(cost_fix2)

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
out.to_csv(os.path.join(RES, 'season_cost_split.csv'), index=False, encoding='utf-8-sig')

# 全年总（2.1-12.31，与论文口径一致）
do = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
for name, dd in [('Q2固定', cost_fix2), ('Q2波动', cost_var2),
                 ('Q3固定', cost_fix3), ('Q3波动', cost_var3)]:
    print(name, round(sum(dd[d] for d in do) / 1e4, 1), '万元')

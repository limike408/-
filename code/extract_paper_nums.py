# -*- coding: utf-8 -*-
"""抓取论文所需全部数值 → 供 tex 引用。"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp

SPEC_MIN_SLOT = [m // 10 for m in C.SPEC_MINUTES]   # 时段索引: 10:00,12:00,...
BLK = [(0, '0-4'), (4, '4-8'), (8, '8-12'), (12, '12-16'), (16, '16-20'), (20, '20-24')]

def blk_sums(arr):
    return [float(np.sum(arr[h0 * 6:(h0 + 4) * 6])) for h0, _ in BLK]

def q1():
    a1 = data.load_attach1()
    rp = lp.solve_day_plan(a1['price'], a1['pv'], a1['load'], C.E_INIT, force_end=C.E_INIT)
    P = rp['P']; c = rp['c']; f = rp['f']
    return dict(
        slots=[float(P[t]) for t in SPEC_MIN_SLOT],
        total=float(P.sum()), cost=float(np.sum(a1['price'] * P)),
        c_blk=blk_sums(c), f_blk=blk_sums(f), E0=float(rp['E'][0]), E24=float(rp['E'][-1]))

def day_rows(price, load, pv, dates, out_dates, plan_rec):
    out = {}
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        i = int(np.where(dates == d)[0][0])
        pr = price[d] if d in plan_rec else None
        r = plan_rec[d] if d in plan_rec else None
        out[dd] = dict(idx=i)
    return out

def compute():
    a1 = data.load_attach1()
    fp = a1['price']
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()
    dates4, p4 = data.load_attach4()

    # ---- Q1 ----
    r1 = q1()

    # ---- Q2 (固定电价 完美信息) 全年 + 指定4日块数据 ----
    rec2 = {}; E = C.E_INIT
    for i in range(len(dates)):
        rp = lp.solve_day_plan(fp, pv[i], load[i], E)
        rec2[dates[i]] = rp
        E = rp['E'][-1]
    do2 = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    cost2 = float(sum(np.sum(fp * rec2[d]['P']) for d in do2))

    # ---- Q4-2 (波动电价 完美信息) ----
    rec42 = {}; E = C.E_INIT
    for i in range(len(dates)):
        pr = p4[i]
        rp = lp.solve_day_plan(pr, pv[i], load[i], E)
        rec42[dates[i]] = rp
        E = rp['E'][-1]
    cost42 = float(sum(np.sum(p4[i] * rec42[d]['P']) for i, d in enumerate(do2)))

    return dict(r1=r1, cost2=cost2, cost42=cost42,
                dates=[str(d.date()) for d in dates],
                spec=[dict(d=str(x.date()), i=int(np.where(dates == pd.Timestamp(x))[0][0]),
                            E2=rec2[x]['E'][-1], E42=rec42[x]['E'][-1]) for x in map(pd.Timestamp, C.SPEC_DAYS)])

d = compute()
print(json.dumps(d, ensure_ascii=False, indent=1))
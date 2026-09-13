# -*- coding: utf-8 -*-
"""抓取指定日期4天在 Q2/Q3/Q4 下的详细结果，供论文表格。"""
import os, sys, json
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp
import main_q3 as M3

SLOT = [m // 10 for m in C.SPEC_MINUTES]
SLOT_LAB = ['10:00-10:10', '12:00-12:10', '14:00-14:10', '16:00-16:10', '18:00-18:10', '20:00-20:10']
BLK = [(0, '0-4'), (4, '4-8'), (8, '8-12'), (12, '12-16'), (16, '16-20'), (20, '20-24')]

def blk(arr):
    return [round(float(np.sum(arr[h * 6:(h + 4) * 6])), 1) for h, _ in BLK]

def price_day(*a):
    pass

a1 = data.load_attach1(); fp = a1['price']
dates, load, pv = data.load_attach2()
fc3 = data.load_attach3()
dates4, p4 = data.load_attach4()

out = {}
for dd in C.SPEC_DAYS:
    d = pd.Timestamp(dd); i = int(np.where(dates == d)[0][0])
    E0 = C.E_INIT if i == 0 else None  # 需追溯前一日本末
    row = {}
    # ---- 前日本末 (Q2) ----
    E = C.E_INIT
    for j in range(i):
        rp = lp.solve_day_plan(fp, pv[j], load[j], E); E = rp['E'][-1]
    Eprev2 = E
    Eprev3 = C.E_INIT
    for j in range(i):
        r = M3._rolling(fp, load, pv, dates, fc3, j, Eprev3, 7); Eprev3 = r['E_end']
    Eprev42 = C.E_INIT
    for j in range(i):
        rp = lp.solve_day_plan(p4[j], pv[j], load[j], Eprev42); Eprev42 = rp['E'][-1]
    Eprev43 = C.E_INIT
    for j in range(i):
        import main_q4 as M4
        r = M4._rolling(p4[j], load[j], pv[j], fc3, dates[j], Eprev43, 7); Eprev43 = r['E_end']

    # Q2
    r2 = lp.solve_day_plan(fp, pv[i], load[i], Eprev2)
    # Q4-2
    r42 = lp.solve_day_plan(p4[i], pv[i], load[i], Eprev42)
    # Q3
    r3 = M3._rolling(fp, load, pv, dates, fc3, i, Eprev3, 7)
    # Q4-3
    r43 = M4._rolling(p4[i], load[i], pv[i], fc3, dates[i], Eprev43, 7)

    row['Q2'] = dict(e0=round(Eprev2,1), e24=round(r2['E'][-1],1),
                     p_slots=[round(float(r2['P'][t]),1) for t in SLOT],
                     c_blk=blk(r2['c']), f_blk=blk(r2['f']),
                     cost_day=round(float(np.sum(fp*r2['P'])),1))
    row['Q4-2'] = dict(e0=round(Eprev42,1), e24=round(r42['E'][-1],1),
                       p_slots=[round(float(r42['P'][t]),1) for t in SLOT],
                       c_blk=blk(r42['c']), f_blk=blk(r42['f']),
                       cost_day=round(float(np.sum(p4[i]*r42['P'])),1))
    row['Q3'] = dict(e0=round(Eprev3,1), e24=round(r3['E_end'],1),
                     p_slots=[round(float(r3['P'][t]),1) for t in SLOT],
                     a_slots=[round(float(r3['A'][t]),1) for t in SLOT],
                     c_blk=blk(r3['c']), f_blk=blk(r3['f']),
                     q_sum=round(float(r3['Q'].sum()),1), nq=int((r3['Q']>1e-6).sum()),
                     grid=round(r3['grid_fee'],1), emerg=round(r3['emerg_fee'],1))
    row['Q4-3'] = dict(e0=round(Eprev43,1), e24=round(r43['E_end'],1),
                       p_slots=[round(float(r43['P'][t]),1) for t in SLOT],
                       a_slots=[round(float(r43['A'][t]),1) for t in SLOT],
                       c_blk=blk(r43['c']), f_blk=blk(r43['f']),
                       q_sum=round(float(r43['Q'].sum()),1), nq=int((r43['Q']>1e-6).sum()),
                       grid=round(r43['grid_fee'],1), emerg=round(r43['emerg_fee'],1))
    out[dd] = row

print(json.dumps(out, ensure_ascii=False, indent=1))
print('SLOT_LAB', SLOT_LAB)
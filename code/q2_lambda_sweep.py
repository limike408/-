# -*- coding: utf-8 -*-
"""Q2 全年 λ 网格扫描（数据驱动选风险权衡权重 λ*）。

对 λ ∈ {0,0.5,1,1.5,2,3,5} 各跑一遍全年预报式两阶段随机规划链
（复用 main_q2._run_forecast_chain，K_L=15/K_P=7，S=30，seed=2026+日序），
汇总全年计划购电费/紧急购电费/紧急购电量/合计 → report/q2_lambda_sweep.csv。
用于在"紧急购电削减 vs 总费用上浮"权衡曲线上选官方 λ*（论文正文引用）。
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data
from main_q2 import _run_forecast_chain, cross_validate_K

LAM_GRID = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]


def main():
    a1 = data.load_attach1()
    price = a1['price']
    dates, load, pv = data.load_attach2()
    KL, KP, cv = cross_validate_K(dates, load, pv)
    print(f'[K 交叉验证] K_L={KL}, K_P={KP}')
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    rows = []
    for lam in LAM_GRID:
        t0 = time.time()
        rec = _run_forecast_chain(price, dates, load, pv, KL, KP, S=C.S_NUM,
                                  lam=lam, verbose=True)
        plan_fee = sum(float(np.sum(price * rec[d]['P'])) for d in dates_out)
        emerg_fee = sum(float(np.sum(C.EMERG_MULT * price * rec[d]['Q'])) for d in dates_out)
        emerg_kwh = sum(float(rec[d]['Q'].sum()) for d in dates_out)
        total = plan_fee + emerg_fee
        rows.append(dict(lam=lam, plan_fee=round(plan_fee, 2), emerg_fee=round(emerg_fee, 2),
                         emerg_kwh=round(emerg_kwh, 2), total=round(total, 2)))
        print(f'[λ={lam}] 计划费={plan_fee:,.2f} 紧急费={emerg_fee:,.2f}'
              f'({emerg_kwh:,.0f} kWh) 合计={total:,.2f} 用时 {time.time()-t0:.0f}s', flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(C.RES_DIR, 'q2_lambda_sweep.csv'), index=False, encoding='utf-8-sig')
    print('\n[λ 网格扫描完成] 已写 report/q2_lambda_sweep.csv')
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()

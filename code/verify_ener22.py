# -*- coding: utf-8 -*-
"""22.0 能量守恒验证：为什么「紧急购电」比「每时刻修改计划」更划算。

口径（与论文 5.3 节 Q3 结算规则一致）：
  方案A（紧急购电）  ：维持 0:00 计划 P，缺电时按 5 倍电价紧急购电 Q；储能按 LP 真实回放
                      （solve_day_fixedP，与论文方案A、result2 同一结算内核）。
  方案C（每时刻修改）：每个时段按实际净需求 n_t=(D_t-G_t)^+ 修改购电，计划 P 已承诺，
                      偏差按 0.5p 违约 / 1.5p 超额结算（式 eq:q3day 的调整项取 A=n）。
  方案B（Q3 实际）   ：result3.xlsx 的滚动再计划实际结果（0/6/12/18 调整）。
  能量守恒核对       ：Σ(D-G) ≈ ΣP + ηΣf - ηΣc + ΣQ（逐日），验证平衡恒等式成立。

输出：
  report/ener22_daily.csv        逐日三方案费用与守恒校验
  report/ener22_summary.txt      年度汇总数字（供论文引用）
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp

SPEC_DAYS = ['2025-03-20', '2025-06-21', '2025-09-23', '2025-12-21']


def load_sheet(nm, agg=None):
    """读取 result3.xlsx 工作簿；紧急购电量 sheet 是(日期,时间段,电量)事件表，按日求和。"""
    df = pd.read_excel(os.path.join(C.RES_DIR, 'result3.xlsx'), sheet_name=nm)
    if nm == '紧急购电量':
        dt = pd.to_datetime(df.iloc[:, 0]).dt.normalize()
        q = pd.to_numeric(df.iloc[:, 2], errors='coerce').fillna(0.0).to_numpy(float)
        return pd.Series(q, index=dt).groupby(level=0).sum()
    dt = pd.to_datetime(df.iloc[:, 0])
    vals = df.iloc[:, 1:1 + C.T_IN_DAY].apply(pd.to_numeric, errors='coerce').to_numpy(float)
    return dict(zip(dt, vals))


def main():
    dates, load, pv = data.load_attach2()
    a1 = data.load_attach1()
    price = a1['price']
    Pmat = load_sheet('计划购电量')
    Amat = load_sheet('调整购电量')
    Qevt = load_sheet('紧急购电量')          # Series: 日期 -> 日紧急购电总量

    rows = []
    for i, d in enumerate(dates):
        if d not in Pmat:
            continue
        P = Pmat[d]
        L, G = load[i], pv[i]
        net = np.maximum(L - G, 0.0)

        # —— 方案A：LP 真实回放（储能 + 5p 紧急）——
        resA = lp.solve_day_fixedP(price, G, L, 6000.0, P, emult=C.EMERG_MULT)
        QA = resA['Q']
        fA, cA, EA = resA['f'], resA['c'], resA['E']
        costA = float(np.sum(price * P + C.EMERG_MULT * price * QA))

        # —— 方案C：每时刻修改计划（A=n，无储能缓冲）——
        uC = np.maximum(P - net, 0.0); wC = np.maximum(net - P, 0.0)
        costC = float(np.sum(price * np.minimum(P, net) + C.DEFAULT_MULT * price * uC
                             + C.EXCESS_MULT * price * wC))

        # —— 方案B：Q3 实际（result3）——
        costB = None
        if d in Amat:
            A = Amat[d]
            uB = np.maximum(P - A, 0.0); wB = np.maximum(A - P, 0.0)
            gB = float(np.sum(price * np.minimum(P, A) + C.DEFAULT_MULT * price * uB
                              + C.EXCESS_MULT * price * wB))
            eB = float(np.sum(C.EMERG_MULT * price * Qevt.get(d, 0.0)))  # 紧急按 5p
            costB = gB + eB

        # —— 能量守恒恒等式核对：D-G = P + ηf - ηc + Q + R(弃光) ——
        lhs = float(np.sum(L - G))
        rhs = float(np.sum(P + C.ETA * fA - C.ETA * cA + QA + resA['R']))
        err = abs(lhs - rhs) / max(abs(lhs), 1.0)

        rows.append(dict(date=d, costA=costA, QA=float(QA.sum()),
                         costC=costC, costB=costB, cons_err=err))
    R = pd.DataFrame(rows)
    R.to_csv(os.path.join(C.RES_DIR, 'ener22_daily.csv'), index=False, encoding='utf-8-sig')

    totA, totC = R.costA.sum(), R.costC.sum()
    QAtot = R.QA.sum()
    nB = R.costB.notna().sum()
    totB = R.costB.fillna(0.0).sum()
    lines = []
    lines.append(f'日期数(2.1-12.31): {len(R)}')
    lines.append(f'方案A(紧急购电,LP回放): 合计 {totA:,.0f} 元 | 紧急购电 {QAtot:,.0f} kWh ({QAtot/1e4:.1f}万)')
    lines.append(f'方案C(每时刻修改计划) : 合计 {totC:,.0f} 元')
    lines.append(f'方案B(Q3实际滚动再计划): 合计 {totB:,.0f} 元 (覆盖 {nB} 天)')
    lines.append(f'方案C − 方案A = {totC-totA:,.0f} 元 (相对方案C {(totC-totA)/totC:.1%}, 相对方案A {(totC/totA-1):.1%})')
    lines.append(f'能量守恒核对: 逐日最大相对残差 {R.cons_err.max():.2e}, 均值 {R.cons_err.mean():.2e}')
    for d in SPEC_DAYS:
        r = R[R.date == pd.Timestamp(d)].iloc[0]
        lines.append(f'  {d}: 方案A={r.costA:,.1f} 紧急={r.QA:.1f}kWh | 方案C={r.costC:,.1f} | 方案B={r.costB:,.1f} | 守恒残差={r.cons_err:.1e}')
    out = '\n'.join(lines)
    print(out)
    with open(os.path.join(C.RES_DIR, 'ener22_summary.txt'), 'w', encoding='utf-8') as f:
        f.write(out + '\n')
    print('已写出 report/ener22_daily.csv 与 report/ener22_summary.txt')


if __name__ == '__main__':
    main()

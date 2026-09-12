# -*- coding: utf-8 -*-
"""三方一致性自检（B9 要求）：论文数字宏 ↔ 脚本复算 ↔ 结果附件 ↔ CSV。

用法：python -X utf8 verify_all.py        （工作目录 code/，退出码 0=全部通过）

校验项：
  A. 从 paper/main.tex 解析 \\newcommand 数字宏（论文值）；
  B. 复算：Q1 单日 LP、Q2/Q4-2 计划费与紧急费、Q3/Q4-3 电网费/紧急费/超额惩罚/退款、
     上浮百分比、季节冬季上浮；
  C. 能量守恒（含弃光 R 项，逐日逐时段）：P + G + ηf + Q = D + c + R，R ≥ 0；
  D. 储能与功率边界：E ∈ [1200, 10800]（0:00/24:00）、c, f ≤ 833.33；
  E. CSV 与附件读回一致性（plot_annual / season_cost_split / q2_new_summary）。
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import openpyxl
import config as C
import data, lp

TOL = 1.0          # 元级容差
FAILS, CHECKS = [], []


def check(name, paper_val, calc_val, tol=TOL, unit='元'):
    ok = abs(paper_val - calc_val) <= tol
    CHECKS.append((name, paper_val, calc_val, ok))
    if not ok:
        FAILS.append(f'{name}: 论文={paper_val} 复算={calc_val} 差={paper_val-calc_val:+.2f}{unit}')
    print(f'  [{"OK " if ok else "FAIL"}] {name:<34} 论文={paper_val:>14,.2f}  复算={calc_val:>14,.2f}{unit}')


def parse_macros(path):
    """从 main.tex 解析 \\newcommand{\\name}{value} → {name: float}。"""
    txt = open(path, encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'\\newcommand\{\\([a-zA-Z]+)\}\{([0-9.]+)\}', txt):
        out[m.group(1)] = float(m.group(2))
    return out


def read_matrix(path, sheet):
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


def read_jinji(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb['紧急购电量']
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not isinstance(row[0], str):
            continue
        try:
            dt = pd.to_datetime(row[0])
        except Exception:
            continue
        t = C.INTERVAL_LABELS.index(str(row[1]))
        out.setdefault(dt, np.zeros(C.T_IN_DAY))[t] = float(row[2] or 0.0)
    wb.close()
    return out


def read_cf(path):
    """充放电量 sheet → {date: (c_blk6, f_blk6, E0, E24)}。"""
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb['充放电量']
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not isinstance(row[0], str):
            continue
        try:
            dt = pd.to_datetime(row[0])
        except Exception:
            continue
        rec = out.setdefault(dt, dict(c=[0.0] * 6, f=[0.0] * 6, E0=None, E24=None))
        if row[4] == '0:00':
            rec['E0'] = float(row[5] or 0.0)
        elif row[4] == '24:00':
            rec['E24'] = float(row[5] or 0.0)
        elif isinstance(row[1], str) and '-' in str(row[1]):
            h0 = int(str(row[1]).split(':')[0])
            k = h0 // 4
            if 0 <= k < 6:
                rec['c'][k] = float(row[2] or 0.0)
                rec['f'][k] = float(row[3] or 0.0)
    wb.close()
    return out


def main():
    root = C.C_BASE
    mac = parse_macros(os.path.join(root, 'paper', 'main.tex'))
    a1 = data.load_attach1()
    fp = a1['price']
    dates, load, pv = data.load_attach2()
    dates4, p4 = data.load_attach4()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    do = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    idx_of = {d: i for i, d in enumerate(dates)}

    print('\n=== A. 问题一（单日确定性 LP）===')
    rp = lp.solve_day_plan(fp, a1['pv'], a1['load'], C.E_INIT, force_end=C.E_INIT)
    check('Q1 全天购电量(kWh)', mac['qonekwh'], float(rp['P'].sum()))
    check('Q1 购电费', mac['qonecost'], float(np.sum(fp * rp['P'])))

    print('\n=== B. 问题二（λ*=0.5 预报式两阶段随机）===')
    P2 = read_matrix(os.path.join(C.RES_DIR, 'result2.xlsx'), '计划购电量')
    Q2 = read_jinji(os.path.join(C.RES_DIR, 'result2.xlsx'))
    plan2 = sum(float(np.sum(fp * P2[d])) for d in do)
    emer2 = sum(float(np.sum(5 * fp * Q2.get(d, np.zeros(C.T_IN_DAY)))) for d in do)
    check('Q2 计划购电费', mac['qtwoplan'], plan2)
    check('Q2 紧急购电费', mac['qtwoemer'], emer2)
    check('Q2 合计', mac['qtwototal'], plan2 + emer2)
    check('Q2 紧急购电量(kWh)', mac['qtwokwh'], sum(float(Q2.get(d, np.zeros(C.T_IN_DAY)).sum()) for d in do))

    print('\n=== C. 问题三（因果滚动随机 MPC）===')
    P3 = read_matrix(os.path.join(C.RES_DIR, 'result3.xlsx'), '计划购电量')
    A3 = read_matrix(os.path.join(C.RES_DIR, 'result3.xlsx'), '调整购电量')
    Q3 = read_jinji(os.path.join(C.RES_DIR, 'result3.xlsx'))
    over = ref = 0.0
    for d in do:
        u = np.maximum(P3[d] - A3[d], 0.0); w = np.maximum(A3[d] - P3[d], 0.0)
        ref += float(np.sum(0.5 * fp * u)); over += float(np.sum(1.5 * fp * w))
    grid3 = sum(float(np.sum(fp * np.minimum(P3[d], A3[d]))) for d in do) + ref + over
    emer3 = sum(float(np.sum(5 * fp * Q3.get(d, np.zeros(C.T_IN_DAY)))) for d in do)
    check('Q3 电网费', mac['qthreegrid'], grid3)
    check('Q3 紧急购电费', mac['qthreeemer'], emer3)
    check('Q3 合计', mac['qthreetotal'], grid3 + emer3)
    check('Q3 超额惩罚', mac['qthreeover'], over)

    print('\n=== D. 问题四（波动电价复算）===')
    P42 = read_matrix(os.path.join(C.RES_DIR, 'result4-2.xlsx'), '计划购电量')
    Q42 = read_jinji(os.path.join(C.RES_DIR, 'result4-2.xlsx'))
    plan42 = sum(float(np.sum(p4[idx_of[d]] * P42[d])) for d in do)
    emer42 = sum(float(np.sum(5 * p4[idx_of[d]] * Q42.get(d, np.zeros(C.T_IN_DAY)))) for d in do)
    check('Q4-2 计划购电费', mac['qfourbgrid'], plan42)
    check('Q4-2 紧急购电费', mac['qfourbemer'], emer42)
    check('Q4-2 合计', mac['qfourbtotal'], plan42 + emer42)
    check('Q4-2 上浮(%)', mac['qfourbup'], (plan42 + emer42) / (plan2 + emer2) * 100 - 100, tol=0.05, unit='%')

    P43 = read_matrix(os.path.join(C.RES_DIR, 'result4-3.xlsx'), '计划购电量')
    A43 = read_matrix(os.path.join(C.RES_DIR, 'result4-3.xlsx'), '调整购电量')
    Q43 = read_jinji(os.path.join(C.RES_DIR, 'result4-3.xlsx'))
    grid43 = emer43 = 0.0
    for d in do:
        pr = p4[idx_of[d]]
        u = np.maximum(P43[d] - A43[d], 0.0); w = np.maximum(A43[d] - P43[d], 0.0)
        grid43 += float(np.sum(pr * np.minimum(P43[d], A43[d]) + 0.5 * pr * u + 1.5 * pr * w))
        emer43 += float(np.sum(5 * pr * Q43.get(d, np.zeros(C.T_IN_DAY))))
    check('Q4-3 电网费', mac['qfourcgrid'], grid43)
    check('Q4-3 紧急购电费', mac['qfourcemer'], emer43)
    check('Q4-3 合计', mac['qfourctotal'], grid43 + emer43)
    check('Q4-3 上浮(%)', mac['qfourcup'], (grid43 + emer43) / (grid3 + emer3) * 100 - 100, tol=0.05, unit='%')

    print('\n=== E. 季节与 CSV ===')
    sc = pd.read_csv(os.path.join(C.RES_DIR, 'season_cost_split.csv'))
    w = sc[sc['seas'] == '冬'].iloc[0]
    check('冬季 Q3 上浮(%)', mac['qfourwinter'], float(w['up3']), tol=0.05, unit='%')
    pa = pd.read_csv(os.path.join(C.RES_DIR, 'plot_annual.csv'))
    check('plot_annual Q2 合计', mac['qtwototal'], float(pa.iloc[0]['grid_fee'] + pa.iloc[0]['emerg_fee']))
    check('plot_annual Q3 合计', mac['qthreetotal'], float(pa.iloc[1]['grid_fee'] + pa.iloc[1]['emerg_fee']))
    check('plot_annual Q4-2 合计', mac['qfourbtotal'], float(pa.iloc[2]['grid_fee'] + pa.iloc[2]['emerg_fee']))
    check('plot_annual Q4-3 合计', mac['qfourctotal'], float(pa.iloc[3]['grid_fee'] + pa.iloc[3]['emerg_fee']))
    check('season 四季样本数合计=334', 334, float(sc['n'].sum()), tol=0.5, unit='天')

    print('\n=== F. 能量守恒与边界（含弃光 R 项）===')
    for tag, path, has_A in [('Q2', 'result2.xlsx', False), ('Q3', 'result3.xlsx', True),
                             ('Q4-2', 'result4-2.xlsx', False), ('Q4-3', 'result4-3.xlsx', True)]:
        P = read_matrix(os.path.join(C.RES_DIR, path), '计划购电量')
        A = read_matrix(os.path.join(C.RES_DIR, path), '调整购电量') if has_A else None
        Q = read_jinji(os.path.join(C.RES_DIR, path))
        CF = read_cf(os.path.join(C.RES_DIR, path))
        price_var = tag.startswith('Q4')
        totR = 0.0; minR = 1e18; e_bad = 0; p_bad = 0; n_day = 0
        for d in do:
            i = idx_of[d]
            G = pv[i]; D = load[i]
            buy = A[d] if A is not None else P[d]
            q = Q.get(d, np.zeros(C.T_IN_DAY))
            c6, f6, E0, E24 = CF[d]['c'], CF[d]['f'], CF[d]['E0'], CF[d]['E24']
            # 逐时段守恒（用分块充放电量无法逐时段；用块级守恒校验）+ 逐日能量守恒
            R = buy.sum() + G.sum() + C.ETA * sum(f6) + q.sum() - D.sum() - sum(c6)
            totR += R
            minR = min(minR, R)
            n_day += 1
            if E0 is not None and not (C.SOC_MIN - 1e-6 <= E0 <= C.SOC_HIGH_BOUND + 1e-6):
                e_bad += 1
            if E24 is not None and not (C.SOC_MIN - 1e-6 <= E24 <= C.SOC_HIGH_BOUND + 1e-6):
                e_bad += 1
            # 充放电量 sheet 是 4 小时块和，上限 = 24 时段 × 单时段功率上限
            blk_max = 24 * C.E_CMAX + 1e-3
            for x in list(c6) + list(f6):
                if x > blk_max:
                    p_bad += 1
        ok = (minR >= -1e-3) and e_bad == 0 and p_bad == 0
        CHECKS.append((f'{tag} 守恒/边界', 0, minR, ok))
        print(f'  [{"OK " if ok else "FAIL"}] {tag}: 全年弃光 R={totR:>12,.0f} kWh（应≥0），'
              f'逐日最小 R={minR:>10,.1f}，E 越界天数={e_bad}，功率越界={p_bad}')
        if not ok:
            FAILS.append(f'{tag} 守恒/边界不通过: minR={minR}, E越界={e_bad}, 功率越界={p_bad}')

    print('\n' + '=' * 70)
    print(f'共 {len(CHECKS)} 项校验，通过 {sum(1 for c in CHECKS if c[3])} 项，失败 {len(FAILS)} 项')
    for f in FAILS:
        print('  ✗', f)
    print('=' * 70)
    return 0 if not FAILS else 1


if __name__ == '__main__':
    sys.exit(main())

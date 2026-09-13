# -*- coding: utf-8 -*-
"""问题4：波动电价(附件4)重算 问题2/问题3 → result4-2.xlsx / result4-3.xlsx + 对比图。

附件2(负载/光伏实际)、附件4(波动电价) 均为 全年366×144 矩阵，日期必须对齐。
口径沿用（18.0 与 Q2/Q3 官方口径对齐）：
  Q4-2 = 问题2 预报式两阶段随机规划（K_L/K_P 沿用 Q2 交叉验证、λ=λ* 沿用 Q2 官方扫描、
         seed=2026+日序），仅把固定电价(附件1)换成当日波动电价 → 紧急购电不再恒 0；
  Q4-3 = 问题3 因果滚动随机 MPC（负荷预报化/实际SOC/去后见之明结算/光伏情景鲁棒），
         按当日波动电价结算（复用 main_q3._rolling_day）。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
import main_q2 as MQ2
from main_q3 import _rolling_day
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
TAU = [0, 6, 12, 18]


# ---------------- Q4-2：波动电价 + 问题2 预报式两阶段随机规划 ----------------
def run_q42():
    dates4, price4 = data.load_attach4()          # price4[365,144]
    dates, load, pv = data.load_attach2()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    # K 沿用 Q2 交叉验证（只依赖负荷/光伏，与电价口径无关）
    KL, KP, _ = MQ2.cross_validate_K(dates, load, pv)
    # λ* 沿用 Q2 官方扫描（风险权衡权重，与电价口径无关）
    summ = pd.read_csv(os.path.join(C.RES_DIR, 'q2_new_summary.csv'))
    lam_star = float(summ.loc[summ['指标'] == '官方风险权重_λ*', '数值'].iloc[0])
    print(f'[Q4-2] K_L={KL}, K_P={KP}, λ*={lam_star}（沿用 Q2 官方口径）')
    rec = MQ2._run_forecast_chain(price4, dates, load, pv, KL, KP, S=C.S_NUM,
                                  lam=lam_star, verbose=False)
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, 'result4-2.xlsx')
    R.write_result2(path, dates_out, P, Q, c, f, E0, Ee, tpl_name='result4-2.xlsx')
    idx_of = {d: i for i, d in enumerate(dates)}
    cost = sum(float(np.sum(price4[idx_of[d]] * rec[d]['P'])) for d in dates_out)
    emerg = sum(float(np.sum(C.EMERG_MULT * price4[idx_of[d]] * rec[d]['Q'])) for d in dates_out)
    print('已写出', path)
    print(f'[Q4-2 波动电价+预报式] 计划费={cost:,.2f} 紧急费={emerg:,.2f} '
          f'合计={cost + emerg:,.2f} 元，紧急购电 ≠ 0 kWh')
    pd.DataFrame({'指标': ['全年计划购电费_元', '全年紧急购电费_元', '合计_元', '紧急购电量_kWh'],
                  '数值': [round(cost, 2), round(emerg, 2), round(cost + emerg, 2),
                          round(sum(float(rec[d]['Q'].sum()) for d in dates_out), 2)]}
                 ).to_csv(os.path.join(C.RES_DIR, 'q4_2_summary.csv'),
                          index=False, encoding='utf-8-sig')
    # 逐日费用 CSV（供 season_split / 论文季节表，覆盖全年含预热月）
    drow = []
    for d in dates:
        dd = rec[d]
        pf = float(np.sum(price4[idx_of[d]] * dd['P']))
        ef = float(np.sum(C.EMERG_MULT * price4[idx_of[d]] * dd['Q']))
        drow.append(dict(date=str(d.date()), plan_fee=round(pf, 2),
                         emerg_fee=round(ef, 2), total=round(pf + ef, 2)))
    pd.DataFrame(drow).to_csv(os.path.join(C.RES_DIR, 'q4_2_daily_cost.csv'),
                              index=False, encoding='utf-8-sig')
    return dict(dates=dates, load=load, pv=pv, price4=price4,
                rec=rec, dates_out=dates_out, cost=cost, emerg=emerg)


# ---------------- Q4-3：波动电价 + 因果滚动随机 MPC ----------------
def _adjust(price, P, A, Q):
    u = np.maximum(P - A, 0.0)
    w = np.maximum(A - P, 0.0)
    grid_fee = float(np.sum(price * np.minimum(P, A) + C.DEFAULT_MULT * price * u + C.EXCESS_MULT * price * w))
    emerg_fee = float(np.sum(C.EMERG_MULT * price * Q))
    return grid_fee, emerg_fee


def run_q43():
    dates4, price4 = data.load_attach4()
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()
    data.assert_aligned(dates4, dates, '附件4', '附件2')
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        pr = price4[i]
        # 复用 main_q3 的 18.0 因果滚动模型（负荷预报化/实际SOC/去后见之明/光伏情景鲁棒）
        res = _rolling_day(pr, load[i], pv[i], load[:i], pv[:i], fc3, dates[i], E_start)
        res['E_start'] = E_start
        rec[dates[i]] = res
        E_start = res['E_end']
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    A = {d: rec[d]['A'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, 'result4-3.xlsx')
    R.write_result3(path, dates_out, P, A, Q, c, f, E0, Ee, tpl_name='result4-3.xlsx')
    tot_grid = sum(rec[d]['grid_fee'] for d in dates_out)
    tot_emerg = sum(rec[d]['emerg_fee'] for d in dates_out)
    print('已写出', path)
    print(f'[Q4-3 波动电价+滚动MPC] 电网费={tot_grid:.2f} 紧急费={tot_emerg:.2f} 合计={tot_grid + tot_emerg:.2f} 元')
    # 逐日费用 CSV（供 season_split / 论文季节表，覆盖全年含预热月）
    drow = [dict(date=str(d.date()), grid_fee=round(rec[d]['grid_fee'], 2),
                 emerg_fee=round(rec[d]['emerg_fee'], 2),
                 total=round(rec[d]['grid_fee'] + rec[d]['emerg_fee'], 2)) for d in dates]
    pd.DataFrame(drow).to_csv(os.path.join(C.RES_DIR, 'q4_3_daily_cost.csv'),
                              index=False, encoding='utf-8-sig')
    return dict(dates=dates, dates_out=dates_out, rec=rec,
                tot_grid=tot_grid, tot_emerg=tot_emerg)


def plot_price_figure():
    """图18：附件4 波动电价（日均）曲线 vs 附件1 固定电价，叠加季节分带与季节均值标注。
    仅依赖原始数据（附件1/附件4），不重新求解，可独立调用。"""
    dates4, price4 = data.load_attach4()
    a1 = data.load_attach1()
    mean_p = price4.mean(axis=1)
    x = np.arange(len(mean_p))

    def _seas(d):
        m = d.month
        return {12: '冬', 1: '冬', 2: '冬', 3: '春', 4: '春', 5: '春',
                6: '夏', 7: '夏', 8: '夏', 9: '秋', 10: '秋', 11: '秋'}[m]
    seas = np.array([_seas(d) for d in dates4])
    SORDER = ['春', '夏', '秋', '冬']
    SCOL = {'春': '#2ca02c', '夏': '#ff7f0e', '秋': '#9467bd', '冬': '#1f77b4'}
    bounds = [i - 0.5 for i in range(1, len(seas)) if seas[i] != seas[i - 1]]

    def _segments(sel):
        """把选中日期的下标按连续性切成 (i0, i1) 段（冬季跨年需分两段）。"""
        idx = np.where(sel)[0]
        if len(idx) == 0:
            return []
        out, start = [], idx[0]
        for a, b in zip(idx[:-1], idx[1:]):
            if b != a + 1:
                out.append((start, a))
                start = b
        out.append((start, idx[-1]))
        return out

    fig, ax = plt.subplots(figsize=(10.5, 4.9))
    # 季节底色带（与表1"波动日电价"列对应；冬季跨年分两段）
    for s in SORDER:
        for i0, i1 in _segments(seas == s):
            ax.axvspan(i0 - 0.5, i1 + 0.5, color=SCOL[s], alpha=0.10)
    ax.plot(x, mean_p, lw=1.3, color='k', label='附件4 波动电价(日均)')
    p_fix = float(a1['price'].mean())
    ax.axhline(p_fix, color='r', ls='--', lw=1.3,
               label=f'附件1 固定电价（日均 {p_fix:.4f} 元/kWh）')
    # 季节均值虚线 + 数值标注（= 表1 波动日电价）；冬季跨年分两段绘制
    for s in SORDER:
        mv = mean_p[seas == s].mean()
        for i0, i1 in _segments(seas == s):
            ax.hlines(mv, i0 - 0.5, i1 + 0.5, color=SCOL[s], ls=':', lw=1.8)
            ax.text((i0 + i1) / 2, mv + 0.012, f'{s}季 {mv:.3f}', ha='center',
                    fontsize=11, color=SCOL[s],
                    bbox=dict(fc='white', ec='none', alpha=0.75, pad=0.2))
    for b in bounds:
        ax.axvline(b, color='gray', ls='--', lw=0.8, alpha=0.6)
    ax.set_xlabel('日期（2025年1月1日起，按季分带）', fontsize=13)
    ax.set_ylabel('平均电价(元/kWh)', fontsize=13)
    ax.set_title('问题4：附件4波动电价（日均）与附件1固定电价对比', fontsize=14)
    ax.legend(fontsize=11, loc='upper right', ncol=2); ax.grid(alpha=0.3)
    ax.tick_params(labelsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q4_price.png'), dpi=150); plt.close(fig)
    print('图已存', os.path.join(C.FIG_DIR, 'q4_price.png'))


def shell():
    q42 = run_q42()
    q43 = run_q43()
    plot_price_figure()


if __name__ == '__main__':
    shell()
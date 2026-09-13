# -*- coding: utf-8 -*-
"""22.0 紧急购电范围模型（问题二）：储能「扛得住 / 扛不住」的判定与图像。

两层判定：
  1) 时段级（机制）——「储能补不上的突发」：
     参考值 R_L(d,t)=过去21天同星期几逐时段中位数（负荷）、R_P(d,t)=过去15天逐时段中位数（光伏），
     同时段偏差 a_L=|L-R_L|、a_P=|P-R_P|；
     突发时段 ⇔ a_L ≥ max(1000, 12%·R_L) 或 a_P ≥ max(700, 35%·R_P)（绝对值与比例「两者取大」互补，
     保证白天大负荷/大光伏不漏报、夜里低负荷/光伏为0不误报）。
  2) 日级（统计）——「突发日」：日净需求低估 ε_d ≥ 20%（与 2.7 节、Q2 口径一致）。

输出：
  report/emergency_range_daily.csv   逐日偏差/命中/突发标记
  report/figures_adv/emergency_range_devi.png  负荷/光伏 同时段偏差散点 + 阈值边界线（范围模型图像）
  report/figures_adv/emergency_range_pie.png   全年突发日占比扇形图（≥20%）
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

THETA = 0.20        # 日级突发阈值（低估净需求 ≥20%）
K_LOAD = 15
W_L = 21            # 负荷参考窗（同星期几）
W_P = 15            # 光伏参考窗
ABS_L, RAT_L = 1000.0, 0.12
ABS_P, RAT_P = 700.0, 0.35


def ref_same_dow(M, w=W_L):
    """过去 w 天且同星期几 的逐时段中位数（因果，负荷参考）。"""
    n = len(M)
    out = np.zeros_like(M)
    for i in range(n):
        lo = max(0, i - w)
        sel = dow[lo:i] == dow[i]
        sub = M[lo:i][sel]
        out[i] = np.median(sub, axis=0) if len(sub) else np.median(M[:max(i, 1)], axis=0)
    return out


def ref_past_med(M, w=W_P):
    """过去 w 天逐时段中位数（因果，光伏参考）。"""
    n = len(M)
    out = np.zeros_like(M)
    for i in range(n):
        lo = max(0, i - w)
        out[i] = np.median(M[lo:i], axis=0) if i > lo else np.median(M[:max(i, 1)], axis=0)
    return out


def main():
    global dow
    dates, load, pv = data.load_attach2()
    L = load / C.DT          # kW（同时段偏差在功率维度判定）
    P = pv / C.DT
    n, T = L.shape
    dow = pd.DatetimeIndex(dates).dayofweek.to_numpy()

    RL = ref_same_dow(L)
    RP = ref_past_med(P)
    aL = np.abs(L - RL)
    aP = np.abs(P - RP)
    relL = aL / np.maximum(RL, 1e-6)
    relP = aP / np.maximum(RP, 1e-6)

    # —— 时段级阈值（两者取大）——
    LTH = np.maximum(ABS_L, RAT_L * RL)
    PTH = np.maximum(ABS_P, RAT_P * RP)
    L_hit = (aL >= LTH) & (RL > 1e-6)
    P_hit = (aP >= PTH) & (RP > 100)
    both = L_hit | P_hit
    nL = int((RL > 1e-6).sum()); nP = int((RP > 100).sum())

    # —— 日级：净需求偏差（与 2.7 一致）——
    day_ld = load.sum(axis=1); day_pv = pv.sum(axis=1)
    a1 = data.load_attach1()
    ld_fc = np.array([
        (a1['load'].sum() if i == 0 else
         np.mean(load[max(0, i - K_LOAD):i], axis=0).sum()) for i in range(n)])
    fc3 = data.load_attach3()
    pv_fc0 = np.array([data.pv_forecast_kwh(fc3, d, 0)[0].sum() for d in dates])
    fc_net = ld_fc - pv_fc0
    day_net = day_ld - day_pv
    eps = (day_net - fc_net) / np.where(fc_net != 0, np.abs(fc_net), 1.0)

    daymat = both.reshape(n, T)
    day_hit = daymat.sum(axis=1) > 0
    frac = daymat.mean(axis=1)
    emer_day = eps >= THETA

    # 表格输出
    frame = pd.DataFrame({
        'date': dates, 'relL_max': relL.max(axis=1), 'relP_max': relP.max(axis=1),
        'L_hits': daymat.sum(axis=1) & 0, 'slot_frac': frac,
        'eps': eps, 'is_emergency_day': emer_day})
    frame['L_hits'] = (L_hit.reshape(n, T)).sum(axis=1)
    frame['P_hits'] = (P_hit.reshape(n, T)).sum(axis=1)
    frame.to_csv(os.path.join(C.RES_DIR, 'emergency_range_daily.csv'),
                 index=False, encoding='utf-8-sig')

    # 关键数字
    print(f'[时段级范围模型] 负荷阈值 max({ABS_L:.0f}, {RAT_L:.0%}·R_L) 命中 {L_hit.sum()} 时段 '
          f'({L_hit.sum()/nL:.2%} of {nL})')
    print(f'[时段级范围模型] 光伏阈值 max({ABS_P:.0f}, {RAT_P:.0%}·R_P) 命中 {P_hit.sum()} 时段 '
          f'({P_hit.sum()/nP:.2%} of {nP})')
    print(f'合计突发时段 {both.sum()} ({(both.sum()/(n*T)):.2%} of 全部 {n*T})')
    print(f'含突发时段的天数: {day_hit.sum()}/{n} ({day_hit.mean():.1%})')
    print(f'负荷相对偏差: ≤8% 占 {(relL[RL>1e-6]<=0.08).mean():.1%} | ≤12% 占 {(relL[RL>1e-6]<=0.12).mean():.1%} '
          f'| p95={np.percentile(relL[RL>1e-6],95):.1%}')
    print(f'光伏相对偏差(白天): ≤35% 占 {(relP[RP>100]<=0.35).mean():.1%} '
          f'| p95={np.percentile(relP[RP>100],95):.1%}')
    print(f'\n[日级突发日] ε_d≥{THETA:.0%}: {int(emer_day.sum())}/{n} ({emer_day.mean():.1%})')
    print(f'突发日中含突发时段的天数: {int((emer_day & day_hit).sum())}')
    print(f'突发日内 平均突发时段占比: {frac[emer_day].mean():.1%} (中位 {np.median(frac[emer_day]):.1%})')

    # —— 图1：同时段偏差散点 + 阈值边界线（范围模型的图像）——
    rng = np.random.default_rng(2026)
    idxL = rng.choice(n * T, size=min(40000, n * T), replace=False)
    idxP = np.flatnonzero(RP > 100)
    idxP = rng.choice(idxP, size=min(40000, len(idxP)), replace=False)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    # 负荷
    ax = axes[0]
    xL = RL.ravel()[idxL]; yL = aL.ravel()[idxL]
    ax.hexbin(xL, yL, gridsize=42, bins='log', cmap='Blues', mincnt=1, alpha=0.85)
    xs = np.linspace(RL.min(), RL.max(), 300)
    ax.plot(xs, np.maximum(ABS_L, RAT_L * xs), color='#c0392b', lw=2.2,
            label=f'阈值 |ΔL| = max({ABS_L:.0f}, {RAT_L:.0%}·R_L)')
    hL = np.flatnonzero(L_hit)
    ax.scatter(RL.ravel()[hL], aL.ravel()[hL], s=16, color='#c0392b', zorder=3, label='突发时段')
    ax.set_xlabel('参考负荷 $R_L$ (kW)', fontsize=12)
    ax.set_ylabel('同时段偏差 $|\\Delta L|$ (kW)', fontsize=12)
    ax.set_title(f'负荷同时段偏差与紧急购电范围（命中 {L_hit.sum()} 时段）', fontsize=13)
    ax.legend(fontsize=10, loc='upper left')
    ax.set_xlim(0, RL.max() * 1.05); ax.set_ylim(0, min(aL.max(), 4000) * 1.05)
    ax.tick_params(labelsize=11)
    # 光伏
    ax = axes[1]
    xP = RP.ravel()[idxP]; yP = aP.ravel()[idxP]
    ax.hexbin(xP, yP, gridsize=42, bins='log', cmap='Oranges', mincnt=1, alpha=0.85)
    ax.plot(xs, np.maximum(ABS_P, RAT_P * xs), color='#c0392b', lw=2.2,
            label=f'阈值 |ΔP| = max({ABS_P:.0f}, {RAT_P:.0%}·R_P)')
    hP = np.flatnonzero(P_hit)
    ax.scatter(RP.ravel()[hP], aP.ravel()[hP], s=30, color='#c0392b', zorder=3, label='突发时段')
    ax.set_xlabel('参考光伏 $R_P$ (kW)', fontsize=12)
    ax.set_ylabel('同时段偏差 $|\\Delta P|$ (kW)', fontsize=12)
    ax.set_title(f'光伏同时段偏差与紧急购电范围（命中 {P_hit.sum()} 时段）', fontsize=13)
    ax.legend(fontsize=10, loc='upper left')
    ax.set_xlim(0, RP.max() * 1.05); ax.set_ylim(0, min(aP.max(), 4000) * 1.05)
    ax.tick_params(labelsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(C.RES_DIR, 'figures_adv', 'emergency_range_devi.png'), dpi=150)
    plt.close(fig)

    # —— 图2：全年突发日扇形图（≥20%）——
    fig, ax = plt.subplots(figsize=(6.6, 5.2))
    n_em, n_ok = int(emer_day.sum()), int((~emer_day).sum())
    wedges, _, autot = ax.pie([n_em, n_ok],
                              labels=['突发日\n(低估≥20%)', '正常日'],
                              colors=['#e74c3c', '#bdc3c7'],
                              startangle=90, counterclock=False,
                              autopct=lambda p: f'{p:.1f}%\n({int(round(p/100*n))}天)',
                              pctdistance=0.68, textprops=dict(fontsize=12))
    for w in wedges:
        w.set_edgecolor('white'); w.set_linewidth(1.5)
    ax.set_title(f'全年突发日占比（日净需求低估 ≥{THETA:.0%}，{n_em}/{n} 天 = {n_em/n:.1%}）', fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(C.RES_DIR, 'figures_adv', 'emergency_range_pie.png'), dpi=150)
    plt.close(fig)
    print('\n图表已生成：figures_adv/emergency_range_devi.png, emergency_range_pie.png')


if __name__ == '__main__':
    main()

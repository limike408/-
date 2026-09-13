# -*- coding: utf-8 -*-
"""Q2 预测窗口 K 敏感性图（论文 fig:Ksens）。

对 K=1..40 做全年(2.1-12.31)逐日交叉验证，画负荷/光伏 平均归一化 RMSE 曲线；
标注所选 K_L=15、K_P=7，并用浅色带标出论文所述的稳健区间（负荷 K∈[8,16] 浅谷、
光伏 K∈[5,7] 平坦平台）。输出 → paper/figures_adv/q2_K_sensitivity.png
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import data

OUT = os.path.join(C.C_BASE, 'paper', 'figures_adv')
os.makedirs(OUT, exist_ok=True)

dates, load, pv = data.load_attach2()
start = int(np.searchsorted(dates, pd.Timestamp('2025-02-01')))


def cv_nrmse(K, kind):
    """K 天逐槽均值点预报 → 144 时段 RMSE/当日均值，全年平均（日均≈0 的天跳过）。"""
    vals = []
    for i in range(start, len(dates)):
        lo = max(0, i - K)
        if kind == 'load':
            fc = load[lo:i].mean(axis=0) if i > lo else load[i] * 0.0
            act, m = load[i], float(load[i].mean())
        else:
            fc = pv[lo:i].mean(axis=0) if i > lo else pv[i] * 0.0
            act, m = pv[i], float(pv[i].mean())
        if m > 1e-6:
            vals.append(float(np.sqrt(np.mean((fc - act) ** 2))) / m)
    return float(np.mean(vals))


Ks = list(range(1, 41))
nL = [cv_nrmse(K, 'load') for K in Ks]
nP = [cv_nrmse(K, 'pv') for K in Ks]
KL, KP = 15, 7   # 论文选定（负荷谷底/光伏整数周平坦平台）

fig, axes = plt.subplots(2, 1, figsize=(9.2, 7.0), sharex=True)
# 稳健区间浅色带（与论文 §5.2 文字一致）
axes[0].axvspan(8, 16, color='#0072B2', alpha=0.08)
axes[1].axvspan(5, 7, color='#D55E00', alpha=0.08)
for ax, nrm, Kstar, ttl, cc, wintxt in [
        (axes[0], nL, KL, '负荷点预报：平均归一化 RMSE vs 窗口 K', '#0072B2',
         '浅谷区间 [8,16]'),
        (axes[1], nP, KP, '光伏点预报：平均归一化 RMSE vs 窗口 K', '#D55E00',
         '平坦平台 [5,7]')]:
    ax.plot(Ks, nrm, '-o', color=cc, lw=1.8, ms=4)
    ax.axvline(Kstar, color='k', ls='--', lw=1.1)
    ax.annotate(f'$K^*$={Kstar}\nnRMSE={nrm[Kstar-1]:.4f}',
                xy=(Kstar, nrm[Kstar-1]), xytext=(Kstar + 2.5, nrm[Kstar-1]),
                fontsize=13, arrowprops=dict(arrowstyle='->', lw=0.9, color='k'))
    ax.text(Ks[-1], np.max(nrm) * 0.98, wintxt, ha='right', va='top',
            fontsize=12, color='#555555')
    ax.set_ylabel('平均归一化 RMSE', fontsize=14)
    ax.set_title(ttl, fontsize=14)
    ax.tick_params(labelsize=12)
    ax.grid(alpha=0.3)
axes[1].set_xlabel('预测窗口 K（天）', fontsize=14)
fig.tight_layout()
fig.savefig(os.path.join(OUT, 'q2_K_sensitivity.png'), dpi=200)
plt.close(fig)
print('已生成 q2_K_sensitivity.png')
print('负荷: K=15 nRMSE=%.4f; 光伏: K=7 nRMSE=%.4f' % (nL[14], nP[6]))

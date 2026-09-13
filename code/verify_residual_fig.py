# -*- coding: utf-8 -*-
"""生成能量守恒残差验证图（论文 6.1 节）：对附件 2 全年逐日、逐时段检验
功率平衡 P+G+ηf+Q = D+c+R 与储能递推 E_t=E_{t-1}+ηc_t-f_t 的残差。

口径与论文 6.1 节一致：问题一完美信息 LP（solve_day_plan，日循环 E_T=E_0）。
输出：figures_adv/verify_residual.png
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import config as C
import data, lp

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

dates, load, pv = data.load_attach2()
a1 = data.load_attach1()
price = a1['price']

bal_max, bal_mean, soc_max = [], [], []
for i in range(len(dates)):
    res = lp.solve_day_plan(price, pv[i], load[i], C.E_INIT, force_end=C.E_INIT)
    P, c, f, Q, R, E = res['P'], res['c'], res['f'], res['Q'], res['R'], res['E']
    lhs = P + pv[i] + C.ETA * f + Q
    rhs = load[i] + c + R
    bal = np.abs(lhs - rhs)
    bal_max.append(bal.max())
    bal_mean.append(bal.mean())
    # 储能递推残差（含日循环闭合 E_T-E_0）
    soc = np.zeros(C.T_IN_DAY)
    soc[0] = C.E_INIT + C.ETA * c[0] - f[0] - E[0]
    for t in range(1, C.T_IN_DAY):
        soc[t] = E[t - 1] + C.ETA * c[t] - f[t] - E[t]
    soc_max.append(np.abs(soc).max())
    soc_max[-1] = max(soc_max[-1], abs(E[-1] - C.E_INIT))

bal_max = np.array(bal_max); bal_mean = np.array(bal_mean); soc_max = np.array(soc_max)
print(f'功率平衡残差: 逐日最大 {bal_max.max():.3e}, 平均 {bal_mean.mean():.3e}')
print(f'储能递推残差: 逐日最大 {soc_max.max():.3e}, 含日循环闭合')

x = np.arange(len(dates))
fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
ax[0].semilogy(x, bal_max, lw=0.8, color='#1f77b4', label='逐日最大功率平衡残差')
ax[0].axhline(1e-6, ls='--', lw=1.0, color='#d62728', label='$10^{-6}$ kWh 基准线')
ax[0].set_xlabel('日期序号（2025-01-01 起）', fontsize=11)
ax[0].set_ylabel('残差 (kWh)', fontsize=11)
ax[0].set_title('(a) 功率平衡残差（逐日最大）', fontsize=12)
ax[0].legend(fontsize=10)
ax[0].tick_params(labelsize=10)
ax[0].grid(True, which='both', alpha=0.3)

ax[1].semilogy(x, soc_max, lw=0.8, color='#2ca02c', label='逐日储能递推残差')
ax[1].axhline(1e-6, ls='--', lw=1.0, color='#d62728', label='$10^{-6}$ kWh 基准线')
ax[1].set_xlabel('日期序号（2025-01-01 起）', fontsize=11)
ax[1].set_ylabel('残差 (kWh)', fontsize=11)
ax[1].set_title('(b) 储能递推残差（含日循环闭合）', fontsize=12)
ax[1].legend(fontsize=10)
ax[1].tick_params(labelsize=10)
ax[1].grid(True, which='both', alpha=0.3)

fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'paper', 'figures_adv',
                   'verify_residual.png')
fig.savefig(out, dpi=200)
print('已输出', os.path.normpath(out))

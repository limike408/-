# -*- coding: utf-8 -*-
"""「紧急波动」定义与全年统计（老师修改意见 24-26/29）。

定义口径（决策日 0:00 视角，信息因果）：
    * 净需求 n_t = 负荷_t - 光伏_t（当日需由 购电+储能 满足的净购电需求）。
    * 0:00 可获得的净需求预测 \hat n_t = 负荷点预报(K=15) - 光伏0点预报(附件3)。
    * 日净需求预测偏差 \epsilon_d = (实际日净需求 - 预测日净需求) / 预测日净需求。
    * 「紧急波动日」= 低估方向缺电风险显著：\epsilon_d <= -theta，
       theta 取 20%（老师建议的「超过 20% 认为紧急」），并做 10%/15%/30% 敏感性。
    * 「紧急程度」用 估净偏差 \epsilon_d 与 当日实际触发紧急购电量 Q_d 双重刻画。

输出：
    * report/emergency_analysis.csv      逐日偏差/紧急购电/标记
    * report/figures_adv/emergency_series.png  全年 \epsilon_d 曲线 + 阈值带 + 标记日
    * report/figures_adv/emergency_season.png  各季「紧急波动日」次数柱状图
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

THETA = 0.20        # 紧急波动阈值（低估净需求 ≥20%）
K_LOAD = 15


def load_q2_emergency():
    """从 result2.xlsx 紧急购电量 sheet 取 日紧急购电总量(kWh)。"""
    df = pd.read_excel(os.path.join(C.RES_DIR, 'result2.xlsx'), sheet_name='紧急购电量')
    dt = pd.to_datetime(df.iloc[:, 0])
    m = df.iloc[:, 1:].apply(pd.to_numeric, errors='coerce').to_numpy(float)
    dayQ = np.nansum(m[:, :C.T_IN_DAY], axis=1)
    return dt, dayQ


def main():
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()

    # 净需求 & 预测（负荷 K=15 点预报，光伏 附件3 0点）
    day_ld = load.sum(axis=1)
    day_pv = pv.sum(axis=1)
    hist = []
    ld_fc = []
    for i, d in enumerate(dates):
        Dk = None
        if i == 0:
            # 冷启动：附件1 典型日剖面（与 Q2 一致）
            a1 = data.load_attach1()
            Dk = a1['load']
        else:
            Dk = day0_mean(load[:i], K_LOAD)
        G0 = data.pv_forecast_kwh(fc3, d, 0)[0]
        hist.append(Dk)
        ld_fc.append(Dk.sum())
    ld_fc = np.array(ld_fc)
    day_net = day_ld - day_pv
    fc_net = ld_fc - day_fc0(fc3, dates)
    eps = (day_net - fc_net) / np.where(fc_net != 0, np.abs(fc_net), 1.0)

    # 紧急购电（Q2 口径）
    qdt, dayQ = load_q2_emergency()
    qmap = pd.DataFrame({'qdt': qdt, 'dayQ': dayQ})
    qmap = qmap.groupby('qdt')['dayQ'].sum()   # 去重（若同日多行取和）

    frame = pd.DataFrame({
        'date': dates, 'load': day_ld, 'pv': day_pv,
        'net_actual': day_net, 'net_fc': fc_net, 'eps': eps})
    frame['Q2_emergency_kwh'] = frame['date'].map(qmap).fillna(0.0)
    frame['emergency'] = eps >= THETA   # eps>0 表示实际净需求>预测（低估需求→缺电风险）

    # 全年统计
    n_emer = int(frame['emergency'].sum())
    n_total = len(frame)
    print(f'[紧急波动统计] 全年 {n_total} 天，低估净需求≥{THETA:.0%} 的紧急波动日：{n_emer} 天 ({n_emer/n_total:.1%})')
    for th in (0.10, 0.15, 0.20, 0.30):
        print(f'  阈值 {th:.0%}: {(eps >= th).sum()} 天')
    # 触发紧急购电
    quo = (frame['Q2_emergency_kwh'] > 0.01)
    print(f'  Q2 实际触发紧急购电天数：{int(quo.sum())}')
    # 严重缺电日（低估≥阈值且实际触发紧急购电）
    severe = frame['emergency'] & quo
    print(f'  严重缺电日（低估≥{THETA:.0%} 且触发紧急购电）：{int(severe.sum())} 天，'
          f'其中单日紧急购电≥50kWh：{int((frame["Q2_emergency_kwh"] >= 50).sum())} 天')
    # 低估方向的紧急日（真正缺电风险）
    print('\n[低估净需求(缺电)严重日期 top10]')
    sub = frame[frame['eps'] >= THETA].copy()
    if len(sub):
        for _, r in sub.sort_values('eps').head(10).iterrows():
            print(' ', r['date'].date(), f"低估={r['eps']:.0%}", '净需求=%.0f' % r['net_actual'],
                  f"紧急购电={r['Q2_emergency_kwh']:.0f} kWh")
    # 典型案例（老师点名 09-23 / 12-21）
    print('\n[老师点名日期核对]')
    for dd in ['2025-09-21', '2025-09-22', '2025-09-23', '2025-12-20', '2025-12-21']:
        r = frame[frame['date'] == pd.Timestamp(dd)]
        if len(r):
            r = r.iloc[0]
            print(f"  {dd} 负荷={r['load']:.0f} 光伏={r['pv']:.0f} "
                  f"净需={r['net_actual']:.0f} 低估={r['eps']:.0%} 紧急={r['Q2_emergency_kwh']:.0f}kWh")

    frame.to_csv(os.path.join(C.RES_DIR, 'emergency_analysis.csv'),
                 index=False, encoding='utf-8-sig')

    # ---- 图1：全年偏差曲线 + 阈值带 + 标记 ----
    fig, ax = plt.subplots(figsize=(12, 4.2))
    x = np.arange(n_total)
    ax.plot(x, eps, color='#34495e', lw=1.1, label='日净需求偏差 $\\varepsilon_d$')
    ax.axhline(0, color='gray', lw=0.8)
    ax.axhspan(THETA, float(eps.max()) * 1.05, color='#e74c3c', alpha=0.12,
               label=f'紧急波动区(低估≥{THETA:.0%})')
    em = frame['emergency'].to_numpy()
    ax.scatter(x[em], eps[em], s=22, color='#e74c3c', zorder=3, label='紧急波动日')
    for dd in ['2025-09-23', '2025-12-21']:
        i = int(np.where(frame['date'] == pd.Timestamp(dd))[0][0])
        ax.annotate(dd, (i, eps[i]), textcoords='offset points', xytext=(0, -14),
                    ha='center', fontsize=9, color='#c0392b')
    ax.set_xlim(0, n_total - 1)
    ax.set_xlabel('日期（2025 年逐日）', fontsize=11)
    ax.set_ylabel('净需求预测偏差 $\\varepsilon_d$', fontsize=11)
    ax.set_title(f'全年净需求预测偏差与「紧急波动日」识别（阈值 {THETA:.0%}）', fontsize=12)
    ax.legend(fontsize=10, loc='lower left')
    ax.tick_params(labelsize=10)
    ax.set_xticks(np.arange(0, n_total, 30))
    ax.set_xticklabels([frame['date'].iloc[i].strftime('%m-%d') for i in np.arange(0, n_total, 30)], rotation=45, fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(C.RES_DIR, 'figures_adv', 'emergency_series.png'), dpi=150)
    plt.close(fig)

    # ---- 图2：各季节紧急波动日次数 ----
    s = frame.set_index('date')
    s['season'] = s.index.month.map({3: '春', 4: '春', 5: '春', 6: '夏', 7: '夏', 8: '夏',
                                     9: '秋', 10: '秋', 11: '秋', 12: '冬', 1: '冬', 2: '冬'})
    stat = s.groupby('season')['emergency'].agg(['sum', 'count'])
    stat['rate'] = stat['sum'] / stat['count']
    order = ['春', '夏', '秋', '冬']
    stat = stat.reindex(order)
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(stat.index, stat['sum'], color=['#2ecc71', '#e67e22', '#3498db', '#95a5a6'],
                  width=0.55, edgecolor='black', linewidth=0.6)
    for b, (r, c) in zip(bars, stat[['rate', 'sum']].itertuples(index=False)):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.3,
                f"{int(c)} 天 ({r:.0%})", ha='center', fontsize=11)
    ax.set_ylim(0, stat['sum'].max() * 1.15)
    ax.set_ylabel('紧急波动日数', fontsize=11)
    ax.set_title(f'各季节「紧急波动日」出现次数（低估净需求≥{THETA:.0%}）', fontsize=12)
    ax.grid(alpha=0.3, axis='y')
    ax.tick_params(labelsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(C.RES_DIR, 'figures_adv', 'emergency_season.png'), dpi=150)
    plt.close(fig)
    print('\n图表已生成：figures_adv/emergency_series.png, figures_adv/emergency_season.png')


def day0_mean(hist, K):
    """前 K 天逐时段均值（kWh/时段）。"""
    if len(hist) == 0:
        return data.load_attach1()['load']
    return np.mean(hist[-min(K, len(hist)):], axis=0)


def day_fc0(fc3, dates):
    """0:00 光伏预报 日总能量(kWh)。"""
    return np.array([data.pv_forecast_kwh(fc3, d, 0)[0].sum() for d in dates])


if __name__ == '__main__':
    main()
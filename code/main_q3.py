# -*- coding: utf-8 -*-
"""问题3：滚动随机 MPC（v2 —— 因果滚动 + 情景鲁棒 + 负荷预报化）。

相对旧版的口径修正：
1) 负荷预报化：0/6/12/18 决策只用历史信息（负荷点预报 = 前 KL 天逐槽均值 + 成对残差情景），
   不再把当日实际负荷当作已知（与 Q2 预报式口径统一）；
2) 光伏情景化：以附件3 各时点官方预报为基准，叠加"实际−当日同点时点预报"的历史整日残差
   bootstrap（S=30，负荷与光伏同一天成对抽取），调整决策对情景做期望最小化（随机 MPC 名副其实）；
3) SOC 实际轨迹：每个调整时点 τ，用"已执行段 [0,t0) 固定购电 + 实际光伏/负荷"因果重放，
   得到真实 SOC 初值，不再沿用 0:00 计划轨迹；
4) 调整目标计费口径修正：Σ_t [p·A + 0.5p·u + 1.5p·w] 且 A+u−w=P 精确绑定违约/超额量
   （旧版 LP 目标把 u 推到上界 P、调整购电 A 退化免费，已修正）；
5) 结算口径与 Q2 一致：固定最终调整购电 A，对当日实际光伏/负荷重放电池调度，
   紧急购电 Q 按 5 倍价吸收偏差；E_end 结转次日（跨日连续 + 1 月预热）。

风险口径：Q3 不引入 CVaR 风险权重（λ=0）。理由：0/6/12/18 四次预报更新已把不确定性
逐次吸收，滚动再计划本身即风险对冲手段；CVaR 权重留作 Q2 单次决策的风险权衡工具
（论文正文点明该设计）。
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
import scenarios
C.setup_plot_style()
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TAU = [0, 6, 12, 18]
KL_Q3 = 15            # 负荷点预报/残差池窗口（与 Q2 的 K_L 一致）
S_Q3 = 30             # 情景数（与 Q2 一致）
SEED_BASE = 2026      # 抽样种子基数：2026 + 日序（确定性、重跑逐位一致）


def _seed_for_day(d):
    return SEED_BASE + int(d.dayofyear)


def build_fc3_hist(fc3, dates):
    """预计算历史 τ 时点光伏预报矩阵 {tau: (N,144)}，避免逐日重复插值。"""
    return {tau: np.stack([data.pv_forecast_kwh(fc3, dd, tau)[0] for dd in dates])
            for tau in TAU}


def _adjust(price, P, A, Q):
    """结算费用口径：p·min(P,A) + 0.5p(P-A)^+ + 1.5p(A-P)^+ + 5p·Q。"""
    u = np.maximum(P - A, 0.0)
    w = np.maximum(A - P, 0.0)
    grid_fee = float(np.sum(price * np.minimum(P, A) + C.DEFAULT_MULT * price * u + C.EXCESS_MULT * price * w))
    emerg_fee = float(np.sum(C.EMERG_MULT * price * Q))
    return grid_fee, emerg_fee


def _rolling(price, load, pv, dates, fc3, i, E_start, a1, FC3_HIST,
             KL=KL_Q3, S=S_Q3):
    """单日因果滚动随机 MPC。返回 dict(P,A,Q,c,f,grid_fee,emerg_fee,E_end)。"""
    d = dates[i]
    seed = _seed_for_day(d)
    # ---- 0:00 计划：两阶段随机（负荷历史残差情景 + 光伏附件3 0:00预报残差情景）----
    if i == 0:
        # 冷启动：无历史可抽残差，用附件1 典型日剖面作负荷情景基准、0:00 预报作光伏基准
        scen_ld = np.tile(a1['load'], (S, 1))
        scen_pv = np.tile(FC3_HIST[0][0], (S, 1))
    else:
        fc = scenarios.residual_scenarios_fc3(load[:i], pv[:i], FC3_HIST[0][:i],
                                              FC3_HIST[0][i], KL, S=S, seed=seed)
        scen_ld, scen_pv = fc['scen_ld'], fc['scen_pv']
    plan = lp.solve_two_stage(price, scen_ld, scen_pv, E_start, lam=0.0, beta=C.BETA)
    P = plan['P']
    A = P.copy()
    # ---- 6/12/18 滚动调整 ----
    for tau in TAU[1:]:
        t0 = tau * 6
        # 实际 SOC：已执行段 [0,t0) 用实际光伏/负荷，未来段 [t0,T) 用 τ 时点点预报
        # （电池对剩余时段有期望需求，保留"为晚间高峰充电"的动机；未来置 0 会导致电池躺平、
        #  SOC 恒为下限，调整购电被迫超买）
        G_mix = pv[i].copy(); G_mix[t0:] = FC3_HIST[tau][i][t0:]
        D_hat = scenarios.point_forecast(load[:i], KL) if i > 0 else a1['load']
        D_mix = load[i].copy(); D_mix[t0:] = D_hat[t0:]
        rep = lp.solve_day_fixedP(price, G_mix, D_mix, E_start, A)
        E_tau = float(rep['E'][t0 - 1])
        # τ 时点情景（截取 [t0,144)）
        if i == 0:
            scenD = np.tile(a1['load'][t0:], (S, 1))
            scenG = np.tile(FC3_HIST[tau][0][t0:], (S, 1))
        else:
            fct = scenarios.residual_scenarios_fc3(load[:i], pv[:i], FC3_HIST[tau][:i],
                                                   FC3_HIST[tau][i], KL, S=S, seed=seed)
            scenD = fct['scen_ld'][:, t0:]
            scenG = fct['scen_pv'][:, t0:]
        rp = lp.solve_adjust_scen(price, scenD, scenG, E_tau, P, t0)
        A[t0:] = rp['A']
    # ---- 日终结算：固定 A，实际光伏/负荷重放电池（电池日内实时调度口径，同 Q2）----
    settle = lp.solve_day_fixedP(price, pv[i], load[i], E_start, A)
    grid_fee, emerg_fee = _adjust(price, P, A, settle['Q'])
    return dict(P=P, A=A, Q=settle['Q'], c=settle['c'], f=settle['f'],
                grid_fee=grid_fee, emerg_fee=emerg_fee, E_end=settle['E'][-1])


def run(outfile='result3.xlsx'):
    a1 = data.load_attach1()
    price = a1['price']
    dates, load, pv = data.load_attach2()
    fc3 = data.load_attach3()
    FC3_HIST = build_fc3_hist(fc3, dates)
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        res = _rolling(price, load, pv, dates, fc3, i, E_start, a1, FC3_HIST)
        res['E_start'] = E_start
        rec[dates[i]] = res
        E_start = res['E_end']
        if (i + 1) % 30 == 0:
            print(f'  滚动进度 {i+1}/{len(dates)} 日（{dates[i].date()}）E={E_start:8.1f} kWh', flush=True)

    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    A = {d: rec[d]['A'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    path = os.path.join(C.RES_DIR, outfile)
    R.write_result3(path, dates_out, P, A, Q, c, f, E0, Ee)
    path = R.strip_personal_meta(path)
    tot_grid = sum(rec[d]['grid_fee'] for d in dates_out)
    tot_emerg = sum(rec[d]['emerg_fee'] for d in dates_out)
    print('已写出', path)
    print(f'[Q3 v2 滚动随机MPC] 计划+调整电网费={tot_grid:.2f} 元, 紧急购电费={tot_emerg:.2f} 元, 合计={tot_grid + tot_emerg:.2f} 元')
    return dict(price=price, dates=dates, load=load, pv=pv, fc3=fc3, rec=rec,
                dates_out=dates_out, a1=a1, FC3_HIST=FC3_HIST)


def analysis(price, dates, load, pv, fc3, rec, a1, FC3_HIST):
    """是否需要其他时刻预报：比较 仅0:00(不调整) vs 0/6/12/18 滚动。"""
    rows = []
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        i = int(np.where(dates == d)[0][0])
        E_start = rec[d]['E_start']
        seed = _seed_for_day(d)
        # 仅 0:00：两阶段随机计划（与滚动链同口径、同种子），固定 P 结算
        if i == 0:
            scen_ld = np.tile(a1['load'], (S_Q3, 1))
            scen_pv = np.tile(FC3_HIST[0][0], (S_Q3, 1))
        else:
            fc = scenarios.residual_scenarios_fc3(load[:i], pv[:i], FC3_HIST[0][:i],
                                                  FC3_HIST[0][i], KL_Q3, S=S_Q3, seed=seed)
            scen_ld, scen_pv = fc['scen_ld'], fc['scen_pv']
        plan = lp.solve_two_stage(price, scen_ld, scen_pv, E_start, lam=0.0, beta=C.BETA)
        st = lp.solve_day_fixedP(price, pv[i], load[i], E_start, plan['P'])
        g0, e0 = _adjust(price, plan['P'], plan['P'], st['Q'])
        r = _rolling(price, load, pv, dates, fc3, i, E_start, a1, FC3_HIST)
        rows.append(dict(day=dd, only0_grid=g0, only0_emerg=e0, only0_total=g0 + e0,
                         roll_grid=r['grid_fee'], roll_emerg=r['emerg_fee'],
                         roll_total=r['grid_fee'] + r['emerg_fee']))
    df = pd.DataFrame(rows)
    print('\n[Q3 调整时点分析]')
    print(df.to_string(index=False))
    df.to_csv(os.path.join(C.RES_DIR, 'q3_rolling_comparison.csv'), index=False, encoding='utf-8-sig')
    x = np.arange(len(df))
    w = 0.32
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w / 2, df.only0_total, w, label='仅0:00(不调整)')
    ax.bar(x + w / 2, df.roll_total, w, label='0/6/12/18 滚动')
    ax.set_xticks(x); ax.set_xticklabels(df.day, fontsize=11)
    ax.set_ylabel('总购电费用(元)', fontsize=12); ax.set_title('问题3：是否引入多时刻预报', fontsize=13)
    ax.legend(fontsize=11); ax.grid(alpha=0.4, axis='y')
    ax.tick_params(labelsize=11)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q3_forecast_time.png'), dpi=150); plt.close(fig)


if __name__ == '__main__':
    A = run()
    analysis(A['price'], A['dates'], A['load'], A['pv'], A['fc3'], A['rec'], A['a1'], A['FC3_HIST'])

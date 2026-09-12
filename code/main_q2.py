# -*- coding: utf-8 -*-
"""问题2：两阶段随机规划（官方口径 v2 —— 预报式，替代原完美信息口径）。

官方结果 result2.xlsx 口径：
  每天 0:00 依据截至前一日的历史数据（信息因果，不含未来）——
  1) 点预报：负荷/光伏分别取各自前 K_L / K_P 天逐槽(144 时段)均值，K 由全年交叉验证选出；
  2) 情景生成：整日残差 bootstrap（scenarios.residual_scenarios），负荷与光伏同一天成对，
     S=30 个情景，抽样种子 = 2026 + 日序（与日期绑定、确定性、重跑逐位一致）；
     2025-01-01 无历史，按拍板规格用附件1 典型日剖面做冷启动情景基准；
  3) 计划 P：lp.solve_two_stage(lam=LAM_OFFICIAL，CVaR 风险权衡口径：接受总费用略升、
     换取紧急购电显著下降；λ* 由 q2_lambda_sweep.py 全年权衡曲线数据驱动选定)；
  4) 结算：固定 P，用当日实际负荷/光伏调 lp.solve_day_fixedP（紧急价 5p）得当日实际
     紧急购电 Q 与充放电 c/f、储能 E；E_end 结转次日（跨日连续，1200~10800 kWh）。
  全年链自 2025-01-01（E=6000）逐日滚动，仅 1 月作储能状态预热，输出 2.1-12.31。

旧口径：perfect_info_legacy()（把当日实际负荷/光伏当作 0:00 已知 → 全年 Q≡0），
仅作对比保留，不再写入 result2.xlsx。
"""
import os, sys, time, hashlib
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np
import pandas as pd
import config as C
import data, lp, results as R
import scenarios

K_CANDIDATES = [7, 15, 30]      # K 候选集（数据驱动选优）
SEED_BASE = 2026                # 抽样种子基数：2026 + 日序
LEGACY_FEE_RECORD = 12260572.90 # 旧完美信息口径计划费（16.0 附件列序修复后复算值）
LAM_OFFICIAL = 0.5              # 官方风险权衡权重 λ*：由 q2_lambda_sweep.py 全年权衡曲线数据驱动选定
                                # （λ=0.5 拐点：紧急购电费较 λ=0 下降 55.4%，合计 16,209,098.16 为全网格最低；
                                #   λ≥1.5 后计划费饱和不再改善。用户拍板：Q2 采用风险权衡——
                                #   接受计划费略升、换取紧急购电显著下降；Q3/Q4 不引入 CVaR，
                                #   理由见 main_q3.py 头部注释，论文正文点明）


def _seed_for_day(d):
    """与日期绑定的确定性随机种子（重跑逐位一致）。"""
    return SEED_BASE + int(d.dayofyear)


def cross_validate_K(dates, load, pv):
    """交叉验证选 K（候选 {7,15,30}）。

    对 2025-02-01~12-31 每天 d：用 d 前 K 天逐槽均值预报 d，计算 144 时段 RMSE，
    除以该日实际均值归一化（当日均值≈0 的天跳过），全年取平均；
    负荷、光伏各自选出平均归一化 RMSE 最小的 K（记为 K_L、K_P）。
    返回 (KL, KP, cv 表)。
    """
    start = int(np.searchsorted(dates, pd.Timestamp('2025-02-01')))
    rows, skip = [], 0
    for K in K_CANDIDATES:
        nrmse_L, nrmse_P = [], []
        for i in range(start, len(dates)):
            lo = max(0, i - K)
            fcL = load[lo:i].mean(axis=0) if i > lo else load[i] * 0.0
            fcP = pv[lo:i].mean(axis=0) if i > lo else pv[i] * 0.0
            mL = float(load[i].mean()); mP = float(pv[i].mean())
            if mL > 1e-6:
                nrmse_L.append(float(np.sqrt(np.mean((fcL - load[i]) ** 2)) / mL))
            else:
                skip += 1
            if mP > 1e-6:
                nrmse_P.append(float(np.sqrt(np.mean((fcP - pv[i]) ** 2)) / mP))
            else:
                skip += 1
        rows.append(dict(K=K, nrmse_load=float(np.mean(nrmse_L)),
                         nrmse_pv=float(np.mean(nrmse_P))))
    cv = pd.DataFrame(rows)
    KL = int(cv.loc[cv['nrmse_load'].idxmin(), 'K'])
    KP = int(cv.loc[cv['nrmse_pv'].idxmin(), 'K'])
    if skip:
        print(f'[K 交叉验证] 跳过日均值≈0 的天次（负荷/光伏合计）: {skip}')
    return KL, KP, cv


def perfect_info_legacy(price, load, pv, dates):
    """【旧口径，仅作对比】完美信息：把当日实际负荷/光伏当作 0:00 已知，
    确定性 LP 计划 → 全年紧急购电 Q≡0。不再用于官方 result2.xlsx。"""
    rec = {}
    E_start = C.E_INIT
    for i in range(len(dates)):
        rp = lp.solve_day_plan(price, pv[i], load[i], E_start)
        rec[dates[i]] = dict(P=rp['P'], Q=np.zeros(C.T_IN_DAY), c=rp['c'], f=rp['f'],
                             E_start=E_start, E_end=rp['E'][-1])
        E_start = rp['E'][-1]
    return rec


def _run_forecast_chain(price, dates, load, pv, KL, KP, S=30, lam=0.0,
                        max_days=None, verbose=True):
    """预报式两阶段随机规划全年滚动链（官方口径）。

    每日：residual_scenarios(load[:i], pv[:i], (KL,KP), S, seed=2026+日序)
    → solve_two_stage(lam) 得计划 P → solve_day_fixedP 按当日实际结算
    → E_end 结转次日。断言每日储能 E 全程 ∈ [1200,10800]。
    max_days: 仅跑前 N 天（冒烟测试用），默认全年。
    """
    n = len(dates) if max_days is None else int(max_days)
    rec = {}
    E_start = C.E_INIT
    t0 = time.time()
    a1 = data.load_attach1()          # 冷启动先验：2025-01-01 无历史可用
    for i in range(n):
        d = dates[i]
        if i == 0:
            # 冷启动（拍板规格）：用附件1 典型日负荷/光伏剖面作当日点预报与情景基准
            # （无历史可抽残差，S 个情景同形）。
            scen_ld = np.tile(a1['load'], (S, 1))
            scen_pv = np.tile(a1['pv'], (S, 1))
        else:
            fc = scenarios.residual_scenarios(load[:i], pv[:i], (KL, KP), S=S,
                                              seed=_seed_for_day(d))
            scen_ld, scen_pv = fc['scen_ld'], fc['scen_pv']
        two = lp.solve_two_stage(price, scen_ld, scen_pv, E_start,
                                 lam=lam, beta=C.BETA)
        settle = lp.solve_day_fixedP(price, pv[i], load[i], E_start, two['P'])
        E_t = np.asarray(settle['E'], float)
        assert np.all(E_t >= C.SOC_MIN - 1e-6) and np.all(E_t <= C.SOC_HIGH_BOUND + 1e-6), \
            f'{d.date()} 储能越界: min={E_t.min():.2f} max={E_t.max():.2f}'
        rec[d] = dict(P=two['P'], Q=settle['Q'], c=settle['c'], f=settle['f'],
                      E_start=float(E_start), E_end=float(E_t[-1]))
        E_start = float(E_t[-1])
        if verbose and (i + 1) % 30 == 0:
            el = time.time() - t0
            print(f'  滚动链进度 {i + 1}/{n} 日（{d.date()}）E={E_start:8.1f} kWh'
                  f'  用时 {el:6.1f}s', flush=True)
    return rec


def _result_digest(price, dates_out, rec):
    """对全部输出序列做确定性哈希，供跨次运行逐位一致性校验。"""
    h = hashlib.sha256()
    for d in dates_out:
        h.update(np.round(np.asarray(rec[d]['P'], float), 6).tobytes())
        h.update(np.round(np.asarray(rec[d]['Q'], float), 6).tobytes())
        h.update(np.round(np.asarray(rec[d]['c'], float), 6).tobytes())
        h.update(np.round(np.asarray(rec[d]['f'], float), 6).tobytes())
        h.update(np.round(np.float64(rec[d]['E_end']), 6).tobytes())
    return h.hexdigest()


def run(outfile='result2.xlsx'):
    a1 = data.load_attach1()
    price = a1['price']
    dates, load, pv = data.load_attach2()

    # ---- 1) 交叉验证选 K（数据驱动）----
    KL, KP, cv = cross_validate_K(dates, load, pv)
    print('[K 交叉验证] 全年平均归一化 RMSE（2025-02-01~12-31，144 时段）:')
    print(cv.to_string(index=False))
    print(f'所选: K_L = {KL}, K_P = {KP}')

    # ---- 2) 预报式两阶段随机规划全年链（1 月预热，不输出；λ=λ* 风险权衡口径）----
    print(f'开始全年滚动链：365 天 × S={C.S_NUM} 情景两阶段 LP（lam={LAM_OFFICIAL}）……')
    rec = _run_forecast_chain(price, dates, load, pv, KL, KP, S=C.S_NUM, lam=LAM_OFFICIAL)

    # ---- 3) 汇总与写 result2.xlsx ----
    dates_out = [d for d in dates if d >= pd.Timestamp('2025-02-01')]
    P = {d: rec[d]['P'] for d in dates_out}
    Q = {d: rec[d]['Q'] for d in dates_out}
    c = {d: rec[d]['c'] for d in dates_out}
    f = {d: rec[d]['f'] for d in dates_out}
    E0 = {d: rec[d]['E_start'] for d in dates_out}
    Ee = {d: rec[d]['E_end'] for d in dates_out}
    plan_fee = sum(float(np.sum(price * rec[d]['P'])) for d in dates_out)
    emerg_fee = sum(float(np.sum(C.EMERG_MULT * price * rec[d]['Q'])) for d in dates_out)
    emerg_kwh = sum(float(rec[d]['Q'].sum()) for d in dates_out)
    total_fee = plan_fee + emerg_fee
    assert emerg_fee > 0, '全年紧急购电费应 > 0（旧完美信息口径为 0，已切换预报式口径）'
    path = os.path.join(C.RES_DIR, outfile)
    R.write_result2(path, dates_out, P, Q, c, f, E0, Ee)
    path = R.strip_personal_meta(path)   # 清除模板带入的个人元数据（提交合规）
    print('已写出', path)
    print(f'[Q2 官方·预报式] 计划购电费 = {plan_fee:,.2f} 元 | '
          f'紧急购电费 = {emerg_fee:,.2f} 元（{emerg_kwh:,.0f} kWh） | '
          f'合计 = {total_fee:,.2f} 元')

    # ---- 4) 指定日期 144 时段 Q 序列（论文表3 用）----
    spec_q = {}
    print('[Q2 指定日期紧急购电（论文表3）]')
    for ds in C.SPEC_DAYS:
        d = pd.Timestamp(ds)
        spec_q[d] = np.asarray(rec[d]['Q'], float)
        if spec_q[d].sum() <= 0:
            # 合法零值：当日实际净需求低于全部情景（如周末低负荷日），计划按情景包络
            # 多购，缺电由计划+储能完全吸收，表现为高弃光而非紧急购电。
            print(f'  注意: {ds} 紧急购电 = 0 kWh（合法结果：当日实际净需求低于全部 S 个'
                  f'情景，计划按情景包络多购，缺电由计划+储能吸收，弃光较高）')
        else:
            print(f'  {ds}: 紧急购电 {spec_q[d].sum():,.1f} kWh，紧急费 '
                  f'{float(np.sum(C.EMERG_MULT * price * spec_q[d])):,.1f} 元')
    qtab = pd.DataFrame({'时间段': C.INTERVAL_LABELS})
    for ds in C.SPEC_DAYS:
        qtab[ds] = np.round(spec_q[pd.Timestamp(ds)], 4)
    qtab.to_csv(os.path.join(C.RES_DIR, 'q2_specdays_Q.csv'),
                index=False, encoding='utf-8-sig')

    # ---- 5) 摘要 CSV ----
    summ_rows = [
        ('全年计划购电费_元', round(plan_fee, 2)),
        ('全年紧急购电费_元', round(emerg_fee, 2)),
        ('合计_元', round(total_fee, 2)),
        ('全年紧急购电量_kWh', round(emerg_kwh, 2)),
        ('K_L', KL), ('K_P', KP),
    ]
    for ds in C.SPEC_DAYS:
        d = pd.Timestamp(ds)
        summ_rows.append((f'{ds}_紧急购电量_kWh', round(float(spec_q[d].sum()), 4)))
        summ_rows.append((f'{ds}_紧急购电费_元',
                          round(float(np.sum(C.EMERG_MULT * price * spec_q[d])), 4)))
    summ = pd.DataFrame(summ_rows, columns=['指标', '数值'])
    summ.to_csv(os.path.join(C.RES_DIR, 'q2_new_summary.csv'),
                index=False, encoding='utf-8-sig')
    cv.to_csv(os.path.join(C.RES_DIR, 'q2_K_cv.csv'), index=False, encoding='utf-8-sig')

    # ---- 6) 重跑一致性校验（seed 固定 → 逐位一致）----
    digest_path = os.path.join(C.RES_DIR, 'q2_digest.txt')
    dg = _result_digest(price, dates_out, rec)
    if os.path.exists(digest_path):
        old = open(digest_path, encoding='utf-8').read().strip()
        assert old == dg, f'重跑结果与上次不一致！旧 digest={old[:16]}… 新 digest={dg[:16]}…'
        print(f'[重跑一致性] digest 校验通过: {dg[:16]}…')
    else:
        with open(digest_path, 'w', encoding='utf-8') as fp:
            fp.write(dg)
        print(f'[重跑一致性] 首次运行，已记录 digest: {dg[:16]}…')

    # ---- 7) 与旧完美信息口径对比（仅对比，不写结果）----
    leg = perfect_info_legacy(price, load, pv, dates)
    leg_fee = sum(float(np.sum(price * leg[d]['P'])) for d in dates_out)
    diff = plan_fee - leg_fee
    print('\n[新旧口径对比]')
    print(f'旧完美信息计划费 = {leg_fee:,.2f} 元'
          f'（历史记录 {LEGACY_FEE_RECORD:,.2f} 元，'
          f'{"复算吻合" if abs(leg_fee - LEGACY_FEE_RECORD) < 1.0 else "复算不一致，请检查"}）')
    print(f'新预报式计划费 = {plan_fee:,.2f} 元，差 = {diff:+,.2f} 元')
    if diff > 0:
        print('解释：完美信息口径下计划即当日实际最优购电（全年紧急购电恒为 0），是计划费的'
              '下界；预报式口径下计划基于历史均值与整日残差情景做期望最小化，为对冲负荷/光伏'
              '不确定性会在低价时段多购电充当“保险”，把缺电风险尽量转移到 1 倍计划电价而非 '
              '5 倍紧急电价，因此计划费略高（保险性多购），多出的计划费换来的是把实际缺电'
              f'风险真实计量为全年 {emerg_fee:,.0f} 元紧急购电费（旧口径 Q≡0，该风险成本'
              '为零计量）。')
    else:
        print('解释：预报式口径计划费不高于完美信息口径，说明历史均值预报在低价时段购电更'
              '克制；完美信息计划因精确贴合当日曲线而把更多购电安排在低价时段，两者均无紧急'
              '购电的完美信息是理论下界，预报式口径的全部费用 = 计划费 + 紧急费才是真实可'
              '支付成本。')
    print(f'[Q2 完成] 全年合计费用（计划+紧急）= {total_fee:,.2f} 元')
    return dict(price=price, dates=dates, load=load, pv=pv, rec=rec,
                dates_out=dates_out, KL=KL, KP=KP, plan_fee=plan_fee,
                emerg_fee=emerg_fee, total_fee=total_fee, leg_fee=leg_fee)


def method_analysis(price, dates, load, pv, rec, KL, KP):
    """λ(CVaR 权重)敏感性（论文用，不计入 result2.xlsx）。

    4 个指定日期 × λ∈{0,0.5,1,2,5}：新情景生成器（(K_L,K_P) 整日成对残差 bootstrap，
    seed=2026+日序，与官方链同源）→ solve_two_stage(lam) → 当日实际结算。
    输出 plan_fee / emerg_fee / total / emerg_kwh 表（CSV）并画 3.20 权衡图。
    """
    rows = []
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        i = int(np.where(dates == d)[0][0])
        E_start = rec[d]['E_start']
        fc = scenarios.residual_scenarios(load[:i], pv[:i], (KL, KP), S=C.S_NUM,
                                          seed=_seed_for_day(d))
        for lam in sorted(set([0.0, 0.5, 1.0, 2.0, 5.0, LAM_OFFICIAL])):
            two = lp.solve_two_stage(price, fc['scen_ld'], fc['scen_pv'], E_start,
                                     lam=lam, beta=C.BETA)
            settle = lp.solve_day_fixedP(price, pv[i], load[i], E_start, two['P'])
            plan_fee = float(np.sum(price * two['P']))
            emerg_fee = float(np.sum(C.EMERG_MULT * price * settle['Q']))
            rows.append(dict(day=dd, lam=lam, plan_fee=plan_fee, emerg_fee=emerg_fee,
                             total=plan_fee + emerg_fee, emerg_kwh=float(settle['Q'].sum())))
    df = pd.DataFrame(rows)
    # 自检：λ=λ* 行应与官方链当日结算一致（同种子、同情景、同 E_start）
    for dd in C.SPEC_DAYS:
        d = pd.Timestamp(dd)
        r0 = df[(df.day == dd) & (df.lam == LAM_OFFICIAL)].iloc[0]
        chain_plan = float(np.sum(price * rec[d]['P']))
        chain_emer = float(np.sum(C.EMERG_MULT * price * rec[d]['Q']))
        assert abs(r0.plan_fee - chain_plan) < 1e-3, f'{dd} λ={LAM_OFFICIAL} 计划费与官方链不一致'
        assert abs(r0.emerg_fee - chain_emer) < 1e-3, f'{dd} λ={LAM_OFFICIAL} 紧急费与官方链不一致'
    print('\n[Q2 λ敏感性 · 两阶段随机+CVaR（新情景生成器）]')
    print(df.to_string(index=False))
    df.to_csv(os.path.join(C.RES_DIR, 'q2_two_stage_comparison.csv'),
              index=False, encoding='utf-8-sig')

    import matplotlib
    matplotlib.use('Agg')
    C.setup_plot_style()
    import matplotlib.pyplot as plt
    df20 = df[df.day == C.SPEC_DAYS[0]].sort_values('lam')
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(df20.lam, df20.plan_fee, '-o', label='计划购电费')
    ax.plot(df20.lam, df20.emerg_fee, '-s', label='紧急购电费')
    ax.plot(df20.lam, df20.total, '--^', label='合计')
    ax.set_xlabel('CVaR 权重 λ'); ax.set_ylabel('费用(元)')
    ax.set_title(f'问题2 两阶段随机+CVaR：{C.SPEC_DAYS[0]} 风险-费用权衡')
    ax.legend(); ax.grid(alpha=0.4)
    fig.tight_layout(); fig.savefig(os.path.join(C.FIG_DIR, 'q2_cvar_tradeoff.png'), dpi=150)
    plt.close(fig)
    print('已写 report/q2_two_stage_comparison.csv 与 figures/q2_cvar_tradeoff.png')


if __name__ == '__main__':
    A = run()
    method_analysis(A['price'], A['dates'], A['load'], A['pv'], A['rec'], A['KL'], A['KP'])

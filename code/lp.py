# -*- coding: utf-8 -*-
"""核心 LP 求解器（scipy.integrate 的 linprog / highs）。

变量单位：所有能量量 kWh/时段(=kW·DT)。平衡方程：
    P + G + eta·f + Q = D + c + R      (购电+光伏+放电+紧急 = 负载+充电+弃光)
    E_t = E_{t-1} + eta·c_t - f_t      (储能递推)
目标：min sum p_t·(购电成本) + 紧急/调整惩罚项。
"""
import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog
import config as C


def _var_breakdown(nvar):
    """6 变量交错布局 [P,c,f,Q,R,E]。"""
    base = np.arange(nvar // 6) * 6
    return dict(P=base, C=base + 1, F=base + 2, Q=base + 3, R=base + 4, E=base + 5)


def solve_day(price, G, D, E_start, T=None, emult=0.0, fixed_P=None,
              force_end=None, allow_emergency=True, allow_P=True,
              soc_lo=C.SOC_MIN, soc_hi=C.SOC_HIGH_BOUND):
    """单日确定性 LP。

    price: (T) 电价；G:(T) 光伏；D:(T) 负载；E_start: 当日 0:00 储电。
    fixed_P : 固定购电量(已承诺)，只优化电池+紧急+弃光。
    force_end: 强制 E_{T-1}=force_end（问题1 日内循环）。
    emult: 紧急购电价格倍数。返回 dict(P,c,f,Q,R,E,obj)。
    """
    T = T if T is not None else C.T_IN_DAY
    nvar = 6 * T
    v = _var_breakdown(nvar)
    iP, iC, iF, iQ, iR, iE = v['P'], v['C'], v['F'], v['Q'], v['R'], v['E']

    c = np.zeros(nvar)
    if allow_P:
        c[iP] = price
    if allow_emergency and emult is not None:
        c[iQ] = emult * price

    # 等式约束
    eq_r, eq_c, eq_v, b = [], [], [], []
    for t in range(T):
        def row(rr):
            eq_r.append(rr); eq_c.append(iP[t]); eq_v.append(1.0)
            eq_r.append(rr); eq_c.append(iC[t]); eq_v.append(-1.0)
            eq_r.append(rr); eq_c.append(iF[t]); eq_v.append(C.ETA)
            eq_r.append(rr); eq_c.append(iQ[t]); eq_v.append(1.0)
            eq_r.append(rr); eq_c.append(iR[t]); eq_v.append(-1.0)
        row(t); b.append(D[t] - G[t])
    for t in range(T):
        rr = T + t
        eq_r.append(rr); eq_c.append(iE[t]); eq_v.append(1.0)
        eq_r.append(rr); eq_c.append(iC[t]); eq_v.append(-C.ETA)
        eq_r.append(rr); eq_c.append(iF[t]); eq_v.append(1.0)
        if t > 0:
            eq_r.append(rr); eq_c.append(iE[t-1]); eq_v.append(-1.0)
            b.append(0.0)
        else:
            b.append(E_start)
    if force_end is not None:
        rr = 2 * T
        eq_r.append(rr); eq_c.append(iE[T-1]); eq_v.append(1.0)
        b.append(force_end)
    A_eq = sp.csr_matrix((eq_v, (eq_r, eq_c)), shape=(len(b), nvar))

    # 边界
    lb = np.zeros(nvar); ub = np.full(nvar, np.inf)
    ub[iC] = C.E_CMAX; ub[iF] = C.E_FMAX
    lb[iE] = soc_lo; ub[iE] = soc_hi
    if not allow_emergency:
        ub[iQ] = 0.0
    if fixed_P is not None:
        loP = np.asarray(fixed_P, float)
        ub[iP] = loP; lb[iP] = loP
    bounds = list(zip(lb, ub))

    res = linprog(c, A_eq=A_eq, b_eq=np.array(b), bounds=bounds, method='highs')
    if not res.success:
        raise RuntimeError('单日LP失败: ' + res.message)
    x = res.x
    return dict(P=x[iP], c=x[iC], f=x[iF], Q=x[iQ], R=x[iR], E=x[iE], obj=res.fun)


def solve_day_plan(price, G, D, E_start, force_end=None):
    """问题1/2 完美信息计划（购电自由，不支持紧急）。"""
    return solve_day(price, G, D, E_start, emult=0.0, force_end=force_end,
                     allow_emergency=False, allow_P=True)


def solve_day_fixedP(price, G, D, E_start, P, emult=C.EMERG_MULT):
    """回放：固定计划购电 P（已承诺付费），优化电池/弃光 + 紧急(5p)。"""
    return solve_day(price, G, D, E_start, emult=emult,
                     fixed_P=np.asarray(P, float), allow_emergency=True, allow_P=False)


def solve_two_stage(price, scenD, scenG, E_start, lam=0.0, beta=0.90):
    """两阶段随机规划（含 CVaR）。

    第一阶段 P(购电, 各情景共用)；第二阶段按情景决策 c,f,Q,R,E。
    目标 = Σ p·P + (1/S)ΣΣ 5p·Q + lam·CVaR_beta(情景总成本)。
    scenD/scenG: (S,144)。返回 dict(P,Q_mean,E_mean,obj)。
    """
    T = C.T_IN_DAY; S = len(scenD); pi = 1.0 / S
    nP = T
    base_s = nP + np.arange(S) * (5 * T)
    vary = _var_rows_scen(base_s, T)
    nvar = nP + S * 5 * T
    c = np.zeros(nvar)
    c[:nP] = price
    alpha_idx = z_idx = None
    if lam > 0:
        alpha_idx = nvar; z_idx = nvar + 1 + np.arange(S)
        nvar_full = nvar + 1 + S
        c = np.concatenate([c, np.zeros(S + 1)])
        c[alpha_idx] = lam; c[z_idx] = lam / ((1 - beta) * S)
    else:
        nvar_full = nvar
    for s in range(S):
        c[vary[s]['Q']] = pi * C.EMERG_MULT * price

    eq_r, eq_c, eq_v, beq = [], [], [], []
    row = 0
    for s in range(S):
        Pv = np.arange(nP); iv = vary[s]
        for t in range(T):
            eq_r.append(row); eq_c.append(Pv[t]); eq_v.append(1.0)
            eq_r.append(row); eq_c.append(iv['C'][t]); eq_v.append(-1.0)
            eq_r.append(row); eq_c.append(iv['F'][t]); eq_v.append(C.ETA)
            eq_r.append(row); eq_c.append(iv['Q'][t]); eq_v.append(1.0)
            eq_r.append(row); eq_c.append(iv['R'][t]); eq_v.append(-1.0)
            beq.append(scenD[s, t] - scenG[s, t]); row += 1
        for t in range(T):
            eq_r.append(row); eq_c.append(iv['E'][t]); eq_v.append(1.0)
            eq_r.append(row); eq_c.append(iv['C'][t]); eq_v.append(-C.ETA)
            eq_r.append(row); eq_c.append(iv['F'][t]); eq_v.append(1.0)
            if t > 0:
                eq_r.append(row); eq_c.append(iv['E'][t-1]); eq_v.append(-1.0)
                beq.append(0.0)
            else:
                beq.append(E_start)
            row += 1
    A_eq = sp.csr_matrix((eq_v, (eq_r, eq_c)), shape=(len(beq), nvar_full))

    # CVaR 不等式： ΣpP+Σ5pQ - α - z_s <= 0
    Aub_r, Aub_c, Aub_v, bub = [], [], [], []
    if lam > 0:
        for s in range(S):
            r = len(bub)
            for t in range(T):
                Aub_r.append(r); Aub_c.append(t); Aub_v.append(price[t])
                Aub_r.append(r); Aub_c.append(vary[s]['Q'][t]); Aub_v.append(C.EMERG_MULT * price[t])
            Aub_r.append(r); Aub_c.append(alpha_idx); Aub_v.append(-1.0)
            Aub_r.append(r); Aub_c.append(z_idx[s]); Aub_v.append(-1.0)
            bub.append(0.0)
        A_ub = sp.csr_matrix((Aub_v, (Aub_r, Aub_c)), shape=(len(bub), nvar_full))
        b_ub = np.array(bub)
    else:
        A_ub = None; b_ub = None

    lb = np.zeros(nvar_full); ub = np.full(nvar_full, np.inf)
    for s in range(S):
        iv = vary[s]
        ub[iv['C']] = C.E_CMAX; ub[iv['F']] = C.E_FMAX
        lb[iv['E']] = C.SOC_MIN; ub[iv['E']] = C.SOC_HIGH_BOUND
    if lam > 0:
        lb[alpha_idx] = -np.inf; lb[z_idx] = 0
    bounds = list(zip(lb, ub))

    res = linprog(c, A_eq=A_eq, A_ub=A_ub, b_eq=np.array(beq), b_ub=b_ub,
                  bounds=bounds, method='highs')
    if not res.success:
        raise RuntimeError('两阶段LP失败: ' + res.message)
    x = res.x
    P = x[:nP]
    Q = np.zeros((S, T)); Cc = np.zeros((S, T)); F = np.zeros((S, T)); E = np.zeros((S, T))
    for s in range(S):
        iv = vary[s]
        Q[s] = x[iv['Q']]; Cc[s] = x[iv['C']]; F[s] = x[iv['F']]; E[s] = x[iv['E']]
    return dict(P=P, Q=Q, c=Cc, f=F, E=E, obj=res.fun)


def _var_rows_scen(base_s, T):
    out = {}
    for s, base in enumerate(base_s):
        ar = base + np.arange(5 * T)
        out[s] = {'C': ar[0::5], 'F': ar[1::5], 'Q': ar[2::5],
                  'R': ar[3::5], 'E': ar[4::5]}
    return out


def solve_adjust_scen(price, scenD, scenG, E_start, P_plan, t0):
    """滚动调整的情景鲁棒版（Q3 v2 用）：在 [t0,T) 对 S 个情景做期望最小化决定调整购电 A。

    与旧 solve_adjust 的区别（口径修正）：
    1) 目标按真实结算口径计费 A：Σ_t [p·A + 0.5p·u + 1.5p·w]，其中违约/超额量由等式
       A + u - w = P 精确绑定（u=(P-A)^+，w=(A-P)^+，最优时 u·w=0）。
       旧版只有 A+u>=P 且 u<=P，目标又把 u 推向 P，造成"调整购电 A 免费"的退化口径。
    2) 两阶段式：A 对情景共用（承诺购电），电池充放 c/f、弃光 R、储电 E 与**情景内紧急购电
       Q（5 倍价期望）**按情景分别决策——A 不必覆盖最坏情景包络，缺电由情景内 Q 计价，
       使调整决策在"多买电(1倍) vs 紧急补购(5倍)"间做期望权衡（"随机 MPC"名副其实）。
    3) 日终结算的紧急购电另由 solve_day_fixedP 按当日实际值给出（与 Q2 结算口径一致）。

    scenD/scenG: (S, nh) 情景净需求侧数据，nh = 144 - t0。
    返回 dict(A,u,w,c,f,Q,R,E,obj)，A/u/w 长度 nh；c/f/Q/R/E 形状 (S,nh)。
    """
    T = C.T_IN_DAY
    nh = T - t0
    if nh <= 0:
        z = np.zeros((len(scenD), 0))
        return dict(A=np.zeros(0), u=np.zeros(0), w=np.zeros(0),
                    c=z, f=z, Q=z, R=z, E=z, obj=0.0)
    S = len(scenD)
    pt = np.arange(t0, T)
    pr = price[pt]
    Pseg = np.asarray(P_plan[pt], float)
    # 变量布局：A(nh), u(nh), w(nh), 每情景 [c,f,Q,R,E](5*nh)
    iA = np.arange(nh)
    iU = np.arange(nh, 2 * nh)
    iW = np.arange(2 * nh, 3 * nh)
    off = 3 * nh
    nvar = off + S * 5 * nh
    pi = 1.0 / S
    c = np.zeros(nvar)
    c[iA] = 0.0
    c[iU] = -C.DEFAULT_MULT * pr
    c[iW] = C.EXCESS_MULT * pr
    iv = {}
    for s in range(S):
        b = off + s * 5 * nh
        iv[s] = dict(C=b + np.arange(nh), F=b + nh + np.arange(nh),
                     Q=b + 2 * nh + np.arange(nh), R=b + 3 * nh + np.arange(nh),
                     E=b + 4 * nh + np.arange(nh))
        c[iv[s]['Q']] = pi * C.EMERG_MULT * pr

    eq_r, eq_c, eq_v, beq = [], [], [], []
    row = 0
    # 违约/超额绑定：A + u - w = P（每时段，与情景无关）
    for t in range(nh):
        eq_r.append(row); eq_c.append(iA[t]); eq_v.append(1.0)
        eq_r.append(row); eq_c.append(iU[t]); eq_v.append(1.0)
        eq_r.append(row); eq_c.append(iW[t]); eq_v.append(-1.0)
        beq.append(Pseg[t]); row += 1
    # 每情景：能量平衡 A + G + ηf + Q = D + c + R 与储能递推
    for s in range(S):
        v = iv[s]
        for t in range(nh):
            eq_r.append(row); eq_c.append(iA[t]); eq_v.append(1.0)
            eq_r.append(row); eq_c.append(v['C'][t]); eq_v.append(-1.0)
            eq_r.append(row); eq_c.append(v['F'][t]); eq_v.append(C.ETA)
            eq_r.append(row); eq_c.append(v['Q'][t]); eq_v.append(1.0)
            eq_r.append(row); eq_c.append(v['R'][t]); eq_v.append(-1.0)
            beq.append(scenD[s, t] - scenG[s, t]); row += 1
        for t in range(nh):
            eq_r.append(row); eq_c.append(v['E'][t]); eq_v.append(1.0)
            eq_r.append(row); eq_c.append(v['C'][t]); eq_v.append(-C.ETA)
            eq_r.append(row); eq_c.append(v['F'][t]); eq_v.append(1.0)
            if t > 0:
                eq_r.append(row); eq_c.append(v['E'][t - 1]); eq_v.append(-1.0)
                beq.append(0.0)
            else:
                beq.append(E_start)
            row += 1
    A_eq = sp.csr_matrix((eq_v, (eq_r, eq_c)), shape=(row, nvar))

    lb = np.zeros(nvar); ub = np.full(nvar, np.inf)
    for s in range(S):
        v = iv[s]
        ub[v['C']] = C.E_CMAX; ub[v['F']] = C.E_FMAX
        lb[v['E']] = C.SOC_MIN; ub[v['E']] = C.SOC_HIGH_BOUND
    bounds = list(zip(lb, ub))

    res = linprog(c, A_eq=A_eq, b_eq=np.array(beq), bounds=bounds, method='highs')
    if not res.success:
        raise RuntimeError('滚动调整情景LP失败: ' + res.message)
    x = res.x
    Cc = np.zeros((S, nh)); F = np.zeros((S, nh)); Qq = np.zeros((S, nh))
    Rr = np.zeros((S, nh)); E = np.zeros((S, nh))
    for s in range(S):
        v = iv[s]
        Cc[s] = x[v['C']]; F[s] = x[v['F']]; Qq[s] = x[v['Q']]
        Rr[s] = x[v['R']]; E[s] = x[v['E']]
    return dict(A=x[iA], u=x[iU], w=x[iW], c=Cc, f=F, Q=Qq, R=Rr, E=E, obj=res.fun)
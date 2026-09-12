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


def solve_adjust(price, G, D, E_start, P_plan, t0):
    """滚动再计划：在 [t0,144) 决定最终购电 A，对计划 P_plan 付违约/超出惩罚。

    u=(P-A)^+ 违约量 → 项 -0.5p u；w=(A-P)^+ 超出量 → 项 +1.5p w。
    再计划阶段不允许紧急购电(Q=0)。返回 dict(A,c,f,Q=0,R,E,u,w,obj)，长度 (144-t0)。
    """
    T = C.T_IN_DAY; nh = T - t0
    if nh <= 0:
        z = np.zeros(0)
        return dict(A=z, c=z, f=z, Q=z, R=z, E=z, u=z, w=z, obj=0.0)
    base = np.arange(nh) * 8
    iA, iC, iF, iQ, iR, iE, iU, iW = (base + k for k in range(8))
    pt = np.arange(t0, T)
    nvar = 8 * nh
    c = np.zeros(nvar)
    c[iU] = -C.DEFAULT_MULT * price[pt]
    c[iW] = C.EXCESS_MULT * price[pt]

    eq_r, eq_c, eq_v, beq = [], [], [], []
    for s in range(nh):
        eq_r.append(s); eq_c.append(iA[s]); eq_v.append(1.0)
        eq_r.append(s); eq_c.append(iC[s]); eq_v.append(-1.0)
        eq_r.append(s); eq_c.append(iF[s]); eq_v.append(C.ETA)
        eq_r.append(s); eq_c.append(iQ[s]); eq_v.append(1.0)
        eq_r.append(s); eq_c.append(iR[s]); eq_v.append(-1.0)
        beq.append(D[pt[s]] - G[pt[s]])
    for s in range(nh):
        rr = nh + s
        eq_r.append(rr); eq_c.append(iE[s]); eq_v.append(1.0)
        eq_r.append(rr); eq_c.append(iC[s]); eq_v.append(-C.ETA)
        eq_r.append(rr); eq_c.append(iF[s]); eq_v.append(1.0)
        if s > 0:
            eq_r.append(rr); eq_c.append(iE[s-1]); eq_v.append(-1.0)
            beq.append(0.0)
        else:
            beq.append(E_start)
    A_eq = sp.csr_matrix((eq_v, (eq_r, eq_c)), shape=(len(beq), nvar))

    Aub_r, Aub_c, Aub_v, bub = [], [], [], []
    for s in range(nh):
        r = len(bub)
        Aub_r.append(r); Aub_c.append(iA[s]); Aub_v.append(-1.0)
        Aub_r.append(r); Aub_c.append(iU[s]); Aub_v.append(-1.0)
        bub.append(-P_plan[pt[s]])
        r = len(bub)
        Aub_r.append(r); Aub_c.append(iA[s]); Aub_v.append(1.0)
        Aub_r.append(r); Aub_c.append(iW[s]); Aub_v.append(-1.0)
        bub.append(P_plan[pt[s]])
    A_ub = sp.csr_matrix((Aub_v, (Aub_r, Aub_c)), shape=(len(bub), nvar))

    lb = np.zeros(nvar); ub = np.full(nvar, np.inf)
    ub[iC] = C.E_CMAX; ub[iF] = C.E_FMAX
    lb[iE] = C.SOC_MIN; ub[iE] = C.SOC_HIGH_BOUND
    ub[iQ] = 0.0
    lb[iU] = 0; ub[iU] = np.maximum(P_plan[pt], 0.0)
    lb[iW] = 0
    bounds = list(zip(lb, ub))

    res = linprog(c, A_eq=A_eq, A_ub=A_ub, b_eq=np.array(beq), b_ub=np.array(bub),
                  bounds=bounds, method='highs')
    if not res.success:
        raise RuntimeError('滚动再计划LP失败: ' + res.message)
    x = res.x
    return dict(A=x[iA], c=x[iC], f=x[iF], Q=x[iQ], R=x[iR], E=x[iE],
                u=x[iU], w=x[iW], obj=res.fun)


def solve_adjust_scen(price, scenG, D, E_start, P_plan, t0, lam=0.0, beta=0.90,
                      emult=C.EMERG_MULT):
    """滚动再计划（情景鲁棒版）：一阶段购电 A 共用，每光伏情景独立电池调度。

    目标 = 期望电网费(违约退款+超额惩罚) + lam·CVaR_beta(情景总成本) + 期望紧急费。
    允许每情景紧急购电 Q_s（代价 emult·price），保证任意光伏情景下可行——
    这正是"随机 MPC"的鲁棒性体现。Q3 官方取 lam=0（纯期望）。
    返回 dict(A,c,f,Q,R,E,u,w,obj)；各量按情景合并为 (S,nh)（A/u/w 广播为 (S,nh)）。
    """
    T = C.T_IN_DAY
    scenG = np.asarray(scenG, float)
    S = scenG.shape[0]
    nh = T - t0
    if nh <= 0:
        z = np.zeros(0)
        return dict(A=z, c=z, f=z, Q=z, R=z, E=z, u=z, w=z, obj=0.0)
    pt = np.arange(t0, T)
    pi = 1.0 / S
    # 一阶段：A, U, W；每情景：C,F,Q,R,E
    baseA, baseU, baseW = 0, nh, 2 * nh
    scen_base = 3 * nh + np.arange(S) * (5 * nh)
    nvar = 3 * nh + S * 5 * nh
    iA = baseA + np.arange(nh)
    iU = baseU + np.arange(nh)
    iW = baseW + np.arange(nh)

    c = np.zeros(nvar)
    c[iU] = -C.DEFAULT_MULT * price[pt]
    c[iW] = C.EXCESS_MULT * price[pt]
    for s in range(S):
        sb = scen_base[s]
        c[sb + 2 * nh + np.arange(nh)] = pi * emult * price[pt]   # Q_s
    alpha_idx = z_idx = None
    if lam > 0:
        alpha_idx = nvar; z_idx = nvar + 1 + np.arange(S)
        nvar_full = nvar + 1 + S
        c = np.concatenate([c, np.zeros(S + 1)])
        c[alpha_idx] = lam; c[z_idx] = lam / ((1 - beta) * S)
    else:
        nvar_full = nvar

    eq_r, eq_c, eq_v, beq = [], [], [], []
    for s in range(S):
        sb = scen_base[s]
        iC = sb + np.arange(nh); iF = sb + nh + np.arange(nh)
        iQ = sb + 2 * nh + np.arange(nh); iR = sb + 3 * nh + np.arange(nh)
        iE = sb + 4 * nh + np.arange(nh)
        for k in range(nh):
            rr = len(beq)
            eq_r.append(rr); eq_c.append(iA[k]); eq_v.append(1.0)
            eq_r.append(rr); eq_c.append(iC[k]); eq_v.append(-1.0)
            eq_r.append(rr); eq_c.append(iF[k]); eq_v.append(C.ETA)
            eq_r.append(rr); eq_c.append(iQ[k]); eq_v.append(1.0)
            eq_r.append(rr); eq_c.append(iR[k]); eq_v.append(-1.0)
            beq.append(D[pt[k]] - scenG[s, pt[k]])
        for k in range(nh):
            rr = len(beq)
            eq_r.append(rr); eq_c.append(iE[k]); eq_v.append(1.0)
            eq_r.append(rr); eq_c.append(iC[k]); eq_v.append(-C.ETA)
            eq_r.append(rr); eq_c.append(iF[k]); eq_v.append(1.0)
            if k > 0:
                eq_r.append(rr); eq_c.append(iE[k - 1]); eq_v.append(-1.0)
                beq.append(0.0)
            else:
                beq.append(E_start)
    A_eq = sp.csr_matrix((eq_v, (eq_r, eq_c)), shape=(len(beq), nvar_full))

    Aub_r, Aub_c, Aub_v, bub = [], [], [], []
    for k in range(nh):
        r = len(bub)
        Aub_r.append(r); Aub_c.append(iA[k]); Aub_v.append(-1.0)
        Aub_r.append(r); Aub_c.append(iU[k]); Aub_v.append(-1.0)
        bub.append(-P_plan[pt[k]])
        r = len(bub)
        Aub_r.append(r); Aub_c.append(iA[k]); Aub_v.append(1.0)
        Aub_r.append(r); Aub_c.append(iW[k]); Aub_v.append(-1.0)
        bub.append(P_plan[pt[k]])
    if lam > 0:
        for s in range(S):
            r = len(bub)
            sb = scen_base[s]
            iQ = sb + 2 * nh + np.arange(nh)
            for k in range(nh):
                Aub_r.append(r); Aub_c.append(iQ[k]); Aub_v.append(emult * price[pt[k]])
            Aub_r.append(r); Aub_c.append(alpha_idx); Aub_v.append(-1.0)
            Aub_r.append(r); Aub_c.append(z_idx[s]); Aub_v.append(-1.0)
            bub.append(0.0)
    A_ub = sp.csr_matrix((Aub_v, (Aub_r, Aub_c)), shape=(len(bub), nvar_full))

    lb = np.zeros(nvar_full); ub = np.full(nvar_full, np.inf)
    for s in range(S):
        sb = scen_base[s]
        ub[sb + np.arange(nh)] = C.E_CMAX               # C_s
        ub[sb + nh + np.arange(nh)] = C.E_FMAX          # F_s
        lb[sb + 4 * nh + np.arange(nh)] = C.SOC_MIN
        ub[sb + 4 * nh + np.arange(nh)] = C.SOC_HIGH_BOUND
    ub[iU] = np.maximum(P_plan[pt], 0.0)
    if lam > 0:
        lb[alpha_idx] = -np.inf; lb[z_idx] = 0
    bounds = list(zip(lb, ub))

    res = linprog(c, A_eq=A_eq, A_ub=A_ub, b_eq=np.array(beq), b_ub=np.array(bub),
                  bounds=bounds, method='highs')
    if not res.success:
        raise RuntimeError('情景鲁棒滚动再计划LP失败: ' + res.message)
    x = res.x
    A = x[iA]; u = x[iU]; w = x[iW]
    Cm = np.zeros((S, nh)); F = np.zeros((S, nh)); Q = np.zeros((S, nh))
    R = np.zeros((S, nh)); E = np.zeros((S, nh))
    for s in range(S):
        sb = scen_base[s]
        Cm[s] = x[sb + np.arange(nh)]
        F[s] = x[sb + nh + np.arange(nh)]
        Q[s] = x[sb + 2 * nh + np.arange(nh)]
        R[s] = x[sb + 3 * nh + np.arange(nh)]
        E[s] = x[sb + 4 * nh + np.arange(nh)]
    return dict(A=A, c=Cm, f=F, Q=Q, R=R, E=E,
                u=np.tile(u, (S, 1)), w=np.tile(w, (S, 1)), obj=res.fun)


def _var_rows_scen(base_s, T):
    out = {}
    for s, base in enumerate(base_s):
        ar = base + np.arange(5 * T)
        out[s] = {'C': ar[0::5], 'F': ar[1::5], 'Q': ar[2::5],
                  'R': ar[3::5], 'E': ar[4::5]}
    return out
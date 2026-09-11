# -*- coding: utf-8 -*-
"""情景生成：非参数 bootstrap 历史残差。返回点预报与 S 个等概率情景。"""
import numpy as np
import config as C


def point_forecast(hist, K=7):
    """hist:(N,144)。前 K 天逐槽均值。"""
    n = len(hist)
    if n == 0:
        return np.zeros(C.T_IN_DAY)
    return np.mean(hist[-min(K, n):], axis=0)


def forecast_and_scenarios(load_hist, pv_hist, S=30, seed=1):
    """由历史构建点预报与 S 个情景。load_hist/pv_hist:(N,144)。
    返回 dict(point_ld,point_pv,scen_ld,scen_pv)。scen_*:(S,144)。"""
    rng = np.random.default_rng(seed)
    n = len(load_hist)
    point_ld = point_forecast(load_hist)
    point_pv = point_forecast(pv_hist)
    if n == 0:
        return dict(point_ld=point_ld, point_pv=point_pv,
                    scen_ld=np.tile(point_ld, (S, 1)),
                    scen_pv=np.tile(point_pv, (S, 1)))
    idx_ld = rng.integers(0, n, size=(S, C.T_IN_DAY))
    idx_pv = rng.integers(0, n, size=(S, C.T_IN_DAY))
    T = C.T_IN_DAY
    scen_ld = load_hist[idx_ld, np.arange(T)[None, :]]
    scen_pv = pv_hist[idx_pv, np.arange(T)[None, :]]
    return dict(point_ld=point_ld, point_pv=point_pv,
                scen_ld=np.asarray(scen_ld), scen_pv=np.asarray(scen_pv))


def pv_scenarios(point_pv, hist_pv, S=30, seed=1, sigma_scale=1.0):
    """以官方点预报 point_pv 为中心，叠加历史光伏(逐槽)变异 → 情景(kWh)。
    hist_pv:(N,144)。"""
    rng = np.random.default_rng(seed)
    T = C.T_IN_DAY
    n = len(hist_pv)
    idx = rng.integers(0, max(n, 1), size=(S, T)) if n > 0 else np.zeros((S, T), int)
    if n > 0:
        # 历史同槽相对偏差
        hist = np.maximum(hist_pv, 0.0)
        base = np.tile(point_pv, (S, 1))
        offset = hist[idx, np.arange(T)[None, :]] - point_forecast(hist_pv, n)
        scen = base + sigma_scale * offset
        scen = np.maximum(scen, 0.0)
    else:
        scen = np.tile(point_pv, (S, 1))
    return np.asarray(scen, float)


def residual_scenarios(load_hist, pv_hist, K, S=30, seed=1):
    """整日残差 bootstrap 情景生成（升级版：负荷与光伏同一天成对抽取，替代逐槽独立抽样）。

    load_hist/pv_hist: (N,144) 按日期升序的历史实际值(kWh/时段)。
    调用方必须只传入目标日 d 之前的数据（信息因果，禁止含未来）。
    K: int（负荷/光伏同一窗口）或 (K_L, K_P)（各自窗口长度）。
    点预报  = 各自最近 K 天逐槽均值；
    残差池  = 池内每一天的 (实际 − 点预报) 整条曲线（K_L=K_P 时即最近 K 天）；
    抽样    = 有放回抽 S 个整天，负荷与光伏使用同一天索引（成对，保留负荷-光伏相关性）；
    情景    = 点预报 + 整日残差；光伏情景截断到 >=0（物理非负）。
    返回 dict(point_ld, point_pv, scen_ld, scen_pv)，scen_*:(S,144)。
    """
    if isinstance(K, (tuple, list, np.ndarray)):
        KL, KP = int(K[0]), int(K[1])
    else:
        KL = KP = int(K)
    T = C.T_IN_DAY
    n = len(load_hist)
    rng = np.random.default_rng(seed)
    point_ld = point_forecast(load_hist, KL)
    point_pv = point_forecast(pv_hist, KP)
    if n == 0:
        return dict(point_ld=point_ld, point_pv=point_pv,
                    scen_ld=np.tile(point_ld, (S, 1)),
                    scen_pv=np.tile(point_pv, (S, 1)))
    # 成对抽样池：取并集窗口（最近 max(KL,KP) 天），同一池内日索引同时决定负荷与光伏残差
    w = min(n, max(KL, KP))
    resid_ld = load_hist[n - w:n] - point_ld[None, :]
    resid_pv = pv_hist[n - w:n] - point_pv[None, :]
    idx = rng.integers(0, w, size=S)          # 池内偏移（0=最早一天，w-1=最近一天）
    scen_ld = point_ld[None, :] + resid_ld[idx]
    scen_pv = point_pv[None, :] + resid_pv[idx]
    scen_pv = np.maximum(scen_pv, 0.0)
    return dict(point_ld=point_ld, point_pv=point_pv,
                scen_ld=np.asarray(scen_ld, float), scen_pv=np.asarray(scen_pv, float))
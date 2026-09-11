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
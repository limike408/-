# -*- coding: utf-8 -*-
"""数据加载：附件1-4 → (日期×144, kWh/时段) 统一 numpy。"""
import numpy as np
import pandas as pd
import os
import config as C


def _read_year_matrix(path, sheet):
    """读取 附件2/4：首列日期，余 144 列时间→返回 (dates, mat[365,144]) kW 或 元/kWh。"""
    df = pd.read_excel(path, sheet_name=sheet)
    dtcol = df.columns[0]
    df = df.set_index(dtcol)
    # 时间列排序（'0:00+1'=24:00 显式归位到末尾，防止被当 0 点排到最前导致整表环移）
    lab = [str(c) for c in df.columns]
    def mm(x):
        s = str(x)
        if '+1' in s:
            return 1440
        s = s.replace('+1', '')
        p = s.split(':')
        return int(p[0]) * 60 + int(p[1]) if len(p) >= 2 else int(p[0]) * 60
    order = np.argsort([mm(x) for x in lab])
    df = df.iloc[:, order]
    # 列序指纹断言（防静默错位复发）
    lab_sorted = [str(c) for c in df.columns]
    assert mm(lab_sorted[0]) == 10, f'{path}[{sheet}] 首列应为 00:10 时段，实际 {lab_sorted[0]}'
    assert mm(lab_sorted[-1]) == 1440, f'{path}[{sheet}] 末列应为 0:00+1(24:00)，实际 {lab_sorted[-1]}'
    dates = pd.to_datetime(df.index)
    mat = df.to_numpy(dtype=float)
    if mat.shape[1] != C.T_IN_DAY:
        raise ValueError(f'{path}[{sheet}] 列数 {mat.shape[1]} != {C.T_IN_DAY}')
    return dates, mat


def load_attach1():
    """附件1：单日 144 行。返回 dict(price,load,pv) 均为 kWh/时段。"""
    df = pd.read_excel(os.path.join(C.DATA_DIR, '附件1.xlsx'), sheet_name='Sheet1')
    def mm(x):
        s = str(x)
        if '+1' in s:
            return 1440
        s = s.replace('+1', '')
        p = s.split(':')
        return int(p[0]) * 60 + int(p[1]) if len(p) >= 2 else int(p[0]) * 60
    order = np.argsort([mm(x) for x in df['时间']])
    df = df.iloc[order]
    # 行序指纹断言（防静默错位复发）
    lab = [str(x) for x in df['时间']]
    assert mm(lab[0]) == 10, f'附件1 首行应为 00:10 时段，实际 {lab[0]}'
    assert mm(lab[-1]) == 1440, f'附件1 末行应为 0:00+1(24:00)，实际 {lab[-1]}'
    price = df['电价'].to_numpy(float)
    load = df['小区负载'].to_numpy(float) * C.DT       # kW -> kWh
    pv = df['光伏发电预测功率'].to_numpy(float) * C.DT
    return dict(price=price, load=load, pv=pv)


def load_attach2():
    """附件2：返回 (dates, load[365,144], pv[365,144]) kWh/时段。"""
    d, ld = _read_year_matrix(os.path.join(C.DATA_DIR, '附件2.xlsx'), '小区负载')
    _, pv = _read_year_matrix(os.path.join(C.DATA_DIR, '附件2.xlsx'), '光伏发电实际功率')
    if not (ld.shape[1] == C.T_IN_DAY == pv.shape[1]):
        raise ValueError(f'附件2 负载/光伏 列数应为 {C.T_IN_DAY}')
    return d, ld * C.DT, pv * C.DT


def load_attach4():
    """附件4：波动电价 元/kWh。返回 (dates, price[365,144])。"""
    d, price = _read_year_matrix(os.path.join(C.DATA_DIR, '附件4.xlsx'), 'Sheet1')
    if price.shape[1] != C.T_IN_DAY:
        raise ValueError(f'附件4 列数应为 {C.T_IN_DAY}')
    return d, price


def assert_aligned(dates_a, dates_b, name_a, name_b):
    """强制校验两份全年附件日期严格逐日一致（防模板改版导致的静默错位）。"""
    if len(dates_a) != len(dates_b) or not (dates_a == dates_b).all():
        raise RuntimeError(f'{name_a} 与 {name_b} 日期未对齐 '
                           f'({len(dates_a)} vs {len(dates_b)})')


def load_attach3():
    """附件3：光伏预报。返回 {date: {tau_hour: arr(24) kW}}，tau∈{0,6,12,18}。
    预报从 tau 起覆盖未来 24 个整点。"""
    df = pd.read_excel(os.path.join(C.DATA_DIR, '附件3.xlsx'), sheet_name='Sheet1')
    df['日期'] = df['日期'].ffill()
    df['日期'] = pd.to_datetime(df['日期'])
    out = {}
    for _, r in df.iterrows():
        d = r['日期']
        hh = int(str(r['预报时刻']).split(':')[0])
        vals = [r[f'预报{i}小时'] for i in range(1, 25)]
        out.setdefault(d, {})[hh] = np.array(vals, dtype=float)
    return out


def pv_forecast_kwh(fc3, day, tau_hour):
    """把附件3 某日某整点发布的未来24h 整点预报(kW) 映射为本日 [0,144) 十min 能量(kWh)。
    预报覆盖 [tau, tau+24)，截取到当日 24:00；次日部分减掉。
    返回 (vec144, first_t0)。"""
    arr_hour = fc3[day][tau_hour]
    vec = np.zeros(C.T_IN_DAY)
    first_t0 = (tau_hour * 60) // 10
    for i in range(24):
        hh = tau_hour + i
        t0s = first_t0 + i * 6
        if t0s >= C.T_IN_DAY:
            break
        for k in range(6):
            tt = t0s + k
            if tt >= C.T_IN_DAY:
                break
            vec[tt] = arr_hour[i] * C.DT
    return vec, first_t0
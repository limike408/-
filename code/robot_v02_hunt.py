# -*- coding: utf-8 -*-
"""
机器狗程序 v0.2 —— 交会定位 + 逼近 + 清除（问题3演练）
流程：
  1. /enter
  2. 原点(0,0)扫频道1~20，找出有信号(direction/near)的频道
  3. 对每个有信号频道：
     a. P0=(0,0) 测示向度 θ1
     b. 沿 θ1 垂直方向走 300m 到 P1，测 θ2
        （若 P1 无信号：沿 θ1 走 500m 到 P2 测 θ2'，用 P0、P2 交会）
     c. 两射线交会求估计位置 G_est
     d. 走向 G_est，途中分段重测校正；near 则立即 clear
     e. 到达 G_est 附近：measure 确认 → clear；失败则局部螺旋搜索
  4. /exit，输出汇总
"""
import json
import math
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://127.0.0.1:2026"
ROBOT_ID = "202609034004"
SPEED = 5.0          # m/s
MEASURE_T = 5        # s
SWITCH_T = 1         # s
CLEAR_OK_T = 5       # s
CLEAR_MISS_T = 3     # s
L_SIDE = 300.0       # 垂向基线长度 m
L_ALONG = 500.0      # 沿向走距离 m
STEP_WALK = 600.0    # 逼近分段步长 m

LOG_DIR = Path(r"C:\Users\NAE\Desktop\数学建模\2026\logs")
LOG_DIR.mkdir(exist_ok=True)

_pos = (0.0, 0.0)   # 机器狗当前位置（跟踪用）
_chan = 1           # 测向机当前频道
_req = 0
_log = []


def post(path, payload, retries=3):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except Exception:
                return e.code, {"accepted": False}
        except Exception as e:
            print(f"    [重试{attempt}] {path} 异常 {type(e).__name__}")
            time.sleep(0.4)
    return None, {"accepted": False}


def base():
    global _req
    _req += 1
    return {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": f"v02-{_req}"}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def move_cost(pos):
    global _pos
    t = dist(_pos, pos) / SPEED
    _pos = pos
    return t


def measure(pos, ch):
    """在 pos 检测频道 ch。返回 (measure_result, svd_deg or None)。"""
    global _chan
    switch = 0.0 if ch == _chan else SWITCH_T
    _chan = ch
    st, resp = post("/measure", {**base(), "position": {"x": pos[0], "y": pos[1]}, "channel": ch})
    _log.append(f"measure ({pos[0]:.1f},{pos[1]:.1f}) ch{ch}: {json.dumps(resp, ensure_ascii=False)}")
    if resp.get("accepted") is not True:
        return "rejected", None
    return resp.get("measure_result"), resp.get("svd_deg")


def clear(pos, ch):
    """在 pos 尝试清除频道 ch。返回 clear_result。"""
    st, resp = post("/clear", {**base(), "position": {"x": pos[0], "y": pos[1]}, "channel": ch})
    _log.append(f"clear ({pos[0]:.1f},{pos[1]:.1f}) ch{ch}: {json.dumps(resp, ensure_ascii=False)}")
    if resp.get("accepted") is not True:
        return "rejected"
    return resp.get("clear_result")


def intersect(P0, a0, P1, a1):
    """两射线 P0+t*u(a0) 与 P1+s*u(a1) 的交点。
    返回 (t, s, G) ；近似平行时返回 None。"""
    u0 = (math.cos(a0), math.sin(a0))
    u1 = (math.cos(a1), math.sin(a1))
    det = u0[0] * u1[1] - u0[1] * u1[0]   # 叉积 = -矩阵行列式
    if abs(det) < 0.03:   # 交角 < 约 1.7°，近似平行
        return None
    dx, dy = P1[0] - P0[0], P1[1] - P0[1]
    # 解 [u0x, -u1x; u0y, -u1y][t;s] = [dx;dy]
    t = (dx * u1[1] - dy * u1[0]) / det
    s = (dx * u0[1] - dy * u0[0]) / det
    G = (P0[0] + t * u0[0], P0[1] + t * u0[1])
    return t, s, G


def spiral_search(center, ch, r=20.0, n_ring=3):
    """以 center 为中心做环状 clear 搜索（米制偏移网格）。"""
    offsets = [(0, 0)]
    for k in range(1, n_ring + 1):
        step = r * 2 * k / n_ring
        for a in range(0, 360, 60):
            offsets.append((step * math.cos(math.radians(a)), step * math.sin(math.radians(a))))
    for ox, oy in offsets:
        p = (center[0] + ox, center[1] + oy)
        res = clear(p, ch)
        if res == "success":
            return True, p
    return False, None


def hunt(ch):
    """对频道 ch 的干扰源执行：交会定位 → 逼近 → 清除。返回是否清除成功。"""
    global _pos
    # --- 原点测 θ1 ---
    mr, th1 = measure((0.0, 0.0), ch)
    if mr == "near":
        ok, _ = spiral_search((0.0, 0.0), ch)
        return ok
    if mr != "direction":
        return False
    a1 = math.radians(th1)
    u1 = (math.cos(a1), math.sin(a1))

    # --- 第二检测点：垂向 300m ---
    P1 = (300 * math.cos(a1 + math.pi / 2), 300 * math.sin(a1 + math.pi / 2))
    move_cost(P1)
    mr2, th2 = measure(P1, ch)
    P2, a2 = P1, math.radians(th2) if th2 is not None else None
    if mr2 != "direction":
        # 垂向点没信号 → 沿 θ1 走 500m 再测
        P2 = (500 * u1[0], 500 * u1[1])
        move_cost(P2)
        mr2, th2 = measure(P2, ch)
        if mr2 == "near":
            return spiral_search(P2, ch)[0]
        if mr2 != "direction":
            return False
        a2 = math.radians(th2)

    sol = intersect((0.0, 0.0), a1, P2, a2)
    if sol is None:
        # 角度近似平行：沿 θ1 走向 P2 方向中点再测一次
        G = ((P2[0] + 400 * u1[0]) / 1, (P2[1] + 400 * u1[1]) / 1)  # 粗略外推
    else:
        _, _, G = sol
        if sol[0] < 0 or sol[1] < 0:
            # 交点在身后：取两射线之间角平分近似方向外推
            G = (P2[0] + 500 * math.cos((a1 + a2) / 2), P2[1] + 500 * math.sin((a1 + a2) / 2))

    # --- 分段逼近 G ---
    while True:
        d = dist(_pos, G)
        if d <= 22:   # 已在清除半径附近
            break
        step = min(d - 10, STEP_WALK)
        if step <= 0:
            break
        ang = math.atan2(G[1] - _pos[1], G[0] - _pos[0])
        way = (_pos[0] + step * math.cos(ang), _pos[1] + step * math.sin(ang))
        move_cost(way)
        mr, th = measure(way, ch)
        if mr == "near":
            return spiral_search(way, ch)[0]
        if mr == "direction":
            # 用最新示向度校正 G 的方向分量
            a_new = math.radians(th)
            # 沿新方向外推一小段更新 G 的方位（距离按原估计）
            G = (way[0] + d * math.cos(a_new) * 0.5, way[1] + d * math.sin(a_new) * 0.5)
            continue
        # no_signal：估计偏了，退回原 G
    # --- 到位：确认 + 清除 ---
    mr, th = measure(G, ch)
    if mr == "near":
        return spiral_search(G, ch)[0]
    res = clear(G, ch)
    if res == "success":
        return True
    return spiral_search(G, ch)[0]


def main():
    cleared, found = [], []
    try:
        # enter
        st, resp = post("/enter", base())
        _log.append(f"enter: {json.dumps(resp, ensure_ascii=False)}")
        if resp.get("accepted") is not True:
            print("!! /enter 失败，请确认演练测试已开始")
            return
        print(f"[enter] ok, remaining_real={resp.get('remaining_real_duration_s')}s")

        # 原点扫描
        for ch in range(1, 21):
            mr, svd = measure((0.0, 0.0), ch)
            tag = f"{mr}"
            if mr == "direction":
                tag += f" svd={svd}"
                found.append(ch)
            elif mr == "near":
                found.append(ch)
            print(f"  扫描 ch{ch:2d}: {tag}")

        print(f"\n原点发现信号频道: {found}")

        # 逐个猎杀
        for ch in found:
            print(f"\n--- 追踪频道 {ch} ---")
            ok = hunt(ch)
            print(f"频道 {ch}: {'清除成功 [OK]' if ok else '未清除 [FAIL]'}")
            if ok:
                cleared.append(ch)
    finally:
        # exit（即使异常也执行）+ 兜底写日志
        try:
            st, resp = post("/exit", base())
            _log.append(f"exit: {json.dumps(resp, ensure_ascii=False)}")
            print(f"\n[exit] 虚拟时间 {resp.get('virtual_time_s')}s")
        except Exception as e:
            print(f"\n[exit] 调用失败: {e}")
        print(f"清除 {len(cleared)}/{len(found)} 个: {cleared}")
        ts = time.strftime("%Y%m%d_%H%M%S")
        lp = LOG_DIR / f"hunt_v02_{ts}.log"
        lp.write_text("\n".join(_log), encoding="utf-8")
        print(f"日志: {lp}")


if __name__ == "__main__":
    main()

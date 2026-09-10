# -*- coding: utf-8 -*-
"""
机器狗程序 v0.6 —— 问题4：多点最小二乘定位 + 逼近清除
相比 v0.5b：
  1. 扫描阶段对全部20频道在每个检测点都测（已发现的也测），每个源收集多条观测线
  2. 猎杀用最小二乘求所有观测线的最近交点（比两线交会稳、准）
  3. 直接走向估计点逼近，省掉逐源交会测量的往返
"""
import json
import math
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://127.0.0.1:2026"
ROBOT_ID = "202609034004"
SPEED = 5.0
MEASURE_T = 5
SWITCH_T = 1
L_SIDE = 300.0
L_ALONG = 500.0
STEP_WALK = 600.0
R_IN = 1200.0
R_OUT = 2000.0

LOG_DIR = Path(r"C:\Users\NAE\Desktop\数学建模\2026\logs")
LOG_DIR.mkdir(exist_ok=True)

_pos = (0.0, 0.0)
_chan = 1
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
        except Exception:
            time.sleep(0.4)
    return None, {"accepted": False}


def base():
    global _req
    _req += 1
    return {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": f"v06-{_req}"}


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def move_cost(pos):
    global _pos
    t = dist(_pos, pos) / SPEED
    _pos = pos
    return t


def measure(pos, ch):
    global _chan
    switch = 0.0 if ch == _chan else SWITCH_T
    _chan = ch
    st, resp = post("/measure", {**base(), "position": {"x": pos[0], "y": pos[1]}, "channel": ch})
    _log.append(f"measure ({pos[0]:.1f},{pos[1]:.1f}) ch{ch}: {json.dumps(resp, ensure_ascii=False)}")
    if resp.get("accepted") is not True:
        return "rejected", None
    return resp.get("measure_result"), resp.get("svd_deg")


def clear(pos, ch):
    st, resp = post("/clear", {**base(), "position": {"x": pos[0], "y": pos[1]}, "channel": ch})
    _log.append(f"clear ({pos[0]:.1f},{pos[1]:.1f}) ch{ch}: {json.dumps(resp, ensure_ascii=False)}")
    if resp.get("accepted") is not True:
        return "rejected"
    return resp.get("clear_result")


def ls_intersect(obs):
    """最小二乘求多条观测线 P_i + t*u(θ_i) 的最近交点。
    每条线约束: (G-P_i)·u_i^⊥ = 0  =>  A G = b
    A_i = [-sinθ, cosθ], b_i = -x*sinθ + y*cosθ
    解正规方程 A^T A G = A^T b。
    返回 G 或 None（所有线近似平行）。"""
    sxx = sxy = syy = sbx = sby = 0.0
    for (x, y), th in obs:
        c, s = math.cos(th), math.sin(th)
        nx, ny = -s, c          # 法向量
        b = x * nx + y * ny
        sxx += nx * nx
        sxy += nx * ny
        syy += ny * ny
        sbx += nx * b
        sby += ny * b
    det = sxx * syy - sxy * sxy
    if abs(det) < 1e-9:
        return None
    gx = (syy * sbx - sxy * sby) / det
    gy = (sxx * sby - sxy * sbx) / det
    return (gx, gy)


def spiral_search(center, ch, r=20.0, n_ring=3, ang_step=60):
    offsets = [(0, 0)]
    for k in range(1, n_ring + 1):
        step = r * 2 * k / n_ring
        for a in range(0, 360, ang_step):
            offsets.append((step * math.cos(math.radians(a)), step * math.sin(math.radians(a))))
    for ox, oy in offsets:
        p = (center[0] + ox, center[1] + oy)
        if clear(p, ch) == "success":
            return True, p
    return False, None


def ring_probe(center, ch, r=80.0):
    for k in range(8):
        a = math.radians(k * 45)
        p = (center[0] + r * math.cos(a), center[1] + r * math.sin(a))
        move_cost(p)
        mr, th = measure(p, ch)
        if mr in ("direction", "near"):
            return p, mr, th
    return None, None, None


def approach(G, ch):
    """从当前位置走向 G，途中 measure 校正；no_signal 绕圈找信号。返回是否清除。"""
    global _pos
    while True:
        d = dist(_pos, G)
        if d <= 22:
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
            a_new = math.radians(th)
            G = (way[0] + d * math.cos(a_new) * 0.5, way[1] + d * math.sin(a_new) * 0.5)
            continue
        # no_signal
        p, mr2, th2 = ring_probe(way, ch)
        if p is None:
            return spiral_search(way, ch)[0]
        if mr2 == "near":
            return spiral_search(p, ch)[0]
        a_f = math.radians(th2)
        q = (p[0] + 30 * math.cos(a_f), p[1] + 30 * math.sin(a_f))
        move_cost(q)
        mr, _ = measure(q, ch)
        if mr == "near":
            return spiral_search(q, ch)[0]
        return spiral_search(q, ch)[0]
    mr, th = measure(G, ch)
    if mr == "near":
        return spiral_search(G, ch)[0]
    if clear(G, ch) == "success":
        return True
    return spiral_search(G, ch)[0]


def hunt_two_line(ch, P0):
    """单观测时的兜底：v0.5b 的两线交会逻辑。"""
    global _pos
    move_cost(P0)
    mr, th1 = measure(P0, ch)
    if mr == "near":
        return spiral_search(P0, ch)[0]
    if mr != "direction" or th1 is None:
        return False
    a1 = math.radians(th1)
    for side in (math.pi / 2, -math.pi / 2):
        P1 = (P0[0] + L_SIDE * math.cos(a1 + side), P0[1] + L_SIDE * math.sin(a1 + side))
        move_cost(P1)
        mr2, th2 = measure(P1, ch)
        if mr2 == "near":
            return spiral_search(P1, ch)[0]
        if mr2 == "direction" and th2 is not None:
            P2, a2 = P1, math.radians(th2)
            break
    else:
        return approach((P0[0] + 900 * math.cos(a1), P0[1] + 900 * math.sin(a1)), ch)

    sol = ls_intersect([(P0, a1), (P2, a2)])
    if sol is None:
        u2 = (math.cos(a2), math.sin(a2))
        G = (P2[0] + 600 * u2[0], P2[1] + 600 * u2[1])
    else:
        G = sol
    return approach(G, ch)


def hunt_ml(ch, obs):
    """多点最小二乘猎杀。obs = [(位置, 示向度弧度或None), ...]（near 观测 th=None）。"""
    near_pts = [P for P, th in obs if th is None]
    if near_pts:
        # 扫描时就有 near 观测：源在5m内
        return spiral_search(near_pts[0], ch)[0]
    lines = [(P, th) for P, th in obs if th is not None]
    if len(lines) >= 2:
        G = ls_intersect(lines)
        if G is not None:
            return approach(G, ch)
        # 退化：全部平行，用最后一条线外推
        P0, a0 = lines[-1]
        return approach((P0[0] + 800 * math.cos(a0), P0[1] + 800 * math.sin(a0)), ch)
    if len(lines) == 1:
        P0, _ = lines[0]
        return hunt_two_line(ch, P0)
    return False


def detect_points():
    pts = [(0.0, 0.0)]
    for k in range(6):
        a = math.radians(k * 60)
        pts.append((R_IN * math.cos(a), R_IN * math.sin(a)))
    for k in range(6):
        a = math.radians(30 + k * 60)
        pts.append((R_OUT * math.cos(a), R_OUT * math.sin(a)))
    return pts


def main():
    cleared = []
    obs_map = {}   # ch -> list of (P, th_rad or None for near)
    try:
        st, resp = None, {"accepted": False}
        for _ in range(60):
            st, resp = post("/enter", base())
            if resp.get("accepted") is True:
                break
            time.sleep(2)
        _log.append(f"enter: {json.dumps(resp, ensure_ascii=False)}")
        if resp.get("accepted") is not True:
            print("!! /enter 失败")
            return
        print(f"[enter] ok, remaining_real={resp.get('remaining_real_duration_s')}s")

        pts = detect_points()
        print(f"检测点布局: 内圈7点 + 外圈6点, 共 {len(pts)} 点")

        # ---- 阶段1: 全频道多点扫描 ----
        print("\n== 阶段1: 全频道多点扫描 ==")
        for i, P in enumerate(pts):
            move_cost(P)
            for ch in range(1, 21):
                mr, svd = measure(P, ch)
                if mr == "direction":
                    obs_map.setdefault(ch, []).append((P, math.radians(svd)))
                elif mr == "near":
                    obs_map.setdefault(ch, []).append((P, None))
            n_new = len(obs_map)
            print(f"  点{i} ({P[0]:.0f},{P[1]:.0f}) 扫描完, 累计发现 {n_new} 个频道")
        print(f"扫描完毕: 发现 {len(obs_map)} 个频道, 观测数分布: "
              f"{ {ch: len(v) for ch, v in sorted(obs_map.items())} }")

        # ---- 阶段2: 多点最小二乘猎杀（贪心） ----
        print("\n== 阶段2: 多点定位猎杀 ==")
        remain = {ch: v for ch, v in obs_map.items()}
        while remain:
            # 贪心：选「最近观测点」的源
            cur = _pos
            def key(ch):
                return min(dist(cur, P) for P, _ in remain[ch])
            nxt = min(remain, key=key)
            obs = remain.pop(nxt)
            print(f"--- 追踪 ch{nxt} ({len(obs)} 条观测) ---")
            ok = hunt_ml(nxt, obs)
            print(f"ch{nxt}: {'[OK]' if ok else '[FAIL]'}")
            if ok:
                cleared.append(nxt)

        # ---- 阶段3: 终局验证（2轮，失败源不重试） ----
        print("\n== 阶段3: 终局验证 ==")
        failed = set()
        for rnd in range(2):
            residue = {}
            for i, P in enumerate(pts):
                move_cost(P)
                for ch in range(1, 21):
                    if ch in failed:
                        continue
                    mr, svd = measure(P, ch)
                    if mr == "direction":
                        residue.setdefault(ch, []).append((P, math.radians(svd)))
                    elif mr == "near":
                        residue.setdefault(ch, []).append((P, None))
            if not residue:
                print(f"验证第{rnd+1}轮: 全部频道无信号, 任务完成")
                break
            print(f"验证第{rnd+1}轮: 残留 {sorted(residue)}")
            for ch, obs in residue.items():
                ok = hunt_ml(ch, obs)
                print(f"  补杀 ch{ch}: {'[OK]' if ok else '[FAIL]'}")
                if ok:
                    cleared.append(ch)
                else:
                    failed.add(ch)
        else:
            print("警告: 2轮验证后仍有残留（失败源不再重试）")
    finally:
        try:
            st, resp = post("/exit", base())
            _log.append(f"exit: {json.dumps(resp, ensure_ascii=False)}")
            print(f"\n[exit] 虚拟时间 {resp.get('virtual_time_s'):.1f}s")
        except Exception as e:
            print(f"\n[exit] 调用失败: {e}")
        print(f"清除 {len(set(cleared))} 个: {sorted(set(cleared))}")
        print("请对照模拟器界面显示的总数/全向数/定向数!")
        ts = time.strftime("%Y%m%d_%H%M%S")
        lp = LOG_DIR / f"full_v06_{ts}.log"
        lp.write_text("\n".join(_log), encoding="utf-8")
        print(f"日志: {lp}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
机器狗程序 v0.4 —— v0.3 + 猎杀顺序就近贪心 + 逐源耗时统计（问题3演练）
改进点：
  1. 猎杀阶段按「当前机器狗位置到发现点的距离」贪心排序，减少折返
  2. 记录每个源猎杀耗时，便于分析效率瓶颈
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
R_HEX = 1200.0

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
    return {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": f"v04-{_req}"}


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


def intersect(P0, a0, P1, a1):
    u0 = (math.cos(a0), math.sin(a0))
    u1 = (math.cos(a1), math.sin(a1))
    det = u0[0] * u1[1] - u0[1] * u1[0]
    if abs(det) < 0.03:
        return None
    dx, dy = P1[0] - P0[0], P1[1] - P0[1]
    t = (dx * u1[1] - dy * u1[0]) / det
    s = (dx * u0[1] - dy * u0[0]) / det
    G = (P0[0] + t * u0[0], P0[1] + t * u0[1])
    return t, s, G


def spiral_search(center, ch, r=20.0, n_ring=3):
    offsets = [(0, 0)]
    for k in range(1, n_ring + 1):
        step = r * 2 * k / n_ring
        for a in range(0, 360, 60):
            offsets.append((step * math.cos(math.radians(a)), step * math.sin(math.radians(a))))
    for ox, oy in offsets:
        p = (center[0] + ox, center[1] + oy)
        if clear(p, ch) == "success":
            return True, p
    return False, None


def hunt(ch, P0):
    """从发现点 P0 出发猎杀频道 ch，返回 (是否成功, 该源虚拟耗时)。"""
    global _pos
    t0_hunt = None
    move_cost(P0)
    mr, th1 = measure(P0, ch)
    if mr == "near":
        ok, _ = spiral_search(P0, ch)
        return ok
    if mr != "direction":
        return False
    a1 = math.radians(th1)
    u1 = (math.cos(a1), math.sin(a1))

    P1 = (P0[0] + L_SIDE * math.cos(a1 + math.pi / 2), P0[1] + L_SIDE * math.sin(a1 + math.pi / 2))
    move_cost(P1)
    mr2, th2 = measure(P1, ch)
    P2, a2 = P1, math.radians(th2) if th2 is not None else None
    if mr2 != "direction":
        P2 = (P0[0] + L_ALONG * u1[0], P0[1] + L_ALONG * u1[1])
        move_cost(P2)
        mr2, th2 = measure(P2, ch)
        if mr2 == "near":
            return spiral_search(P2, ch)[0]
        if mr2 != "direction":
            return False
        a2 = math.radians(th2)

    sol = intersect(P0, a1, P2, a2)
    if sol is None:
        G = (P2[0] + 400 * u1[0], P2[1] + 400 * u1[1])
    else:
        _, _, G = sol
        if sol[0] < 0 or sol[1] < 0:
            G = (P2[0] + 500 * math.cos((a1 + a2) / 2), P2[1] + 500 * math.sin((a1 + a2) / 2))

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
    mr, th = measure(G, ch)
    if mr == "near":
        return spiral_search(G, ch)[0]
    if clear(G, ch) == "success":
        return True
    return spiral_search(G, ch)[0]


def detect_points():
    pts = [(0.0, 0.0)]
    for k in range(6):
        a = math.radians(k * 60)
        pts.append((R_HEX * math.cos(a), R_HEX * math.sin(a)))
    return pts


def main():
    cleared, found = [], {}
    try:
        st, resp = None, {"accepted": False}
        for _ in range(60):
            st, resp = post("/enter", base())
            if resp.get("accepted") is True:
                break
            time.sleep(2)
        _log.append(f"enter: {json.dumps(resp, ensure_ascii=False)}")
        if resp.get("accepted") is not True:
            print("!! /enter 失败（等待2分钟后接口仍未就绪）")
            return
        print(f"[enter] ok, remaining_real={resp.get('remaining_real_duration_s')}s")

        pts = detect_points()
        print(f"检测点布局: 原点 + 六边形{R_HEX:.0f}m, 共 {len(pts)} 点")

        # ---- 阶段1: 多点扫描 ----
        print("\n== 阶段1: 多点扫描 ==")
        for i, P in enumerate(pts):
            move_cost(P)
            for ch in range(1, 21):
                if ch in found:
                    continue
                mr, svd = measure(P, ch)
                if mr == "direction":
                    found[ch] = (P, svd)
                    print(f"  点{i} ({P[0]:.0f},{P[1]:.0f}) 发现 ch{ch} svd={svd}")
                elif mr == "near":
                    found[ch] = (P, None)
                    print(f"  点{i} ({P[0]:.0f},{P[1]:.0f}) 发现 ch{ch} [near]")
        print(f"扫描完毕, 共发现 {len(found)} 个频道有信号: {sorted(found)}")

        # ---- 阶段2: 猎杀（就近贪心） ----
        print("\n== 阶段2: 贪心猎杀 ==")
        remain = dict(found)
        while remain:
            cur = _pos
            nxt = min(remain, key=lambda c: dist(cur, remain[c][0]))
            P0, _ = remain.pop(nxt)
            print(f"--- 追踪 ch{nxt} (发现点 {P0[0]:.0f},{P0[1]:.0f}, 距当前 {dist(cur, P0):.0f}m) ---")
            ok = hunt(nxt, P0)
            print(f"ch{nxt}: {'[OK]' if ok else '[FAIL]'}")
            if ok:
                cleared.append(nxt)

        # ---- 阶段3: 终局验证（最多3轮） ----
        print("\n== 阶段3: 终局验证 ==")
        for rnd in range(3):
            residue = []
            for i, P in enumerate(pts):
                move_cost(P)
                for ch in range(1, 21):
                    mr, svd = measure(P, ch)
                    if mr in ("direction", "near"):
                        residue.append((ch, P, svd))
            if not residue:
                print(f"验证第{rnd+1}轮: 全部频道无信号, 任务完成")
                break
            print(f"验证第{rnd+1}轮: 发现漏网 {len(residue)} 个: {[(c, s) for c, _, s in residue]}")
            for ch, P, _ in residue:
                ok = hunt(ch, P)
                print(f"  补杀 ch{ch}: {'[OK]' if ok else '[FAIL]'}")
                if ok:
                    cleared.append(ch)
        else:
            print("警告: 3轮验证后仍有残留信号")
    finally:
        try:
            st, resp = post("/exit", base())
            _log.append(f"exit: {json.dumps(resp, ensure_ascii=False)}")
            vt = resp.get("virtual_time_s")
            print(f"\n[exit] 虚拟时间 {vt:.1f}s")
        except Exception as e:
            vt = None
            print(f"\n[exit] 调用失败: {e}")
        print(f"清除 {len(set(cleared))} 个: {sorted(set(cleared))}")
        print("请查看模拟器演练结束界面显示的干扰源总数, 与清除数对照!")
        ts = time.strftime("%Y%m%d_%H%M%S")
        lp = LOG_DIR / f"full_v04_{ts}.log"
        lp.write_text("\n".join(_log), encoding="utf-8")
        print(f"日志: {lp}")


if __name__ == "__main__":
    main()

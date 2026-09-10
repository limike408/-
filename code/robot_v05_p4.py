# -*- coding: utf-8 -*-
"""
机器狗程序 v0.5 —— 问题4（全向+定向混合）策略
相比 v0.4 的改动：
  1. 检测点 7 -> 13：内圈(原点+六边形1200m) + 外圈(六边形2000m, 旋转30°)，外圈用于
     发现「贴着边缘朝外发射」的定向源
  2. hunt 逼近中途 no_signal（可能走进定向源背向）时：大螺旋 clear 兜底（覆盖半径100m）
  3. 终局验证扫全部13个检测点（定向源可能只对个别点可见）
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
R_IN = 1200.0    # 内圈六边形半径
R_OUT = 2000.0   # 外圈六边形半径（圆域外，允许）

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
    return {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": f"v05-{_req}"}


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


def spiral_search(center, ch, r=20.0, n_ring=3, ang_step=60):
    """环状 clear 搜索：n_ring 环、每环 ang_step 度一个点，覆盖半径 r*2*n_ring。"""
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
    """在 center 周围半径 r 的圆上8方向找信号，返回 (位置, measure_result, svd)。"""
    for k in range(8):
        a = math.radians(k * 45)
        p = (center[0] + r * math.cos(a), center[1] + r * math.sin(a))
        move_cost(p)
        mr, th = measure(p, ch)
        if mr in ("direction", "near"):
            return p, mr, th
    return None, None, None


def hunt(ch, P0):
    """从发现点 P0 出发猎杀频道 ch（定向源：垂向背对改反垂向；逼近背向绕圈找信号）。"""
    global _pos
    move_cost(P0)
    mr, th1 = measure(P0, ch)
    if mr == "near":
        return spiral_search(P0, ch)[0]
    if mr != "direction":
        return False
    if th1 is None:
        return False
    a1 = math.radians(th1)
    u1 = (math.cos(a1), math.sin(a1))

    # 第二检测点：垂向；背对则反垂向；再不行才沿向
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
        # 垂向、反垂向都背对：沿向边走边搜
        return walk_and_sweep(P0, a1, ch)

    sol = intersect(P0, a1, P2, a2)
    if sol is None:
        # 交会退化：沿 θ2 外推（θ2 是最近测的，取 P2 出发）
        u2 = (math.cos(a2), math.sin(a2))
        G = (P2[0] + 600 * u2[0], P2[1] + 600 * u2[1])
    else:
        _, _, G = sol
        if sol[0] < 0 or sol[1] < 0:
            G = (P2[0] + 500 * math.cos((a1 + a2) / 2), P2[1] + 500 * math.sin((a1 + a2) / 2))

    # 分段逼近；no_signal 就绕圈找信号方向
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
        # no_signal：绕圈找信号方向
        p, mr, th = ring_probe(way, ch)
        if p is None:
            ok, _ = spiral_search(way, ch)
            return ok
        if mr == "near":
            return spiral_search(p, ch)[0]
        # 沿找到的方向走一小段，再试
        a_f = math.radians(th)
        q = (p[0] + 30 * math.cos(a_f), p[1] + 30 * math.sin(a_f))
        move_cost(q)
        mr, _ = measure(q, ch)
        if mr == "near":
            return spiral_search(q, ch)[0]
        ok, _ = spiral_search(q, ch)
        return ok
    mr, th = measure(G, ch)
    if mr == "near":
        return spiral_search(G, ch)[0]
    if clear(G, ch) == "success":
        return True
    return spiral_search(G, ch)[0]


def walk_and_sweep(P0, a1, ch, total=1500, seg=300):
    """沿 θ1 方向分段走，每段末做小螺旋 clear 搜索（定向源兜底）。"""
    global _pos
    for k in range(1, int(total / seg) + 1):
        d = k * seg
        p = (P0[0] + d * math.cos(a1), P0[1] + d * math.sin(a1))
        move_cost(p)
        ok, _ = spiral_search(p, ch, r=20.0, n_ring=3, ang_step=60)
        if ok:
            return True
        mr, _ = measure(p, ch)
        if mr == "near":
            return spiral_search(p, ch)[0]
    return False


def detect_points():
    pts = [(0.0, 0.0)]
    for k in range(6):   # 内圈
        a = math.radians(k * 60)
        pts.append((R_IN * math.cos(a), R_IN * math.sin(a)))
    for k in range(6):   # 外圈（旋转30°）
        a = math.radians(30 + k * 60)
        pts.append((R_OUT * math.cos(a), R_OUT * math.sin(a)))
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
        print(f"检测点布局: 内圈7点 + 外圈6点, 共 {len(pts)} 点")

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

        # ---- 阶段2: 贪心猎杀 ----
        print("\n== 阶段2: 贪心猎杀 ==")
        remain = dict(found)
        while remain:
            cur = _pos
            nxt = min(remain, key=lambda c: dist(cur, remain[c][0]))
            P0, _ = remain.pop(nxt)
            print(f"--- 追踪 ch{nxt} (发现点 {P0[0]:.0f},{P0[1]:.0f}) ---")
            ok = hunt(nxt, P0)
            print(f"ch{nxt}: {'[OK]' if ok else '[FAIL]'}")
            if ok:
                cleared.append(nxt)

        # ---- 阶段3: 终局验证（最多2轮；失败源不重复补杀） ----
        print("\n== 阶段3: 终局验证 ==")
        failed = set()
        for rnd in range(2):
            residue = []
            for i, P in enumerate(pts):
                move_cost(P)
                for ch in range(1, 21):
                    if ch in failed:
                        continue
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
                    failed.add(ch)
        else:
            print("警告: 2轮验证后仍有残留信号（部分源标记为失败，不再重试）")
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
        print("请查看模拟器演练结束界面显示的干扰源总数/全向数/定向数, 对照清除数!")
        ts = time.strftime("%Y%m%d_%H%M%S")
        lp = LOG_DIR / f"full_v05_{ts}.log"
        lp.write_text("\n".join(_log), encoding="utf-8")
        print(f"日志: {lp}")


if __name__ == "__main__":
    main()

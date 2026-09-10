# -*- coding: utf-8 -*-
"""
机器狗程序 v0.1 —— 最小闭环验证 + 原点频道扫描
目标：验证 /enter -> /measure -> /exit 全流程通信，并摸清原点处各频道信号情况。
作者：AI + 教练辅导
日期：2026-09-10
"""
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://127.0.0.1:2026"
ROBOT_ID = "202609034004"

LOG_DIR = Path(r"C:\Users\NAE\Desktop\数学建模\2026\logs")
LOG_DIR.mkdir(exist_ok=True)


def post(path, payload, retries=3):
    """发送一次动作请求。网络异常时按规范复用原 payload（含 request_id）重试。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, json.loads(body)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, {"raw": body}
        except Exception as e:
            print(f"  [重试 {attempt}/{retries}] {path} 网络异常: {type(e).__name__}: {e}")
            time.sleep(0.5)
    return None, {"accepted": False, "error": "network_fail"}


def base(request_id):
    return {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": request_id}


def main():
    log_lines = []

    # 1. 进入
    st, resp = post("/enter", base("enter-1"))
    print(f"[enter] HTTP {st} -> {resp}")
    log_lines.append(f"enter: {json.dumps(resp, ensure_ascii=False)}")
    if resp.get("accepted") is not True:
        print("!! /enter 失败。可能测试未开始或窗口已关闭。请联系操作员重新开始一次演练测试。")
        return
    remaining = resp.get("remaining_real_duration_s", 0)
    print(f"本局剩余现实时间: {remaining} 秒；虚拟时间上限: {resp.get('max_virtual_duration_s')} 秒")

    # 2. 原点扫描频道 1~20
    print("\n开始原点 (0,0) 频道扫描 ...")
    scan_results = []
    for ch in range(1, 21):
        st, resp = post("/measure", {**base(f"scan-{ch}"), "position": {"x": 0, "y": 0}, "channel": ch})
        if resp.get("accepted") is not True:
            print(f"  channel {ch:2d}: accepted=false (HTTP {st}) -> {resp}")
            log_lines.append(f"measure ch{ch}: HTTP {st} {json.dumps(resp, ensure_ascii=False)}")
            continue
        mr = resp.get("measure_result")
        svd = resp.get("svd_deg")
        vt = resp.get("virtual_time_s")
        line = f"  channel {ch:2d}: {mr:10s}" + (f" svd={svd}" if mr == "direction" else "") + f"  vt={vt}s"
        print(line)
        scan_results.append((ch, mr, svd))
        log_lines.append(f"measure ch{ch}: {json.dumps(resp, ensure_ascii=False)}")

    # 3. 汇总
    n_signal = sum(1 for _, mr, _ in scan_results if mr == "direction")
    n_near = sum(1 for _, mr, _ in scan_results if mr == "near")
    n_none = sum(1 for _, mr, _ in scan_results if mr == "no_signal")
    print(f"\n汇总: 有信号 {n_signal} 个频道, near {n_near} 个, 无信号 {n_none} 个")

    # 4. 退出
    st, resp = post("/exit", base("exit-1"))
    print(f"[exit] HTTP {st} -> {resp}")
    log_lines.append(f"exit: {json.dumps(resp, ensure_ascii=False)}")

    # 5. 写日志
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"scan_v01_{ts}.log"
    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"\n日志已保存: {log_path}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""等待接口就绪并 /enter，成功后立即 /exit 释放本局（供后续正式跑）。"""
import json
import time
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:2026"
ROBOT_ID = "202609034004"


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {"accepted": False}
    except Exception as e:
        return None, {"error": str(e)}


for i in range(12):
    st, resp = post("/enter", {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": f"wait-{i}"})
    print(f"尝试{i+1}: HTTP {st} -> {resp}")
    if resp.get("accepted") is True:
        print("ENTER OK! 接口就绪。立即 exit 释放本局。")
        st2, resp2 = post("/exit", {"arena_id": "default", "robot_id": ROBOT_ID, "request_id": f"wait-exit-{i}"})
        print(f"exit -> {resp2}")
        break
    time.sleep(5)
else:
    print("等待60秒后接口仍未就绪。请检查模拟器界面状态（是否在倒计时/准备中/已开始）。")

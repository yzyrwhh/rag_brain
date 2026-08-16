"""Phase 0 端到端冒烟：health → register/login → Hello Agent 任务 → SSE 事件流。

前置：API(8000) 与 celery worker 均已启动。运行: python scripts/smoke_test.py
"""
import sys

import httpx

BASE = "http://127.0.0.1:8000/api/v1"


def main() -> None:
    with httpx.Client(timeout=30) as c:
        # 1. 健康
        r = c.get(f"{BASE}/health")
        print("health:", r.json())
        if r.json().get("status") == "degraded":
            bad = [k for k, v in r.json()["services"].items() if not v["ok"]]
            print(f"  ⚠ 未连通: {bad}（neo4j=disabled 属预期；其他需排查）")

        # 2. 注册（已存在则登录）
        r = c.post(f"{BASE}/auth/register", json={"username": "smoke", "password": "password123"})
        if r.status_code == 409:
            r = c.post(f"{BASE}/auth/login", json={"username": "smoke", "password": "password123"})
        elif r.status_code != 201:
            print(f"register failed: {r.status_code} {r.text}")
            sys.exit(1)
        token = r.json()["access_token"]
        print("auth: ok")

        # 3. 提交 Hello Agent 任务
        headers = {"Authorization": f"Bearer {token}"}
        r = c.post(f"{BASE}/tasks", headers=headers, json={"agent": "hello"})
        if r.status_code != 202:
            print(f"task submit failed: {r.status_code} {r.text}")
            sys.exit(1)
        task_id = r.json()["task_id"]
        print(f"task: {task_id} status={r.json()['status']}")

        # 4. 订阅 SSE 事件流（游标 after_seq=0）
        seen: list[str] = []
        with c.stream("GET", f"{BASE}/tasks/{task_id}/events?after_seq=0", headers=headers) as resp:
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    evt = line[len("event: "):]
                    seen.append(evt)
                    print("event:", evt)

        # 5. 校验事件序列
        expected = ["task.ready", "task.plan", "node.start", "message.delta", "task.completed"]
        ok = all(e in seen for e in expected) and seen[-1] in ("task.completed", "task.failed")
        print("PASS ✅ 事件序列完整" if ok else f"FAIL ❌ 事件序列: {seen}")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

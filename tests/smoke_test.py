"""端到端 smoke test：需要 API 和 Generation Worker 已在运行。

    python tests/smoke_test.py

覆盖：健康检查 → 图片上传 → 创建任务（结构化需求）→ LLM 对话 →
持久化异步方案生成 → 状态 / 结果 / 导出。
注意：会产生 1 次 DeepSeek 方案生成调用和 1 次对话调用。
"""

import io
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8081"
SESSION_ID = None


def post_json(path, data, *, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    headers.update(extra_headers or {})
    if SESSION_ID:
        headers["X-Session-ID"] = SESSION_ID
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def get_json(path):
    headers = {"X-Session-ID": SESSION_ID} if SESSION_ID else {}
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def upload_image():
    boundary = "----smoketest"
    payload = io.BytesIO()
    payload.write(f"--{boundary}\r\n".encode())
    payload.write(
        b'Content-Disposition: form-data; name="file"; filename="test_floorplan.png"\r\n'
        b"Content-Type: image/png\r\n\r\n"
    )
    payload.write(b"\x89PNG\r\n\x1a\nsmoke-test-image")
    payload.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        BASE + "/api/upload/image",
        data=payload.getvalue(),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Session-ID": SESSION_ID,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def wait_for_generation(task_id, *, timeout_seconds=600):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        run = get_json(f"/api/design/tasks/{task_id}/generation")
        status = run["status"]
        if status == "completed":
            return run
        if status in {
            "failed",
            "dead_letter",
            "cancelled",
            "provider_unavailable",
            "cost_limit_exceeded",
        }:
            raise RuntimeError(
                f"generation stopped: status={status}, error={run.get('error_message')}"
            )
        time.sleep(2)
    raise TimeoutError(f"generation did not finish within {timeout_seconds}s")


def main():
    global SESSION_ID

    def ok(name, cond):
        print(("PASS" if cond else "FAIL"), name)
        return bool(cond)

    passed = True
    health = get_json("/health")
    passed &= ok("health", health.get("status") == "ok")

    anonymous_session = post_json("/api/sessions", {})
    SESSION_ID = anonymous_session["session_id"]
    passed &= ok("anonymous session", bool(SESSION_ID))

    img = upload_image()
    passed &= ok("upload", "image_id" in img and img["analysis"]["findings"])

    requirement = {
        "rooms": ["客厅"],
        "area": 98,
        "budgetRange": "8-15 万",
        "familySize": 3,
        "hasPets": True,
        "styles": ["奶油风"],
    }
    task = post_json(
        "/api/design/tasks",
        {
            "session_id": SESSION_ID,
            "user_input": "smoke test",
            "requirement": requirement,
            "image_ids": [img["image_id"]],
        },
    )
    tid = task["task_id"]
    passed &= ok("create task", task["status"] == "confirmed")

    chat = post_json(
        "/api/design/chat",
        {"message": "帮我看看沙发选什么材质", "task_id": tid, "requirement": requirement},
    )
    passed &= ok("chat", len(chat.get("reply", "")) > 10)

    t0 = time.time()
    queued = post_json(
        f"/api/design/tasks/{tid}/generate-async",
        {},
        extra_headers={"Idempotency-Key": f"smoke-generation-{tid}"},
    )
    passed &= ok(
        "generation queued",
        queued["status"] in {"queued", "running", "completed"},
    )
    generation = wait_for_generation(tid)
    print(
        f"     generator={generation.get('generator')}, "
        f"attempts={generation.get('attempt_count')}, {time.time() - t0:.0f}s"
    )
    passed &= ok("generation completed", generation["status"] == "completed")

    status = get_json(f"/api/design/tasks/{tid}")
    passed &= ok("status", status["progress"] == 100)

    result = get_json(f"/api/design/tasks/{tid}/result")
    plans = result["plans"]
    passed &= ok("result: 2-3 plans", 2 <= len(plans) <= 3)
    required = ["id", "name", "style", "budget", "furnitureSuggestions", "colorPalette", "budgetBreakdown"]
    passed &= ok("result: plan schema", all(k in p for p in plans for k in required))
    passed &= ok("result: images linked", len(result["images"]) >= 1)

    export = post_json(f"/api/design/tasks/{tid}/export-pdf", {})
    passed &= ok("export-pdf", "pdf_url" in export)

    print("\n" + ("ALL PASSED" if passed else "SOME FAILED"))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

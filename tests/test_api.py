"""API 契约测试（含统一返回结构、参数校验与完整运行链路）。"""

from __future__ import annotations

import time


def test_health_and_meta(client):
    health = client.get("/api/health").json()
    assert health["code"] == 0
    assert health["data"]["status"] == "ok"

    meta = client.get("/api/meta").json()
    assert meta["code"] == 0
    assert meta["data"]["llm_mode"] == "mock"
    assert "topic_suggestions" in meta["data"]


def test_create_user_and_update_subscription(client):
    created = client.post("/api/users", json={"name": "张三", "email": "zhang@example.com"}).json()
    assert created["code"] == 0
    user_id = created["data"]["id"]
    assert created["data"]["subscription"]["max_items"] == 5

    updated = client.put(
        f"/api/users/{user_id}/subscription",
        json={
            "topics": ["AI Agent"],
            "keywords": ["MCP"],
            "exclude_keywords": ["招聘"],
            "max_items": 4,
            "channels": ["web"],
            "push_time": "09:30",
        },
    ).json()
    assert updated["code"] == 0
    assert updated["data"]["topics"] == ["AI Agent"]
    assert updated["data"]["max_items"] == 4
    assert updated["data"]["push_time"] == "09:30"


def test_duplicate_email_returns_conflict(client):
    client.post("/api/users", json={"name": "A", "email": "dup@example.com"})
    response = client.post("/api/users", json={"name": "B", "email": "dup@example.com"})
    assert response.status_code == 409
    assert response.json()["code"] == 40901


def test_invalid_subscription_returns_validation_envelope(client):
    user_id = client.post("/api/users", json={"name": "校验用户"}).json()["data"]["id"]
    response = client.put(f"/api/users/{user_id}/subscription", json={"max_items": 99})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 40001
    assert "参数校验失败" in body["message"]


def test_invalid_channel_rejected(client):
    user_id = client.post("/api/users", json={"name": "渠道用户"}).json()["data"]["id"]
    response = client.put(f"/api/users/{user_id}/subscription", json={"channels": ["telegram"]})
    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_not_found_resources(client):
    assert client.get("/api/users/9999").json()["code"] == 40401
    assert client.get("/api/briefings/9999").json()["code"] == 40401
    assert client.get("/api/runs/9999").json()["code"] == 40401
    assert client.post("/api/users/9999/run").json()["code"] == 40401


def _wait_run(client, run_id: int, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/runs/{run_id}").json()["data"]
        if data["status"] != "running":
            return data
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} 超时未结束")


def test_full_run_flow_with_mock(client):
    user_id = client.post("/api/users", json={"name": "演示", "email": "flow@example.com"}).json()["data"]["id"]
    started = client.post(f"/api/users/{user_id}/run", json={"mock": True}).json()
    assert started["code"] == 0
    run_id = started["data"]["run_id"]

    run = _wait_run(client, run_id)
    assert run["status"] == "success"
    assert run["step_count"] >= 9
    tool_names = [step["tool_name"] for step in run["steps"] if step["kind"] == "tool_call"]
    # 9 个必需/自定义工具在 mock 序列中全部被真实调用
    for expected in ["list_dir", "read_file", "search_content", "write_file", "bash", "search_news", "fetch_url"]:
        assert expected in tool_names, f"{expected} 未被调用: {tool_names}"
    # publish_briefing 之后循环立即结束
    assert tool_names[-1] == "publish_briefing"

    briefings = client.get(f"/api/users/{user_id}/briefings").json()["data"]
    assert len(briefings) == 1
    detail = client.get(f"/api/briefings/{briefings[0]['id']}").json()["data"]
    assert detail["items"]
    assert detail["content_md"].startswith("# ")
    assert detail["deliveries"][0]["channel"] == "web"
    assert detail["deliveries"][0]["status"] == "success"


def test_second_run_same_day_is_no_update(client):
    user_id = client.post("/api/users", json={"name": "去重演示"}).json()["data"]["id"]
    for _ in range(2):
        run_id = client.post(f"/api/users/{user_id}/run", json={"mock": True}).json()["data"]["run_id"]
        run = _wait_run(client, run_id)
        assert run["status"] == "success"
    briefings = client.get(f"/api/users/{user_id}/briefings").json()["data"]
    assert len(briefings) == 2
    assert "无新增" in briefings[0]["title"]
    assert briefings[0]["item_count"] == 0

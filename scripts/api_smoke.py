import json, time, urllib.request

BASE = "http://127.0.0.1:8765"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


print("health:", call("GET", "/api/health")["data"])
print("meta ok, topics:", call("GET", "/api/meta")["data"]["topic_suggestions"][:3])
users = call("GET", "/api/users")["data"]
print("users:", [(u["id"], u["name"]) for u in users])
uid = users[0]["id"]

run = call("POST", f"/api/users/{uid}/run", {"mock": True})["data"]
print("run created:", run)
run_id = run["run_id"]
for _ in range(40):
    detail = call("GET", f"/api/runs/{run_id}")["data"]
    if detail["status"] != "running":
        break
    time.sleep(0.5)
print("run status:", detail["status"], "steps:", detail["step_count"], "tools:", detail["tool_call_count"])
print("step kinds:", [(s["step_index"], s["kind"], s["tool_name"]) for s in detail["steps"]][:12])

briefings = call("GET", f"/api/users/{uid}/briefings")["data"]
print("briefings:", [(b["id"], b["title"], b["item_count"]) for b in briefings])
if briefings:
    bid = briefings[0]["id"]
    br = call("GET", f"/api/briefings/{bid}")["data"]
    print("detail title:", br["title"], "items:", len(br["items"]), "deliveries:", br["deliveries"])
    if br["items"]:
        print("first item:", br["items"][0]["title"][:40], br["items"][0]["url"])
print("ALL OK" if detail["status"] == "success" else "FAILED: " + detail.get("error", ""))

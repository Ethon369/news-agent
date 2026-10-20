# API 契约（前后端共同遵守）

- Base URL：`/api`
- 所有响应使用统一信封；`code=0` 表示成功。
- 时间：ISO8601 字符串（服务端 UTC，展示层可格式化）。
- 前端仅使用原生 `fetch`，不引入构建工具与外部 CDN。

## 0. 统一返回结构

```json
// 成功
{ "code": 0, "message": "ok", "data": { } }

// 失败
{ "code": 40401, "message": "briefing not found", "data": null }
```

| code | 含义 |
|---|---|
| 0 | 成功 |
| 40001 | 请求参数校验失败 |
| 40401 | 资源不存在 |
| 40901 | 冲突（如邮箱重复） |
| 50001 | 服务器内部错误 |
| 50301 | LLM 未配置或不可用 |

## 1. 元信息

### `GET /api/meta`

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "version": "0.1.0",
    "llm_mode": "real",              // real | mock
    "model": "deepseek-chat",
    "channels_available": ["web", "feishu"],
    "topic_suggestions": ["AI Agent", "大模型", "开源模型", "算力芯片", "AI 应用"],
    "news_sources": ["Bing News RSS", "Hacker News", "arXiv cs.AI", "TechCrunch AI", "机器之心"],
    "daily_run_time": "08:00"
  }
}
```

## 2. 用户与订阅

### `POST /api/users`

请求：`{ "name": "张三", "email": "zhang@example.com" }`（email 可空）

响应：
```json
{
  "code": 0, "message": "ok",
  "data": {
    "id": 1, "name": "张三", "email": "zhang@example.com",
    "timezone": "Asia/Shanghai", "created_at": "2026-10-20T04:00:00+00:00",
    "subscription": {
      "topics": ["AI Agent"], "keywords": ["DeepSeek"], "exclude_keywords": [],
      "max_items": 5, "language": "zh", "channels": ["web"],
      "push_time": "08:00", "enabled": true
    }
  }
}
```

### `GET /api/users`
返回 `data: [UserDetail]`（按 created_at 倒序）。

### `GET /api/users/{id}`
返回 `data: UserDetail`；不存在 → `40401`。

### `PUT /api/users/{id}/subscription`

请求体（全部可选，未传字段保持不变）：
```json
{
  "topics": ["AI Agent", "开源模型"],
  "keywords": ["LangGraph", "MCP"],
  "exclude_keywords": ["招聘", "融资"],
  "max_items": 5,
  "language": "zh",
  "channels": ["web", "feishu"],
  "push_time": "08:30",
  "enabled": true
}
```
约束：`max_items` 3–10；`push_time` 符合 `HH:MM`；`channels` 只能是 `web|feishu|email`。

响应：`data: Subscription`

## 3. 简报

### `GET /api/users/{id}/briefings?limit=20&offset=0`

```json
{
  "code": 0, "message": "ok",
  "data": [
    {
      "id": 3, "title": "AI Daily · 2026-10-20",
      "summary": "今日 5 条：……",
      "item_count": 5,
      "briefing_date": "2026-10-20",
      "created_at": "2026-10-20T00:01:00+00:00"
    }
  ]
}
```

### `GET /api/briefings/{id}`

```json
{
  "code": 0, "message": "ok",
  "data": {
    "id": 3, "title": "AI Daily · 2026-10-20", "summary": "……",
    "content_md": "## 今日焦点\n……",
    "item_count": 5, "briefing_date": "2026-10-20",
    "created_at": "2026-10-20T00:01:00+00:00",
    "items": [
      {
        "rank": 1, "title": "……", "url": "https://…",
        "source": "TechCrunch AI", "published_at": "2026-10-20T08:00:00+00:00",
        "summary": "……", "reason": "命中关键词 DeepSeek",
        "tags": ["DeepSeek"], "score": 0.92
      }
    ],
    "deliveries": [
      { "channel": "web", "status": "success", "detail": "", "created_at": "…" },
      { "channel": "feishu", "status": "skipped", "detail": "webhook 未配置" }
    ]
  }
}
```

## 4. 运行与轨迹

### `POST /api/users/{id}/run`

请求（可选）：`{ "mock": false }` —— `mock=true` 时强制用离线脚本模型跑。

响应：`data: { "run_id": 12, "status": "queued" }`（后台线程执行，立即返回）

### `GET /api/runs/{id}` —— 前端轮询此接口

```json
{
  "code": 0, "message": "ok",
  "data": {
    "id": 12, "user_id": 1,
    "status": "running",             // running | success | failed
    "trigger": "manual",             // manual | schedule
    "llm_mode": "real", "model": "deepseek-chat",
    "step_count": 4, "tool_call_count": 6,
    "prompt_tokens": 3200, "completion_tokens": 900,
    "briefing_id": null, "error": "",
    "started_at": "…", "finished_at": null,
    "steps": [
      {
        "step_index": 0, "kind": "assistant_message",
        "thought": "先看历史简报，避免重复选题", "tool_name": "",
        "tool_args": "", "tool_result": "", "duration_ms": 0,
        "created_at": "…"
      },
      {
        "step_index": 1, "kind": "tool_call",
        "thought": "", "tool_name": "list_dir",
        "tool_args": "{\"path\": \"archive\"}",
        "tool_result": "2026-10-19.md\n2026-10-18.md", "duration_ms": 3,
        "created_at": "…"
      }
    ]
  }
}
```

- 前端每 1200ms 轮询一次，`status != running` 时停止；
- 步骤按 `step_index` 升序渲染。

### `GET /api/runs?user_id=1&limit=10`
返回 `data: [RunSummary]`（不含 steps）。

## 5. 健康检查

### `GET /api/health`
`{ "code": 0, "message": "ok", "data": { "status": "ok", "version": "0.1.0" } }`

## 6. 前端交互约定

1. 首次进入：`GET /api/meta` → 顶部显示模型模式徽标（`real` 绿 / `mock` 琥珀）；`GET /api/users` → 有用户则选中第一个，否则展示新建身份表单。
2. 保存偏好：`PUT /api/users/{id}/subscription`，成功后 toast「已保存」。
3. 点击「立即生成简报」：`POST /api/users/{id}/run` → 轮询 `GET /api/runs/{id}` → 轨迹面板逐步追加步骤；成功后自动刷新历史列表并打开新简报。
4. 历史简报：点击列表项 → `GET /api/briefings/{id}` 渲染详情（Markdown → HTML，先转义再解析）。
5. 所有错误按统一信封展示 `message`。

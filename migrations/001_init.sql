-- 001_init.sql —— AI Daily Agent 初始表结构
-- 约定：JSON 数组字段以 TEXT 存储（SQLite 兼容；切 MySQL 时可用 JSON 类型）。
-- 时间统一存 UTC ISO8601（SQLite 的 DATETIME 实际为 TEXT）。

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        VARCHAR(80)  NOT NULL,
    email       VARCHAR(255) UNIQUE,
    timezone    VARCHAR(64)  NOT NULL DEFAULT 'Asia/Shanghai',
    created_at  DATETIME     NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER      NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    topics            TEXT         NOT NULL DEFAULT '[]',
    keywords          TEXT         NOT NULL DEFAULT '[]',
    exclude_keywords  TEXT         NOT NULL DEFAULT '[]',
    max_items         INTEGER      NOT NULL DEFAULT 5,
    language          VARCHAR(16)  NOT NULL DEFAULT 'zh',
    channels          TEXT         NOT NULL DEFAULT '["web"]',
    push_time         VARCHAR(5)   NOT NULL DEFAULT '08:00',
    enabled           BOOLEAN      NOT NULL DEFAULT 1,
    updated_at        DATETIME     NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status             VARCHAR(20)  NOT NULL DEFAULT 'running',
    trigger            VARCHAR(20)  NOT NULL DEFAULT 'manual',
    llm_mode           VARCHAR(20)  NOT NULL DEFAULT 'real',
    model              VARCHAR(120) NOT NULL DEFAULT '',
    step_count         INTEGER      NOT NULL DEFAULT 0,
    tool_call_count    INTEGER      NOT NULL DEFAULT 0,
    prompt_tokens      INTEGER      NOT NULL DEFAULT 0,
    completion_tokens  INTEGER      NOT NULL DEFAULT 0,
    briefing_id        INTEGER,
    error              TEXT         NOT NULL DEFAULT '',
    started_at         DATETIME     NOT NULL,
    finished_at        DATETIME
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs(user_id);

CREATE TABLE IF NOT EXISTS agent_steps (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER      NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_index   INTEGER      NOT NULL,
    kind         VARCHAR(30)  NOT NULL,
    thought      TEXT         NOT NULL DEFAULT '',
    tool_name    VARCHAR(80)  NOT NULL DEFAULT '',
    tool_args    TEXT         NOT NULL DEFAULT '',
    tool_result  TEXT         NOT NULL DEFAULT '',
    duration_ms  INTEGER,
    created_at   DATETIME     NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_agent_steps_run_id ON agent_steps(run_id);

CREATE TABLE IF NOT EXISTS briefings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    run_id         INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    title          VARCHAR(200) NOT NULL,
    summary        TEXT         NOT NULL DEFAULT '',
    content_md     TEXT         NOT NULL DEFAULT '',
    item_count     INTEGER      NOT NULL DEFAULT 0,
    briefing_date  DATE         NOT NULL,
    created_at     DATETIME     NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_briefings_user_id ON briefings(user_id);

CREATE TABLE IF NOT EXISTS briefing_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_id   INTEGER      NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    rank          INTEGER      NOT NULL DEFAULT 0,
    title         VARCHAR(300) NOT NULL,
    url           TEXT         NOT NULL,
    source        VARCHAR(120) NOT NULL DEFAULT '',
    published_at  VARCHAR(40),
    summary       TEXT         NOT NULL DEFAULT '',
    reason        TEXT         NOT NULL DEFAULT '',
    tags          TEXT         NOT NULL DEFAULT '[]',
    score         REAL
);
CREATE INDEX IF NOT EXISTS ix_briefing_items_briefing_id ON briefing_items(briefing_id);

CREATE TABLE IF NOT EXISTS deliveries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER,
    briefing_id  INTEGER      NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
    channel      VARCHAR(30)  NOT NULL,
    status       VARCHAR(20)  NOT NULL,
    detail       TEXT         NOT NULL DEFAULT '',
    created_at   DATETIME     NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_deliveries_briefing_id ON deliveries(briefing_id);
CREATE INDEX IF NOT EXISTS ix_deliveries_run_id ON deliveries(run_id);

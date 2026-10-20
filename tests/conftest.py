"""测试公共 fixture：临时数据库/工作区、TestClient、脚本化假模型。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.llm import LLMResponse, ToolCall
from app.config import Settings
from app.db import Database
from app.models import Subscription, User, utcnow
from app.schemas import dump_json_list
from app.tools.base import ToolContext


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        workspace_dir=str(tmp_path / "workspace"),
        llm_mode="mock",
        scheduler_enabled=False,
        push_channels="web",
        daily_run_time="08:00",
        app_timezone="Asia/Shanghai",
        agent_max_steps=12,
        feishu_webhook_url="",
        smtp_host="",
    )


@pytest.fixture
def database(test_settings: Settings) -> Database:
    db = Database(test_settings)
    db.migrate()
    return db


@pytest.fixture
def session(database: Database):
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user(session, test_settings: Settings) -> User:
    user = User(name="测试用户", email="tester@example.com", timezone="Asia/Shanghai")
    session.add(user)
    session.flush()
    session.add(
        Subscription(
            user_id=user.id,
            topics=dump_json_list(["AI Agent", "大模型"]),
            keywords=dump_json_list(["MCP", "RAG"]),
            exclude_keywords=dump_json_list(["招聘"]),
            max_items=5,
            language="zh",
            channels=dump_json_list(["web"]),
            push_time="08:00",
            enabled=True,
            updated_at=utcnow(),
        )
    )
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def client(test_settings: Settings):
    from app.main import create_app

    app = create_app(settings=test_settings, start_scheduler=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def tool_ctx(test_settings: Settings, tmp_path: Path) -> ToolContext:
    workspace = tmp_path / "workspace"
    for sub in ("archive", "cache", "drafts"):
        (workspace / sub).mkdir(parents=True, exist_ok=True)
    return ToolContext(
        settings=test_settings,
        workspace=workspace,
        user_id=1,
        user_name="测试用户",
        preferences={
            "topics": ["AI Agent"],
            "keywords": ["MCP"],
            "exclude_keywords": ["招聘"],
            "max_items": 5,
            "language": "zh",
            "channels": ["web"],
        },
    )


class ScriptedLLM:
    """按脚本返回响应的假模型，用来验证循环行为（不依赖真实 API）。"""

    model = "scripted-model"

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0
        self.seen_messages: list[list[dict]] = []

    def chat(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        self.calls += 1
        self.seen_messages.append(messages)
        if not self.script:
            return LLMResponse(content="（脚本结束）任务完成", tool_calls=[], model=self.model)
        item = self.script.pop(0)
        if isinstance(item, str):
            return LLMResponse(content=item, tool_calls=[], model=self.model)
        calls = []
        for index, raw in enumerate(item.get("tool_calls") or []):
            if raw.get("raw_arguments") is not None:
                # 模拟模型输出被 max_tokens 截断、JSON 不合法的情况
                calls.append(
                    ToolCall(
                        id=raw.get("id") or f"call_{self.calls}_{index}",
                        name=raw["name"],
                        arguments={},
                        raw_arguments=raw["raw_arguments"],
                        parse_error="参数解析失败: Unterminated string（模拟截断）",
                    )
                )
                continue
            calls.append(
                ToolCall(
                    id=raw.get("id") or f"call_{self.calls}_{index}",
                    name=raw["name"],
                    arguments=raw.get("arguments") or {},
                    raw_arguments=json.dumps(raw.get("arguments") or {}, ensure_ascii=False),
                )
            )
        return LLMResponse(
            content=item.get("content", ""),
            tool_calls=calls,
            model=self.model,
            prompt_tokens=10,
            completion_tokens=5,
        )


@pytest.fixture
def scripted_llm():
    return ScriptedLLM

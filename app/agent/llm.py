"""LLM 客户端：OpenAI 兼容协议实现 + 确定性的 MockLLM（离线演示/CI 用）。

只依赖 ``/chat/completions`` 这一个端点，因此 DeepSeek / OpenAI / Qwen 等
兼容服务都可通过 ``LLM_BASE_URL`` 切换（见 .env.example）。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import Settings

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
MAX_RETRIES = 3


class LLMError(Exception):
    """LLM 调用失败（已完成重试）。"""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    parse_error: str = ""


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    finish_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(Protocol):
    model: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse: ...


# ---------------------------------------------------------------------------
# 真实实现
# ---------------------------------------------------------------------------


def _completion_endpoint(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


class OpenAICompatibleLLM:
    """通过 OpenAI 兼容的 chat completions 协议调用模型。"""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.model = settings.llm_model
        self._client = client
        self.endpoint = _completion_endpoint(settings.llm_base_url)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                if self._client is not None:
                    response = self._client.post(self.endpoint, json=payload, headers=headers)
                else:
                    with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                        response = client.post(self.endpoint, json=payload, headers=headers)
                if response.status_code in RETRYABLE_STATUS:
                    last_error = LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
                    time.sleep(min(2**attempt, 8))
                    continue
                if response.status_code >= 400:
                    raise LLMError(f"HTTP {response.status_code}: {response.text[:500]}")
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(min(2**attempt, 8))
        raise LLMError(f"LLM 调用失败（已重试 {MAX_RETRIES} 次）: {last_error}")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        if not self.settings.llm_api_key:
            raise LLMError("LLM_API_KEY 未配置：请在 .env 中填写，或使用 LLM_MODE=mock 离线体验")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        data = self._post(payload)

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"LLM 返回缺少 choices: {str(data)[:300]}")
        choice = choices[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}

        tool_calls: list[ToolCall] = []
        for index, raw_call in enumerate(message.get("tool_calls") or []):
            function = raw_call.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            parse_error = ""
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                if not isinstance(args, dict):
                    raise ValueError("tool arguments 必须是 JSON 对象")
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                args = {}
                parse_error = f"参数解析失败: {exc}"
            tool_calls.append(
                ToolCall(
                    id=raw_call.get("id") or f"call_{index}",
                    name=function.get("name") or "",
                    arguments=args,
                    raw_arguments=raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False),
                    parse_error=parse_error,
                )
            )

        return LLMResponse(
            content=(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            model=data.get("model") or self.model,
            finish_reason=choice.get("finish_reason") or "",
        )


# ---------------------------------------------------------------------------
# Mock 实现（见 ADR-0004）
# ---------------------------------------------------------------------------


def _parse_news_results(text: str) -> list[dict[str, str]]:
    """从 search_news 工具结果文本里解析出候选新闻（供 MockLLM 组装简报）。"""
    items: list[dict[str, str]] = []
    pattern = re.compile(
        r"^\d+\.\s*\[(?P<source>[^\]]*)\]\s*(?P<title>.+?)\n\s*时间:\s*(?P<time>[^\n]*)\n\s*链接:\s*(?P<url>\S+)\n\s*摘要:\s*(?P<summary>[^\n]*)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        items.append(
            {
                "source": match.group("source").strip(),
                "title": match.group("title").strip(),
                "published_at": match.group("time").strip(),
                "url": match.group("url").strip(),
                "summary": match.group("summary").strip(),
            }
        )
    return items


class MockLLM:
    """确定性的脚本模型：走完整的 ReAct 循环，但每一步由固定策略决定。

    它让评审在没有 API Key 的情况下也能体验「LLM 决定工具顺序」的完整机制：
    序列仍由 ``loop.py`` 的通用循环驱动，MockLLM 只是替换了"模型"。
    """

    model = "mock-model"

    def __init__(self, max_items: int = 5) -> None:
        self.max_items = max_items
        self._collected: list[dict[str, str]] = []

    # 计划中的工具调用序列（顺序在运行中被逐步消费）
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> LLMResponse:
        executed = self._executed_steps(messages)
        tool_outputs = self._tool_outputs(messages)

        # 收集 search_news 的结果
        for text in tool_outputs:
            if "检索 '" in text:
                for item in _parse_news_results(text):
                    if all(existing["url"] != item["url"] for existing in self._collected):
                        self._collected.append(item)

        step = len(executed)

        if step == 0:
            return self._call("call_1", "list_dir", {"path": "archive"}, "先看看历史简报归档，避免今天推送重复内容。")
        if step == 1:
            return self._call(
                "call_2",
                "read_file",
                {"path": "archive/index.md", "limit": 4000},
                "读一下历史简报索引，记住已经推送过的主题与链接。",
            )
        if step == 2:
            return self._call(
                "call_3",
                "search_content",
                {"keyword": "AI", "dir": "archive"},
                "在历史归档里搜一下与今日话题相关的关键词，确认是否已经写过。",
            )
        if step == 3:
            return self._call(
                "call_4",
                "search_news",
                {"query": "AI Agent 大模型", "days": 2, "limit": 8},
                "按用户偏好检索今天的 AI 新闻。",
            )
        if step == 4:
            return self._call(
                "call_5",
                "search_news",
                {"query": "开源模型 发布", "days": 2, "limit": 8},
                "换一组关键词补充检索，避免单一 query 漏掉重要新闻。",
            )
        if step == 5 and self._collected:
            first_url = self._collected[0]["url"]
            return self._call(
                "call_6",
                "fetch_url",
                {"url": first_url, "max_chars": 2000},
                "抓一篇正文核实关键细节，摘要不能只靠标题。",
            )
        if step == 6 and self._collected:
            draft = self._draft_markdown()
            return self._call(
                "call_7",
                "write_file",
                {"path": "drafts/latest.md", "content": draft},
                "把简报草稿落到 workspace，便于复用与排查。",
            )
        if step == 7 and self._collected:
            return self._call(
                "call_8",
                "bash",
                {"command": "wc -l drafts/latest.md"},
                "用沙箱命令统计草稿行数，确认内容完整。",
            )
        if step == 8 and self._collected:
            return self._call(
                "call_9",
                "publish_briefing",
                {
                    "title": "AI Daily · 今日简报（mock 模式）",
                    "summary": "mock 模式下由脚本模型生成的演示简报。",
                    "items": self._items_payload(),
                },
                "提交最终简报。",
            )
        return LLMResponse(
            content="（mock 模式）今日简报已提交完成。",
            tool_calls=[],
            model=self.model,
            prompt_tokens=len(json.dumps(messages, ensure_ascii=False)),
            completion_tokens=64,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _call(call_id: str, name: str, args: dict[str, Any], thought: str) -> LLMResponse:
        return LLMResponse(
            content=thought,
            tool_calls=[
                ToolCall(id=call_id, name=name, arguments=args, raw_arguments=json.dumps(args, ensure_ascii=False))
            ],
            model="mock-model",
            prompt_tokens=120,
            completion_tokens=48,
        )

    @staticmethod
    def _executed_steps(messages: list[dict[str, Any]]) -> list[str]:
        return [message.get("name", "") for message in messages if message.get("role") == "tool"]

    @staticmethod
    def _tool_outputs(messages: list[dict[str, Any]]) -> list[str]:
        return [str(message.get("content") or "") for message in messages if message.get("role") == "tool"]

    def _items_payload(self) -> list[dict[str, Any]]:
        payload = []
        for item in self._collected[: self.max_items]:
            payload.append(
                {
                    "title": item["title"],
                    "url": item["url"],
                    "source": item["source"],
                    "published_at": item.get("published_at") or None,
                    "summary": item.get("summary") or "（mock 模式演示摘要）",
                    "reason": "命中用户订阅的 AI 话题",
                    "tags": ["AI", "mock"],
                }
            )
        return payload

    def _draft_markdown(self) -> str:
        lines = ["# AI Daily 草稿（mock）", ""]
        for index, item in enumerate(self._collected[: self.max_items], start=1):
            lines.append(f"{index}. [{item['title']}]({item['url']}) — {item['source']}")
        return "\n".join(lines)


def build_llm(settings: Settings, client: httpx.Client | None = None) -> LLMClient:
    if settings.llm_mode == "mock":
        return MockLLM()
    return OpenAICompatibleLLM(settings, client=client)

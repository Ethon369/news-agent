"""工具层基础设施：结果结构、上下文、异常与沙箱路径校验。

设计要点：
- 工具只返回结构化 ``ToolResult``，由注册表序列化成模型可读文本；
- 任何工具参数错误都返回 ok=False 而不是抛异常，让 LLM 能自我修正；
- 文件类工具只能访问 ``WORKSPACE_DIR`` 内的路径（见 ADR-0002）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.config import Settings

MAX_TOOL_RESULT_CHARS = 8000


class ToolError(Exception):
    """可被模型看到并自行修正的工具错误。"""

    def __init__(self, message: str, code: str = "tool_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: Any = None
    error: str = ""
    code: str = ""
    truncated: bool = False

    @classmethod
    def success(cls, content: str, data: Any = None) -> ToolResult:
        text, truncated = _truncate(content)
        return cls(ok=True, content=text, data=data, truncated=truncated)

    @classmethod
    def failure(cls, message: str, code: str = "tool_error") -> ToolResult:
        return cls(ok=False, content=f"ERROR[{code}]: {message}", error=message, code=code)

    def to_llm_text(self) -> str:
        return self.content


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = text[: limit // 2]
    tail = text[-(limit // 2 - 200) :]
    return f"{head}\n...[truncated {len(text) - limit} chars]...\n{tail}", True


@dataclass
class ToolContext:
    """一次运行内共享的工具上下文。"""

    settings: Settings
    workspace: Path
    user_id: int
    user_name: str
    preferences: dict[str, Any]
    run_id: int | None = None
    news_service: Any = None
    briefing_payload: dict[str, Any] | None = None
    committed_urls: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class ToolHandler(Protocol):
    def __call__(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# 沙箱路径解析（文件工具共用）
# ---------------------------------------------------------------------------

_FORBIDDEN_SEGMENTS = {".."}


def resolve_workspace_path(workspace: Path, raw_path: str) -> Path:
    """把模型给的路径解析为 workspace 内的绝对路径，越界即拒绝。

    规则：
    - 空路径视为 workspace 根；
    - 拒绝绝对路径与 ``..`` 段（即便最终仍在根内，也一律拒绝，减少歧义）；
    - resolve() 后必须仍在 workspace 内，防符号链接逃逸。
    """
    if raw_path is None:
        raw_path = "."
    if not isinstance(raw_path, str):
        raise ToolError("path 必须是字符串", "bad_argument")
    candidate = raw_path.strip().replace("\\", "/")
    if candidate in {"", ".", "./"}:
        candidate = "."
    path = Path(candidate)
    if path.is_absolute():
        raise ToolError(f"不允许绝对路径: {raw_path}", "absolute_path_denied")
    if any(part in _FORBIDDEN_SEGMENTS for part in path.parts):
        raise ToolError(f"不允许路径穿越: {raw_path}", "path_traversal_denied")

    workspace = workspace.resolve()
    target = (workspace / path).resolve()
    try:
        target.relative_to(workspace)
    except ValueError:
        raise ToolError(f"路径越界，只允许访问 workspace 内: {raw_path}", "out_of_workspace") from None
    return target


def relative_to_workspace(workspace: Path, target: Path) -> str:
    rel = target.resolve().relative_to(workspace.resolve())
    return "." if str(rel) == "." else rel.as_posix()

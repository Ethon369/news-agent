"""工具注册表：把 ToolSpec 暴露成 OpenAI function schema，并统一执行/兜底错误。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.tools.base import ToolContext, ToolError, ToolResult, ToolSpec


@dataclass
class ToolRegistry:
    specs: list[ToolSpec] = field(default_factory=list)
    ctx: ToolContext | None = None

    def __post_init__(self) -> None:
        self._by_name = {spec.name: spec for spec in self.specs}

    @property
    def names(self) -> list[str]:
        return list(self._by_name)

    def schemas(self) -> list[dict]:
        return [spec.as_openai_schema() for spec in self.specs]

    def execute(self, name: str, arguments: dict | None) -> ToolResult:
        if self.ctx is None:
            return ToolResult.failure("工具上下文未初始化", "no_context")
        spec = self._by_name.get(name)
        if spec is None:
            return ToolResult.failure(f"未知工具: {name}。可用工具: {', '.join(self.names)}", "unknown_tool")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return ToolResult.failure("工具参数必须是 JSON 对象", "bad_arguments")
        try:
            result = spec.handler(arguments, self.ctx)
        except ToolError as exc:
            return ToolResult.failure(exc.message, exc.code)
        except Exception as exc:  # noqa: BLE001 - 工具异常不能打死整次运行
            return ToolResult.failure(f"工具 {name} 执行异常: {type(exc).__name__}: {exc}", "tool_exception")
        if not isinstance(result, ToolResult):
            return ToolResult.failure(f"工具 {name} 返回类型错误", "bad_tool_result")
        return result

    @staticmethod
    def format_arguments(arguments: dict) -> str:
        try:
            return json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(arguments)

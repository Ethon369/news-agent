"""手写 function-calling / ReAct 循环（核心考点，见 ADR-0001）。

关键点：
- **每一轮调用哪个工具、调用几次、什么时候停，全部由 LLM 决定**；
- 框架层只做硬边界：max_steps、token 预算、结果截断、异常兜底；
- 每个事件通过 ``on_event`` 实时回调，服务层据此落库，前端可轮询看到轨迹；
- 到达步数/token 上限时仍暴露 ``publish_briefing`` 让模型有机会提交简报（强制收敛）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.agent.llm import LLMClient, LLMError
from app.agent.prompts import FORCE_FINAL_PROMPT, build_system_prompt, build_task_prompt
from app.agent.registry import ToolRegistry
from app.tools.base import ToolContext

EventCallback = Callable[["LoopEvent"], None]

DEFAULT_TOKEN_BUDGET = 150_000


@dataclass
class LoopEvent:
    kind: str  # assistant_message | tool_call | final | error
    thought: str = ""
    tool_name: str = ""
    tool_args: str = ""
    tool_result: str = ""
    duration_ms: int = 0
    # 累计 token（仅 assistant_message / final 事件携带，供前端实时展示）
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LoopResult:
    status: str  # success | failed | running
    events: list[LoopEvent] = field(default_factory=list)
    step_count: int = 0
    tool_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    briefing_payload: dict[str, Any] | None = None
    final_text: str = ""
    error: str = ""
    model: str = ""


def _assistant_message(content: str, tool_calls: list) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content or None}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.raw_arguments or "{}"},
            }
            for call in tool_calls
        ]
    return message


def run_agent(
    ctx: ToolContext,
    llm: LLMClient,
    registry: ToolRegistry,
    max_steps: int = 24,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    on_event: EventCallback | None = None,
) -> LoopResult:
    """执行一次完整的 Agent 循环。"""
    result = LoopResult(status="running", model=getattr(llm, "model", ""))
    registry.ctx = ctx
    preferences = ctx.preferences
    today = str(ctx.extra.get("today") or datetime.now(ZoneInfo(ctx.settings.app_timezone)).date().isoformat())

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                preferences,
                user_name=ctx.user_name,
                today=today,
                workspace=str(ctx.workspace),
                language=preferences.get("language", "zh"),
            ),
        },
        {
            "role": "user",
            "content": build_task_prompt(
                ctx.user_name,
                preferences,
                history_lines=ctx.extra.get("history_lines", []),
                today=today,
            ),
        },
    ]

    def emit(event: LoopEvent) -> None:
        """记录事件；持久化失败会向上抛出，由服务层把 run 标为失败（不再静默吞掉）。"""
        result.events.append(event)
        if on_event is not None:
            on_event(event)

    def execute_call(call) -> None:
        """执行一个工具调用：落轨迹 + 追加 tool 消息。"""
        result.tool_call_count += 1
        started = time.monotonic()
        if call.parse_error:
            tool_result = f"ERROR[bad_arguments]: {call.parse_error}；请修正 JSON 后重试。"
            emit(
                LoopEvent(
                    kind="tool_call",
                    tool_name=call.name,
                    tool_args=call.raw_arguments,
                    tool_result=tool_result,
                    duration_ms=0,
                )
            )
        else:
            execution = registry.execute(call.name, call.arguments)
            duration_ms = int((time.monotonic() - started) * 1000)
            tool_result = execution.to_llm_text()
            emit(
                LoopEvent(
                    kind="tool_call",
                    tool_name=call.name,
                    tool_args=registry.format_arguments(call.arguments),
                    tool_result=tool_result,
                    duration_ms=duration_ms,
                )
            )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.name,
                "content": tool_result,
            }
        )

    tools_schema = registry.schemas()
    force_final = False

    for step in range(max(1, max_steps)):
        result.step_count = step + 1
        try:
            response = llm.chat(messages, tools=tools_schema, tool_choice="auto")
        except LLMError as exc:
            result.status = "failed"
            result.error = str(exc)
            emit(LoopEvent(kind="error", thought=result.error))
            return result
        except Exception as exc:  # noqa: BLE001 - 兜底，避免后台线程静默死亡
            result.status = "failed"
            result.error = f"LLM 调用异常: {type(exc).__name__}: {exc}"
            emit(LoopEvent(kind="error", thought=result.error))
            return result

        result.prompt_tokens += response.prompt_tokens
        result.completion_tokens += response.completion_tokens
        if response.model:
            result.model = response.model

        if response.content:
            emit(
                LoopEvent(
                    kind="assistant_message",
                    thought=response.content,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
            )

        if not response.has_tool_calls:
            result.final_text = response.content
            result.status = "success" if ctx.briefing_payload else "failed"
            if not ctx.briefing_payload and not result.error:
                result.error = "模型结束运行但未调用 publish_briefing 提交简报"
            emit(LoopEvent(kind="final", thought=response.content or result.error))
            break

        messages.append(_assistant_message(response.content, response.tool_calls))
        for call in response.tool_calls:
            execute_call(call)

        if ctx.briefing_payload:
            result.briefing_payload = ctx.briefing_payload
            result.status = "success"
            result.final_text = "简报已提交"
            emit(
                LoopEvent(
                    kind="final",
                    thought="publish_briefing 成功，运行结束",
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
            )
            break

        if result.prompt_tokens > token_budget:
            emit(
                LoopEvent(
                    kind="assistant_message",
                    thought=(
                        f"[预算收紧] 累计 prompt tokens {result.prompt_tokens} 超过预算 {token_budget}，提前进入收尾"
                    ),
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                )
            )
            force_final = True
            break
    else:
        force_final = True

    if force_final and result.status == "running":
        result.briefing_payload = ctx.briefing_payload
        if ctx.briefing_payload:  # 理论上不会走到，但保持幂等
            result.status = "success"
            return result
        messages.append({"role": "user", "content": FORCE_FINAL_PROMPT})
        publish_schema = [spec.as_openai_schema() for spec in registry.specs if spec.name == "publish_briefing"]
        try:
            response = llm.chat(messages, tools=publish_schema or None)
            result.prompt_tokens += response.prompt_tokens
            result.completion_tokens += response.completion_tokens
            if response.content:
                emit(
                    LoopEvent(
                        kind="assistant_message",
                        thought=f"[强制收敛] {response.content}",
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                    )
                )
            if response.has_tool_calls:
                messages.append(_assistant_message(response.content, response.tool_calls))
                for call in response.tool_calls:
                    execute_call(call)
            result.briefing_payload = ctx.briefing_payload
            if ctx.briefing_payload:
                result.status = "success"
                result.final_text = "强制收敛阶段提交简报成功"
                emit(LoopEvent(kind="final", thought="强制收敛阶段 publish_briefing 成功，运行结束"))
            else:
                result.status = "failed"
                result.error = f"达到最大步数 {max_steps} 或 token 预算后仍未提交简报"
                emit(LoopEvent(kind="final", thought=result.error))
        except Exception as exc:  # noqa: BLE001 - 收尾失败不应抛出到线程外
            result.briefing_payload = ctx.briefing_payload
            result.status = "success" if ctx.briefing_payload else "failed"
            result.error = f"强制收敛失败: {type(exc).__name__}: {exc}"
            emit(LoopEvent(kind="error", thought=result.error))

    return result

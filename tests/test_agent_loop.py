"""Agent 循环测试：证明「工具调用顺序由 LLM 决定」且框架只做硬边界。"""

from __future__ import annotations

from app.agent.loop import run_agent
from app.agent.registry import ToolRegistry
from app.news.fixture import FixtureNewsService
from app.tools import build_default_tools


def _registry(ctx) -> ToolRegistry:
    ctx.news_service = FixtureNewsService()
    return ToolRegistry(build_default_tools(), ctx)


PUBLISH = {
    "title": "AI Daily · 测试",
    "summary": "测试简报",
    "items": [
        {
            "title": "演示新闻",
            "url": "https://example.com/demo/1",
            "source": "Demo",
            "summary": "摘要",
            "reason": "命中偏好",
        }
    ],
}


def _tool_order(result) -> list[str]:
    return [event.tool_name for event in result.events if event.kind == "tool_call"]


def test_loop_follows_model_given_order(tool_ctx, scripted_llm):
    llm = scripted_llm(
        [
            {"content": "先检索", "tool_calls": [{"name": "search_news", "arguments": {"query": "AI", "limit": 3}}]},
            {"content": "再看归档", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]},
            {"content": "提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
        ]
    )
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=8)

    assert result.status == "success"
    assert _tool_order(result) == ["search_news", "list_dir", "publish_briefing"]
    assert result.briefing_payload is not None
    assert result.briefing_payload["items"][0]["url"] == "https://example.com/demo/1"


def test_loop_order_is_not_hardcoded(tool_ctx, scripted_llm):
    """同一套代码，换一个模型给的顺序，执行顺序随之改变 —— 说明顺序来自模型。"""
    llm = scripted_llm(
        [
            {"content": "先看归档", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]},
            {"content": "再检索", "tool_calls": [{"name": "search_news", "arguments": {"query": "AI", "limit": 2}}]},
            {"content": "提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
        ]
    )
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=8)
    assert _tool_order(result) == ["list_dir", "search_news", "publish_briefing"]


def test_tool_error_is_fed_back_and_loop_continues(tool_ctx, scripted_llm):
    llm = scripted_llm(
        [
            {"content": "读一个不存在的文件", "tool_calls": [{"name": "read_file", "arguments": {"path": "nope.md"}}]},
            {"content": "改用检索", "tool_calls": [{"name": "search_news", "arguments": {"query": "AI", "limit": 2}}]},
            {"content": "提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
        ]
    )
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=8)
    assert result.status == "success"
    first_tool_event = next(event for event in result.events if event.kind == "tool_call")
    assert "ERROR" in first_tool_event.tool_result
    assert _tool_order(result) == ["read_file", "search_news", "publish_briefing"]


def test_unknown_tool_returns_error_not_crash(tool_ctx, scripted_llm):
    llm = scripted_llm(
        [
            {"content": "调用不存在的工具", "tool_calls": [{"name": "rm_rf", "arguments": {}}]},
            {"content": "提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
        ]
    )
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=6)
    assert result.status == "success"
    assert "未知工具" in result.events[1].tool_result


def test_publish_briefing_terminates_loop_immediately(tool_ctx, scripted_llm):
    llm = scripted_llm(
        [
            {"content": "直接提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
            {"content": "这一段不应该被执行", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]},
        ]
    )
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=8)
    assert result.status == "success"
    assert _tool_order(result) == ["publish_briefing"]
    assert llm.calls == 1


def test_max_steps_forces_final_answer(tool_ctx, scripted_llm):
    script = [
        {"content": f"第{i}次看目录", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]}
        for i in range(5)
    ]
    llm = scripted_llm(script)
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=2)
    assert result.status == "failed"
    assert "最大步数" in result.error
    assert llm.calls == 3  # 2 轮正常 + 1 次强制收敛


def test_forced_final_can_still_publish(tool_ctx, scripted_llm):
    """AI code review 发现的 P2：强制收敛阶段只暴露 publish_briefing，模型仍可提交。"""
    script = [
        {"content": "看目录", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]},
        {"content": "再搜一次", "tool_calls": [{"name": "search_news", "arguments": {"query": "AI", "limit": 2}}]},
        # 第 3 次调用发生在「强制收敛」阶段：模型此时只拿到 publish_briefing 的 schema
        {"content": "收尾提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
    ]
    llm = scripted_llm(script)
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=2)

    assert llm.calls == 3
    assert result.status == "success"
    assert result.briefing_payload is not None
    assert _tool_order(result)[-1] == "publish_briefing"


def test_token_budget_forces_final(tool_ctx, scripted_llm):
    class TokenHungryLLM(scripted_llm):
        def chat(self, messages, tools=None, tool_choice="auto"):
            response = super().chat(messages, tools=tools, tool_choice=tool_choice)
            response.prompt_tokens = 100_000
            return response

    script = [
        {"content": f"第{i}轮", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]}
        for i in range(4)
    ]
    llm = TokenHungryLLM(script)
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=10, token_budget=150_000)
    assert result.status in {"success", "failed"}
    # 超过预算后不再继续满步数循环（第 2 轮后触发收尾）
    assert result.step_count <= 3


def test_forced_final_retries_on_truncated_json(tool_ctx, scripted_llm):
    """真实踩坑：max_tokens 截断导致 publish_briefing 参数 JSON 不完整，收敛阶段应再给一次机会。"""
    truncated = '{"title": "AI Daily", "items": [{"title": "演示", "url": "https://example.com/demo/1"}]'
    script = [
        {"content": "看目录", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]},
        {"content": "再看一次", "tool_calls": [{"name": "list_dir", "arguments": {"path": "archive"}}]},
        {"content": "提交（被截断）", "tool_calls": [{"name": "publish_briefing", "raw_arguments": truncated}]},
        {"content": "重试提交", "tool_calls": [{"name": "publish_briefing", "arguments": PUBLISH}]},
    ]
    result = run_agent(tool_ctx, scripted_llm(script), _registry(tool_ctx), max_steps=2)
    assert result.status == "success"
    assert result.briefing_payload is not None
    assert result.briefing_payload["items"][0]["url"] == "https://example.com/demo/1"


def test_finish_without_publish_is_failure(tool_ctx, scripted_llm):
    llm = scripted_llm(["我觉得今天没什么新闻。"])
    result = run_agent(tool_ctx, llm, _registry(tool_ctx), max_steps=4)
    assert result.status == "failed"
    assert "publish_briefing" in result.error

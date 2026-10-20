"""离线演示用的固定新闻源（LLM_MODE=mock 时启用）。

为什么需要它：评审/CI 环境下没有外网或不想调用外部新闻源时，mock 模式仍要
能跑通「检索 → 筛选 → 写简报 → 推送」的完整链路。数据是演示用的占位新闻，
URL 指向 example.com，明确标注 mock，不冒充真实新闻。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.news.extractor import Article
from app.news.sources import FeedItem

_DEMO_STORIES = [
    {
        "title": "开源大模型发布新的推理优化方案，显存占用降低 40%",
        "source": "Demo · 开源模型",
        "summary": "新的推理优化方案通过算子融合与 KV Cache 压缩，在同等硬件上把长上下文推理显存占用降低约 40%。",
        "tags": ["开源模型", "推理优化"],
    },
    {
        "title": "AI Agent 框架新增 MCP 工具生态支持，多智能体协作能力增强",
        "source": "Demo · Agent",
        "summary": "主流 Agent 框架宣布兼容 MCP 协议，开发者可以把外部工具以标准协议接入多智能体工作流。",
        "tags": ["AI Agent", "MCP"],
    },
    {
        "title": "多模态模型在文档理解评测中刷新纪录",
        "source": "Demo · 多模态",
        "summary": "新版多模态模型在长文档问答与表格抽取任务上刷新公开评测纪录，官方同时开源了评测集。",
        "tags": ["多模态", "评测"],
    },
    {
        "title": "AI 编程助手加入代码审查能力，支持仓库级上下文理解",
        "source": "Demo · 开发工具",
        "summary": "AI 编程助手新增代码审查模式，可读取整个仓库上下文并对改动给出结构化评审意见。",
        "tags": ["AI 编程", "代码审查"],
    },
    {
        "title": "企业级 RAG 方案支持增量索引，检索延迟下降明显",
        "source": "Demo · RAG",
        "summary": "面向企业知识库的 RAG 方案引入增量索引与混合检索，官方基准显示检索延迟下降超过一半。",
        "tags": ["RAG", "检索"],
    },
]


class FixtureNewsService:
    """与 NewsService 同接口的离线实现：不发起网络请求。"""

    def __init__(self, days: int = 2) -> None:
        now = datetime.now(UTC)
        self._items = [
            FeedItem(
                title=story["title"],
                url=f"https://example.com/ai-daily-demo/{index + 1}",
                source=story["source"],
                published_at=(now - timedelta(hours=index * 5 + 2)).isoformat(),
                summary=story["summary"],
                query="",
                origin="fixture",
            )
            for index, story in enumerate(_DEMO_STORIES)
        ]
        self._days = days

    def search(self, query: str, days: int = 2, limit: int = 8) -> list[FeedItem]:
        tokens = [token for token in (query or "").replace("，", " ").replace(",", " ").split() if token]
        if tokens:
            matched = [
                item
                for item in self._items
                if any(token.lower() in f"{item.title} {item.summary}".lower() for token in tokens)
            ]
            if matched:
                return matched[:limit]
        return self._items[:limit]

    def fetch(self, url: str, max_chars: int = 4000) -> Article:
        for item in self._items:
            if item.url == url:
                text = (
                    f"{item.title}。\n{item.summary}\n\n"
                    "（这是 mock 模式的离线演示正文，用于验证 Agent 的抓取-摘要链路；"
                    "真实新闻请使用 LLM_MODE=real。）"
                )[:max_chars]
                return Article(url=url, title=item.title, text=text, site="Demo Fixture")
        return Article(url=url, title="", text="", ok=False, error="离线演示模式下仅支持内置演示链接")

    def close(self) -> None:  # pragma: no cover - 保持接口一致
        return None

"""新闻领域工具：search_news（检索）与 fetch_url（抓正文）。

这两个工具是题目「至少实现 5 个，签名自定」之外的自定义工具：
让 Agent 能真正去外部世界找新闻，而不是只依赖框架喂给它的上下文。
"""

from __future__ import annotations

from app.tools.base import ToolContext, ToolResult, ToolSpec, to_json

MAX_SEARCH_LIMIT = 12
MAX_FETCH_CHARS = 6000


def _fallback_news(ctx: ToolContext):
    from app.news.service import NewsService

    return NewsService(ctx.settings)


def _search_news(args: dict, ctx: ToolContext) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        return ToolResult.failure("query 不能为空", "bad_argument")
    limit = min(int(args.get("limit") or 8), MAX_SEARCH_LIMIT)
    days = int(args.get("days") or 2)

    service = ctx.news_service
    news_service = _fallback_news(ctx) if service is None else getattr(service, "inner", service)

    items = news_service.search(query, days=days, limit=limit)
    if not items:
        return ToolResult.success(
            f"检索 '{query}' 没有返回结果（可能源不可达或时间窗内无新闻）。可以换关键词或放宽 days 再试一次。"
        )

    lines = [f"检索 '{query}'（近 {days} 天，返回 {len(items)} 条）:"]
    for index, item in enumerate(items, start=1):
        published = item.published_at[:16].replace("T", " ") if item.published_at else "时间未知"
        lines.append(
            f"{index}. [{item.source or item.origin}] {item.title}\n"
            f"   时间: {published}\n"
            f"   链接: {item.url}\n"
            f"   摘要: {item.summary[:160] or '(无摘要)'}"
        )
    return ToolResult.success("\n".join(lines), data=[item.to_dict() for item in items])


def search_news_tool() -> ToolSpec:
    return ToolSpec(
        name="search_news",
        description=(
            "按关键词检索近几日新闻（Bing News RSS + 固定 RSS 源），返回标题/来源/时间/链接/摘要。"
            "可根据已看到的结果继续换关键词检索。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词，例如 'AI Agent 开源'、'DeepSeek 新模型'"},
                "days": {
                    "type": "integer",
                    "description": "时间窗（天），默认 2，最大 14",
                    "minimum": 1,
                    "maximum": 14,
                },
                "limit": {
                    "type": "integer",
                    "description": f"返回条数，默认 8，最大 {MAX_SEARCH_LIMIT}",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_LIMIT,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_search_news,
    )


def _fetch_url(args: dict, ctx: ToolContext) -> ToolResult:
    url = str(args.get("url") or "").strip()
    if not url:
        return ToolResult.failure("url 不能为空", "bad_argument")
    max_chars = min(int(args.get("max_chars") or 3000), MAX_FETCH_CHARS)

    service = ctx.news_service
    news_service = getattr(service, "inner", service) if service is not None else _fallback_news(ctx)
    article = news_service.fetch(url, max_chars=max_chars)
    if not article.ok:
        return ToolResult.failure(f"{article.error}。可改用标题+摘要写作，并在简报中标注正文不可用。", "fetch_failed")
    if not article.text.strip():
        return ToolResult.failure("正文抽取为空（可能是动态渲染页面）。建议改用摘要信息。", "empty_content")

    content = f"标题: {article.title}\n站点: {article.site or '未知'}\n链接: {article.url}\n正文:\n{article.text}"
    return ToolResult.success(content, data=article.to_dict())


def fetch_url_tool() -> ToolSpec:
    return ToolSpec(
        name="fetch_url",
        description="抓取一个网页链接并抽取正文纯文本（用于核实新闻细节、避免只凭标题写作）。",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "http(s) 链接"},
                "max_chars": {
                    "type": "integer",
                    "description": f"最多返回多少字符，默认 3000，最大 {MAX_FETCH_CHARS}",
                    "minimum": 500,
                    "maximum": MAX_FETCH_CHARS,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=_fetch_url,
    )


__all__ = ["search_news_tool", "fetch_url_tool", "to_json"]

"""工具层导出：按需构建工具清单。"""

from __future__ import annotations

from app.tools.base import ToolContext, ToolResult, ToolSpec
from app.tools.bash_tool import bash_tool
from app.tools.fs_tools import list_dir_tool, read_file_tool, search_content_tool, write_file_tool
from app.tools.news_tools import fetch_url_tool, search_news_tool
from app.tools.publish_tool import publish_briefing_tool


def build_default_tools() -> list[ToolSpec]:
    """返回本项目的全部工具（5 个必需工具 + 3 个新闻领域工具）。"""
    return [
        list_dir_tool(),
        read_file_tool(),
        search_content_tool(),
        write_file_tool(),
        bash_tool(),
        search_news_tool(),
        fetch_url_tool(),
        publish_briefing_tool(),
    ]


__all__ = [
    "ToolContext",
    "ToolResult",
    "ToolSpec",
    "build_default_tools",
]

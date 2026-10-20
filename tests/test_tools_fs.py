"""工具层测试：文件工具的沙箱边界与核心行为。"""

from __future__ import annotations

import pytest

from app.tools.fs_tools import list_dir_tool, read_file_tool, search_content_tool, write_file_tool


def _call(spec, args, ctx):
    return spec.handler(args, ctx)


def test_write_then_read_roundtrip(tool_ctx):
    write = write_file_tool()
    read = read_file_tool()

    result = _call(write, {"path": "drafts/note.md", "content": "你好 AI Daily"}, tool_ctx)
    assert result.ok
    assert (tool_ctx.workspace / "drafts" / "note.md").exists()

    result = _call(read, {"path": "drafts/note.md"}, tool_ctx)
    assert result.ok
    assert "你好 AI Daily" in result.content


def test_list_dir_lists_archive(tool_ctx):
    (tool_ctx.workspace / "archive" / "2026-10-19.md").write_text("# 昨日简报", encoding="utf-8")
    result = _call(list_dir_tool(), {"path": "archive"}, tool_ctx)
    assert result.ok
    assert "2026-10-19.md" in result.content


def test_search_content_finds_keyword_with_line_number(tool_ctx):
    (tool_ctx.workspace / "archive" / "2026-10-19.md").write_text(
        "# 昨日简报\n- DeepSeek 发布新模型\n- 其它新闻", encoding="utf-8"
    )
    result = _call(search_content_tool(), {"keyword": "deepseek", "dir": "archive"}, tool_ctx)
    assert result.ok
    assert "2026-10-19.md:2" in result.content


@pytest.mark.parametrize(
    "path",
    ["../outside.md", "../../etc/passwd", "/etc/passwd", "C:/Windows/win.ini"],
)
def test_paths_outside_workspace_are_rejected(tool_ctx, path):
    result = _call(write_file_tool(), {"path": path, "content": "x"}, tool_ctx)
    assert not result.ok
    assert result.code in {"path_traversal_denied", "absolute_path_denied", "out_of_workspace"}


@pytest.mark.parametrize(
    "path",
    [
        "C:/Windows/win.ini",
        "C:\\Windows\\win.ini",
        "D:\\secret\\x.md",
        "\\\\server\\share\\x.md",
        "//server/share/x.md",
    ],
)
def test_windows_style_absolute_paths_rejected_on_every_platform(tool_ctx, path):
    """跨平台回归：Linux 上 Path('C:/x') 是相对路径，必须显式拒绝 Windows 盘符/UNC。"""
    result = _call(write_file_tool(), {"path": path, "content": "x"}, tool_ctx)
    assert not result.ok
    assert result.code == "absolute_path_denied", f"{path} -> {result.code}"


def test_symlink_escape_is_rejected(tool_ctx, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("top secret", encoding="utf-8")
    link = tool_ctx.workspace / "link.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows 无权限时跳过
        pytest.skip("当前环境不支持创建符号链接")
    result = _call(read_file_tool(), {"path": "link.md"}, tool_ctx)
    assert not result.ok
    assert result.code == "out_of_workspace"


def test_unsupported_extension_rejected(tool_ctx):
    result = _call(write_file_tool(), {"path": "evil.exe", "content": "MZ"}, tool_ctx)
    assert not result.ok
    assert result.code == "unsupported_file_type"


def test_missing_file_returns_tool_error(tool_ctx):
    result = _call(read_file_tool(), {"path": "nope.md"}, tool_ctx)
    assert not result.ok
    assert result.code == "not_found"


def test_write_oversize_content_rejected(tool_ctx):
    result = _call(write_file_tool(), {"path": "big.md", "content": "x" * (600 * 1024)}, tool_ctx)
    assert not result.ok
    assert result.code == "content_too_large"


def test_read_respects_offset_and_limit(tool_ctx):
    path = tool_ctx.workspace / "drafts" / "long.md"
    path.write_text("0123456789" * 10, encoding="utf-8")
    result = _call(read_file_tool(), {"path": "drafts/long.md", "offset": 5, "limit": 3}, tool_ctx)
    assert result.ok
    assert "567" in result.content

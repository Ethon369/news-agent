"""必需工具集之一：沙箱化文件工具。

- list_dir(path)：列出目录内容
- read_file(path, offset, limit)：读取文件
- search_content(keyword, dir)：在目录下按关键词搜索文件内容
- write_file(path, content)：写入文件

全部限制在 workspace 根目录内，见 ``app/tools/base.py`` 的路径解析。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from app.tools.base import (
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
    relative_to_workspace,
    resolve_workspace_path,
    to_json,
)

MAX_READ_CHARS = 8000
MAX_WRITE_BYTES = 512 * 1024
MAX_LIST_ENTRIES = 200
MAX_SEARCH_FILES = 300
MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_SEARCH_HITS = 40

_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".log", ".html", ".xml", ".py", ".js"}
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules"}


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


def _fmt_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M")


def _ensure_workspace(ctx: ToolContext) -> Path:
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    return ctx.workspace


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------

_LIST_DIR_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "相对 workspace 的目录路径，默认 '.'（workspace 根）"},
    },
    "additionalProperties": False,
}


def _list_dir(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        workspace = _ensure_workspace(ctx)
        target = resolve_workspace_path(workspace, args.get("path", "."))
    except ToolError as exc:
        return ToolResult.failure(exc.message, exc.code)

    if not target.exists():
        return ToolResult.failure(f"目录不存在: {args.get('path')}", "not_found")
    if target.is_file():
        return ToolResult.failure(f"这是一个文件而不是目录: {args.get('path')}；可用 read_file 读取", "not_a_dir")

    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if child.name in _SKIP_DIRS:
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        kind = "dir" if child.is_dir() else "file"
        entries.append(
            {
                "name": child.name,
                "type": kind,
                "size": 0 if kind == "dir" else stat.st_size,
                "modified": _fmt_mtime(stat.st_mtime),
            }
        )
        if len(entries) >= MAX_LIST_ENTRIES:
            break

    rel = relative_to_workspace(workspace, target)
    if not entries:
        return ToolResult.success(f"目录 {rel} 为空。", data=[])

    lines = [f"目录 {rel} 下共 {len(entries)} 项:"]
    for item in entries:
        suffix = "/" if item["type"] == "dir" else f" ({_fmt_size(item['size'])})"
        lines.append(f"- {item['name']}{suffix}  修改于 {item['modified']}")
    return ToolResult.success("\n".join(lines), data=entries)


def list_dir_tool() -> ToolSpec:
    return ToolSpec(
        name="list_dir",
        description="列出 workspace 内某个目录的内容（文件名、类型、大小、修改时间）。用于查看历史简报归档与素材缓存。",
        parameters=_LIST_DIR_PARAMS,
        handler=_list_dir,
    )


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

_READ_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "相对 workspace 的文件路径"},
        "offset": {"type": "integer", "description": "从第几个字符开始读，默认 0", "minimum": 0},
        "limit": {
            "type": "integer",
            "description": f"最多读取多少字符（默认 {MAX_READ_CHARS}）",
            "minimum": 1,
            "maximum": MAX_READ_CHARS * 2,
        },
    },
    "required": ["path"],
    "additionalProperties": False,
}


def _read_file(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        workspace = _ensure_workspace(ctx)
        target = resolve_workspace_path(workspace, args.get("path", ""))
    except ToolError as exc:
        return ToolResult.failure(exc.message, exc.code)

    if not target.exists():
        return ToolResult.failure(f"文件不存在: {args.get('path')}", "not_found")
    if target.is_dir():
        return ToolResult.failure(f"{args.get('path')} 是目录，请用 list_dir", "is_a_dir")
    if target.suffix.lower() not in _TEXT_SUFFIXES:
        return ToolResult.failure(
            f"仅支持读取文本文件，{target.suffix or '无后缀'} 不在白名单内", "unsupported_file_type"
        )

    raw = target.read_bytes()
    if len(raw) > MAX_FILE_SIZE:
        return ToolResult.failure(f"文件过大（{_fmt_size(len(raw))}），超过 2MB 限制", "file_too_large")
    text = raw.decode("utf-8", errors="replace")

    offset = max(0, int(args.get("offset") or 0))
    limit = min(int(args.get("limit") or MAX_READ_CHARS), MAX_READ_CHARS * 2)
    chunk = text[offset : offset + limit]
    rel = relative_to_workspace(workspace, target)

    header = f"[{rel}] 共 {len(text)} 字符，读取 offset={offset} limit={limit}"
    body = chunk if chunk else "(空)"
    if offset + limit < len(text):
        body += f"\n...（还有 {len(text) - offset - limit} 字符未读，可增大 offset 继续）"
    return ToolResult.success(f"{header}\n{body}", data={"path": rel, "content": chunk, "total_chars": len(text)})


def read_file_tool() -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description="读取 workspace 内文本文件的内容，支持 offset/limit 分页。用于读取历史简报或素材缓存。",
        parameters=_READ_FILE_PARAMS,
        handler=_read_file,
    )


# ---------------------------------------------------------------------------
# search_content
# ---------------------------------------------------------------------------

_SEARCH_PARAMS = {
    "type": "object",
    "properties": {
        "keyword": {"type": "string", "description": "要搜索的关键词（不区分大小写）"},
        "dir": {"type": "string", "description": "搜索目录（相对 workspace），默认 '.'"},
        "max_hits": {"type": "integer", "description": "最多返回多少条命中", "minimum": 1, "maximum": 50},
    },
    "required": ["keyword"],
    "additionalProperties": False,
}


def _search_content(args: dict, ctx: ToolContext) -> ToolResult:
    keyword = str(args.get("keyword") or "").strip()
    if not keyword:
        return ToolResult.failure("keyword 不能为空", "bad_argument")
    try:
        workspace = _ensure_workspace(ctx)
        base = resolve_workspace_path(workspace, args.get("dir", "."))
    except ToolError as exc:
        return ToolResult.failure(exc.message, exc.code)
    if not base.exists():
        return ToolResult.failure(f"目录不存在: {args.get('dir')}", "not_found")

    max_hits = min(int(args.get("max_hits") or MAX_SEARCH_HITS), MAX_SEARCH_HITS)
    needle = keyword.lower()
    hits: list[str] = []
    scanned = 0
    workspace_root = workspace.resolve()
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for filename in files:
            if scanned >= MAX_SEARCH_FILES or len(hits) >= max_hits:
                break
            path = Path(root) / filename
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                # 先 resolve 再校验：符号链接指向 workspace 外时直接跳过（不读取、不报错泄露路径）
                resolved = path.resolve()
                try:
                    resolved.relative_to(workspace_root)
                except ValueError:
                    continue
                if path.is_symlink() and not resolved.is_file():
                    continue
                if resolved.stat().st_size > MAX_FILE_SIZE:
                    continue
                scanned += 1
                content = resolved.read_text(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue
            rel = relative_to_workspace(workspace, resolved)
            for lineno, line in enumerate(content.splitlines(), start=1):
                if needle in line.lower():
                    snippet = line.strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "…"
                    hits.append(f"{rel}:{lineno}: {snippet}")
                    if len(hits) >= max_hits:
                        break
            if len(hits) >= max_hits:
                break
        if len(hits) >= max_hits:
            break

    rel_base = relative_to_workspace(workspace, base)
    if not hits:
        return ToolResult.success(f"在 {rel_base} 下未找到关键词 '{keyword}'（扫描 {scanned} 个文件）。")
    return ToolResult.success(
        f"关键词 '{keyword}' 命中 {len(hits)} 条（扫描 {scanned} 个文件）:\n" + "\n".join(hits),
        data=hits,
    )


def search_content_tool() -> ToolSpec:
    return ToolSpec(
        name="search_content",
        description=(
            "在 workspace 目录下按关键词搜索文本文件内容，返回 文件:行号: 片段。用于判断某条新闻是否已经写过（去重）。"
        ),
        parameters=_SEARCH_PARAMS,
        handler=_search_content,
    )


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

_WRITE_FILE_PARAMS = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "相对 workspace 的文件路径（目录会自动创建）"},
        "content": {"type": "string", "description": "要写入的完整文本内容（会覆盖原文件）"},
    },
    "required": ["path", "content"],
    "additionalProperties": False,
}


def _write_file(args: dict, ctx: ToolContext) -> ToolResult:
    path_arg = str(args.get("path") or "").strip()
    content = args.get("content")
    if not path_arg:
        return ToolResult.failure("path 不能为空", "bad_argument")
    if not isinstance(content, str):
        return ToolResult.failure("content 必须是字符串", "bad_argument")
    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return ToolResult.failure(f"内容过大，超过 {MAX_WRITE_BYTES // 1024}KB 限制", "content_too_large")
    try:
        workspace = _ensure_workspace(ctx)
        target = resolve_workspace_path(workspace, path_arg)
    except ToolError as exc:
        return ToolResult.failure(exc.message, exc.code)

    if target.is_dir():
        return ToolResult.failure("目标路径是目录，不能写入", "is_a_dir")
    if target.suffix.lower() not in _TEXT_SUFFIXES:
        return ToolResult.failure("仅允许写入文本类文件（.md/.txt/.json 等）", "unsupported_file_type")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    rel = relative_to_workspace(workspace, target)
    return ToolResult.success(
        f"已写入 {rel}，共 {len(content)} 字符（{_fmt_size(target.stat().st_size)}）。",
        data={"path": rel, "chars": len(content)},
    )


def write_file_tool() -> ToolSpec:
    return ToolSpec(
        name="write_file",
        description="把文本内容写入 workspace 内的文件（覆盖写）。用于缓存素材、写简报草稿或落盘笔记。",
        parameters=_WRITE_FILE_PARAMS,
        handler=_write_file,
    )


__all__ = [
    "list_dir_tool",
    "read_file_tool",
    "search_content_tool",
    "write_file_tool",
    "to_json",
]

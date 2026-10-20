"""必需工具集之一：沙箱化 bash 工具。

**真实实现取舍**（见 ADR-0002）：
本工具不调用系统 shell（无 ``shell=True``），而是内置一小批 POSIX 风格子命令
（date/pwd/ls/cat/head/tail/wc/grep/echo）在 Python 侧实现，并额外允许少量
只读真实二进制（whoami/hostname/git 的受限子命令）。这样：

1. 任意命令注入与管道/重定向/命令替换都被协议层拒绝；
2. 跨平台可用（Windows 上没有 ``date``/``wc`` 等 POSIX 命令）；
3. 输出可控（超时 + 截断），且单测可稳定覆盖。
"""

from __future__ import annotations

import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.tools.base import (
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
    relative_to_workspace,
    resolve_workspace_path,
)

DEFAULT_TIMEOUT = 15
MAX_OUTPUT_CHARS = 4000
MAX_SCAN_LINES = 500
MAX_GREP_PATTERN_CHARS = 120

FORBIDDEN_CHARS = set("|&;><`$\n\r")
ALLOWED_REAL_BINARIES = {"whoami", "hostname"}
# git 只保留「不接触路径参数」的只读子命令；diff/show 可通过 --no-index/--output 越权，已移除
GIT_COMMAND_RULES: dict[str, set[str]] = {
    "status": {"--short"},
    "log": {"--oneline", "-n"},
    "rev-parse": {"HEAD", "--short"},
}
ALLOWED_GIT_SUBCOMMANDS = set(GIT_COMMAND_RULES)

_HELP = (
    "允许的命令：date | pwd | echo <text> | ls [path] | cat <file> | head -n <N> <file> | "
    "tail -n <N> <file> | wc [-l|-c|-w] <file> | grep [-i] <pattern> <file> | "
    "whoami | hostname | git status --short | git log --oneline -n <N> | git rev-parse [--short] HEAD"
)

_PARAMS = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": f"要执行的命令（沙箱白名单）。{_HELP}"},
        "timeout": {
            "type": "integer",
            "description": f"超时秒数（默认 {DEFAULT_TIMEOUT}，最大 30）",
            "minimum": 1,
            "maximum": 30,
        },
    },
    "required": ["command"],
    "additionalProperties": False,
}


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n...[output truncated, {len(text) - MAX_OUTPUT_CHARS} chars omitted]"


def _workspace_path(ctx: ToolContext, raw: str) -> Path:
    return resolve_workspace_path(ctx.workspace, raw)


def _builtin_date(ctx: ToolContext) -> str:
    tz = ZoneInfo(ctx.settings.app_timezone)
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def _builtin_ls(ctx: ToolContext, args: list[str]) -> str:
    target = _workspace_path(ctx, args[0] if args else ".")
    if not target.exists():
        raise ToolError(f"路径不存在: {args[0] if args else '.'}", "not_found")
    if target.is_file():
        return target.name
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    lines = []
    for entry in entries[:MAX_SCAN_LINES]:
        lines.append(f"{entry.name}/" if entry.is_dir() else entry.name)
    if len(entries) > MAX_SCAN_LINES:
        lines.append(f"...（共 {len(entries)} 项，已截断）")
    return "\n".join(lines) if lines else "(空目录)"


def _read_text(ctx: ToolContext, raw_path: str, limit_chars: int = 60_000) -> str:
    target = _workspace_path(ctx, raw_path)
    if not target.exists():
        raise ToolError(f"文件不存在: {raw_path}", "not_found")
    if target.is_dir():
        raise ToolError(f"{raw_path} 是目录，不是文件", "is_a_dir")
    if target.stat().st_size > 2 * 1024 * 1024:
        raise ToolError("文件过大（>2MB），拒绝读取", "file_too_large")
    return target.read_text(encoding="utf-8", errors="replace")[:limit_chars]


def _builtin_head_tail(ctx: ToolContext, args: list[str], tail: bool) -> str:
    count = 10
    rest = list(args)
    if len(rest) >= 2 and rest[0] == "-n":
        count = int(rest[1])
        rest = rest[2:]
    elif rest and re.fullmatch(r"-\d+", rest[0]):
        count = int(rest[0][1:])
        rest = rest[1:]
    if count <= 0 or count > 500:
        raise ToolError("行数需在 1-500 之间", "bad_argument")
    if not rest:
        raise ToolError("缺少文件参数", "bad_argument")
    lines = _read_text(ctx, rest[0]).splitlines()
    selected = lines[-count:] if tail else lines[:count]
    return "\n".join(selected)


def _builtin_wc(ctx: ToolContext, args: list[str]) -> str:
    mode = "-l"
    rest = list(args)
    if rest and rest[0] in {"-l", "-w", "-c"}:
        mode = rest[0]
        rest = rest[1:]
    if not rest:
        raise ToolError("缺少文件参数", "bad_argument")
    text = _read_text(ctx, rest[0])
    value = {"-l": len(text.splitlines()), "-w": len(text.split()), "-c": len(text)}[mode]
    return f"{value} {rest[0]}"


def _builtin_grep(ctx: ToolContext, args: list[str]) -> str:
    ignore_case = False
    rest = list(args)
    if rest and rest[0] == "-i":
        ignore_case = True
        rest = rest[1:]
    if len(rest) < 2:
        raise ToolError("用法: grep [-i] <pattern> <file>", "bad_argument")
    pattern, file_path = rest[0], rest[1]
    if len(pattern) > MAX_GREP_PATTERN_CHARS:
        raise ToolError(f"正则表达式过长（>{MAX_GREP_PATTERN_CHARS} 字符）", "bad_argument")
    # 拒绝嵌套量词（如 (a+)+），避免灾难性回溯把工具线程卡死
    if re.search(r"\([^()]*[+*][^()]*\)[+*{]", pattern):
        raise ToolError("不允许嵌套量词的正则表达式（可能导致灾难性回溯）", "bad_argument")
    text = _read_text(ctx, file_path)
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        raise ToolError(f"无效的正则表达式: {exc}", "bad_argument") from None
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if len(line) > 20_000:  # 超长单行跳过，避免正则回溯放大
            continue
        if regex.search(line):
            hits.append(f"{lineno}:{line}")
            if len(hits) >= 200:
                hits.append("...（命中过多，已截断）")
                break
    return "\n".join(hits) if hits else "(无命中)"


def _run_real(ctx: ToolContext, argv: list[str], timeout: int) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - argv 已白名单校验，且 shell=False
            argv,
            cwd=str(ctx.workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except FileNotFoundError:
        raise ToolError(f"命令不可用: {argv[0]}", "command_unavailable") from None
    except subprocess.TimeoutExpired:
        raise ToolError(f"命令超时（>{timeout}s）: {' '.join(argv)}", "timeout") from None
    output = proc.stdout.strip()
    if proc.returncode != 0 and proc.stderr.strip():
        output = f"{output}\n[stderr]\n{proc.stderr.strip()}".strip()
    return output or "(无输出)"


def _validate_git(argv: list[str]) -> None:
    """严格按子命令做 token 级白名单，避免任何路径/输出参数绕过 workspace 沙箱。

    （AI code review 发现：`git diff --no-index <file>` 可读 workspace 外文件，
    `git diff --output=<path>` 可写 workspace 外文件。这里彻底移除了接触路径的
    diff/show，并对剩余子命令做逐 token 校验。）
    """
    if len(argv) < 2 or argv[1] not in GIT_COMMAND_RULES:
        raise ToolError(
            "git 仅允许 git status --short | git log --oneline -n <N> | git rev-parse [--short] HEAD",
            "command_denied",
        )
    subcommand = argv[1]
    allowed = GIT_COMMAND_RULES[subcommand]
    rest = argv[2:]
    for token in rest:
        if token in allowed:
            continue
        if subcommand == "log" and re.fullmatch(r"\d{1,3}", token):
            continue  # -n 的行数参数
        raise ToolError(f"git {subcommand} 不允许参数: {token!r}", "command_denied")
    if subcommand == "status" and rest not in ([], ["--short"]):
        raise ToolError("git status 仅允许 --short", "command_denied")
    if subcommand == "log":
        has_n = "-n" in rest
        has_number = any(re.fullmatch(r"\d{1,3}", token) for token in rest)
        if has_n != has_number or ("--oneline" not in rest and has_n):
            raise ToolError("git log 仅允许 --oneline -n <N>", "command_denied")
    if subcommand == "rev-parse" and rest and rest[-1] != "HEAD":
        raise ToolError("git rev-parse 仅允许 [--short] HEAD", "command_denied")


def run_bash(command: str, ctx: ToolContext, timeout: int = DEFAULT_TIMEOUT) -> str:
    if not command or not command.strip():
        raise ToolError("command 不能为空", "bad_argument")
    forbidden = [ch for ch in command if ch in FORBIDDEN_CHARS]
    if forbidden:
        raise ToolError(
            f"命令包含被禁止的 shell 组合符: {''.join(sorted(set(forbidden)))}（不支持管道/重定向/命令替换）",
            "shell_operator_denied",
        )
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ToolError(f"命令解析失败: {exc}", "bad_argument") from None
    if not argv:
        raise ToolError("command 不能为空", "bad_argument")

    name = argv[0].lower()
    args = argv[1:]

    if name == "date":
        return _builtin_date(ctx)
    if name == "pwd":
        return str(ctx.workspace)
    if name == "echo":
        return " ".join(args)
    if name == "ls":
        return _builtin_ls(ctx, args)
    if name == "cat":
        if not args:
            raise ToolError("缺少文件参数", "bad_argument")
        return _read_text(ctx, args[0])
    if name == "head":
        return _builtin_head_tail(ctx, args, tail=False)
    if name == "tail":
        return _builtin_head_tail(ctx, args, tail=True)
    if name == "wc":
        return _builtin_wc(ctx, args)
    if name == "grep":
        return _builtin_grep(ctx, args)
    if name in ALLOWED_REAL_BINARIES:
        if args:
            raise ToolError(f"{name} 不接受参数", "command_denied")
        return _run_real(ctx, [name], timeout)
    if name == "git":
        _validate_git(argv)
        return _run_real(ctx, argv, timeout)

    raise ToolError(f"命令不在白名单内: {name}。{_HELP}", "command_denied")


def _bash_handler(args: dict, ctx: ToolContext) -> ToolResult:
    command = args.get("command")
    if not isinstance(command, str):
        return ToolResult.failure("command 必须是字符串", "bad_argument")
    timeout = min(int(args.get("timeout") or DEFAULT_TIMEOUT), 30)
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    try:
        output = run_bash(command, ctx, timeout=timeout)
    except ToolError as exc:
        return ToolResult.failure(exc.message, exc.code)
    except Exception as exc:  # noqa: BLE001 - 工具层兜底，避免拖垮 Agent 循环
        return ToolResult.failure(f"命令执行异常: {exc}", "execution_error")
    return ToolResult.success(_clip(f"$ {command}\n{output}"))


def bash_tool() -> ToolSpec:
    return ToolSpec(
        name="bash",
        description=(f"在 workspace 沙箱内执行受限命令（不做真实 shell 解析，白名单 + 超时 + 输出截断）。{_HELP}"),
        parameters=_PARAMS,
        handler=_bash_handler,
    )


def _relative(ctx: ToolContext, path: Path) -> str:  # pragma: no cover - 预留调试用
    return relative_to_workspace(ctx.workspace, path)

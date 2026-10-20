"""工具层测试：bash 沙箱的白名单与注入防护。"""

from __future__ import annotations

import pytest

from app.tools.bash_tool import bash_tool


def _run(command: str, ctx):
    return bash_tool().handler({"command": command}, ctx)


def test_date_command(tool_ctx):
    result = _run("date", tool_ctx)
    assert result.ok
    assert "-" in result.content


def test_wc_and_cat(tool_ctx):
    (tool_ctx.workspace / "archive" / "a.md").write_text("第一行\n第二行\n", encoding="utf-8")
    result = _run("wc -l archive/a.md", tool_ctx)
    assert result.ok and "2 archive/a.md" in result.content

    result = _run("cat archive/a.md", tool_ctx)
    assert result.ok and "第一行" in result.content


def test_head_and_tail(tool_ctx):
    (tool_ctx.workspace / "archive" / "b.md").write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
    head = _run("head -n 2 archive/b.md", tool_ctx)
    assert head.ok and "line0" in head.content and "line2" not in head.content
    tail = _run("tail -n 2 archive/b.md", tool_ctx)
    assert tail.ok and "line9" in tail.content and "line7" not in tail.content


def test_grep_and_ls(tool_ctx):
    (tool_ctx.workspace / "archive" / "c.md").write_text("DeepSeek 新闻\n其它\n", encoding="utf-8")
    grep = _run("grep DeepSeek archive/c.md", tool_ctx)
    assert grep.ok and "DeepSeek" in grep.content
    ls = _run("ls archive", tool_ctx)
    assert ls.ok and "c.md" in ls.content


@pytest.mark.parametrize("command", ["rm -rf /", "curl http://x", "powershell Get-Process", "python -c 1", "node -v"])
def test_dangerous_commands_are_denied(tool_ctx, command):
    result = _run(command, tool_ctx)
    assert not result.ok
    assert result.code == "command_denied"


@pytest.mark.parametrize("command", ["cat a.md | head", "ls; rm x", "cat $(whoami)", "echo `id`", "ls > out.txt"])
def test_shell_operators_are_denied(tool_ctx, command):
    result = _run(command, tool_ctx)
    assert not result.ok
    assert result.code == "shell_operator_denied"


def test_absolute_path_in_builtin_is_denied(tool_ctx):
    result = _run("cat /etc/passwd", tool_ctx)
    assert not result.ok
    assert result.code in {"absolute_path_denied", "out_of_workspace"}


def test_git_disallowed_subcommand(tool_ctx):
    result = _run("git push origin main", tool_ctx)
    assert not result.ok
    assert result.code == "command_denied"

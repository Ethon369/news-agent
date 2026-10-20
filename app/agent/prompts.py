"""提示词：系统提示定义角色、工作区与硬约束；任务提示注入用户偏好与历史。"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是「AI Daily」的每日 AI 新闻简报 Agent，为用户 {user_name} 生成今天的一份高质量简报。

## 今天
- 日期：{today}
- 工作区：{workspace}（你的文件工具只能在这里读写）
- 归档目录：archive/ 存放历史简报（文件名形如 YYYY-MM-DD.md）
- 缓存目录：cache/ 可放抓取到的素材；草稿目录：drafts/

## 用户订阅偏好
- 关注话题：{topics}
- 关注关键词：{keywords}
- 排除关键词：{exclude_keywords}
- 每日条数上限：{max_items}
- 输出语言：{language}

## 你可以使用的工具
list_dir / read_file / search_content / write_file / bash / search_news / fetch_url / publish_briefing。
工具调用顺序完全由你决定：你可以先看历史归档、也可以直接检索；可以多轮检索；可以抓正文核实；觉得信息够了就提交。

## 硬性规则（违反会被校验拒绝）
1. 每条新闻必须来自工具返回的真实结果，URL 必须来自 search_news 或 fetch_url 的输出，禁止编造链接或事实。
2. 只收录与用户偏好相关、且过去 1-2 天内的新闻；命中排除关键词的不要收录。
3. 与历史简报重复的新闻不要重复收录（用 list_dir/read_file/search_content 检查 archive/）。
4. 摘要必须基于标题+正文/摘要的事实，不要添加未出现的信息；正文抓取失败时摘要要保守。
5. 最终必须调用一次 publish_briefing 提交：items 按重要性排序，条数不超过 {max_items}。
6. 全程使用{language_name}输出；不要输出多余寒暄。

## 工作建议（不是强制流程）
- 先快速确认历史（避免重复），再按话题分别检索，结果不足时换关键词补充；
- 对最关键的 1-2 条抓正文核实后再写摘要；
- 草稿可写入 drafts/ 便于复盘。
"""

FORCE_FINAL_PROMPT = (
    "工具调用步数已达到上限。请立刻停止调用工具，基于已经获得的信息调用 publish_briefing 提交最终简报；"
    "如果信息确实不足，请提交你能确认的条目，并在 summary 中说明信息有限。"
)


def build_system_prompt(
    preferences: dict[str, Any],
    user_name: str,
    today: str,
    workspace: str,
    language: str = "zh",
) -> str:
    topics = preferences.get("topics") or []
    keywords = preferences.get("keywords") or []
    exclude = preferences.get("exclude_keywords") or []
    language_name = "中文" if language.startswith("zh") else "English"
    return SYSTEM_PROMPT.format(
        user_name=user_name,
        today=today,
        workspace=workspace,
        topics="、".join(topics) if topics else "（未设置，可覆盖通用 AI 新闻）",
        keywords="、".join(keywords) if keywords else "（未设置）",
        exclude_keywords="、".join(exclude) if exclude else "（无）",
        max_items=preferences.get("max_items") or 5,
        language=language,
        language_name=language_name,
    )


def build_task_prompt(
    user_name: str,
    preferences: dict[str, Any],
    history_lines: list[str],
    today: str,
) -> str:
    history = "\n".join(history_lines) if history_lines else "（这是你的第一份简报，没有历史记录）"
    topics = "、".join(preferences.get("topics") or []) or "（未设置）"
    keywords = "、".join(preferences.get("keywords") or []) or "（未设置）"
    return f"""请为 {user_name} 生成 {today} 的 AI 新闻简报。

最近的简报记录（可用于去重）：
{history}

订阅话题：{topics}
订阅关键词：{keywords}
每日条数上限：{preferences.get("max_items") or 5}

要求：
1. 先用工具确认历史与检索新闻，再决定入选条目（顺序由你决定）；
2. 每条给出：标题、来源、真实链接、发布时间（如有）、1-2 句事实摘要、入选理由；
3. 最后调用 publish_briefing 提交。"""

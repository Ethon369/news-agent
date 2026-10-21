"""邮件推送（SMTP，SSL 或 STARTTLS）。

版式目标：像一份「日报」，而不是一坨纯文本——
- 主题：`AI 每日简报｜10月20日：<当日头条>`（收件箱里一眼知道今天讲什么）；
- 正文：品牌头 / 总览 / 编号条目（来源·时间·摘要·证据范围·原文链接）/ 页脚。
"""

from __future__ import annotations

import html
import smtplib
import ssl
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from urllib.parse import urlsplit

from app.notify.base import BaseNotifier, DeliveryResult

BRAND = "AI 每日简报"
FOOTER = "由 AI Daily Agent 基于 LLM 自主工具调用生成；每条均附原始来源与证据范围，请以原文为准。"


def _safe_url(url: str) -> str:
    """只允许 http(s) 链接进入邮件（防 javascript: / data: 注入），并做 HTML 转义。"""
    raw = str(url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        return "#"
    return html.escape(raw, quote=True)


def _date_label(value) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return f"{value.month}月{value.day}日"
    return datetime.now().strftime("%m月%d日")


def _top_title(briefing) -> str:
    items = getattr(briefing, "items", None) or []
    if items:
        return str(items[0].title or "").strip()
    return str(briefing.title or "").strip()


def build_subject(briefing) -> str:
    """生成收件箱可读的主题：AI 每日简报｜10月20日：当日头条。"""
    head = _top_title(briefing) or str(briefing.title or BRAND).strip()
    if len(head) > 46:
        head = head[:46].rstrip() + "…"
    return f"{BRAND}｜{_date_label(getattr(briefing, 'briefing_date', None))}：{head}"[:180]


def _evidence(item) -> str:
    return str(getattr(item, "evidence_level", "") or "").strip()


def render_email_html(briefing, user) -> str:
    # 所有来自 LLM / 新闻源的文本都必须转义（AI code review 发现的 HTML 注入面）
    title = html.escape(str(briefing.title or ""))
    summary = html.escape(str(briefing.summary or ""))
    date_label = _date_label(getattr(briefing, "briefing_date", None))
    user_name = html.escape(str(getattr(user, "name", "") or ""))
    parts = [
        '<html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:#f6f7f9;">',
        '<div style="font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;'
        'max-width:640px;margin:0 auto;padding:28px 24px;color:#1f2937;line-height:1.7;background:#ffffff;">',
        f'<div style="font-size:12px;letter-spacing:2px;color:#6b7280;text-transform:uppercase;">{BRAND}</div>',
        f'<div style="font-size:12px;color:#9ca3af;margin:2px 0 18px;">'
        f"{html.escape(date_label)} · 每日 AI 新闻助手</div>",
        f'<h1 style="font-size:22px;line-height:1.45;margin:0 0 12px;">{title}</h1>',
    ]
    if summary:
        parts.append(
            f'<p style="margin:0 0 8px;padding:12px 14px;background:#f3f4ff;border-left:3px solid #6366f1;'
            f'border-radius:4px;color:#374151;">{summary}</p>'
        )
    parts.append('<div style="height:8px;"></div>')
    for index, item in enumerate(briefing.items or [], start=1):
        meta = html.escape(str(item.source or "未知来源"))
        if item.published_at:
            meta += f" · {html.escape(str(item.published_at)[:16].replace('T', ' '))}"
        evidence = _evidence(item)
        parts.append(
            '<div style="margin:22px 0 0;padding:16px 0 0;border-top:1px solid #e5e7eb;">'
            f'<div style="font-size:12px;color:#9ca3af;margin-bottom:4px;">{index:02d}</div>'
            f'<h2 style="font-size:17px;line-height:1.5;margin:0 0 8px;color:#111827;">'
            f"{html.escape(str(item.title or ''))}</h2>"
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px;">{meta}</div>'
        )
        if item.summary:
            parts.append(
                '<p style="margin:0 0 10px;font-size:14px;color:#374151;">'
                f"{html.escape(str(item.summary))}</p>"
            )
        if evidence:
            parts.append(
                '<div style="font-size:12px;color:#6b7280;margin:0 0 10px;">'
                f"证据范围：{html.escape(evidence)}</div>"
            )
        parts.append(
            f'<a href="{_safe_url(item.url)}" style="display:inline-block;font-size:13px;color:#4f46e5;'
            'text-decoration:none;border:1px solid #c7d2fe;border-radius:6px;padding:6px 12px;">阅读原文 →</a>'
            "</div>"
        )
    parts.append(
        f'<p style="margin:28px 0 0;padding-top:14px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af;">'
        f"{FOOTER}<br>为 {user_name} 定制</p>"
    )
    parts.append("</div></body></html>")
    return "".join(parts)


class EmailNotifier(BaseNotifier):
    channel = "email"

    def _plain_text_with_evidence(self, briefing, user) -> str:
        lines = [f"{BRAND} · {_date_label(getattr(briefing, 'briefing_date', None))}", "", str(briefing.title or "")]
        if briefing.summary:
            lines += ["", str(briefing.summary)]
        for index, item in enumerate(briefing.items or [], start=1):
            lines += ["", f"{index}. {item.title}", f"   {item.source or ''} {item.published_at or ''}".rstrip()]
            if item.summary:
                lines += [f"   {item.summary}"]
            if _evidence(item):
                lines += [f"   证据范围：{_evidence(item)}"]
            lines += [f"   {item.url}"]
        lines += ["", FOOTER]
        return "\n".join(lines)[:8000]

    def send(self, briefing, user) -> DeliveryResult:
        missing = [
            name
            for name, value in (
                ("SMTP_HOST", self.settings.smtp_host),
                ("SMTP_USER", self.settings.smtp_user),
                ("SMTP_PASSWORD", self.settings.smtp_password),
            )
            if not value
        ]
        if missing:
            return DeliveryResult(channel=self.channel, status="skipped", detail=f"邮件配置缺失: {', '.join(missing)}")
        to_address = user.email
        if not to_address:
            return DeliveryResult(channel=self.channel, status="skipped", detail="用户未填写邮箱")

        sender = self.settings.smtp_from or self.settings.smtp_user
        message = MIMEMultipart("alternative")
        message["Subject"] = build_subject(briefing)
        message["From"] = formataddr(("AI 每日简报", sender))
        message["To"] = to_address
        message["Date"] = formatdate(localtime=True)
        plain = self._plain_text_with_evidence(briefing, user)
        message.attach(MIMEText(plain, "plain", "utf-8"))
        message.attach(MIMEText(render_email_html(briefing, user), "html", "utf-8"))

        try:
            if self.settings.smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    self.settings.smtp_host, self.settings.smtp_port, context=context, timeout=20
                ) as server:
                    server.login(self.settings.smtp_user, self.settings.smtp_password)
                    server.sendmail(sender, [to_address], message.as_string())
            else:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as server:
                    server.starttls(context=ssl.create_default_context())
                    server.login(self.settings.smtp_user, self.settings.smtp_password)
                    server.sendmail(sender, [to_address], message.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            return DeliveryResult(channel=self.channel, status="failed", detail=f"发送失败: {exc}")
        return DeliveryResult(channel=self.channel, status="success", detail=f"已发送至 {to_address}")


__all__ = ["EmailNotifier", "build_subject", "render_email_html", "BRAND"]

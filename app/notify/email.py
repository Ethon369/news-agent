"""邮件推送（SMTP，SSL 或 STARTTLS）。"""

from __future__ import annotations

import html
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from urllib.parse import urlsplit

from app.notify.base import BaseNotifier, DeliveryResult


def _safe_url(url: str) -> str:
    """只允许 http(s) 链接进入邮件（防 javascript: / data: 注入），并做 HTML 转义。"""
    raw = str(url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        return "#"
    return html.escape(raw, quote=True)


def render_email_html(briefing, user) -> str:
    # 所有来自 LLM / 新闻源的文本都必须转义（AI code review 发现的 HTML 注入面）
    title = html.escape(str(briefing.title or ""))
    summary = html.escape(str(briefing.summary or ""))
    parts = [
        '<html><body style="font-family:-apple-system,Segoe UI,Microsoft YaHei,sans-serif;'
        'max-width:640px;margin:0 auto;padding:24px;color:#1f2937;line-height:1.65;">',
        f'<h1 style="font-size:22px;">{title}</h1>',
    ]
    if briefing.summary:
        parts.append(f'<p style="color:#4b5563;border-left:3px solid #6366f1;padding-left:12px;">{summary}</p>')
    for index, item in enumerate(briefing.items, start=1):
        meta = html.escape(str(item.source or "")) + (
            f" · {html.escape(str(item.published_at)[:16])}" if item.published_at else ""
        )
        parts.append(
            '<div style="margin:20px 0;padding-bottom:16px;border-bottom:1px solid #e5e7eb;">'
            f'<h2 style="font-size:17px;margin:0 0 6px;">{index}. {html.escape(str(item.title or ""))}</h2>'
            f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px;">{meta}</div>'
            f'<p style="margin:0 0 8px;">{html.escape(str(item.summary or ""))}</p>'
            f'<a href="{_safe_url(item.url)}" style="color:#6366f1;">阅读原文</a>'
            "</div>"
        )
    parts.append(
        f'<p style="font-size:12px;color:#9ca3af;">由 AI Daily Agent 为 '
        f"{html.escape(str(getattr(user, 'name', '') or ''))} 生成 · 每条均附原始来源链接</p>"
    )
    parts.append("</body></html>")
    return "".join(parts)


class EmailNotifier(BaseNotifier):
    channel = "email"

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
        message["Subject"] = f"{briefing.title}"
        message["From"] = formataddr(("AI Daily", sender))
        message["To"] = to_address
        message["Date"] = formatdate(localtime=True)
        message.attach(MIMEText(self._plain_text(briefing, user), "plain", "utf-8"))
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

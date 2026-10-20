"""飞书群机器人推送：支持签名校验的 interactive card。

文档：https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import httpx

from app.notify.base import BaseNotifier, DeliveryResult


class FeishuNotifier(BaseNotifier):
    channel = "feishu"

    def _sign(self, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{self.settings.feishu_secret}"
        digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _payload(self, briefing, user) -> dict:
        items = briefing.items[:10]
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{briefing.summary or briefing.title}**"}}
        ]
        for index, item in enumerate(items, start=1):
            content = f"**{index}. {item.title}**\n{item.source} · {item.reason or ''}\n[阅读原文]({item.url})"
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content[:1800]}})
            elements.append({"tag": "hr"})
        elements.append(
            {"tag": "note", "elements": [{"tag": "plain_text", "content": f"AI Daily · 为 {user.name} 生成"}]}
        )
        card = {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": briefing.title[:80]}},
            "elements": elements,
        }
        return {"msg_type": "interactive", "card": card}

    def send(self, briefing, user) -> DeliveryResult:
        if not self.settings.feishu_webhook_url:
            return DeliveryResult(channel=self.channel, status="skipped", detail="FEISHU_WEBHOOK_URL 未配置")
        payload = self._payload(briefing, user)
        if self.settings.feishu_secret:
            timestamp = str(int(time.time()))
            payload |= {"timestamp": timestamp, "sign": self._sign(timestamp)}
        try:
            with httpx.Client(verify=self.settings.feishu_verify_ssl, timeout=15) as client:
                response = client.post(self.settings.feishu_webhook_url, json=payload)
            data = {}
            try:
                data = response.json()
            except ValueError:
                data = {}
            code = data.get("code", data.get("StatusCode", 0))
            if response.status_code == 200 and code in (0, None):
                return DeliveryResult(channel=self.channel, status="success", detail="飞书群机器人推送成功")
            return DeliveryResult(
                channel=self.channel,
                status="failed",
                detail=f"HTTP {response.status_code}: {str(data)[:300]}",
            )
        except httpx.HTTPError as exc:
            return DeliveryResult(channel=self.channel, status="failed", detail=f"请求失败: {exc}")

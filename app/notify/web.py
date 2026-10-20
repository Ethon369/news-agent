"""站内推送：简报已经落库，前端可见，因此这里只做记账。"""

from __future__ import annotations

from app.notify.base import BaseNotifier, DeliveryResult


class WebNotifier(BaseNotifier):
    channel = "web"

    def send(self, briefing, user) -> DeliveryResult:
        return DeliveryResult(channel=self.channel, status="success", detail="已保存到站内历史简报")

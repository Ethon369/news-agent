"""推送通道：web（站内）/ feishu（群机器人）/ email（SMTP）。"""

from app.notify.base import DeliveryResult
from app.notify.email import EmailNotifier
from app.notify.feishu import FeishuNotifier
from app.notify.web import WebNotifier


def build_notifiers(settings, channels: list[str]) -> list:
    """按用户偏好 + 服务端配置构建本次要尝试的推送通道。"""
    notifiers = []
    for channel in channels:
        if channel == "web":
            notifiers.append(WebNotifier(settings))
        elif channel == "feishu":
            notifiers.append(FeishuNotifier(settings))
        elif channel == "email":
            notifiers.append(EmailNotifier(settings))
    return notifiers


__all__ = ["DeliveryResult", "EmailNotifier", "FeishuNotifier", "WebNotifier", "build_notifiers"]

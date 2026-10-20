"""推送通道基类与结果结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import Settings


@dataclass
class DeliveryResult:
    channel: str
    status: str  # success | failed | skipped
    detail: str = ""


class Notifier(Protocol):
    channel: str

    def send(self, briefing, user) -> DeliveryResult: ...


class BaseNotifier:
    channel = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _plain_text(briefing, user) -> str:
        lines = [briefing.title, ""]
        if briefing.summary:
            lines += [briefing.summary, ""]
        for index, item in enumerate(briefing.items, start=1):
            lines.append(f"{index}. {item.title}")
            lines.append(f"   {item.source} · {item.url}")
        return "\n".join(lines)[:6000]

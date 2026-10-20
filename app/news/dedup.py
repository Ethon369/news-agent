"""去重：URL 归一化 + 标题近似判重，防止连续几天推送同一条新闻。"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PREFIXES = ("utm_", "spm", "from", "ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid")
TRACKING_EXACT = {"ocid", "cmpid", "ncid", "sr_share", "share", "sh", "source"}


def normalize_url(url: str) -> str:
    """去掉协议差异、fragment 与常见跟踪参数，输出可用于判重的规范 URL。"""
    if not url:
        return ""
    raw = url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if not (key.lower().startswith(TRACKING_PREFIXES) or key.lower() in TRACKING_EXACT)
    ]
    query = urlencode(kept_query)
    return urlunsplit(("https", host, path, query, ""))


_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_title(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[-|—–]\s*[^-|—–]{0,30}$", "", text)  # 去掉常见的站点后缀
    return _PUNCT_RE.sub("", text)


class Deduplicator:
    """记忆历史 URL / 标题，判断候选新闻是否已经推送过。"""

    def __init__(self, known_urls: list[str] | None = None, known_titles: list[str] | None = None) -> None:
        self._urls = {normalize_url(url) for url in (known_urls or []) if url}
        self._titles = [normalize_title(title) for title in (known_titles or []) if title]

    def is_duplicate(self, url: str, title: str = "", similarity_threshold: float = 0.9) -> bool:
        normalized_url = normalize_url(url)
        if normalized_url and normalized_url in self._urls:
            return True
        normalized_title = normalize_title(title)
        if normalized_title:
            for known in self._titles:
                if not known:
                    continue
                if known == normalized_title:
                    return True
                if abs(len(known) - len(normalized_title)) > 12:
                    continue
                if SequenceMatcher(None, known, normalized_title).ratio() >= similarity_threshold:
                    return True
        return False

    def remember(self, url: str, title: str = "") -> None:
        normalized_url = normalize_url(url)
        if normalized_url:
            self._urls.add(normalized_url)
        normalized_title = normalize_title(title)
        if normalized_title:
            self._titles.append(normalized_title)

    @property
    def known_url_count(self) -> int:
        return len(self._urls)

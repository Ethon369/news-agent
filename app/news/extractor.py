"""正文抽取：抓取网页并提取可读正文，供 Agent 核实与摘要。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; AIDailyAgent/0.1; +https://github.com/; news briefing demo)"
MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0

_STRIP_TAGS = ["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header", "aside", "form"]
_BOILERPLATE_HINTS = ("cookie", "subscribe", "advertisement", "sign up", "newsletter", "advertise")


@dataclass
class Article:
    url: str
    title: str
    text: str
    site: str = ""
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "site": self.site,
            "chars": len(self.text),
            "ok": self.ok,
            "error": self.error,
        }


def _extract_site(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"property": "og:site_name"})
    if meta and meta.get("content"):
        return str(meta["content"]).strip()
    return ""


def _pick_container(soup: BeautifulSoup):
    for selector in ("article", "main", '[role="main"]', ".post-content", ".article-content", "#content"):
        node = soup.select_one(selector)
        if node and len(node.get_text(strip=True)) > 200:
            return node
    return soup.body or soup


def extract_from_html(html: str, url: str = "") -> Article:
    """把 HTML 抽成标题 + 正文纯文本（不依赖外部服务）。"""
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = str(og_title["content"]).strip()

    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    container = _pick_container(soup)
    paragraphs: list[str] = []
    for node in container.find_all(["p", "h1", "h2", "h3", "li", "blockquote"]):
        text = node.get_text(" ", strip=True)
        if not text or len(text) < 20:
            continue
        lowered = text.lower()
        if any(hint in lowered for hint in _BOILERPLATE_HINTS):
            continue
        paragraphs.append(text)
    text = "\n".join(paragraphs)
    if not text:
        text = container.get_text(" ", strip=True)[:4000]
    return Article(url=url, title=title, text=text[:12000], site=_extract_site(soup))


def fetch_article(url: str, max_chars: int = 4000, client: httpx.Client | None = None) -> Article:
    """抓取并抽取正文；任何网络/解析失败都返回 ok=False 的 Article，不抛异常。"""
    if not url.lower().startswith(("http://", "https://")):
        return Article(url=url, title="", text="", ok=False, error="仅支持 http/https 链接")
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        if client is not None:
            response = client.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        else:
            with httpx.Client(follow_redirects=True) as own:
                response = own.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        content = response.content[:MAX_HTML_BYTES]
        encoding = response.encoding or "utf-8"
        html = content.decode(encoding, errors="replace")
    except (httpx.HTTPError, UnicodeDecodeError, OSError) as exc:
        return Article(url=url, title="", text="", ok=False, error=f"抓取失败: {exc}")

    article = extract_from_html(html, url=url)
    article.text = article.text[:max_chars]
    return article

"""正文抽取：抓取网页并提取可读正文，供 Agent 核实与摘要。"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; AIDailyAgent/0.1; +https://github.com/; news briefing demo)"
MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
MAX_REDIRECTS = 3

_STRIP_TAGS = ["script", "style", "noscript", "iframe", "svg", "nav", "footer", "header", "aside", "form"]
_BOILERPLATE_HINTS = ("cookie", "subscribe", "advertisement", "sign up", "newsletter", "advertise")

# 本机/内网/元数据服务常见主机名（即使 DNS 解析到公网也拒绝）
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}


class UnsafeURLError(ValueError):
    """目标 URL 不是公网可访问地址（SSRF 防护）。"""


_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _is_fake_ip(raw_ip: str) -> bool:
    try:
        return ipaddress.ip_address(raw_ip.split("%", 1)[0]) in _FAKE_IP_NETWORK
    except ValueError:
        return False


def _is_public_ip(raw_ip: str, allow_fake_ip: bool = False) -> bool:
    try:
        ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
    except ValueError:
        return False
    if allow_fake_ip and ip in _FAKE_IP_NETWORK:
        # 代理软件（Clash/Surge 等）的 Fake-IP：DNS 被接管，真实目标由代理解析。
        # 这是显式开启的兼容模式，默认关闭；其余私网地址仍然拒绝。
        return True
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_public_ip(str(ip.ipv4_mapped), allow_fake_ip=allow_fake_ip)
    return True


def assert_public_url(url: str, allow_fake_ip: bool = False) -> None:
    """校验 URL 只指向公网 http(s) 地址，否则抛 UnsafeURLError。

    - 拒绝非 http(s) 协议、缺失主机名；
    - 拒绝 localhost / *.local / *.internal / 云元数据主机名；
    - 对域名做 DNS 解析，逐个检查解析出的 IP（含 IPv6），拒绝私网/回环/链路本地/保留地址；
    - ``allow_fake_ip=True`` 时放过 198.18.0.0/15（Clash 等代理的 Fake-IP 段），
      代价是此时无法在本机校验真实目标 IP，需由代理层保证出口；默认关闭；
    - 注意：DNS pinning 仍非绝对（存在 rebinding 窗口），生产环境应配合出口代理白名单。
    """
    parts = urlsplit(url or "")
    if parts.scheme not in {"http", "https"}:
        raise UnsafeURLError("仅允许访问 http/https 公网地址")
    host = (parts.hostname or "").strip().lower()
    if not host:
        raise UnsafeURLError("URL 缺少主机名")
    if host in _BLOCKED_HOSTNAMES or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeURLError(f"拒绝访问本机/内网地址: {host}")

    try:
        infos = socket.getaddrinfo(
            host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        raise UnsafeURLError(f"域名解析失败: {host}") from exc
    if not infos:
        raise UnsafeURLError(f"域名无解析结果: {host}")
    for info in infos:
        ip_text = str(info[4][0])
        if not _is_public_ip(ip_text, allow_fake_ip=allow_fake_ip):
            raise UnsafeURLError(f"拒绝访问内网/保留地址: {host} -> {ip_text}")


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


def fetch_article(
    url: str,
    max_chars: int = 4000,
    client: httpx.Client | None = None,
    allow_fake_ip: bool = False,
) -> Article:
    """抓取并抽取正文；任何网络/解析失败都返回 ok=False 的 Article，不抛异常。

    安全：只允许访问公网 http(s) 地址，且对每一跳重定向重新校验（防 SSRF /
    内网探测 / 云元数据读取）。见 ADR-0007。
    """
    current = url
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    own_client = client is None
    http = client or httpx.Client(follow_redirects=False)
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            assert_public_url(current, allow_fake_ip=allow_fake_ip)
            response = http.get(current, headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=False)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return Article(url=url, title="", text="", ok=False, error="重定向缺少 Location 头")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content = response.content[:MAX_HTML_BYTES]
            encoding = response.encoding or "utf-8"
            html = content.decode(encoding, errors="replace")
            break
        else:
            return Article(url=url, title="", text="", ok=False, error="重定向次数过多，已中止")
    except UnsafeURLError as exc:
        return Article(url=url, title="", text="", ok=False, error=str(exc))
    except (httpx.HTTPError, UnicodeDecodeError, OSError) as exc:
        return Article(url=url, title="", text="", ok=False, error=f"抓取失败: {exc}")
    finally:
        if own_client:
            http.close()

    article = extract_from_html(html, url=current)
    article.text = article.text[:max_chars]
    return article

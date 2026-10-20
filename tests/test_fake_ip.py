"""Fake-IP 代理兼容测试（Clash/Surge 会把域名解析到 198.18.0.0/15）。"""

from __future__ import annotations

import socket

import httpx
import pytest

from app.news.extractor import UnsafeURLError, assert_public_url, fetch_article


def _fake_resolver(ip: str):
    def resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]

    return resolver


def test_fake_ip_rejected_by_default(monkeypatch):
    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", _fake_resolver("198.18.0.35"))
    with pytest.raises(UnsafeURLError):
        assert_public_url("https://finance.sina.com.cn/tech/roll/x.shtml")


def test_fake_ip_allowed_when_opted_in(monkeypatch):
    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", _fake_resolver("198.18.0.35"))
    assert_public_url("https://finance.sina.com.cn/tech/roll/x.shtml", allow_fake_ip=True)


@pytest.mark.parametrize("ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "172.16.0.2", "192.168.1.1"])
def test_opt_in_still_rejects_real_private_ranges(monkeypatch, ip):
    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", _fake_resolver(ip))
    with pytest.raises(UnsafeURLError):
        assert_public_url("https://internal.example.com/x", allow_fake_ip=True)


def test_fetch_article_with_fake_ip_opt_in(monkeypatch):
    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", _fake_resolver("198.18.0.166"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><title>正文标题</title></head><body><article><p>"
            "这是一段足够长的正文内容，用来验证 Fake-IP 兼容模式下可以正常抓取与抽取。</p></article></body></html>",
            headers={"content-type": "text/html"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    article = fetch_article("https://techcrunch.com/x", client=client, allow_fake_ip=True)
    assert article.ok
    assert "足够长的正文内容" in article.text


def test_fetch_article_fake_ip_still_blocked_by_default(monkeypatch):
    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", _fake_resolver("198.18.0.166"))
    article = fetch_article("https://techcrunch.com/x")
    assert not article.ok
    assert "内网" in article.error or "保留" in article.error

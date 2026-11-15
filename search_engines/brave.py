"""Brave 引擎（可选，默认关闭）：search.brave.com HTML 抓取。

仅当环境变量 BRAVE_ENABLED=1 时启用（编排层与引擎双重校验）。
Brave 的防护主要是 TLS 指纹检测（curl_cffi 可过），不是 Cloudflare JS challenge；
但它与 DDG 一样属灰色抓取 + 猫鼠游戏：一旦出现 PoW/clearance 挑战页直接放弃，
不为"稳"引入浏览器解题这类重依赖。默认关闭的理由：快准稳优先，Brave 增益有限。
"""
from __future__ import annotations

import os
import time

from bs4 import BeautifulSoup

from .http import http_get
from .util import EngineError, apply_pushdown, domain_of, host_matches

_ENABLED_ENV = "BRAVE_ENABLED"
_MAX_RESULTS = 12


def is_enabled() -> bool:
    return os.environ.get(_ENABLED_ENV, "").strip() == "1"


def _parse(html: str, blocked: list[str]) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    for el in soup.select('div.snippet[data-type="web"]'):
        a = el.select_one("a[href]")
        if not a:
            continue
        url = a["href"]
        if not url.startswith("http") or url in seen:
            continue
        title_el = el.select_one(".title")
        title = title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True)
        snip_el = el.select_one(".snippet-description, .snippet-content")
        snippet = snip_el.get_text(" ", strip=True) if snip_el else ""
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "domain": domain, "snippet": snippet})
        if len(items) >= _MAX_RESULTS:
            break
    return items


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 6.0,
    deadline: float | None = None,  # 契约统一；单请求引擎不使用
) -> dict:
    started = time.perf_counter()
    if not is_enabled():
        return {
            "name": "brave",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未启用（设环境变量 BRAVE_ENABLED=1 开启）",
        }

    q = apply_pushdown(query, baseline_block or [])
    resp = http_get("https://search.brave.com/search", params={"q": q}, timeout=timeout)
    head = resp.text[:2000].lower()
    if resp.status_code in (403, 429) or "challenge" in head or "captcha" in head:
        raise EngineError("触发 Brave 反爬挑战页")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    items = _parse(resp.text, baseline_block or [])
    return {
        "name": "brave",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

"""DuckDuckGo 引擎：lite 端点优先，html 端点兜底。

DDG 无官方免费 API，html/lite 端点属灰色抓取；2025-2026 风控持续升级
（验证码、假 HTTP 202、TCP 封锁），数据中心 IP 是重灾区。护栏：
- curl_cffi Chrome TLS 指纹伪装（见 http.py）；
- 上层边缘缓存压低请求频率；
- 非 200（含假 202）一律按风控处理，lite 失败自动换 html 端点重试一次。
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .http import http_get
from .util import EngineError, apply_pushdown, domain_of, host_matches

_ENDPOINTS = ("https://lite.duckduckgo.com/lite/", "https://html.duckduckgo.com/html/")
_MAX_RESULTS = 15


def _unwrap_link(href: str | None) -> str | None:
    """DDG 结果链接包在 //duckduckgo.com/l/?uddg=<urlencoded> 重定向里，解出真实地址。"""
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]  # type: ignore[list-item]
        return target if target and target.startswith("http") else None
    return href if href.startswith("http") else None


def _make_item(title: str, url: str, snippet: str, blocked: list[str]) -> dict | None:
    domain = domain_of(url)
    if not domain or any(host_matches(domain, b) for b in blocked):
        return None
    return {"title": title, "url": url, "domain": domain, "snippet": snippet}


def _parse(html: str, blocked: list[str]) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()

    # lite 端点：<a class="result-link">，摘要在其后对应的 <td class="result-snippet">
    links = soup.select("a.result-link")
    snippets = soup.select("td.result-snippet")
    for i, a in enumerate(links):
        url = _unwrap_link(a.get("href"))
        if not url or url in seen:
            continue
        snippet = snippets[i].get_text(" ", strip=True) if i < len(snippets) else ""
        item = _make_item(a.get_text(" ", strip=True), url, snippet, blocked)
        if item:
            seen.add(url)
            items.append(item)

    # html 端点：<div class="result"> 内 a.result__a + .result__snippet
    if not items:
        for block in soup.select("div.result"):
            a = block.select_one("a.result__a")
            if not a:
                continue
            url = _unwrap_link(a.get("href"))
            if not url or url in seen:
                continue
            snippet_el = block.select_one(".result__snippet")
            item = _make_item(
                a.get_text(" ", strip=True),
                url,
                snippet_el.get_text(" ", strip=True) if snippet_el else "",
                blocked,
            )
            if item:
                seen.add(url)
                items.append(item)

    return items[:_MAX_RESULTS]


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 6.0,
    deadline: float | None = None,
) -> dict:
    started = time.perf_counter()
    blocked = baseline_block or []
    q = apply_pushdown(query, blocked)
    kl = {"zh": "zh-cn", "en": "us-en"}.get(lang, "wt-wt")
    params: dict = {"q": q, "kl": kl}
    if page > 1:
        params["s"] = str((page - 1) * 20)

    last_note = "无结果"
    for endpoint in _ENDPOINTS:
        # 编排层总超时前预留 2s 余量；第二端点来不及就不试（避免响应被拖过上限）
        if deadline is not None and time.perf_counter() > deadline - 2.0:
            break
        try:
            resp = http_get(endpoint, params=params, timeout=timeout)
            # DDG 风控会返回假 "202 Accepted"，按非 200 处理
            if resp.status_code != 200:
                last_note = f"HTTP {resp.status_code}（可能被风控）"
                continue
            items = _parse(resp.text, blocked)
            if items:
                return {
                    "name": "ddg",
                    "status": "ok",
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "results": items,
                }
        except EngineError:
            raise
        except Exception as exc:  # 网络/解析异常，换下一个端点
            last_note = type(exc).__name__
            continue

    raise EngineError(last_note)

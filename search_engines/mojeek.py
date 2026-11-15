"""Mojeek 引擎：HTML 抓取。西方仅有的真独立索引之一（另一个 Brave），对元搜索生态友好，
searxng 多年默认引擎、无云 IP 封锁史。中文覆盖弱——作为索引多样性增量源，权重低。
Mojeek 对 -site: 运算符支持不明，不做服务端下推（客户端过滤兜底）。
"""
from __future__ import annotations

import time

from bs4 import BeautifulSoup

from .http import http_get
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_ENDPOINT = "https://www.mojeek.com/search"
_MAX_RESULTS = 10


def _parse(html: str, blocked: list[str]) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict] = []
    seen: set[str] = set()
    blocks = soup.select("ul.results-standard > li") or soup.select("li.result")
    for li in blocks:
        a = li.select_one("a.title") or li.select_one("h2 a")
        if not a:
            continue
        url = a.get("href") or ""
        if not url.startswith("http") or url in seen:
            continue
        snippet_el = li.select_one("p.s") or li.select_one("p")
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append(
            {"title": a.get_text(" ", strip=True), "url": url, "domain": domain, "snippet": snippet}
        )
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
    blocked = baseline_block or []
    params: dict = {"q": query}  # 不做 -site: 下推（支持度不明）
    if page > 1:
        params["page"] = str(page)

    resp = http_get(_ENDPOINT, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    items = _parse(resp.text, blocked)
    tokens = relevance_tokens(query)
    if items and tokens and not any(overlap_any(tokens, r["title"], r["snippet"]) for r in items):
        return {
            "name": "mojeek",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "相关性校验未通过，已丢弃",
            "discarded_sample": [i["title"][:80] for i in items[:3]],
        }

    return {
        "name": "mojeek",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

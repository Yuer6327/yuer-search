"""Firecrawl 引擎：搜索 + 正文抓取一体，免费 1000 credits/月（约 500 次 /search），不绑卡。
响应结构在不同版本有扁平列表与 data.web 两种形态，解析两者兼容。
"""
from __future__ import annotations

import os
import time

from .http import http_post_json
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_ENDPOINT = "https://api.firecrawl.dev/v1/search"
_MAX_RESULTS = 8


def has_key() -> bool:
    return bool(os.environ.get("FIRECRAWL_API_KEY", "").strip())


def _extract_rows(data: dict) -> list[dict]:
    d = data.get("data")
    if isinstance(d, list):
        return [r for r in d if isinstance(r, dict)]
    if isinstance(d, dict):
        for key in ("web", "results", "news"):
            v = d.get(key)
            if isinstance(v, list) and v:
                return [r for r in v if isinstance(r, dict)]
    return []


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 8.0,
    deadline: float | None = None,  # 契约统一；单请求引擎不使用
) -> dict:
    started = time.perf_counter()
    key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not key:
        return {
            "name": "firecrawl",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 FIRECRAWL_API_KEY（firecrawl.dev 免费 1000 credits/月，无需绑卡）",
        }
    if page > 1:
        return {"name": "firecrawl", "status": "skipped", "latency_ms": 0, "results": [], "note": "翻页未启用（节省免费额度）"}

    resp = http_post_json(
        _ENDPOINT,
        {"query": query, "limit": _MAX_RESULTS},
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise EngineError(f"HTTP {resp.status_code}（API key 无效）")
    if resp.status_code == 429:
        raise EngineError("HTTP 429（免费额度/限速）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    if data.get("success") is False:
        raise EngineError(f"API error: {str(data.get('error'))[:80]}")

    blocked = baseline_block or []
    tokens = relevance_tokens(query)
    items: list[dict] = []
    seen: set[str] = set()
    for r in _extract_rows(data):
        url = r.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        title = (r.get("title") or url).strip()
        snippet = (r.get("description") or r.get("snippet") or r.get("markdown") or "").strip()
        snippet = snippet[:300]
        if tokens and not overlap_any(tokens, title, snippet):
            continue
        items.append({"title": title, "url": url, "domain": domain, "snippet": snippet})
        if len(items) >= _MAX_RESULTS:
            break

    return {
        "name": "firecrawl",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

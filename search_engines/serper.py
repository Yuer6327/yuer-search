"""Serper 引擎：Google SERP 代理 API，注册送 2500 次一次性额度、官方明示不绑卡。
Google 中文结果的质量基准源（仅额度内可用）。支持 Google 运算符 → 基线 -site: 下推有效。
环境变量 SERPER_API_KEY 未配置时跳过。
"""
from __future__ import annotations

import os
import time

from .http import http_post_json
from .util import EngineError, apply_pushdown, domain_of, host_matches, overlap_any, relevance_tokens

_ENDPOINT = "https://google.serper.dev/search"
_MAX_RESULTS = 10


def has_key() -> bool:
    return bool(os.environ.get("SERPER_API_KEY", "").strip())


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
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        return {
            "name": "serper",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 SERPER_API_KEY（serper.dev 注册送 2500 次，无需绑卡）",
        }

    blocked = baseline_block or []
    q = apply_pushdown(query, blocked)
    payload: dict = {"q": q, "num": _MAX_RESULTS}
    if lang == "zh":
        payload.update({"hl": "zh-cn", "gl": "cn"})
    else:
        payload.update({"hl": "en", "gl": "us"})
    if page > 1:
        payload["page"] = page

    resp = http_post_json(_ENDPOINT, payload, headers={"X-API-KEY": key}, timeout=timeout)
    if resp.status_code in (401, 403):
        raise EngineError(f"HTTP {resp.status_code}（API key 无效或额度耗尽）")
    if resp.status_code == 429:
        raise EngineError("HTTP 429（免费额度/限速）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    tokens = relevance_tokens(query)
    items: list[dict] = []
    seen: set[str] = set()
    for r in data.get("organic") or []:
        url = r.get("link") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        title = (r.get("title") or url).strip()
        snippet = (r.get("snippet") or "").strip()
        # Google 结果质量高，但仍保留护栏兜底（额度内被反爬污染的概率极低）
        if tokens and not overlap_any(tokens, title, snippet):
            continue
        items.append({"title": title, "url": url, "domain": domain, "snippet": snippet})
        if len(items) >= _MAX_RESULTS:
            break

    return {
        "name": "serper",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

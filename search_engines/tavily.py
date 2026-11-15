"""Tavily 引擎：官方搜索 API，免费层 1000 credits/月、每月重置、官方明示不绑卡。
基线屏蔽域名经 API 原生 exclude_domains 下推（比 -site: 更可靠）。
环境变量 TAVILY_API_KEY 未配置时跳过。
"""
from __future__ import annotations

import os
import time

from .http import http_post_json
from .util import EngineError, domain_of, host_matches

_ENDPOINT = "https://api.tavily.com/search"
_MAX_RESULTS = 10


def has_key() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY", "").strip())


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
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        return {
            "name": "tavily",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 TAVILY_API_KEY（tavily.com 免费注册 1000 次/月，无需绑卡）",
        }
    if page > 1:
        # 免费层按结果条数计费，翻页价值有限，先只做第一页
        return {
            "name": "tavily",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "翻页未启用（节省免费额度）",
        }

    payload: dict = {"query": query, "max_results": _MAX_RESULTS, "search_depth": "basic"}
    blocked = [b for b in (baseline_block or []) if isinstance(b, str)]
    if blocked:
        payload["exclude_domains"] = blocked[:12]  # API 原生屏蔽下推

    resp = http_post_json(_ENDPOINT, payload, headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
    if resp.status_code == 432 or resp.status_code == 429:
        raise EngineError(f"HTTP {resp.status_code}（免费额度/限速）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    items: list[dict] = []
    for r in data.get("results") or []:
        url = r.get("url") or ""
        if not url.startswith("http"):
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        items.append(
            {"title": (r.get("title") or url).strip(), "url": url, "domain": domain, "snippet": (r.get("content") or "").strip()}
        )
        if len(items) >= _MAX_RESULTS:
            break

    return {
        "name": "tavily",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

"""Marginalia 引擎：官方免费 JSON API（公共凭据，限速严格，官方标记 deprecated 但仍在线）。

独立索引、偏非主流内容型英文站点——作为"官方、免费、无需绑卡"的合规兜底源；
中文覆盖≈0，中文查询直接跳过以省时间。
"""
from __future__ import annotations

import time
from urllib.parse import quote

from .http import http_get
from .util import EngineError, domain_of, host_matches

_BASE = "https://api.marginalia.nu/public/search/"
_MAX_RESULTS = 10


def _make_item(raw: dict, blocked: list[str]) -> dict | None:
    url = raw.get("url") or ""
    if not url.startswith("http"):
        return None
    domain = domain_of(url)
    if not domain or any(host_matches(domain, b) for b in blocked):
        return None
    return {
        "title": (raw.get("title") or url).strip(),
        "url": url,
        "domain": domain,
        "snippet": (raw.get("description") or "").strip(),
    }


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
    if lang == "zh":
        return {
            "name": "marginalia",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "英文独立索引，中文查询自动跳过",
        }

    resp = http_get(
        _BASE + quote(query, safe=""),
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    if resp.status_code in (429, 503):
        raise EngineError(f"HTTP {resp.status_code}（公共 API 限速，稍后再试）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    items: list[dict] = []
    for raw in (data.get("results") or []):
        item = _make_item(raw, baseline_block or [])
        if item:
            items.append(item)
        if len(items) >= _MAX_RESULTS:
            break

    return {
        "name": "marginalia",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

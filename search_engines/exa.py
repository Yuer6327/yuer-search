"""Exa 引擎：神经/关键词混合搜索 API，每月 $10 免费 credits（约 2500 次）+ 注册赠金，无需绑卡。
2025-11 起官方支持查询语言检测与结果语言过滤。语义引擎——结果可能不含查询字面词元，
**不做相关性护栏**（避免误杀语义匹配）。
"""
from __future__ import annotations

import os
import time

from .http import http_post_json
from .util import EngineError, domain_of, host_matches

_ENDPOINT = "https://api.exa.ai/search"
_MAX_RESULTS = 10


def has_key() -> bool:
    return bool(os.environ.get("EXA_API_KEY", "").strip())


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
    key = os.environ.get("EXA_API_KEY", "").strip()
    if not key:
        return {
            "name": "exa",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 EXA_API_KEY（exa.ai 每月 $10 免费 credits，无需绑卡）",
        }
    if page > 1:
        return {"name": "exa", "status": "skipped", "latency_ms": 0, "results": [], "note": "翻页未启用（节省免费额度）"}

    payload = {
        "query": query,
        "numResults": _MAX_RESULTS,
        "contents": {"text": {"maxCharacters": 400}},
    }
    resp = http_post_json(_ENDPOINT, payload, headers={"x-api-key": key}, timeout=timeout)
    if resp.status_code == 401 or resp.status_code == 403:
        raise EngineError(f"HTTP {resp.status_code}（API key 无效）")
    if resp.status_code == 429:
        raise EngineError("HTTP 429（免费额度/限速）")
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    blocked = baseline_block or []
    items: list[dict] = []
    seen: set[str] = set()
    for r in data.get("results") or []:
        url = r.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        text = (r.get("text") or r.get("summary") or "").strip()
        items.append(
            {"title": (r.get("title") or url).strip(), "url": url, "domain": domain, "snippet": text[:300]}
        )
        if len(items) >= _MAX_RESULTS:
            break

    return {
        "name": "exa",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

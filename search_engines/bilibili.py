"""B 站搜索引擎：公开 JSON 接口，未登录可搜（伪造 buvid3 + Referer，参考 searxng bilibili.py）。
补齐中文/视频内容增量。不做 -site: 下推（站内搜索无此运算符），基线过滤在结果侧执行。
"""
from __future__ import annotations

import re
import time
import uuid

from .http import http_get
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_API = "https://api.bilibili.com/x/web-interface/search/type"
_MAX_RESULTS = 12


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse(data: dict, blocked: list[str]) -> list[dict]:
    results = (data.get("data") or {}).get("result") or []
    items: list[dict] = []
    seen: set[str] = set()
    for r in results:
        url = r.get("arcurl") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        author = _clean(r.get("author"))
        duration = _clean(r.get("duration"))
        snippet = _clean(r.get("description"))
        if author:
            snippet = f"{snippet}｜UP 主：{author}" + (f"（{duration}）" if duration else "")
        items.append({"title": _clean(r.get("title")) or url, "url": url, "domain": domain, "snippet": snippet})
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
    if lang != "zh":
        return {
            "name": "bilibili",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "视频内容以中文为主，英文查询自动跳过",
        }

    buvid = uuid.uuid4().hex + "infoc"  # searxng 同款：伪造 buvid3 即可通过基础风控
    headers = {"Cookie": f"buvid3={buvid}", "Referer": "https://search.bilibili.com/"}
    params = {"search_type": "video", "keyword": query, "page": str(page)}
    resp = http_get(_API, params=params, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    data = resp.json()
    code = data.get("code")
    if code == -412:
        raise EngineError("触发 B 站风控（-412），稍后再试")
    if code != 0:
        raise EngineError(f"API code {code}")

    items = _parse(data, baseline_block or [])
    tokens = relevance_tokens(query)
    if items and tokens and not any(overlap_any(tokens, r["title"], r["snippet"]) for r in items):
        return {
            "name": "bilibili",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "相关性校验未通过，已丢弃",
            "discarded_sample": [i["title"][:80] for i in items[:3]],
        }

    return {
        "name": "bilibili",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

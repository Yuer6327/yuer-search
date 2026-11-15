"""Bright Data SERP 引擎：经 Bright Data 代理端点取百度 SERP（免费层 5000 credits/月、官方支持百度）。

用法：Bright Data 控制台建一个 **SERP 类型** 的代理 Zone，把
`BRIGHTDATA_PROXY_USER`（形如 brd-customer-hl_xxxxx-zone-serp_cn）与
`BRIGHTDATA_PROXY_PASSWORD` 两个环境变量配上即可自动启用。

请求路径：代理 GET https://www.baidu.com/s?wd=...（SERP Zone 会返回解析后的 JSON）。
响应结构以实测为准：优先解析 organic/results 列表；若返回 HTML（Zone 类型不对）则降级并留样本。
"""
from __future__ import annotations

import os
import time

from .http import http_get
from .util import EngineError, domain_of, host_matches, overlap_any, relevance_tokens

_PROXY_HOST = "http://brd.superproxy.io:22225"
_MAX_RESULTS = 10
_PROXY_USER_ENV = "BRIGHTDATA_PROXY_USER"
_PROXY_PASS_ENV = "BRIGHTDATA_PROXY_PASSWORD"


def has_key() -> bool:
    return bool(os.environ.get(_PROXY_USER_ENV, "").strip() and os.environ.get(_PROXY_PASS_ENV, "").strip())


def fetch_raw(query: str, *, lang: str = "zh", page: int = 1, timeout: float = 10.0) -> dict:
    """诊断转储：/api/debug/raw?engine=brightdata。"""
    creds = _creds()
    proxies = {"http": f"{creds}", "https": f"{creds}"}
    resp = http_get(
        "https://www.baidu.com/s",
        params={"wd": query, "rn": "10", "pn": str((page - 1) * 10)},
        timeout=timeout,
        proxies=proxies,
    )
    return {"http_status": resp.status_code, "url": str(resp.url), "body_head": resp.text[:3000], "body_full": resp.text}


def _creds() -> str:
    import urllib.parse

    user = urllib.parse.quote(os.environ.get(_PROXY_USER_ENV, "").strip(), safe="")
    pwd = urllib.parse.quote(os.environ.get(_PROXY_PASS_ENV, "").strip(), safe="")
    return f"{user}:{pwd}@brd.superproxy.io:22225"


def _extract_list(data: dict) -> list[dict]:
    for key in ("organic", "results", "organic_results", "items"):
        v = data.get(key)
        if isinstance(v, list) and v:
            return [r for r in v if isinstance(r, dict)]
    return []


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 10.0,
    deadline: float | None = None,  # 契约统一；单请求引擎不使用
) -> dict:
    started = time.perf_counter()
    if lang != "zh":
        return {"name": "brightdata", "status": "skipped", "latency_ms": 0, "results": [], "note": "百度源，英文查询自动跳过"}
    if not has_key():
        return {
            "name": "brightdata",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "未配置 BRIGHTDATA_PROXY_USER/BRIGHTDATA_PROXY_PASSWORD（SERP Zone 凭据）",
        }

    blocked = baseline_block or []
    creds = _creds()
    proxies = {"http": f"http://{creds}", "https": f"http://{creds}"}
    resp = http_get(
        "https://www.baidu.com/s",
        params={"wd": query, "rn": "10", "pn": str((page - 1) * 10)},
        timeout=timeout,
        proxies=proxies,
    )
    if resp.status_code != 200:
        raise EngineError(f"HTTP {resp.status_code}")

    text = resp.text.strip()
    data = None
    if text.startswith("{") or text.startswith("["):
        import json

        try:
            data = json.loads(text)
        except Exception:
            data = None
    if not isinstance(data, dict):
        # Zone 类型不对（返回了 HTML 而非 SERP JSON）——降级并留样本供诊断
        return {
            "name": "brightdata",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "响应非 SERP JSON：请确认 Bright Data Zone 类型为 SERP",
            "discarded_sample": [text[:120]],
        }

    rows = _extract_list(data)
    tokens = relevance_tokens(query)
    items: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        url = r.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        title = str(r.get("title") or url).strip()
        snippet = str(r.get("description") or r.get("snippet") or r.get("abstract") or "").strip()
        items.append({"title": title, "url": url, "domain": domain, "snippet": snippet})
        if len(items) >= _MAX_RESULTS:
            break

    if items and tokens and not any(overlap_any(tokens, r["title"], r["snippet"]) for r in items):
        return {
            "name": "brightdata",
            "status": "degraded",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": [],
            "note": "相关性校验未通过，已丢弃",
            "discarded_sample": [i["title"][:80] for i in items[:3]],
        }

    return {
        "name": "brightdata",
        "status": "ok",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": items,
    }

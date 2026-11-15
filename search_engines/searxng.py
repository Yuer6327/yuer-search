"""SearXNG 公共实例引擎（「聚合的聚合」）：一个源 = 别人维护的多引擎聚合结果。

- 实例清单默认内置，可用环境变量 SEARXNG_INSTANCES（逗号分隔）覆盖；
- 熔断轮换：403/429/坏 JSON → 该实例冷却 10 分钟，逐实例尝试直到拿到结果或全部不健康；
- 请求方是 Vercel 函数（hkg1），与用户本地网络无关；实例只需活着且开了 format=json；
- 结果已是聚合形态，不做相关性护栏（与 Marginalia 同理）。
"""
from __future__ import annotations

import os
import time

from .http import http_get
from .util import EngineError, domain_of, host_matches

_DEFAULT_INSTANCES = (
    "https://searx.be",
    "https://searx.tiekoetter.com",
    "https://searxng.site",
    "https://baresearch.org",
    "https://priv.au",
    "https://search.inetol.net",
    "https://opnxng.com",
    "https://search.inetol.net",
)
_MAX_INSTANCES_TRIED = 3
_MAX_RESULTS = 12
_COOLDOWN_SECONDS = 600

_unhealthy_until: dict[str, float] = {}


def _instances() -> list[str]:
    raw = os.environ.get("SEARXNG_INSTANCES", "").strip()
    urls = [u.strip().rstrip("/") for u in raw.split(",") if u.strip()] if raw else list(_DEFAULT_INSTANCES)
    return urls


def _extract_items(data: dict, blocked: list[str]) -> list[dict]:
    results = data.get("results") or []
    items: list[dict] = []
    seen: set[str] = set()
    for r in results:
        url = r.get("url") or ""
        if not url.startswith("http") or url in seen:
            continue
        domain = domain_of(url)
        if not domain or any(host_matches(domain, b) for b in blocked):
            continue
        seen.add(url)
        items.append(
            {
                "title": (r.get("title") or url).strip(),
                "url": url,
                "domain": domain,
                "snippet": (r.get("content") or "").strip(),
            }
        )
        if len(items) >= _MAX_RESULTS:
            break
    return items


def probe_instances(
    query: str = "test",
    *,
    instances_override: list[str] | None = None,
    timeout: float = 6.0,
    limit: int = 40,
) -> dict:
    """逐实例实测 format=json 开放性（运维诊断用）：/api/debug/searxng。

    并行探测，每实例分类：OPEN（200+有结果）/ EMPTY（200无结果）/ JSON_DISABLED(403) /
    RATE_LIMITED(429) / HTTP_xxx / UNREACHABLE。开放实例清单可直接用于 SEARXNG_INSTANCES。
    """
    import concurrent.futures

    now = time.time()
    instances = (instances_override or _instances())[:limit]
    alive = [u for u in instances if _unhealthy_until.get(u, 0) <= now]
    dead = [u for u in instances if _unhealthy_until.get(u, 0) > now]

    def _probe(inst: str) -> dict:
        t0 = time.perf_counter()
        try:
            resp = http_get(
                f"{inst}/search",
                params={"q": query, "format": "json", "safesearch": "1"},
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
            latency = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    n = len(data.get("results") or [])
                    verdict = "OPEN" if n else "EMPTY"
                    return {"instance": inst, "status": 200, "json": True, "results": n, "latency_ms": latency, "verdict": verdict}
                except Exception:
                    return {"instance": inst, "status": 200, "json": False, "latency_ms": latency, "verdict": "NOT_JSON"}
            verdict = {403: "JSON_DISABLED", 429: "RATE_LIMITED"}.get(resp.status_code, f"HTTP_{resp.status_code}")
            return {"instance": inst, "status": resp.status_code, "latency_ms": latency, "verdict": verdict}
        except Exception as exc:
            return {
                "instance": inst,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "verdict": "UNREACHABLE",
                "error": type(exc).__name__,
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        details = list(pool.map(_probe, alive))

    opened = [r["instance"] for r in details if r.get("verdict") == "OPEN"]
    return {
        "query": query,
        "tested": len(details),
        "open": opened,
        "cooldown_skipped": dead,
        "details": details,
    }


def search(
    query: str,
    *,
    lang: str = "en",
    page: int = 1,
    baseline_block: list[str] | None = None,
    timeout: float = 5.0,
    deadline: float | None = None,
) -> dict:
    started = time.perf_counter()
    now = time.time()
    instances = [u for u in _instances() if _unhealthy_until.get(u, 0) <= now]
    if not instances:
        return {
            "name": "searxng",
            "status": "skipped",
            "latency_ms": 0,
            "results": [],
            "note": "所有实例处于熔断冷却中",
        }

    blocked = baseline_block or []
    language = "zh-CN" if lang == "zh" else "en"
    tried = 0
    for inst in instances:
        if tried >= _MAX_INSTANCES_TRIED:
            break
        if deadline is not None and time.perf_counter() > deadline - 2.0:
            break
        tried += 1
        try:
            resp = http_get(
                f"{inst}/search",
                params={"q": query, "format": "json", "language": language, "safesearch": "1", "pageno": str(page)},
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
            if resp.status_code in (403, 429, 503):
                _unhealthy_until[inst] = now + _COOLDOWN_SECONDS
                continue
            if resp.status_code != 200:
                _unhealthy_until[inst] = now + _COOLDOWN_SECONDS
                continue
            data = resp.json()
        except Exception:
            _unhealthy_until[inst] = now + _COOLDOWN_SECONDS
            continue

        results = data.get("results") or []
        items = _extract_items(data, blocked)

        return {
            "name": "searxng",
            "status": "ok",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "results": items,
            "note": f"via {inst}",
        }

    return {
        "name": "searxng",
        "status": "degraded",
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "results": [],
        "note": f"尝试 {tried} 个实例均不可用（JSON 关闭/风控/下线），已熔断冷却",
    }
